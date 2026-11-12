"""Op family `scenario` (agent_scenario): Python table, console lines, refusals and Java parity (offline).

Nothing here talks to a server. The Java class is read as text: every op's method, the exact
parser it applies to each argument, the bounds behind those parsers, the tagging of everything
it creates and the guard copied from agent_fixture.java are compared with the Python module.
Every test class carries at least one seeded fault showing its check can fail.
"""
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest import mock

from swg_test_studio import agent_fixture as af
from swg_test_studio import model
from swg_test_studio.fixture_ops import scenario as sc

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "devtools" / "zones" / "fixtures"
JAVA = (FIXTURES / "agent_scenario.java").read_text(encoding="ISO-8859-1")
REFERENCE = (FIXTURES / "agent_fixture.java").read_text(encoding="ISO-8859-1")
BOT = {"player": "123456789", "station": "4242", "character": "Capabcdefghijkl"}
IDENT = "123456789:4242:Capabcdefghijkl"
GUARD = ("request", "refusal", "num", "integer", "oid", "list", "botBuilding", "scope", "enc", "start", "kv",
         "row", "end", "fail", "invalidArgs")

# One valid sample per argument kind the family uses.
SAMPLES = {"scenario": "arena_1", "objtemplate": "object/tangible/furniture/all/frn_all_chair_wooden_s1.iff",
           "worldxz": "-1200.5", "worldy": "12.5", "yaw": "90", "oid": "987654321", "cell": "r2",
           "celllocal": "1.5", "spawncount": "3", "creaturename": "womp_rat", "spawnoffset": "8",
           "spawnlevel": "12", "onoff": "on", "questname": "quest/naboo_rescue", "questsignal": "talkedToNpc",
           "vartarget": "self", "varname": "phase", "vartype": "int", "varvalue": "3", "scenename": "naboo"}

# The exact Java parser each kind must be re-validated with ({i} = argument index in args[]).
JAVA_PARSER = {
    "scenario": "match(args[{i}],SCENARIO_RE)",
    "objtemplate": "template(args[{i}])",
    "worldxz": "num(args[{i}],-WORLD_XZ_MAX,WORLD_XZ_MAX)",
    "worldy": "num(args[{i}],WORLD_Y_MIN,WORLD_Y_MAX)",
    "yaw": "num(args[{i}],-YAW_MAX,YAW_MAX)",
    "oid": "oid(args[{i}])",
    "cell": "match(args[{i}],CELL_RE)",
    "celllocal": "num(args[{i}],-CELL_LOCAL_MAX,CELL_LOCAL_MAX)",
    "spawncount": "integer(args[{i}],1,INVENTORY_COUNT_MAX)",
    "creaturename": "match(args[{i}],CREATURE_RE)",
    "spawnoffset": "num(args[{i}],-SPAWN_OFFSET_MAX,SPAWN_OFFSET_MAX)",
    "spawnlevel": "integer(args[{i}],SPAWN_LEVEL_MIN,SPAWN_LEVEL_MAX)",
    "onoff": "match(args[{i}],ONOFF_RE)",
    "questname": "match(args[{i}],QUEST_RE)",
    "questsignal": "match(args[{i}],SIGNAL_RE)",
    "vartarget": "varTarget(bot,args[{i}])",
    "varname": "match(args[{i}],VAR_NAME_RE)",
    "vartype": "match(args[{i}],VAR_TYPE_RE)",
    "varvalue": "match(args[{i}],VAR_VALUE_RE)",
    "scenename": "sceneName(args[{i}])",
}

# Java regex constant -> the Python kind regex it must equal.
JAVA_REGEX = {"SCENARIO_RE": af.SCENARIO_RE, "CELL_RE": af.CORE_TYPES["cell"], "OID_RE": af.CORE_TYPES["oid"],
              "TEMPLATE_RE": sc.TYPES["objtemplate"], "CREATURE_RE": sc.TYPES["creaturename"],
              "QUEST_RE": sc.TYPES["questname"], "SIGNAL_RE": sc.TYPES["questsignal"],
              "TARGET_RE": sc.TYPES["vartarget"], "VAR_NAME_RE": sc.TYPES["varname"],
              "VAR_TYPE_RE": sc.TYPES["vartype"], "VAR_VALUE_RE": sc.TYPES["varvalue"],
              "ONOFF_RE": sc.TYPES["onoff"], "NUM_RE": sc.TYPES["worldxz"]}

