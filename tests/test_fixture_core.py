"""Dispatcher, runner and installer of the agent fixture families (offline).

Families here are small fake modules of this file, never the real family modules, so the
tests hold with zero, one or all families present. The checks that read real files (the
README table, the manifest hashes, Java/Python parity) run over whatever families exist.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from swg_test_studio import agent_fixture as af
from swg_test_studio import backend, cli, model

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "devtools" / "zones" / "fixtures"
BOT = {"player": "123456789", "station": "4242", "character": "Capabcdefghijkl"}
OTHER = {"player": "223456789", "station": "4343", "character": "Capmnopqrstuvwx"}
IDENT = "123456789:4242:Capabcdefghijkl"
GUARD = ("request", "refusal", "num", "integer", "oid", "list", "botBuilding", "scope", "enc", "kv", "row", "end")
# One valid sample per core argument kind.
SAMPLES = {"oid": "987654321", "oids": "11,12", "coord": "-2.25", "yaw": "90", "radius": "12.5",
           "scale": "1.5", "trees": "3,7", "name": "weapon_book", "names": "item_a,item_b", "cell": "r2",
           "tag": "decor_1", "regex": "combat_.*", "mods": "luck=10,precision=-5", "role": "member",
           "scenario": "s1"}


def family(name, **extra):
    values = {"FIXTURE": "agent_" + name, "TYPES": {}, "OPS": {name + "Op": ((), False)}}
    values.update(extra)
    return name, SimpleNamespace(**values)


def char_family():
    return family("character", TYPES={"credits": r"[0-9]{1,9}"}, RANGES={"credits": (0, 1000000)},
                  OPS={"setCredits": (("credits",), True), "level": ((), False)})


def scenario_family():
    return family("scenario", TYPES={"template": r"object/[a-z0-9_/]{1,120}\.iff"},
                  OPS={"scenarioBegin": (("scenario",), True), "scenarioEnd": (("scenario",), True),
                       "spawn": (("template", "coord", "coord"), True),
                       "warpScene": (("name", "coord", "coord", "coord"), True)},
                  SCENARIO_OPS=frozenset({"spawn"}), SCENE_CHANGING=frozenset({"warpScene"}))


def multi_family():
    return family("multi", OPS={"bring": (("role",), True), "groupOf": (("role", "role?"), False)},
                  ROLE_ARGS={"bring": (0,), "groupOf": (0, 1)},
                  check=lambda op, args: (_ for _ in ()).throw(ValueError("same role twice"))
                  if len(args) == 2 and args[0] == args[1] else None)


def all_families():
    return af.merge([char_family(), scenario_family(), multi_family()])


def suite(steps, roles=("actor",)):
    return {"format": "swg-test-studio", "schema_version": 1, "id": "core_probe", "title": "Core probe",
            "category": "regression", "roles": list(roles), "steps": steps,
            "review": {"approved": True, "recording": None, "unsupported": []}}


def fixture_step(step_id, **options):
    return {"id": step_id, "action": "agent_fixture", "options": dict({"role": "actor", "args": []}, **options)}


# --- Java text helpers ---------------------------------------------------------------------

def java_body(text, name):
    """Source of one private helper (signature through its closing brace), whitespace-normalised."""
    match = re.search(r"\n    private [^\n=;]*?\b" + re.escape(name) + r"\(", text)
    if not match:
        return None
    depth, index = 0, text.index("{", match.end())
    for index in range(index, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            break
    return " ".join(text[match.start():index + 1].split())


PUBLIC = re.compile(r"public String (\w+)\(String value\) throws InterruptedException \{\s*"
                    r"(?:Object\[\] q=request\(value,\"(\w+)\",(\d+),(\d+)\);)?")


def parity(registry, fixture, text):
    """Problems between a fixture class's Java text and its ops in the merged table."""
    problems = []
    ops = {op for op, owner in registry.fixture_of.items() if owner == fixture}
    methods = {m.group(1): m for m in PUBLIC.finditer(text)}
    for op in sorted(ops - set(methods)):
        problems.append("no Java method for " + op)
    for name in sorted(set(methods) - ops):
        problems.append("Java method without an op: " + name)
    for op in sorted(ops & set(methods)):
        m = methods[op]
        spec = registry.ops[op][0]
        extra = 1 if op in registry.scenario_ops else 0
        wanted = (op, str(len([k for k in spec if not k.endswith("?")]) + extra), str(len(spec) + extra))
        if m.group(2) is None:
            problems.append(op + " does not start with request(...)")
        elif m.groups()[1:] != wanted:
            problems.append(f"{op} request(...) is {m.groups()[1:]}, expected {wanted}")
    if not re.search(r"public class " + fixture + r" extends (script\.)?base_script \{", text):
        problems.append("class header")
    if re.search(r"\bnew\s+\w+\s*\([^)]*\)\s*\{|\b(class|interface|enum)\s+\w+[^\n]*\{", text.split("{", 1)[1]):
        problems.append("nested or anonymous class")
    return problems


def guard_problems(text, reference):
    return [name for name in GUARD if java_body(text, name) is None or java_body(text, name) != java_body(reference, name)]


