"""Op family `multi` (agent_multi): ops that name a second registered fixture bot. Offline only.

Covers the module shape, the exact console line of every op, typed refusals, Python/Java handler
parity (each Java method starts with request(...) and re-validates every argument with the same
bounds), the guard copied verbatim from agent_fixture.java, the partner check mirroring the
acting-bot check, reply keys a step's `expect` can assert, and the three example suites. Every
test class carries at least one seeded fault showing its check can fail.
"""
import copy
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest import mock

from swg_test_studio import agent_fixture as af
from swg_test_studio import model
from swg_test_studio.fixture_ops import character, multi
from swg_test_studio.store import EXAMPLES, read_json

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "devtools" / "zones" / "fixtures"
JAVA = (FIXTURES / "agent_multi.java").read_text(encoding="latin-1")
CORE_JAVA = (FIXTURES / "agent_fixture.java").read_text(encoding="latin-1")

BOT = {"player": "123456789", "station": "4242", "character": "Capabcdefghijkl"}
OTHER = {"player": "223456789", "station": "4343", "character": "Capmnopqrstuvwx"}
IDENT = "123456789:4242:Capabcdefghijkl"
OTHER_IDENT = "223456789:4343:Capmnopqrstuvwx"
GUARD = ("request", "refusal", "num", "integer", "oid", "list", "botBuilding", "scope", "enc", "start", "kv",
         "row", "end", "fail", "invalidArgs")
SAMPLES = {"role": "member", "oid": "987654321", "bring_offset": "2.5", "snapshot_name": "trade1",
           "pay_amount": "500"}
EXPECT_KEY = re.compile(r"[a-z][a-zA-Z0-9_]{0,31}")
MULTI_EXAMPLES = ("trade_between_accounts", "group_with_fixture_asserts", "scenario_concert")


def registry(*extra):
    return af.merge([("multi", multi), *extra])


def line(op, args, reg=None):
    return af.command(3, BOT, op, args, identities={"member": OTHER}, registry=reg or registry())


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