FORBIDDEN = ("sendConsoleCommand", "attachScript", "detachScript", "setGod", "setAdminLevel", "Runtime.getRuntime",
             "ProcessBuilder", "Class.forName", "java.lang.reflect", "reloadScript", "messageTo(", "new Thread")


def forbidden(text):
    return [name for name in FORBIDDEN if name in text]


def registry():
    return af.merge([("scenario", sc)])


def sample_args(op):
    return [SAMPLES[k.rstrip("?")] for k in sc.OPS[op][0]]


def line(op, args, scenario=None, reg=None):
    return af.command(5, BOT, op, args, scenario=scenario, registry=reg or registry())


def constants(text):
    """Java `private static final` String/int/float constants -> Python values."""
    found = {}
    for name, raw in re.findall(r"private static final (?:String|int|float) (\w+)=(.*?);\n", text):
        if raw.startswith('"'):
            found[name] = raw[1:-1].replace("\\\\", "\\")
        else:
            found[name] = float(raw.rstrip("f"))
    return found


def method(text, op):
    """Body of one public op method, from its signature through its closing brace."""
    start = text.find(f"public String {op}(String value) throws InterruptedException {{")
    if start < 0:
        return None
    depth, index = 0, text.index("{", start)
    for index in range(index, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            break
    return text[start:index + 1]


def helper(text, name):
    """One private helper (signature through closing brace), whitespace-normalised."""
    match = re.search(r"\n    private [^\n=;]*?\b" + re.escape(name) + r"\(", text)
    if not match:
        return None
    depth, index = 0, text.index("{", match.end())
    for index in range(index, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            break
    return " ".join(text[match.start():index + 1].split())


def parity(text):
    """Problems between the Java class and the Python op table (empty when they agree)."""
    problems = []
    public = set(re.findall(r"public String (\w+)\(String value\) throws InterruptedException", text))
    problems += ["no Java method for " + op for op in sorted(set(sc.OPS) - public)]
    problems += ["Java method without an op: " + op for op in sorted(public - set(sc.OPS))]
    for op, (spec, _) in sc.OPS.items():
        body = method(text, op)
        if body is None:
            continue
        kinds = (["scenario"] if op in sc.SCENARIO_OPS else []) + [k.rstrip("?") for k in spec]
        required = len([k for k in spec if not k.endswith("?")]) + (1 if op in sc.SCENARIO_OPS else 0)
        first = re.search(r"\{\s*Object\[\] q=request\(value,\"(\w+)\",(\d+),(\d+)\);", body)
        if not first or first.groups() != (op, str(required), str(len(kinds))):
            problems.append(f"{op} does not start with request(value,\"{op}\",{required},{len(kinds)})")
        for index, kind in enumerate(kinds):
            if JAVA_PARSER[kind].format(i=index) not in body:
                problems.append(f"{op} does not re-validate argument {index} as {kind}")
        if re.search(r"args\[" + str(len(kinds)) + r"\]", body):
            problems.append(f"{op} reads an argument beyond its arity")
    return problems


def bound_problems(text):
    """Java constants that disagree with the Python kinds, ranges and caps."""
    c, problems = constants(text), []
    for name, regex in JAVA_REGEX.items():
        if c.get(name) != regex:
            problems.append(name)
    expected = {"WORLD_XZ_MAX": sc.RANGES["worldxz"][1], "WORLD_Y_MIN": sc.RANGES["worldy"][0],
                "WORLD_Y_MAX": sc.RANGES["worldy"][1], "CELL_LOCAL_MAX": sc.RANGES["celllocal"][1],
                "SPAWN_OFFSET_MAX": sc.RANGES["spawnoffset"][1], "SPAWN_LEVEL_MIN": sc.RANGES["spawnlevel"][0],
                "SPAWN_LEVEL_MAX": sc.RANGES["spawnlevel"][1], "INVENTORY_COUNT_MAX": sc.RANGES["spawncount"][1],
                "YAW_MAX": af.CORE_RANGES["yaw"][1], "VAR_INT_MAX": sc.VAR_INT_MAX, "VAR_FLOAT_MAX": sc.VAR_FLOAT_MAX,
                "SCENARIO_CREATE_MAX": sc.SCENARIO_CREATE_MAX, "SCENARIO_END_MAX": sc.SCENARIO_END_MAX,
                "TEMPLATE_MAX": sc.TEMPLATE_MAX}
    for name, value in expected.items():
        if c.get(name) != float(value):
            problems.append(name)
    for kind in ("worldxz", "celllocal", "spawnoffset"):
        if sc.RANGES[kind][0] != -sc.RANGES[kind][1]:
            problems.append("symmetric range " + kind)
    if sc.RANGES["spawncount"][0] != 1 or af.CORE_RANGES["yaw"][0] != -af.CORE_RANGES["yaw"][1]:
        problems.append("lower bounds")
    scenes = re.search(r"String\[\] SCENES=\{(.*?)\};", text, re.S)
    if not scenes or tuple(re.findall(r'"([a-z0-9_]+)"', scenes.group(1))) != sc.SCENES:
        problems.append("SCENES")
    if sc.TYPES["scenename"] != "|".join(sc.SCENES):
        problems.append("scenename kind")
    for name in ("TAG_SCENARIO", "TAG_OWNER", "OPEN_VAR", "TEST_VAR_ROOT"):
        if c.get(name) != {"TAG_SCENARIO": "fixture.scenario", "TAG_OWNER": "fixture.owner",
                           "OPEN_VAR": "fixture.scenario_open", "TEST_VAR_ROOT": "fixture.t"}[name]:
            problems.append(name)
    return problems


class ModuleShapeTests(unittest.TestCase):
    def test_module_follows_the_interface_and_merges(self):
        names = {n for n in vars(sc) if n.isupper() or n == "check"}
        self.assertTrue({"FIXTURE", "TYPES", "RANGES", "OPS", "SCENARIO_OPS", "SCENE_CHANGING"} <= names)
        self.assertEqual(sc.FIXTURE, "agent_scenario")
        reg = registry()
        self.assertEqual(reg.fixtures, ("agent_fixture", "agent_scenario"))
        self.assertTrue(set(sc.OPS).isdisjoint(af.CORE_OPS))
        self.assertEqual(reg.scenario_ops, set(sc.SCENARIO_OPS))
        self.assertEqual(reg.scene_changing, {"warpScene"})
        for kind in sc.TYPES:
            self.assertNotIn(kind, af.CORE_TYPES, kind)
        # The real dispatcher picked the family up.
        self.assertEqual(af.REGISTRY.fixture_of["scenarioEnd"], "agent_scenario")

    def test_scenario_lifecycle_ops_take_the_id_as_an_argument(self):
        self.assertEqual(af.scenario_end_options("actor", "arena_1", registry()),
                         {"role": "actor", "op": "scenarioEnd", "args": ["arena_1"]})
        self.assertTrue({"scenarioBegin", "scenarioEnd", "scenarioList"}.isdisjoint(sc.SCENARIO_OPS))

    def test_seeded_fault_a_clashing_module_is_refused(self):
        def copy(**changes):
            values = {k: getattr(sc, k) for k in ("FIXTURE", "TYPES", "RANGES", "OPS", "SCENARIO_OPS",
                                                   "SCENE_CHANGING", "check")}
            return SimpleNamespace(**dict(values, **changes))

        self.assertEqual(af.merge([("scenario", copy())]).fixture_of["face"], "agent_scenario")
        for label, changes in (("core kind redefined", {"TYPES": dict(sc.TYPES, cell=r"[a-z]+")}),
                               ("core op redefined", {"OPS": dict(sc.OPS, warp=((), True))}),
                               ("core range changed", {"RANGES": dict(sc.RANGES, yaw=(-720.0, 720.0))}),
                               ("scene op not an op", {"SCENE_CHANGING": frozenset({"warp"})})):
            with self.subTest(label), self.assertRaises(ValueError):
                af.merge([("scenario", copy(**changes))])


class ConsoleLineTests(unittest.TestCase):
    def test_every_op_has_its_exact_line(self):
        reg = registry()
        for op in sc.OPS:
            args = sample_args(op)
            scenario = "arena_1" if op in sc.SCENARIO_OPS else None
            expected = ["game 5 runScript fixture.agent_scenario", op, IDENT] + (["arena_1"] if scenario else []) + args
            with self.subTest(op=op):
                self.assertEqual(line(op, args, scenario, reg), " ".join(expected))

    def test_lines_spelled_out(self):
        self.assertEqual(line("scenarioBegin", ["arena_1"]),
                         f"game 5 runScript fixture.agent_scenario scenarioBegin {IDENT} arena_1")
        self.assertEqual(line("spawnCreature", ["womp_rat", "8", "-4.5", "12"], "arena_1"),
                         f"game 5 runScript fixture.agent_scenario spawnCreature {IDENT} arena_1 womp_rat 8 -4.5 12")
        self.assertEqual(line("createInInventory", ["object/tangible/loot/misc/damaged_datapad.iff"], "arena_1"),
                         f"game 5 runScript fixture.agent_scenario createInInventory {IDENT} arena_1 "
                         "object/tangible/loot/misc/damaged_datapad.iff")
        self.assertEqual(line("warpScene", ["naboo", "-4856", "6", "4162"]),
                         f"game 5 runScript fixture.agent_scenario warpScene {IDENT} naboo -4856 6 4162")
        self.assertEqual(line("setTestVar", ["987654321", "wave.count", "float", "2.5"]),
                         f"game 5 runScript fixture.agent_scenario setTestVar {IDENT} 987654321 wave.count float 2.5")
        self.assertEqual(line("quests", []), f"game 5 runScript fixture.agent_scenario quests {IDENT}")

    def test_scenario_id_rules(self):
        for op in sc.SCENARIO_OPS:
            for bad in (None, "Arena", "a b", "1abc", "a" * 33, "a;b"):
                with self.subTest(op=op, scenario=bad), self.assertRaises(ValueError):
                    line(op, sample_args(op), bad)
        with self.assertRaises(ValueError):
            line("face", ["90"], "arena_1")  # not a creating op

    def test_seeded_fault_a_dropped_scenario_op_would_send_without_an_id(self):
        loose = registry()
        loose.scenario_ops = set()
        self.assertNotIn("arena_1", line("createAt", sample_args("createAt"), None, loose))
        with self.assertRaises(ValueError):
            line("createAt", sample_args("createAt"), None)


class RefusalTests(unittest.TestCase):
    ATTACKS = ("1;game", "1 2", "", "1\n", "`id`", "1\x00", "١", "$(id)", "../x")

    def test_injection_in_every_argument_position_is_refused(self):
        reg = registry()
        for op, (spec, _) in sc.OPS.items():
            for position in range(len(spec)):
                for attack in self.ATTACKS:
                    args = sample_args(op)
                    args[position] = attack
                    with self.subTest(op=op, position=position, attack=attack), self.assertRaises(ValueError):
                        line(op, args, "arena_1" if op in sc.SCENARIO_OPS else None, reg)

    def test_out_of_range_and_disallowed_values(self):
        bad = [
            ("createAt", ["object/creature/player/human_male.iff", "1", "2", "0"]),
            ("createAt", ["object/mobile/womp_rat.iff", "1", "2", "0"]),
            ("createAt", ["object/building/player/player_house_tatooine_small_style_01.iff", "1", "2", "0"]),
            ("createAt", ["object/tangible/shared_chair.iff", "1", "2", "0"]),
            ("createAt", ["object/tangible/player/x.iff", "1", "2", "0"]),
            ("createAt", ["object/tangible/../creature/x.iff", "1", "2", "0"]),
            ("createAt", ["object/tangible/Chair.iff", "1", "2", "0"]),
            ("createAt", ["object/tangible/chair.tpf", "1", "2", "0"]),
            ("createAt", ["object/tangible/" + "a/" * 8 + "x.iff", "1", "2", "0"]),
            ("createAt", ["object/tangible/" + "a" * 60 + "/" + "b" * 60 + "/" + "c" * 60 + "/x.iff", "1", "2", "0"]),
            ("createAt", [SAMPLES["objtemplate"], "8193", "2", "0"]),
            ("createAt", [SAMPLES["objtemplate"], "1", "2", "361"]),
            ("createInCell", [SAMPLES["objtemplate"], "5", "r2", "513", "0", "0", "0"]),
            ("createInCell", [SAMPLES["objtemplate"], "0", "r2", "1", "0", "0", "0"]),
            ("createInInventory", [SAMPLES["objtemplate"], "11"]),
            ("createInInventory", [SAMPLES["objtemplate"], "0"]),
            ("createInInventory", [SAMPLES["objtemplate"], "-1"]),
            ("spawnCreature", ["womp_rat", "64.5", "0"]),
            ("spawnCreature", ["womp_rat", "0", "0", "91"]),
            ("spawnCreature", ["womp_rat", "0", "0", "0"]),
            ("spawnCreature", ["Womp_Rat", "0", "0"]),
            ("spawnCreature", ["object/mobile/womp_rat.iff", "0", "0"]),
            ("creatureInvulnerable", ["987654321", "yes"]),
            ("creatureMove", ["987654321", "-65", "0"]),
            ("questGrant", ["quest/../x"]),
            ("questGrant", ["Quest/X"]),
            ("questGrant", ["a/b/c/d/e"]),
            ("questSignal", ["sig-nal"]),
            ("setTestVar", ["self", "phase", "int", "1.5"]),
            ("setTestVar", ["self", "phase", "int", "1000000000"]),
            ("setTestVar", ["self", "phase", "float", "abc"]),
            ("setTestVar", ["self", "phase", "float", "100000.5"]),
            ("setTestVar", ["self", "phase", "bool", "1"]),
            ("setTestVar", ["self", "Phase", "int", "1"]),
            ("setTestVar", ["self", "a.b.c.d.e", "int", "1"]),
            ("setTestVar", ["self", "phase", "string", "a=b"]),
            ("setTestVar", ["player", "phase", "int", "1"]),
            ("setTestVar", ["0", "phase", "int", "1"]),
            ("clearTestVar", ["self", "..phase"]),
            ("getTestVar", ["self", "phase", "extra"]),
            ("warpScene", ["tutorial", "0", "0", "0"]),
            ("warpScene", ["dungeon1", "0", "0", "0"]),
            ("warpScene", ["space_tatooine", "0", "0", "0"]),
            ("warpScene", ["kashyyyk_hunting", "0", "0", "0"]),
            ("warpScene", ["naboo", "0", "10001", "0"]),
            ("warpScene", ["naboo", "-9000", "0", "0"]),
            ("face", ["-361"]),
            ("scenarioBegin", ["Arena"]),
            ("scenarioEnd", ["arena_1", "arena_2"]),
            ("quests", ["x"]),
            ("nosuchOp", []),
        ]
        reg = registry()
        for op, args in bad:
            with self.subTest(op=op, args=args), self.assertRaises(ValueError):
                line(op, args, "arena_1" if op in sc.SCENARIO_OPS else None, reg)

    def test_valid_edges_are_accepted(self):
        good = [("createAt", [SAMPLES["objtemplate"], "-8192", "8192", "-360"]),
                ("createAt", ["object/weapon/melee/sword/sword_01.iff", "0", "0", "0"]),
                ("createAt", ["object/static/structure/general/tent_s01.iff", "0", "0", "0"]),
                ("createInInventory", [SAMPLES["objtemplate"], "10"]),
                ("spawnCreature", ["womp_rat", "-64", "64", "90"]),
                ("setTestVar", ["self", "a.b.c.d", "int", "-999999999"]),
                ("setTestVar", ["987654321", "x", "float", "-99999.5"]),
                ("setTestVar", ["self", "x", "string", "hello_world/1,2:3+4-5"]),
                ("getTestVar", ["self"]),
                ("warpScene", ["kashyyyk_main", "0", "-1000", "0"]),
                ("questGrant", ["quest/a/b/c"])]
        for op, args in good:
            with self.subTest(op=op, args=args):
                line(op, args, "arena_1" if op in sc.SCENARIO_OPS else None)

    def test_seeded_fault_a_widened_kind_or_missing_check_lets_a_bad_value_through(self):
        widened = registry()
        widened.types = dict(widened.types, objtemplate=r"object/[a-z0-9_/]{1,120}\.iff")
        self.assertIn("object/mobile/womp_rat.iff",
                      line("createAt", ["object/mobile/womp_rat.iff", "1", "2", "0"], "arena_1", widened))
        # The check() layer still refuses player templates even under the widened kind.
        with self.assertRaises(ValueError):
            line("createAt", ["object/creature/player/human_male.iff", "1", "2", "0"], "arena_1", widened)
        unchecked = registry()
        unchecked.checks = {}
        self.assertTrue(line("setTestVar", ["self", "phase", "int", "1.5"], None, unchecked).endswith("int 1.5"))


class StepTests(unittest.TestCase):
    def suite(self, steps):
        return {"format": "swg-test-studio", "schema_version": 1, "id": "scenario_probe", "title": "Scenario probe",
                "category": "regression", "roles": ["actor"], "steps": steps,
                "review": {"approved": True, "recording": None, "unsupported": []}}

    def step(self, step_id, **options):
        return {"id": step_id, "action": "agent_fixture", "options": dict({"role": "actor", "args": []}, **options)}

    def test_suite_with_scenario_steps_validates_and_plans(self):
        reg = registry()
        steps = [self.step("open", op="scenarioBegin", args=["arena_1"]),
                 self.step("rat", op="spawnCreature", args=["womp_rat", "8", "0"], scenario="arena_1"),
                 self.step("chair", op="createInInventory", args=[SAMPLES["objtemplate"], "2"], scenario="arena_1"),
                 self.step("list", op="scenarioList", args=["arena_1"], expect={"count": "3"}),
                 self.step("close", op="scenarioEnd", args=["arena_1"], expect={"open": "none"})]
        with mock.patch.object(af, "REGISTRY", reg):
            model.validate(self.suite(steps), runnable=True)
            rows = af.scenario_ids(steps, reg)
            self.assertEqual(rows, [{"id": "arena_1", "begun": ["open"], "ended": ["close"], "used": ["rat", "chair"]}])
            # Seeded fault: a creating step without its scenario id fails validation.
            del steps[1]["options"]["scenario"]
            with self.assertRaises(ValueError):
                model.validate(self.suite(steps), runnable=True)

    def test_reply_of_the_family_is_parsed_and_checked(self):
        reg = registry()
        reply = af.parse("agent_scenario=ok scenario=arena_1 destroyed=3 failed=0 open=none", "agent_scenario", reg)
        self.assertIsNone(af.check(reply, {"destroyed": "3", "open": "none"}))
        self.assertEqual(af.check(af.parse("agent_scenario=refused reason=scenario-not-open", "agent_scenario", reg),
                                  {}), "fixture status refused")
        # Seeded fault: a reply of the core class does not satisfy a scenario step.
        self.assertEqual(af.parse("agent_fixture=ok destroyed=3", "agent_scenario", reg)["status"], "unrecognized")


class JavaParityTests(unittest.TestCase):
    def test_every_op_has_a_method_that_revalidates_each_argument(self):
        self.assertEqual(parity(JAVA), [])

    def test_java_bounds_and_regexes_equal_the_python_kinds(self):
        self.assertEqual(bound_problems(JAVA), [])

    def test_guard_helpers_are_verbatim_copies_of_agent_fixture(self):
        for name in GUARD:
            with self.subTest(helper=name):
                self.assertIsNotNone(helper(JAVA, name))
                self.assertEqual(helper(JAVA, name), helper(REFERENCE, name))
        reference = constants(REFERENCE)
        for name in ("P", "MAX_ROWS", "SCOPE_RANGE", "CHAIN_MAX", "OID_RE", "NUM_RE", "INT_RE", "CELL_RE"):
            if name != "P":
                self.assertEqual(constants(JAVA)[name], reference[name], name)
        self.assertEqual(constants(JAVA)["P"], "agent_scenario=")

    def test_class_shape(self):
        self.assertIn("package script.fixture;", JAVA)
        self.assertIn("public class agent_scenario extends base_script {", JAVA)
        body = JAVA.split("{", 1)[1]
        self.assertIsNone(re.search(r"\bnew\s+\w+\s*\([^)]*\)\s*\{|\b(class|interface|enum)\s+\w+[^\n]*\{", body))
        self.assertNotIn("->", JAVA)  # no lambdas: one class file, nothing synthetic to deploy

    def test_seeded_faults_are_detected(self):
        dropped = JAVA.replace("public String face(String value)", "public String turn(String value)")
        self.assertIn("no Java method for face", parity(dropped))
        arity = JAVA.replace('request(value,"createAt",5,5)', 'request(value,"createAt",4,4)')
        self.assertTrue(any(p.startswith("createAt does not start") for p in parity(arity)))
        unchecked = JAVA.replace("Float yaw=num(args[0],-YAW_MAX,YAW_MAX);", "Float yaw=Float.parseFloat(args[0]);")
        self.assertIn("face does not re-validate argument 0 as yaw", parity(unchecked))
        wider = JAVA.replace("SPAWN_OFFSET_MAX=64.0f", "SPAWN_OFFSET_MAX=640.0f")
        self.assertIn("SPAWN_OFFSET_MAX", bound_problems(wider))
        scene = JAVA.replace('"mustafar","naboo"', '"mustafar","tutorial","naboo"')
        self.assertIn("SCENES", bound_problems(scene))
        guard = JAVA.replace('schema.matches("WGC_[A-F0-9]{12}")', 'schema.matches("WGC_.*")')
        self.assertNotEqual(helper(guard, "request"), helper(REFERENCE, "request"))


class SafetyTests(unittest.TestCase):
    def test_no_free_form_or_privileged_calls(self):
        self.assertEqual(forbidden(JAVA), [])

    def test_everything_created_is_tagged_and_only_scenario_ops_create(self):
        creating = set()
        for op in sc.OPS:
            body = method(JAVA, op)
            calls = re.findall(r"\b(createObject|createCreature)\(", body)
            if calls:
                creating.add(op)
                self.assertIn("mayCreate(bot,id,", body, op)
                self.assertGreaterEqual(body.count("tag(bot,"), 1, op)
        self.assertEqual(creating, set(sc.SCENARIO_OPS))
        self.assertEqual(JAVA.count("createObject(") + JAVA.count("createCreature("),
                         sum(method(JAVA, op).count("createObject(") + method(JAVA, op).count("createCreature(")
                             for op in sc.SCENARIO_OPS))
        tag = helper(JAVA, "tag")
        self.assertIn("setObjVar(o,TAG_SCENARIO,id)", tag)
        self.assertIn("setObjVar(o,TAG_OWNER,bot)", tag)
        self.assertIn("destroyObject(o)", tag)  # an untaggable object is not left behind

    def test_destroying_and_controlling_ops_only_touch_fixture_created_objects(self):
        for op in ("destroyCreated", "creatureAttack", "creaturePassive", "creatureInvulnerable", "creatureMove",
                   "creatureKill", "creatureDespawn"):
            with self.subTest(op=op):
                body = method(JAVA, op)
                self.assertRegex(body, r"String s=created\(bot,\w,(true|false)\);\s*if\(s!=null\) return fail\(s\);")
        self.assertIn("id.equals(taggedFor(bot,o)) && scope(bot,o,false)==null", JAVA)
        self.assertIn("bot.equals(owner)", helper(JAVA, "taggedFor"))
        self.assertIn('"self".equals(s)', helper(JAVA, "varTarget"))
        self.assertIn("created(bot,o,false)", helper(JAVA, "varTarget"))

    def test_scene_change_reply_names_the_target_scene(self):
        body = method(JAVA, "warpScene")
        self.assertIn('kv(sb,"scene",scene)', body)
        self.assertIn("warpPlayer(bot,scene,", body)
        self.assertEqual(sc.SCENE_CHANGING, frozenset({"warpScene"}))

    def test_seeded_fault_an_untagged_create_is_detected(self):
        bad = JAVA.replace("if(!tag(bot,o,id)) return fail(\"refused reason=create-failed template=\"+enc(t));\n"
                           "        setYaw(o,yaw);\n        StringBuilder sb=start(\"ok\");\n"
                           "        kv(sb,\"object\",o);kv(sb,\"template\",t);kv(sb,\"scenario\",id);kv(sb,\"scene\",scene);",
                           "setYaw(o,yaw);\n        StringBuilder sb=start(\"ok\");")
        self.assertNotEqual(bad, JAVA)
        self.assertEqual(method(bad, "createAt").count("tag(bot,"), 0)
        self.assertEqual(forbidden(JAVA), [])
        self.assertEqual(forbidden(JAVA.replace("stop(c);", "sendConsoleCommand(\"x\",c);")), ["sendConsoleCommand"])


if __name__ == "__main__":
    unittest.main()