class MergeTests(unittest.TestCase):
    def test_zero_one_or_all_families(self):
        core = af.merge([])
        self.assertEqual(core.ops, af.CORE_OPS)
        self.assertEqual(core.fixtures, ("agent_fixture",))
        one = af.merge([char_family()])
        self.assertEqual(one.fixture_of["setCredits"], "agent_character")
        self.assertEqual(one.fixture_of["inspect"], "agent_fixture")
        merged = all_families()
        self.assertEqual(merged.fixtures, ("agent_fixture", "agent_character", "agent_multi", "agent_scenario"))
        self.assertEqual(len(merged.ops), len(af.CORE_OPS) + 8)
        self.assertEqual(merged.scenario_ops, {"spawn"})
        self.assertEqual(merged.scene_changing, {"warpScene"})
        self.assertEqual(merged.role_args["groupOf"], (0, 1))

    def test_real_package_merges(self):
        self.assertEqual(set(af.OPS), set(af.REGISTRY.ops))
        self.assertTrue(set(af.CORE_OPS) <= set(af.OPS))
        for name, module in af.discover():
            self.assertEqual(module.FIXTURE, "agent_" + name)

    def test_interface_violations_are_refused(self):
        bad = {
            "duplicate op across families": [family("aaa", OPS={"x1": ((), False)}), family("bbb", OPS={"x1": ((), False)})],
            "op clashing a core op": [family("aaa", OPS={"warp": ((), True)})],
            "kind redefined": [family("aaa", TYPES={"oid": r"[0-9]+"}, OPS={"x1": (("oid",), False)})],
            "kind redefined by two families": [family("aaa", TYPES={"k": "a"}, OPS={"x1": (("k",), False)}),
                                               family("bbb", TYPES={"k": "b"}, OPS={"x2": (("k",), False)})],
            "role kind redefined": [family("aaa", TYPES={"role": r".*"})],
            "wrong FIXTURE": [family("aaa", FIXTURE="agent_bbb")],
            "fixture name taken": [family("fixture")],
            "undeclared kind": [family("aaa", OPS={"x1": (("nothing",), False)})],
            "optional not trailing": [family("aaa", OPS={"x1": (("oid?", "oid"), False)})],
            "mutating not bool": [family("aaa", OPS={"x1": ((), 1)})],
            "bad op name": [family("aaa", OPS={"Exec x": ((), False)})],
            "ROLE_ARGS on a non-role arg": [family("aaa", OPS={"x1": (("oid",), False)}, ROLE_ARGS={"x1": (0,)})],
            "ROLE_ARGS out of range": [family("aaa", OPS={"x1": (("role",), False)}, ROLE_ARGS={"x1": (1,)})],
            "SCENARIO_OPS not an op": [family("aaa", SCENARIO_OPS=frozenset({"warp"}))],
            "SCENE_CHANGING not a set": [family("aaa", SCENE_CHANGING=["aaaOp"])],
            "range conflict": [family("aaa", RANGES={"yaw": (0, 1)})],
            "range on unknown kind": [family("aaa", RANGES={"zzz": (0, 1)})],
            "invalid regex": [family("aaa", TYPES={"k": "("}, OPS={"x1": (("k",), False)})],
            "bad module name": [family("Bad")],
        }
        for label, families in bad.items():
            with self.subTest(label), self.assertRaises(ValueError):
                af.merge(families)

    def test_identical_reuse_is_allowed_and_seeded_fault_is_caught(self):
        same = af.merge([family("aaa", TYPES={"oid": af.CORE_TYPES["oid"], "role": af.ROLE_RE},
                               RANGES={"yaw": (-360.0, 360.0)}, OPS={"x1": (("oid",), False)})])
        self.assertEqual(same.fixture_of["x1"], "agent_aaa")
        # Seeded fault: one character of the reused regex changed must be refused.
        with self.assertRaises(ValueError):
            af.merge([family("aaa", TYPES={"oid": af.CORE_TYPES["oid"] + "?"}, OPS={"x1": (("oid",), False)})])


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.reg = all_families()

    def line(self, op, args, **kw):
        return af.command(3, BOT, op, args, registry=self.reg, **kw)

    def test_family_op_goes_to_its_class(self):
        self.assertEqual(self.line("setCredits", ["5000"]),
                         f"game 3 runScript fixture.agent_character setCredits {IDENT} 5000")
        self.assertEqual(self.line("inspect", []), f"game 3 runScript fixture.agent_fixture inspect {IDENT}")

    def test_scenario_is_the_first_argument(self):
        self.assertEqual(self.line("spawn", ["object/mobile/bantha.iff", "1", "2"], scenario="arena_1"),
                         f"game 3 runScript fixture.agent_scenario spawn {IDENT} arena_1 object/mobile/bantha.iff 1 2")
        self.assertEqual(self.line("scenarioBegin", ["arena_1"]),
                         f"game 3 runScript fixture.agent_scenario scenarioBegin {IDENT} arena_1")
        for scenario in (None, "Arena", "a b", "1abc", "a" * 33):
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                self.line("spawn", ["object/mobile/bantha.iff", "1", "2"], scenario=scenario)
        with self.assertRaises(ValueError):
            self.line("inspect", [], scenario="arena_1")

    def test_role_arguments_become_identities(self):
        self.assertEqual(self.line("bring", ["member"], identities={"member": OTHER}),
                         f"game 3 runScript fixture.agent_multi bring {IDENT} 223456789:4343:Capmnopqrstuvwx")
        self.assertEqual(self.line("groupOf", ["member"], identities={"member": OTHER}).split()[-1],
                         "223456789:4343:Capmnopqrstuvwx")
        refusals = [
            ("bring", ["member"], {}),                                              # role not bound
            ("bring", ["member"], {"member": BOT}),                                 # the acting bot itself
            ("bring", ["member"], {"member": dict(OTHER, character="Someplayer")}),  # not a fixture bot
            ("bring", ["Member;x"], {"Member;x": OTHER}),                           # not a role name
            ("groupOf", ["member", "member"], {"member": OTHER}),                   # family check()
        ]
        for op, args, identities in refusals:
            with self.subTest(args=args, identities=identities), self.assertRaises(ValueError):
                self.line(op, args, identities=identities)

    def test_typed_refusals_for_family_ops(self):
        for op, args in (("setCredits", ["1000001"]), ("setCredits", ["-1"]), ("setCredits", ["1 2"]),
                         ("spawn", ["object/../x.iff", "1", "2"]), ("spawn", ["/setGod", "1", "2"]),
                         ("nosuchOp", []), ("setCredits", [5])):
            with self.subTest(op=op, args=args), self.assertRaises(ValueError):
                self.line(op, args, scenario="s1" if op == "spawn" else None)

    def test_whitespace_is_refused_even_if_a_family_regex_allows_it(self):
        loose = af.merge([family("aaa", TYPES={"text": r".{1,20}"}, OPS={"say": (("text",), True)})])
        self.assertTrue(af.command(1, BOT, "say", ["hello"], registry=loose).endswith(" hello"))
        for value in ("a b", "a\tb", "x\ngame 1 runScript y", "café", "\x00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                af.command(1, BOT, "say", [value], registry=loose)

    def test_reply_prefix_of_the_family(self):
        reply = af.parse("agent_character=ok credits=5000 row=a", registry=self.reg)
        self.assertEqual((reply["fixture"], reply["status"], reply["fields"]), ("agent_character", "ok", {"credits": "5000"}))
        self.assertEqual(af.parse("agent_character=ok", "agent_scenario", self.reg)["status"], "unrecognized")
        self.assertEqual(af.parse("agent_unknown=ok", registry=self.reg)["status"], "unrecognized")
        self.assertEqual(af.parse("agent_fixture=refused reason=x")["status"], "refused reason=x".split()[0])
        # Seeded fault: a reply of another class must not satisfy an expectation.
        self.assertEqual(af.check(af.parse("agent_multi=ok members=2", "agent_character", self.reg), {"members": "2"}),
                         "fixture status unrecognized")


class CoreConsoleLineTests(unittest.TestCase):
    def test_every_core_op_has_its_exact_line(self):
        for op, (spec, _) in af.CORE_OPS.items():
            args = [SAMPLES[k.rstrip("?")] for k in spec]
            with self.subTest(op=op):
                self.assertEqual(af.command(7, BOT, op, args, registry=af.merge([])),
                                 " ".join(["game 7 runScript fixture.agent_fixture", op, IDENT, *args]))

    def test_injection_in_every_argument_position_is_refused(self):
        attacks = ("1;game", "1 2", "", "1\n", "`id`","1\x00", "١")
        core = af.merge([])
        for op, (spec, _) in af.CORE_OPS.items():
            for position in range(len(spec)):
                for attack in attacks:
                    args = [SAMPLES[k.rstrip("?")] for k in spec]
                    args[position] = attack
                    with self.subTest(op=op, position=position, attack=attack), self.assertRaises(ValueError):
                        af.command(7, BOT, op, args, registry=core)

    def test_seeded_fault_a_widened_regex_would_be_caught(self):
        widened = af.merge([])
        widened.types = dict(widened.types, name=r"[a-z0-9_ ]{1,64}")
        self.assertRaises(ValueError, af.command, 7, BOT, "completeCollection", ["a b"], registry=widened)


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.reg = all_families()

    def test_step_options(self):
        roles = ["actor", "member"]
        af.validate({"role": "actor", "op": "bring", "args": ["member"]}, roles, self.reg)
        af.validate({"role": "actor", "op": "spawn", "args": ["object/x.iff", "1", "2"], "scenario": "s1"}, roles, self.reg)
        bad = [
            {"role": "actor", "op": "bring", "args": ["actor"]},              # the acting role
            {"role": "actor", "op": "bring", "args": ["ghost"]},              # not a role of the suite
            {"role": "actor", "op": "spawn", "args": ["object/x.iff", "1", "2"]},           # scenario missing
            {"role": "actor", "op": "inspect", "args": [], "scenario": "s1"},               # not a scenario op
            {"role": "actor", "op": "spawn", "args": ["object/x.iff", "1", "2"], "scenario": 5},
            {"role": "actor", "op": "inspect", "args": [], "extra": 1},
        ]
        for options in bad:
            with self.subTest(options=options), self.assertRaises(ValueError):
                af.validate(options, roles, self.reg)

    def test_model_step_with_families(self):
        steps = [fixture_step("open", op="scenarioBegin", args=["s1"]),
                 fixture_step("put", op="spawn", args=["object/x.iff", "1", "2"], scenario="s1"),
                 fixture_step("meet", op="bring", args=["member"]),
                 fixture_step("close", op="scenarioEnd", args=["s1"])]
        with mock.patch.object(af, "REGISTRY", self.reg):
            model.validate(suite(steps, ("actor", "member")), runnable=True)
            # Seeded fault: the scenario id dropped from a creating step fails validation.
            del steps[1]["options"]["scenario"]
            with self.assertRaises(ValueError):
                model.validate(suite(steps, ("actor", "member")), runnable=True)


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.reg = all_families()

    def test_plan_bookkeeping(self):
        steps = [fixture_step("open", op="scenarioBegin", args=["s1"]),
                 fixture_step("put", op="spawn", args=["object/x.iff", "1", "2"], scenario="s1"),
                 fixture_step("put2", op="spawn", args=["object/x.iff", "1", "2"], scenario="s2"),
                 fixture_step("close", op="scenarioEnd", args=["s1"])]
        rows = af.scenario_ids(steps, self.reg)
        self.assertEqual(rows, [{"id": "s1", "role": "actor", "begun": ["open"], "ended": ["close"], "used": ["put"],
                                 "problems": []},
                                {"id": "s2", "role": "actor", "begun": [], "ended": [], "used": ["put2"],
                                 "problems": ["put2: use-without-begin"]}])

    def test_plan_reports_scenarios_classes_and_partners(self):
        steps = [fixture_step("open", op="scenarioBegin", args=["s1"]),
                 fixture_step("put", op="spawn", args=["object/x.iff", "1", "2"], scenario="s1"),
                 fixture_step("meet", op="bring", args=["member"])]
        env = {"bindings": {"actor": "tester", "member": "helper"}, "server_checkout": "/nonexistent", "name": "Offline"}
        with mock.patch.object(af, "REGISTRY", self.reg), mock.patch.object(backend, "AGENT_REGISTRY", self.reg), \
                mock.patch.dict(backend.AGENT_OPS, self.reg.ops):
            effects = backend.plan(suite(steps, ("actor", "member")), env)["effects"]
            self.assertEqual(effects["agent_fixture_classes"], ["agent_multi", "agent_scenario"])
            self.assertEqual(effects["agent_fixture_partner_roles"], ["member"])
            self.assertEqual(effects["agent_fixture_changes"], ["bring", "scenarioBegin", "spawn"])
            self.assertFalse(effects["agent_fixture_scenarios_all_ended"])
            steps.append(fixture_step("close", op="scenarioEnd", args=["s1"]))
            self.assertTrue(backend.plan(suite(steps, ("actor", "member")), env)["effects"]["agent_fixture_scenarios_all_ended"])

    def test_scenario_end_options(self):
        self.assertEqual(af.scenario_end_options("actor", "s1", self.reg),
                         {"role": "actor", "op": "scenarioEnd", "args": ["s1"]})
        tagged = af.merge([family("scenario", OPS={"scenarioEnd": ((), True)}, SCENARIO_OPS=frozenset({"scenarioEnd"}))])
        self.assertEqual(af.scenario_end_options("actor", "s1", tagged),
                         {"role": "actor", "op": "scenarioEnd", "args": [], "scenario": "s1"})
        for registry, scenario in ((af.merge([]), "s1"), (self.reg, "S 1"), (self.reg, "x;y")):
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                af.scenario_end_options("actor", scenario, registry)

    def run_cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(argv)
        return code, [json.loads(line) for line in out.getvalue().splitlines()]

    def test_cli_scenario_end(self):
        """scenario-end: exit 0 only for a clean end; the studio lock; the role must be bound."""
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / "environment.json"
            env = {"schema_version": 1, "name": "Offline", "server_checkout": "/srv/checkout",
                   "folder": "/tmp/swg-cold-test-0123abcd/client-012345abcdef", "binary": "/tmp/driver",
                   "bindings": {"actor": "tester", "member": "helper"}}
            env_file.write_text(json.dumps(env))
            workspace = Path(folder) / "ws"
            argv = ["--workspace", str(workspace), "scenario-end", "--environment", str(env_file),
                    "--role", "actor", "--id", "s1"]
            calls, replies = [], []

            def fake_run(options, env_, key, bindings, accept=("ok",)):
                calls.append((options, key, bindings, accept))
                return {"reply": replies.pop(0)}

            clean = {"status": "ok", "fields": {"destroyed": "3", "leaked": "0", "was_open": "true"}}
            with mock.patch.object(af, "REGISTRY", self.reg), mock.patch.object(af, "run_live", fake_run):
                replies[:] = [clean]
                code, events = self.run_cli(argv)
                self.assertEqual(code, 0)
                self.assertEqual(events[-1], {"event": "scenario_ended", "role": "actor", "scenario": "s1",
                                              "status": "ok", "fields": clean["fields"]})
                # A partial reply is returned to the CLI (not raised) so it can report the leak.
                self.assertEqual(calls, [({"role": "actor", "op": "scenarioEnd", "args": ["s1"]}, "tester",
                                          {"actor": "tester", "member": "helper"}, ("ok", "partial"))])
                # A mistyped id: nothing was open on the bot, so nothing was cleaned up.
                replies[:] = [{"status": "ok", "fields": {"destroyed": "0", "leaked": "0", "was_open": "false"}}]
                code, events = self.run_cli(argv)
                self.assertEqual(code, 1)
                self.assertIn("was_open=false", events[-1]["error"])
                # Objects left out of reach: the scenario stays open and the command fails.
                replies[:] = [{"status": "partial", "fields": {"destroyed": "1", "leaked": "2", "leaked_ids": "5,6",
                                                               "was_open": "true", "open": "s1"}}]
                code, events = self.run_cli(argv)
                self.assertEqual(code, 1)
                self.assertIn("leaked=2", events[-1]["error"])
                self.assertEqual(events[-1]["fields"]["leaked_ids"], "5,6")
                replies[:] = [{"status": "ok", "fields": {"destroyed": "0", "leaked": "1", "was_open": "true"}}]
                self.assertEqual(self.run_cli(argv)[0], 1)
                # An unbound role is refused by scenario_end itself, before anything is sent.
                sent = len(calls)
                code, events = self.run_cli(argv[:-4] + ["--role", "ghost", "--id", "s1"])
                self.assertEqual(code, 1)
                self.assertIn("binds no registry to role ghost", events[-1]["error"])
                # Another Studio operation holds the lock: refused, nothing sent.
                from swg_test_studio.backend import studio_lock
                replies[:] = [clean]
                with studio_lock(workspace):
                    code, events = self.run_cli(argv)
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), sent)
            # Without a scenario family the command refuses before anything is sent.
            with mock.patch.object(af, "REGISTRY", af.merge([])):
                code, events = self.run_cli(argv)
            self.assertEqual(code, 1)
            self.assertIn("scenarioEnd", events[-1]["error"])

    def test_scenario_end_refuses_an_unbound_role(self):
        with mock.patch.object(af, "run_live", lambda *a, **k: self.fail("nothing may be sent")):
            with self.assertRaisesRegex(ValueError, "binds no registry to role ghost"):
                af.scenario_end({"bindings": {"actor": "tester"}}, "ghost", "s1")

    def test_scenario_end_failure(self):
        self.assertIsNone(af.scenario_end_failure({"status": "ok", "fields": {"leaked": "0", "was_open": "true"}}))
        for reply, text in (({"status": "partial", "fields": {"leaked": "2", "was_open": "true"}}, "leaked=2"),
                            ({"status": "refused", "fields": {"failed": "1"}}, "status refused"),
                            ({"status": "ok", "fields": {"leaked": "1", "was_open": "true"}}, "leaked=1"),
                            ({"status": "ok", "fields": {"leaked": "0", "was_open": "false"}}, "was_open=false")):
            with self.subTest(reply=reply):
                self.assertIn(text, af.scenario_end_failure(reply))

    def test_plan_flags_every_ordering_problem(self):
        roles = ("actor", "member")

        def step(step_id, role, op, args, scenario=None):
            return fixture_step(step_id, role=role, op=op, args=args, **({"scenario": scenario} if scenario else {}))

        spawn = ["object/x.iff", "1", "2"]
        steps = [step("early_end", "actor", "scenarioEnd", ["s0"]),
                 step("early_use", "actor", "spawn", spawn, "s1"),
                 step("open", "actor", "scenarioBegin", ["s1"]),
                 step("again", "actor", "scenarioBegin", ["s1"]),
                 step("other", "actor", "scenarioBegin", ["s2"]),
                 step("use", "actor", "spawn", spawn, "s1"),
                 step("away", "actor", "warpScene", ["naboo", "1", "2", "3"]),
                 step("member_use", "member", "spawn", spawn, "s1"),
                 step("member_end", "member", "scenarioEnd", ["s1"]),
                 step("m_open", "member", "scenarioBegin", ["m1"]),
                 step("m_close", "member", "scenarioEnd", ["m1"]),
                 step("m_away", "member", "warpScene", ["naboo", "1", "2", "3"]),
                 step("s0_open", "actor", "scenarioBegin", ["s0"])]
        rows = {(r["id"], r["role"]): r for r in af.scenario_ids(steps, self.reg)}
        self.assertEqual(rows[("s0", "actor")]["problems"], ["early_end: end-before-begin",
                                                             "s0_open: begin-while-other-open"])
        self.assertEqual(rows[("s1", "actor")]["problems"],
                         ["early_use: use-without-begin", "again: begun-twice", "away: scene-change-while-open",
                          "open: never-ended"])
        self.assertEqual(rows[("s2", "actor")]["problems"], ["other: begin-while-other-open"])
        self.assertEqual(rows[("s1", "member")]["problems"], ["member_use: use-without-begin",
                                                              "member_end: ended-by-other-role"])
        self.assertEqual(rows[("m1", "member")]["problems"], [])  # m_away is after m_close
        self.assertEqual(rows[("s1", "actor")]["used"], ["early_use", "use"])
        # Existing plan keys stay: id, begun, ended, used.
        self.assertTrue(all({"id", "begun", "ended", "used"} <= set(r) for r in rows.values()))
        # Seeded fault: the same steps in a correct order raise no problem.
        good = [step("open", "actor", "scenarioBegin", ["s1"]), step("use", "actor", "spawn", spawn, "s1"),
                step("close", "actor", "scenarioEnd", ["s1"]), step("away", "actor", "warpScene", ["naboo", "1", "2", "3"])]
        self.assertEqual([r["problems"] for r in af.scenario_ids(good, self.reg)], [[]])
        with mock.patch.object(af, "REGISTRY", self.reg), mock.patch.object(backend, "AGENT_REGISTRY", self.reg), \
                mock.patch.dict(backend.AGENT_OPS, self.reg.ops):
            env = {"bindings": {"actor": "tester", "member": "helper"}, "server_checkout": "/nonexistent",
                   "name": "Offline"}
            plan_rows = backend.plan(suite(steps, roles), env)["effects"]["agent_fixture_scenarios"]
        self.assertIn("away: scene-change-while-open",
                      next(r for r in plan_rows if r["id"] == "s1" and r["role"] == "actor")["problems"])