def public_method(text, op):
    """Body of one public op method, whitespace-normalised."""
    match = re.search(r"public String " + op + r"\(String value\) throws InterruptedException \{", text)
    if not match:
        return None
    depth, index = 0, match.end() - 1
    for index in range(index, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            break
    return " ".join(text[match.end():index].split())


def java_constant(text, name):
    match = re.search(r"private static final \w+ " + name + r"=(.+?);", text)
    return match.group(1) if match else None


def java_regex(text, name):
    value = java_constant(text, name)
    return None if value is None else value.strip('"').replace("\\\\", "\\")


# What each Python kind must be re-validated with in Java, for argument position i.
def validators(kind, i):
    return {
        "role": [f"partner(bot,args[{i}])"],
        "oid": [f"oid(args[{i}])"],
        "bring_offset": [f"args[{i}].matches(OFFSET_RE)", f"num(args[{i}],BRING_OFFSET_MIN,BRING_OFFSET_MAX)"],
        "snapshot_name": [f"args[{i}].matches(SNAPSHOT_RE)"],
        "pay_amount": [f"args[{i}].matches(AMOUNT_RE)", f"integer(args[{i}],1,PAY_MAX)"],
    }[kind]


def parity_problems(ops, text):
    problems = []
    methods = set(re.findall(r"public String (\w+)\(String value\) throws InterruptedException", text))
    problems += ["no Java method for " + op for op in sorted(set(ops) - methods)]
    problems += ["Java method without an op: " + m for m in sorted(methods - set(ops))]
    for op in sorted(set(ops) & methods):
        spec = ops[op][0]
        body = public_method(text, op)
        low, high = len([k for k in spec if not k.endswith("?")]), len(spec)
        if not body.startswith(f'Object[] q=request(value,"{op}",{low},{high});'):
            problems.append(op + " does not start with its request(...)")
        for i, kind in enumerate(spec):
            for needle in validators(kind.rstrip("?"), i):
                if needle not in body:
                    problems.append(f"{op}: argument {i} ({kind}) is not re-validated with {needle}")
    return problems


def suite(steps, roles):
    return {"format": "swg-test-studio", "schema_version": 1, "id": "multi_probe", "title": "Multi probe",
            "category": "functional", "roles": list(roles), "steps": steps,
            "review": {"approved": True, "recording": None, "unsupported": []}}


class ModuleShapeTests(unittest.TestCase):
    def test_module_defines_only_interface_names_and_merges(self):
        public = {n for n in vars(multi) if not n.startswith("_")}
        self.assertLessEqual(public, af.FAMILY_NAMES)
        self.assertEqual(multi.FIXTURE, "agent_multi")
        reg = registry()
        self.assertEqual({op for op, f in reg.fixture_of.items() if f == "agent_multi"}, set(multi.OPS))
        self.assertEqual(reg.scenario_ops, set())
        # The real package merged this family.
        self.assertTrue(set(multi.OPS) <= set(af.OPS))
        self.assertEqual(af.REGISTRY.fixture_of["groupOf"], "agent_multi")

    def test_shared_kinds_are_reused_verbatim(self):
        self.assertEqual(multi.TYPES["role"], af.ROLE_RE)
        self.assertEqual(multi.TYPES["oid"], af.CORE_TYPES["oid"])
        for kind in set(multi.TYPES) - {"role", "oid"}:
            self.assertNotIn(kind, af.CORE_TYPES, kind)

    def test_every_op_names_another_bot_by_role(self):
        for op, (spec, _) in multi.OPS.items():
            roles = [i for i, k in enumerate(spec) if k.rstrip("?") == "role"]
            self.assertEqual(multi.ROLE_ARGS[op], tuple(roles), op)

    def test_seeded_fault_a_conflicting_kind_is_refused(self):
        fake = SimpleNamespace(**{k: getattr(multi, k) for k in ("FIXTURE", "OPS", "ROLE_ARGS", "RANGES")},
                               TYPES=dict(multi.TYPES, role=r"[a-z ]{1,32}"))
        with self.assertRaises(ValueError):
            af.merge([("multi", fake)])


class ConsoleLineTests(unittest.TestCase):
    LINES = {
        ("bring", ("member",)): f"bring {IDENT} {OTHER_IDENT}",
        ("bring", ("member", "2.5")): f"bring {IDENT} {OTHER_IDENT} 2.5",
        ("distanceTo", ("member",)): f"distanceTo {IDENT} {OTHER_IDENT}",
        ("groupOf", ()): f"groupOf {IDENT}",
        ("groupOf", ("member",)): f"groupOf {IDENT} {OTHER_IDENT}",
        ("groupLeave", ()): f"groupLeave {IDENT}",
        ("groupLeave", ("member",)): f"groupLeave {IDENT} {OTHER_IDENT}",
        ("creditsOf", ("member",)): f"creditsOf {IDENT} {OTHER_IDENT}",
        ("accountOf", ("member",)): f"accountOf {IDENT} {OTHER_IDENT}",
        ("tradeState", ()): f"tradeState {IDENT}",
        ("tradeState", ("member",)): f"tradeState {IDENT} {OTHER_IDENT}",
        ("snapshot", ("trade1",)): f"snapshot {IDENT} trade1",
        ("snapshot", ("trade1", "member")): f"snapshot {IDENT} trade1 {OTHER_IDENT}",
        ("diff", ("trade1", "member")): f"diff {IDENT} trade1 {OTHER_IDENT}",
        ("snapshotDrop", ("trade1", "member")): f"snapshotDrop {IDENT} trade1 {OTHER_IDENT}",
        ("giveTo", ("member", "987654321")): f"giveTo {IDENT} {OTHER_IDENT} 987654321",
        ("payTo", ("member", "500")): f"payTo {IDENT} {OTHER_IDENT} 500",
    }

    def test_exact_line_of_every_op(self):
        self.assertEqual({op for op, _ in self.LINES}, set(multi.OPS))
        for (op, args), tail in self.LINES.items():
            with self.subTest(op=op, args=args):
                self.assertEqual(line(op, list(args)), "game 3 runScript fixture.agent_multi " + tail)

    def test_seeded_fault_a_wrong_class_would_be_caught(self):
        reg = registry()
        reg.fixture_of["bring"] = "agent_fixture"
        self.assertNotEqual(line("bring", ["member"], reg), "game 3 runScript fixture.agent_multi " +
                            self.LINES[("bring", ("member",))])


class RefusalTests(unittest.TestCase):
    def test_injection_in_every_argument_position(self):
        attacks = ("1;game", "1 2", "", "x\ngame 1 runScript fixture.agent_fixture", "`id`", "1\x00", "١",
                   "member:1:Capabc", "../x", "A" * 600)
        for op, (spec, _) in multi.OPS.items():
            for position in range(len(spec)):
                for attack in attacks:
                    args = [SAMPLES[k.rstrip("?")] for k in spec]
                    args[position] = attack
                    with self.subTest(op=op, position=position, attack=attack), self.assertRaises(ValueError):
                        line(op, args)

    def test_out_of_range_and_disallowed_values(self):
        bad = [("bring", ["member", "0.4"]), ("bring", ["member", "16.5"]), ("bring", ["member", "-1"]),
               ("bring", ["member", "2.555"]), ("payTo", ["member", "0"]), ("payTo", ["member", "1000001"]),
               ("payTo", ["member", "-5"]), ("payTo", ["member", "1e3"]), ("snapshot", ["Trade"]),
               ("snapshot", ["t" * 25]), ("snapshot", ["1abc"]), ("giveTo", ["member", "0"]),
               ("giveTo", ["member", "1" * 20]), ("diff", ["trade1", "member", "extra"]), ("creditsOf", []),
               ("accountOf", ["member", "member"]), ("nosuchOp", [])]
        for op, args in bad:
            with self.subTest(op=op, args=args), self.assertRaises(ValueError):
                line(op, args)
        for good in (("bring", ["member", "0.5"]), ("bring", ["member", "16"]), ("payTo", ["member", "1000000"])):
            line(*good)

    def test_partner_must_be_another_registered_bot(self):
        reg = registry()
        cases = [({}, "member"),                                              # role not bound
                 ({"member": BOT}, "member"),                                 # the acting bot itself
                 ({"member": dict(OTHER, character="Someplayer")}, "member"),  # not a fixture bot name
                 ({"member": dict(OTHER, station="0")}, "member"),            # malformed station
                 ({"Member": OTHER}, "Member")]                               # not a role name
        for identities, role in cases:
            with self.subTest(identities=identities), self.assertRaises(ValueError):
                af.command(3, BOT, "bring", [role], identities=identities, registry=reg)

    def test_step_validation_refuses_the_acting_or_an_undeclared_role(self):
        roles = ["seller", "buyer"]
        af.validate({"role": "seller", "op": "creditsOf", "args": ["buyer"]}, roles, registry())
        for options in ({"role": "seller", "op": "creditsOf", "args": ["seller"]},
                        {"role": "seller", "op": "creditsOf", "args": ["ghost"]},
                        {"role": "seller", "op": "payTo", "args": ["buyer", "5"], "scenario": "s1"},
                        {"role": "seller", "op": "diff", "args": ["trade1", "buyer"], "expect": {"Bad-Key": "1"}}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                af.validate(options, roles, registry())

    def test_seeded_fault_a_widened_range_would_be_caught(self):
        widened = registry()
        widened.ranges = dict(widened.ranges, pay_amount=(1, 9999999))
        self.assertTrue(line("payTo", ["member", "1000001"], widened).endswith(" 1000001"))


class JavaParityTests(unittest.TestCase):
    def test_every_op_has_its_method_request_and_argument_checks(self):
        self.assertEqual(parity_problems(multi.OPS, JAVA), [])

    def test_class_shape(self):
        self.assertRegex(JAVA, r"package script\.fixture;\s*import script\.\*;\s*import script\.library\.\*;")
        self.assertRegex(JAVA, r"public class agent_multi extends base_script \{")
        self.assertEqual(java_constant(JAVA, "P"), '"agent_multi="')
        after = JAVA.split("public class agent_multi", 1)[1]
        self.assertNotRegex(after, r"\bnew\s+[\w.<>]+\s*\([^)]*\)\s*\{")       # anonymous class
        self.assertNotRegex(after, r"\b(class|interface|enum)\s+\w+[^\n]*\{")  # nested class
        self.assertNotIn("->", after)                                           # lambda
        for forbidden in ("sendConsoleCommand", "attachScript", "detachScript", "setGod", "createObject",
                          "Runtime", "ProcessBuilder", "Class.forName"):
            self.assertNotIn(forbidden, after, forbidden)

    def test_java_bounds_equal_python_bounds(self):
        self.assertEqual(java_regex(JAVA, "OFFSET_RE"), multi.TYPES["bring_offset"])
        self.assertEqual(java_regex(JAVA, "SNAPSHOT_RE"), multi.TYPES["snapshot_name"])
        self.assertEqual(java_regex(JAVA, "AMOUNT_RE"), multi.TYPES["pay_amount"])
        self.assertEqual(java_regex(JAVA, "OID_RE"), multi.TYPES["oid"])
        self.assertEqual(float(java_constant(JAVA, "BRING_OFFSET_MIN").rstrip("f")), multi.RANGES["bring_offset"][0])
        self.assertEqual(float(java_constant(JAVA, "BRING_OFFSET_MAX").rstrip("f")), multi.RANGES["bring_offset"][1])
        self.assertEqual(int(java_constant(JAVA, "PAY_MAX")), multi.RANGES["pay_amount"][1])
        self.assertEqual(int(java_constant(JAVA, "SNAPSHOT_ITEMS_MAX")), 100)  # docs/fixture-multi.md
        self.assertEqual(int(java_constant(JAVA, "CREDITS_MAX")), character.CREDITS_MAX)

    def test_seeded_faults_are_detected(self):
        dropped = JAVA.replace("Object[] o=partner(bot,args[0]);\n        if(o[0]!=null) return fail((String)o[0]);\n"
                               "        obj_id other=(obj_id)o[1];\n        Float offset", "obj_id other=null;\n        Float offset", 1)
        self.assertNotEqual(dropped, JAVA)
        self.assertIn("bring: argument 0 (role) is not re-validated with partner(bot,args[0])",
                      parity_problems(multi.OPS, dropped))
        arity = JAVA.replace('request(value,"payTo",2,2)', 'request(value,"payTo",1,2)')
        self.assertIn("payTo does not start with its request(...)", parity_problems(multi.OPS, arity))
        extra = dict(multi.OPS, groupJoin=(("role",), True))
        self.assertIn("no Java method for groupJoin", parity_problems(extra, JAVA))
        self.assertNotEqual(java_regex(JAVA.replace('"[1-9][0-9]{0,6}"', '"[0-9]{1,7}"'), "AMOUNT_RE"),
                            multi.TYPES["pay_amount"])


class GuardTests(unittest.TestCase):
    def test_guard_and_helpers_are_verbatim_copies(self):
        for name in GUARD:
            with self.subTest(helper=name):
                self.assertIsNotNone(java_body(CORE_JAVA, name))
                self.assertEqual(java_body(JAVA, name), java_body(CORE_JAVA, name))
        for constant in ("MAX_ROWS", "SCOPE_RANGE", "CHAIN_MAX", "OID_RE", "NUM_RE", "INT_RE"):
            self.assertEqual(java_constant(JAVA, constant), java_constant(CORE_JAVA, constant), constant)

    def test_partner_check_mirrors_the_acting_bot_check(self):
        request, partner = java_body(JAVA, "request"), java_body(JAVA, "partner")
        for clause in ('!fields[0].matches("[1-9][0-9]{0,18}")', '!fields[1].matches("[1-9][0-9]{0,9}")',
                       '!fields[2].matches("Cap[a-z]{12}")', 'split(":",-1)', "fields.length!=3",
                       "id=Long.parseLong(fields[0]);station=Long.parseLong(fields[1]);",
                       "obj_id p=obj_id.getObjId(id);", "!isIdValid(p) || !p.isAuthoritative() || !exists(p)",
                       "!isPlayer(p) || !fields[2].equals(getPlayerFullName(p)) ||",
                       "Integer.toUnsignedLong(getPlayerStationId(p))!=station || isGod(p)"):
            with self.subTest(clause=clause):
                self.assertIn(clause, request)
                self.assertIn(clause, partner)
        self.assertIn("if(p.equals(bot)) return new Object[]{\"invalid-args reason=partner-is-self\",null};", partner)

    def test_seeded_fault_an_edited_guard_is_detected(self):
        edited = JAVA.replace("isGod(p)) return refusal(\"invalid-identity\")", "false) return refusal(\"invalid-identity\")")
        self.assertNotEqual(edited, JAVA)
        self.assertNotEqual(java_body(edited, "request"), java_body(CORE_JAVA, "request"))
        weak = JAVA.replace("Integer.toUnsignedLong(getPlayerStationId(p))!=station || isGod(p))\n            return",
                            "false)\n            return")
        self.assertNotEqual(weak, JAVA)
        self.assertNotIn("isGod(p)", java_body(weak, "partner"))


class ReplyTests(unittest.TestCase):
    def test_every_reply_key_can_be_named_in_expect(self):
        keys = set(re.findall(r'kv\(sb,"(\w+)"', JAVA))
        self.assertTrue({"same_group", "leader_is", "credits_conserved", "items_conserved", "duplicated",
                         "moved_to_partner", "same_account", "cash_delta"} <= keys)
        for key in keys:
            self.assertRegex(key, EXPECT_KEY)
        # Seeded fault: a hyphenated key could never be asserted.
        self.assertIsNone(EXPECT_KEY.fullmatch("credits-conserved"))

    def test_a_diff_reply_satisfies_the_example_expectations(self):
        reply = af.parse("agent_multi=ok snapshot=trade1 gained=0 lost=0 cash_delta=500 bank_delta=0 gained_ids=none "
                         "lost_ids=none row=x partner_gained=0 partner_lost=0 partner_cash_delta=-500 "
                         "partner_bank_delta=0 moved_to_partner=0 moved_from_partner=0 duplicated=0 "
                         "items_conserved=true credits_conserved=true rows=0 truncated=false", "agent_multi", registry())
        expect = next(s for s in read_json(EXAMPLES / "trade_between_accounts.json")["steps"]
                      if s["id"] == "after_trade")["options"]["expect"]
        self.assertIsNone(af.check(reply, expect))
        # Seeded fault: credits created out of nothing fail the step.
        broken = copy.deepcopy(reply)
        broken["fields"]["credits_conserved"] = "false"
        self.assertEqual(af.check(broken, expect), "credits_conserved: expected 'true', got 'false'")
        self.assertEqual(af.parse("agent_fixture=ok", "agent_multi", registry())["status"], "unrecognized")


# Stand-ins for the character and scenario families (atoms CHAR and WORLD land in parallel); only
# their op shapes matter here, so the full concert can be validated before they are on the branch.
CHARACTER = SimpleNamespace(FIXTURE="agent_character", TYPES={"stub_level": r"[0-9]{1,2}"},
                            OPS={"setLevel": (("stub_level",), True), "stats": ((), False)})
SCENARIO = SimpleNamespace(FIXTURE="agent_scenario", TYPES={"stub_template": r"object/[a-z0-9_/]{1,120}\.iff"},
                           OPS={"scenarioBegin": (("scenario",), True), "scenarioEnd": (("scenario",), True),
                                "createObject": (("stub_template", "coord", "coord"), True)},
                           SCENARIO_OPS=frozenset({"createObject"}))
FULL_CONCERT = [
    {"id": "hold_actor", "action": "client", "options": {"role": "actor", "kind": "session_hold"}},
    {"id": "hold_helper", "action": "client", "options": {"role": "helper", "kind": "session_hold"}},
    {"id": "open", "action": "agent_fixture", "options": {"role": "actor", "op": "scenarioBegin", "args": ["concert"]}},
    {"id": "level", "action": "agent_fixture", "options": {"role": "actor", "op": "setLevel", "args": ["20"]}},
    {"id": "crate", "action": "agent_fixture", "options": {"role": "actor", "op": "createObject", "scenario": "concert",
                                                          "args": ["object/tangible/container/crate.iff", "1", "2"]}},
    {"id": "meet", "action": "agent_fixture", "options": {"role": "actor", "op": "bring", "args": ["helper"]}},
    {"id": "invite", "action": "client", "options": {"role": "actor", "kind": "group_invite", "peer": "helper"}},
    {"id": "join", "action": "client", "options": {"role": "helper", "kind": "group_join", "peer": "actor"}},
    {"id": "where", "action": "agent_fixture", "options": {"role": "actor", "op": "inspect", "args": [],
                                                          "expect": {"god": "false"}}},
    {"id": "grouped", "action": "agent_fixture", "options": {"role": "actor", "op": "groupOf", "args": ["helper"],
                                                            "expect": {"same_group": "true"}}},
    {"id": "close", "action": "agent_fixture", "options": {"role": "actor", "op": "scenarioEnd", "args": ["concert"]}},
    {"id": "release_actor", "action": "client", "options": {"role": "actor", "kind": "session_release"}},
    {"id": "release_helper", "action": "client", "options": {"role": "helper", "kind": "session_release"}},
]


class ExampleTests(unittest.TestCase):
    def test_examples_validate_with_the_families_present_now(self):
        for name in MULTI_EXAMPLES:
            with self.subTest(example=name):
                data = read_json(EXAMPLES / (name + ".json"))
                model.validate(data, runnable=True)
                self.assertEqual(len(data["roles"]), 2)
                used = {s["options"]["op"] for s in data["steps"] if s["action"] == "agent_fixture"}
                self.assertTrue(used <= set(af.CORE_OPS) | set(multi.OPS), used)
                self.assertTrue(any(s["action"] == "client" for s in data["steps"]))
                self.assertTrue(used & set(multi.OPS))

    def test_examples_end_with_released_sessions_and_no_open_trade(self):
        for name in MULTI_EXAMPLES:
            steps = read_json(EXAMPLES / (name + ".json"))["steps"]
            state = model.client_order(steps)
            self.assertEqual((state["held"], state["open_trades"]), ([], []), name)

    def test_full_concert_validates_once_character_and_scenario_are_present(self):
        reg = registry(("character", CHARACTER), ("scenario", SCENARIO))
        data = suite(FULL_CONCERT, ("actor", "helper"))
        with mock.patch.object(af, "REGISTRY", reg):
            model.validate(data, runnable=True)
            rows = af.scenario_ids([s for s in FULL_CONCERT if s["action"] == "agent_fixture"], reg)
            self.assertEqual(rows, [{"id": "concert", "role": "actor", "begun": ["open"], "ended": ["close"],
                                     "used": ["crate"], "problems": []}])
            # Seeded fault: the creating step without its scenario id is refused.
            broken = copy.deepcopy(data)
            del broken["steps"][4]["options"]["scenario"]
            with self.assertRaises(ValueError):
                model.validate(broken, runnable=True)
        # Without those families the same concert is refused: the gap is reported, never passed silently.
        if "scenarioBegin" not in af.OPS:
            with self.assertRaises(ValueError):
                model.validate(data, runnable=True)

    def test_seeded_fault_a_trade_without_verification_is_refused(self):
        data = read_json(EXAMPLES / "trade_between_accounts.json")
        data["steps"] = [s for s in data["steps"] if s["id"] != "verify_buyer"]
        with self.assertRaises(ValueError):  # the trade stays open at session_release
            model.validate(data, runnable=True)
        data = read_json(EXAMPLES / "group_with_fixture_asserts.json")
        for step in data["steps"]:
            if step["id"] == "grouped":
                step["options"]["args"] = ["leader"]  # the acting role named as the other bot
        with self.assertRaises(ValueError):
            model.validate(data, runnable=True)


if __name__ == "__main__":
    unittest.main()