class ArgumentClassTests(unittest.TestCase):
    """The dispatcher's own argument rules, whatever a family's kind regex allows."""

    def loose(self):
        return af.merge([family("aaa", TYPES={"text": r".{1,40}"}, OPS={"say": (("text",), True),
                                                                        "meet": (("role", "text"), True)},
                               ROLE_ARGS={"meet": (0,)})])

    def test_fixed_safe_character_class(self):
        reg = self.loose()
        for value in ("hello", "a=b,c:d/e", "-1.5", "x_y.z*", "^a|b$", "(a)[b]+?"):
            with self.subTest(value=value):
                self.assertTrue(af.command(1, BOT, "say", [value], registry=reg).endswith(" " + value))
        for value in ("a;b", "a'b", 'a"b', "a`b", "a&b", "a\\b", "a<b", "a>b", "a#b", "a%b", "a!b", "a@b", "a{b}",
                      "a~b", "a b", "caf\u00e9"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                af.command(1, BOT, "say", [value], registry=reg)
        # Seeded fault: the old printable-ASCII token would let these through.
        self.assertTrue(re.fullmatch(r"[\x21-\x7e]{1,512}", "a;b"))

    def test_an_identity_only_arrives_through_a_role_argument(self):
        reg = self.loose()
        for value in (IDENT, "x" + IDENT, IDENT + ",1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                af.arguments("say", [value], reg)
        with self.assertRaises(ValueError):
            af.arguments("meet", ["member", IDENT], reg)
        line = af.command(1, BOT, "meet", ["member", "hi"], identities={"member": OTHER}, registry=reg)
        self.assertTrue(line.endswith(" 223456789:4343:Capmnopqrstuvwx hi"))
        # The real scenario family: a test objvar value shaped like an identity is refused.
        if "setTestVar" in af.OPS:
            with self.assertRaises(ValueError):
                af.arguments("setTestVar", ["self", "x", "string", IDENT])


class RegistryTests(unittest.TestCase):
    def test_core_tables_are_read_only_and_snapshotted(self):
        for table in (af.CORE_TYPES, af.CORE_RANGES, af.CORE_OPS):
            with self.assertRaises(TypeError):
                table["oid"] = "x"
        # A family module that rebinds the core names at import changes nothing in a merge.
        with mock.patch.object(af, "CORE_TYPES", {"oid": r".*"}), mock.patch.object(af, "CORE_OPS", {}):
            core = af.merge([])
        self.assertEqual(core.types["oid"], r"[1-9][0-9]{0,18}")
        self.assertIn("warp", core.ops)

    def test_a_family_may_not_bound_a_core_kind(self):
        for kind in ("coord", "oid", "role", "scenario"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                af.merge([family("aaa", RANGES={kind: (0, 1)})])
        # Identical reuse of a core range stays allowed.
        af.merge([family("aaa", RANGES={"yaw": (-360.0, 360.0)})])

    def test_one_family_name_rule_for_install_and_reload(self):
        for name in ("a", "x_y", "a" * 24, "multi"):
            with self.subTest(name=name):
                self.assertTrue(af.FAMILY_NAME.fullmatch(name))
                self.assertTrue(af.FIXTURE_SOURCE.fullmatch(f"agent_{name}.java"))
                self.assertEqual(af.reload_command(2, f"fixture.agent_{name}"), f"game 2 reloadScript fixture.agent_{name}")
        for name in ("a1", "x2y", "A", "_a", "a" * 25):
            with self.subTest(name=name):
                self.assertFalse(af.FAMILY_NAME.fullmatch(name))
                self.assertFalse(af.FIXTURE_SOURCE.fullmatch(f"agent_{name}.java"))
                with self.assertRaises(ValueError):
                    af.merge([family(name)])


class ReplyTests(unittest.TestCase):
    def test_a_duplicate_key_is_never_last_key_wins(self):
        reply = af.parse("agent_fixture=ok count=1 count=2")
        self.assertEqual(reply["status"], "malformed")
        self.assertEqual(af.check(reply, {"count": "2"}), "fixture status malformed")
        # Rows repeat by design.
        self.assertEqual(af.parse("agent_fixture=ok row=a row=b rows=2")["rows"], ["a", "b"])
        self.assertIsNone(af.check(af.parse("agent_fixture=ok count=2"), {"count": "2"}))


class RunnerMutantTests(unittest.TestCase):
    """run_live, the registry key, the run report and the installer: each guard with its effect."""

    class Driver:
        REPO = None

        @staticmethod
        def fixture(folder):
            return "proj", "WGC_0123456789AB", {"game": {"Id": "game1"}}

        @staticmethod
        def identity(value):
            return value

        @staticmethod
        def bot_query(project, bot):
            return {"worker": 3, "scene": "tatooine"}

    def run_step(self, options, key="tester", bindings=None, reply="agent_scenario=ok"):
        sent = []
        bots = {"tester": BOT, "helper": OTHER}
        reg = all_families()
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(af, "REGISTRY", reg), mock.patch.dict(af.OPS, reg.ops), \
                mock.patch("swg_test_studio.backend.driver_modules", lambda env: (self.Driver, None)), \
                mock.patch.object(af, "central_host", lambda project, inspect: "10.0.0.2"), \
                mock.patch.object(Path, "read_text", lambda path: json.dumps(bots[path.stem])), \
                mock.patch.object(af, "send", lambda host, line: sent.append(line) or reply), \
                contextlib.redirect_stdout(io.StringIO()):
            art = af.run_live(options, {"folder": folder}, key, bindings or {"actor": key})
        return sent, art

    def test_run_live_sends_the_scenario_id(self):
        sent, art = self.run_step({"role": "actor", "op": "spawn", "args": ["object/x.iff", "1", "2"], "scenario": "s1"})
        self.assertEqual(sent, [f"game 3 runScript fixture.agent_scenario spawn {IDENT} s1 object/x.iff 1 2"])
        self.assertEqual(art["scenario"], "s1")

    def test_run_live_refuses_an_acting_role_bound_elsewhere(self):
        with self.assertRaisesRegex(ValueError, "bound to a different registry"):
            self.run_step({"role": "actor", "op": "level", "args": []}, "tester", {"actor": "helper"})
        sent, _ = self.run_step({"role": "actor", "op": "level", "args": []}, "tester", {"actor": "tester"},
                                "agent_character=ok")
        self.assertEqual(sent, [f"game 3 runScript fixture.agent_character level {IDENT}"])

    def test_run_live_accepts_only_the_given_statuses(self):
        options = {"role": "actor", "op": "scenarioEnd", "args": ["s1"]}
        with self.assertRaisesRegex(RuntimeError, "fixture status partial"):
            self.run_step(options, reply="agent_scenario=partial leaked=1")
        reg = all_families()
        with mock.patch.object(af, "run_live", lambda o, e, k, b, accept: (o, accept)):
            self.assertEqual(af.scenario_end({"bindings": {"actor": "tester"}}, "actor", "s1")[1], ("ok", "partial"))
        self.assertTrue(reg)

    def test_registered_bot_key_is_checked_before_any_file_is_read(self):
        driver = SimpleNamespace(identity=lambda value: value)
        with tempfile.TemporaryDirectory() as folder:
            registry = Path(folder) / "protocol-driver"
            registry.mkdir()
            (registry / "tester.json").write_text(json.dumps(BOT))
            self.assertEqual(af._registered_bot(driver, Path(folder), "tester"), BOT)
            (Path(folder) / "x.json").write_text(json.dumps(OTHER))
            for key in ("../x", "Tester", "ab", "a" * 17, "tester.json", None, "te ster"):
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "registry key"):
                    af._registered_bot(driver, Path(folder), key)

    def test_run_report_hashes_the_fixture_op_modules(self):
        options = {"role": "actor", "op": "stats", "args": []}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "tools" / "teststudio_server").mkdir(parents=True)
            (root / "tools" / "teststudio_server" / "retained_peer.py").write_text("peer")
            driver = SimpleNamespace(REPO=root / "repo")
            legacy = SimpleNamespace(source_hashes=lambda: {})
            selected = {"manifest": {"tests": [{"id": "look", "kind": "agent_fixture", "options": options}]},
                        "bindings": {"actor": "tester"}}
            with mock.patch.object(backend, "plan", lambda suite, env: selected), \
                    mock.patch.object(backend, "driver_modules", lambda env: (driver, legacy)), \
                    mock.patch.object(backend, "verified_tool_root", lambda: root / "tools"), \
                    mock.patch.object(af, "run_live", lambda *a, **k: {"fixture": "agent_character"}):
                result = backend.run_suite({"id": "probe"}, {"folder": str(root)}, root / "ws", emit=lambda e: None)
            report = json.loads((Path(result["evidence"]) / "result.json").read_text())
        self.assertTrue(report["passed"])
        hashed = report["application_sha256"]
        modules = sorted((ROOT / "swg_test_studio" / "fixture_ops").glob("*.py"))
        self.assertTrue(modules)
        for module in modules:
            self.assertEqual(hashed["fixture_ops/" + module.name], hashlib.sha256(module.read_bytes()).hexdigest())

    def install(self, class_files):
        """install() with docker and javac replaced; javac writes class_files for each source."""
        calls = []

        def run(argv, capture_output, text, check, **kw):
            calls.append(argv)
            if argv[:2] == ["docker", "cp"] and argv[2].endswith("/."):
                target = Path(argv[3]) / "fixture"
                target.mkdir(parents=True)
                (Path(argv[3]) / "base_script.class").write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x41")
            elif argv[0] == "javac":
                out = Path(argv[argv.index("-d") + 1]) / "script" / "fixture"
                out.mkdir(parents=True)
                for name in class_files(Path(argv[-1]).stem):
                    (out / name).write_bytes(b"class")
            elif argv[:2] == ["docker", "exec"]:
                return SimpleNamespace(stdout="Adding server 3 for scene tatooine\n")
            return SimpleNamespace(stdout="[]")

        profile = SimpleNamespace(fixtures=(), runtime_scripts="/scripts", runtime_log="/log")
        with tempfile.TemporaryDirectory() as folder:
            tools = Path(folder) / "tools"
            with mock.patch("swg_test_studio.backend.driver_modules", lambda env: (self.Driver, None)), \
                    mock.patch("swg_test_studio.server_tools.profile_of", lambda env: profile), \
                    mock.patch("swg_test_studio.server_tools.verified_tool_root", lambda: tools), \
                    mock.patch("swg_test_studio.server_tools._bundle", SimpleNamespace(verify=lambda root: {})), \
                    mock.patch.object(af, "fixture_sources", lambda *a: ["fixtures/agent_fixture.java"]), \
                    mock.patch.object(af, "central_host", lambda project, inspect: "10.0.0.2"), \
                    mock.patch.object(af, "send", lambda host, line: "ok"), mock.patch("subprocess.run", run):
                replies = af.install({"folder": folder}, emit=lambda event: None)
        return replies, calls

    def test_install_requires_exactly_one_class_file_per_source(self):
        replies, calls = self.install(lambda stem: [stem + ".class"])
        self.assertEqual(replies, {3: "ok"})
        self.assertIn(["docker", "cp", mock.ANY, "game1:/scripts/fixture/agent_fixture.class"],
                      [c[:2] + [mock.ANY, c[3]] for c in calls if c[:2] == ["docker", "cp"]])
        # A nested or anonymous class would leave a second class file that the overlay never copies.
        with self.assertRaisesRegex(RuntimeError, "exactly one class file"):
            self.install(lambda stem: [stem + ".class", stem + "$1.class"])


class RelocateTests(unittest.TestCase):
    def clock(self):
        state = {"t": 0.0}
        return state, (lambda: state["t"]), (lambda s: state.__setitem__("t", state["t"] + s))

    def test_waits_until_the_bot_is_found_in_the_target_scene(self):
        _, clock, sleep = self.clock()
        answers = iter([None, RuntimeError("Multiple authoritative bot actors"),
                        {"worker": 4, "scene": "tatooine"}, {"worker": 9, "scene": "naboo"}])

        def query():
            value = next(answers)
            if isinstance(value, Exception):
                raise value
            return value

        found = af.relocate(query, {"worker": 4, "scene": "tatooine"}, "naboo", sleep=sleep, clock=clock)
        self.assertEqual(found, {"worker": 9, "scene": "naboo", "moved_server": True, "seconds": 3.0})

    def test_bounded_wait(self):
        _, clock, sleep = self.clock()
        calls = []
        with self.assertRaises(RuntimeError):
            af.relocate(lambda: calls.append(1) or {"worker": 4, "scene": "tatooine"}, None, "naboo",
                        timeout=10, interval=1, sleep=sleep, clock=clock)
        self.assertLessEqual(len(calls), 12)
        # Seeded fault: without a target scene the first sighting is accepted at once.
        _, clock, sleep = self.clock()
        self.assertEqual(af.relocate(lambda: {"worker": 4, "scene": "tatooine"}, None, None,
                                     sleep=sleep, clock=clock)["seconds"], 0.0)


class RunLiveTests(unittest.TestCase):
    """run_live with the driver and console replaced: role identities, prefix, relocation."""

    def test_family_step_end_to_end_offline(self):
        reg = all_families()
        sent, queries = [], []
        bots = {"tester": BOT, "helper": OTHER}
        located = [{"worker": 3, "scene": "tatooine"}, {"worker": 3, "scene": "tatooine"},
                   {"worker": 8, "scene": "naboo"}]

        class Driver:
            @staticmethod
            def fixture(folder):
                return "proj", "WGC_0123456789AB", {}

            @staticmethod
            def identity(value):
                return value

            @staticmethod
            def bot_query(project, bot):
                queries.append(bot["character"])
                return located.pop(0) if len(located) > 1 else located[0]

        def read_text(path):
            return json.dumps(bots[path.stem])

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(af, "REGISTRY", reg), mock.patch.dict(af.OPS, reg.ops), \
                mock.patch("swg_test_studio.backend.driver_modules", lambda env: (Driver, None)), \
                mock.patch.object(af, "central_host", lambda project, inspect: "10.0.0.2"), \
                mock.patch.object(Path, "read_text", read_text), \
                mock.patch.object(af, "relocate", lambda q, before, scene: {"scene": scene, "found": q()}), \
                contextlib.redirect_stdout(io.StringIO()):
            env = {"folder": folder}
            with mock.patch.object(af, "send", lambda host, line: sent.append(line) or "agent_multi=ok members=2"):
                art = af.run_live({"role": "actor", "op": "bring", "args": ["member"], "expect": {"members": "2"}},
                                  env, "tester", {"actor": "tester", "member": "helper"})
            self.assertEqual(sent[-1], f"game 3 runScript fixture.agent_multi bring {IDENT} 223456789:4343:Capmnopqrstuvwx")
            self.assertEqual(art["fixture"], "agent_multi")
            with mock.patch.object(af, "send", lambda host, line: sent.append(line) or "agent_scenario=ok scene=naboo"):
                art = af.run_live({"role": "actor", "op": "warpScene", "args": ["naboo", "1", "2", "3"]},
                                  env, "tester", {"actor": "tester"})
            self.assertEqual(art["relocated"], {"scene": "naboo", "found": {"worker": 8, "scene": "naboo"}})
            # Seeded fault: a reply from the wrong class fails the step.
            with mock.patch.object(af, "send", lambda host, line: "agent_fixture=ok members=2"), \
                    self.assertRaises(RuntimeError):
                af.run_live({"role": "actor", "op": "bring", "args": ["member"]}, env, "tester",
                            {"actor": "tester", "member": "helper"})
            # The other role must be bound in this run.
            with self.assertRaises(ValueError):
                af.run_live({"role": "actor", "op": "bring", "args": ["member"]}, env, "tester", {"actor": "tester"})


class InstallTests(unittest.TestCase):
    def tree(self, folder, names):
        root = Path(folder)
        (root / "zones" / "fixtures" / "restoration").mkdir(parents=True)
        for name in names:
            (root / "zones" / "fixtures" / name).write_text("class")
        return root

    def test_sources_order_and_verification(self):
        reg = af.merge([char_family(), multi_family()])
        with tempfile.TemporaryDirectory() as folder:
            root = self.tree(folder, ["agent_fixture.java", "agent_multi.java", "agent_character.java"])
            listed = {"zones/fixtures/" + n: "0" * 64 for n in
                      ("agent_fixture.java", "agent_multi.java", "agent_character.java", "restoration/protocol_bot.java")}
            profile = ("fixtures/restoration/protocol_bot.java", "fixtures/agent_fixture.java")
            self.assertEqual(af.fixture_sources(root, profile, listed, reg),
                             ["fixtures/restoration/protocol_bot.java", "fixtures/agent_fixture.java",
                              "fixtures/agent_character.java", "fixtures/agent_multi.java"])
            # Seeded faults: an unlisted source, and a family without its Java class.
            del listed["zones/fixtures/agent_multi.java"]
            with self.assertRaises(ValueError):
                af.fixture_sources(root, profile, listed, reg)
            listed["zones/fixtures/agent_multi.java"] = "0" * 64
            with self.assertRaises(ValueError):
                af.fixture_sources(root, profile, listed, af.merge([char_family(), multi_family(), scenario_family()]))
            (root / "zones" / "fixtures" / "agent_Bad.java").write_text("x")
            with self.assertRaises(ValueError):
                af.fixture_sources(root, profile, listed, reg)

    def test_real_tree_sources_are_verified(self):
        from swg_test_studio.server_tools import TOOLS_ROOT, _bundle, server_profile
        files = _bundle.verify(TOOLS_ROOT)
        for name in ("whitengold", "restoration"):
            with self.subTest(profile=name):
                sources = af.fixture_sources(TOOLS_ROOT, server_profile(name).fixtures, files)
                self.assertIn("fixtures/agent_fixture.java", sources)
                for fixture in af.REGISTRY.fixtures:
                    self.assertIn(f"fixtures/{fixture}.java", sources)

    def test_reload_lines(self):
        for fixture in af.REGISTRY.fixtures:
            self.assertEqual(af.reload_command(2, "fixture." + fixture), f"game 2 reloadScript fixture.{fixture}")
        with self.assertRaises(ValueError):
            af.reload_command(2, "fixture.agent_x; game 1 runScript y")


class GeneratedFileTests(unittest.TestCase):
    def test_readme_table_matches_the_merged_ops(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(af.readme_with_table(text), text,
                         "README op table is stale: python3 -m swg_test_studio.agent_fixture refresh")
        for op in af.OPS:
            self.assertIn(f"| `{op}` |", text)
        # Seeded fault: a row removed from the README is detected.
        broken = text.replace("| `warp` | `agent_fixture` | coord, coord, coord | yes | - |\n", "")
        self.assertNotEqual(af.readme_with_table(broken), broken)

    def test_table_shows_family_columns(self):
        table = af.op_table(all_families())
        self.assertIn("| `spawn` | `agent_scenario` | template, coord, coord | yes | required |", table)
        self.assertIn("| `groupOf` | `agent_multi` | role, role (optional) (argument 1 is a role, argument 2 is a role) | no | - |", table)
        self.assertIn("(changes scene)", table)

    def test_manifest_lists_every_fixture_class_with_its_hash(self):
        from swg_test_studio.server_tools import TOOLS_ROOT, _bundle
        text = (TOOLS_ROOT / "studio-tools.json").read_text(encoding="utf-8")
        self.assertEqual(af.manifest_with_fixtures(text, TOOLS_ROOT), text,
                         "studio-tools.json is stale: python3 -m swg_test_studio.agent_fixture refresh")
        files = _bundle.verify(TOOLS_ROOT)
        for path in FIXTURES.glob("agent_*.java"):
            self.assertEqual(files["zones/fixtures/" + path.name], hashlib.sha256(path.read_bytes()).hexdigest())
        # Seeded fault: a stale hash is rewritten.
        stale = text.replace(files["zones/fixtures/agent_fixture.java"], "0" * 64)
        self.assertNotEqual(af.manifest_with_fixtures(stale, TOOLS_ROOT), stale)

    def test_refresh_check_mode_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "devtools" / "zones" / "fixtures").mkdir(parents=True)
            (root / "devtools" / "zones" / "fixtures" / "agent_fixture.java").write_text("x")
            (root / "devtools" / "studio-tools.json").write_text(json.dumps(
                {"schema_version": 1, "files": {"zones/a.py": "0" * 64}}, indent=2) + "\n")
            (root / "README.md").write_text(f"a\n{af.README_BEGIN}\nold\n{af.README_END}\nb\n")
            self.assertEqual(af.refresh(root, check_only=True), ["README.md", "devtools/studio-tools.json"])
            self.assertIn("old", (root / "README.md").read_text())
            af.refresh(root)
            self.assertEqual(af.refresh(root, check_only=True), [])
            self.assertIn("zones/fixtures/agent_fixture.java", (root / "devtools" / "studio-tools.json").read_text())


class JavaParityTests(unittest.TestCase):
    def setUp(self):
        self.reference = (FIXTURES / "agent_fixture.java").read_text(encoding="ISO-8859-1")

    def test_core_class_matches_core_ops(self):
        self.assertEqual(parity(af.merge([]), "agent_fixture", self.reference), [])

    def test_every_family_class_matches_its_ops_and_guard(self):
        for fixture in af.REGISTRY.fixtures[1:]:
            with self.subTest(fixture=fixture):
                text = (FIXTURES / (fixture + ".java")).read_text(encoding="ISO-8859-1")
                self.assertEqual(parity(af.REGISTRY, fixture, text), [])
                self.assertEqual(guard_problems(text, self.reference), [])

    def test_seeded_faults_are_detected(self):
        core = af.merge([])
        self.assertTrue(guard_problems(self.reference, self.reference) == [])
        dropped = self.reference.replace("public String warp(String value)", "public String warpTo(String value)")
        self.assertIn("no Java method for warp", parity(core, "agent_fixture", dropped))
        arity = self.reference.replace('request(value,"warp",3,3)', 'request(value,"warp",3,4)')
        self.assertTrue(any(p.startswith("warp request") for p in parity(core, "agent_fixture", arity)))
        guard = self.reference.replace('schema.matches("WGC_[A-F0-9]{12}")', 'schema.matches("WGC_.*")')
        self.assertEqual(guard_problems(guard, self.reference), ["request"])
        nested = self.reference.replace("public class agent_fixture extends base_script {",
                                        "public class agent_fixture extends base_script {\n class X {}")
        self.assertIn("nested or anonymous class", parity(core, "agent_fixture", nested))
        # A family class built from the reference passes; with the scenario argument the arity grows by one.
        reg = af.merge([family("demo", OPS={"spawnIt": (("oid",), True)}, SCENARIO_OPS=frozenset({"spawnIt"}))])
        body = "\n".join(f"    {line}" for line in ["public String spawnIt(String value) throws InterruptedException {",
                                                    '    Object[] q=request(value,"spawnIt",2,2);', "    return null;", "}"])
        text = "package script.fixture;\npublic class agent_demo extends script.base_script {\n" + body + "\n}\n"
        self.assertEqual(parity(reg, "agent_demo", text), [])
        self.assertTrue(parity(reg, "agent_demo", text.replace(",2,2)", ",1,1)")))


if __name__ == "__main__":
    unittest.main()
