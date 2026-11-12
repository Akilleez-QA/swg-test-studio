"""Op family `character` (agent_character): module shape, console lines, typed refusals,
Python/Java parity, the copied guard, safety rules and grounding in the server tree.

Everything is offline. The grounding tests read the server tree named by SWG_RESTORATION_TREE
and run only when it is present; the job gate always provides it. Every test class has at
least one seeded fault that shows its check can fail.
"""
import os
from pathlib import Path
import re
import unittest

from swg_test_studio import agent_fixture as af
from swg_test_studio import model
from swg_test_studio.fixture_ops import character as ch

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "devtools" / "zones" / "fixtures"
JAVA = (FIXTURES / "agent_character.java").read_text(encoding="ISO-8859-1")
REFERENCE = (FIXTURES / "agent_fixture.java").read_text(encoding="ISO-8859-1")
TREE = Path(os.environ.get("SWG_RESTORATION_TREE") or "/nonexistent/restoration-tree")
HAVE_TREE = (TREE / "src/engine/server/application/CentralServer/Makefile.am").is_file()
SCRIPT = "dsrc/sku.0/sys.server/compiled/game/script/"

BOT = {"player": "123456789", "station": "4242", "character": "Capabcdefghijkl"}
IDENT = "123456789:4242:Capabcdefghijkl"
GUARD = ("request", "refusal", "num", "integer", "oid", "list", "botBuilding", "scope", "enc", "kv", "row", "end")

# op -> (args, scenario or None). One valid call per op.
SAMPLES = {
    "stats": ([], None),
    "buffs": (["me_buff_health_1"], None),
    "standing": (["Imperial"], None),
    "setHealth": (["2500"], None),
    "setAction": (["1800"], None),
    "setMaxHealth": (["12000"], None),
    "setMaxAction": (["9000"], None),
    "healFull": ([], None),
    "incapacitate": ([], None),
    "revive": ([], None),
    "setPosture": (["prone"], None),
    "setLevel": (["90"], None),
    "setProfession": (["commando_1a", "50"], None),
    "revokeSkills": (["class_commando_phase1_.*"], None),
    "resetExpertise": ([], None),
    "setBank": (["1000000"], None),
    "setCash": (["25000"], None),
    "depositCash": (["5000"], None),
    "withdrawCash": (["5000"], None),
    "setFaction": (["Rebel"], None),
    "setStanding": (["Rebel", "4500.5"], None),
    "setPvpType": (["declared"], None),
    "applyBuff": (["me_buff_health_1", "600"], None),
    "removeBuff": (["me_buff_health_1"], None),
    "equipItem": (["987654321"], None),
    "unequipItem": (["987654321"], None),
    "giveStaticCount": (["item_stimpack_a_01", "10"], "loadout_1"),
}

# Each argument kind and the Java token that re-validates it inside the method (or a helper it calls).
JAVA_VALIDATOR = {
    "char_pool": "POOL_RE", "char_level": "LEVEL_RE", "char_credits": "CREDITS_RE",
    "char_profession": "PROFESSIONS", "char_aligned": "ALIGNED", "char_faction": "FACTION_RE",
    "char_standing": "STANDING_RE", "char_pvp": "PVP_TYPES", "char_posture": "POSTURE_NAMES",
    "char_seconds": "SECONDS_RE", "char_count": "COUNT_RE", "name": "name(", "oid": "oid(",
    "regex": "skillPattern(", "scenario": "SCENARIO_RE",
}
# Java constant holding each kind's regex (string kinds) or allow-list (enumerations).
JAVA_REGEX = {"char_pool": "POOL_RE", "char_level": "LEVEL_RE", "char_credits": "CREDITS_RE",
              "char_faction": "FACTION_RE", "char_standing": "STANDING_RE", "char_seconds": "SECONDS_RE",
              "char_count": "COUNT_RE", "regex": "SKILL_PATTERN_RE", "scenario": "SCENARIO_RE"}
JAVA_LIST = {"char_profession": ("PROFESSIONS", ch.PROFESSIONS), "char_aligned": ("ALIGNED", ch.ALIGNED),
             "char_pvp": ("PVP_TYPES", ch.PVP_TYPES), "char_posture": ("POSTURE_NAMES", ch.POSTURES)}
CAPS = {"POOL_MAX": ch.POOL_MAX, "LEVEL_MAX": ch.LEVEL_MAX, "CREDITS_MAX": ch.CREDITS_MAX,
        "BUFF_SECONDS_MAX": ch.BUFF_SECONDS_MAX, "GIVE_COUNT_MAX": ch.GIVE_COUNT_MAX}

# The closed script API this class uses (docs/fixture-character.md lists it per op).
API_LIB = {
    "buff": {"getAllBuffs", "getBuffNameFromCrc", "getBuffTimeRemaining", "hasBuff", "applyBuff", "removeBuff"},
    "factions": {"getFactionNumber", "getFactionNameByHashCode", "getFactionStanding", "getFactionMax",
                 "setFactionStanding", "FACTION_TABLE"},
    "gm": {"getRoadmapList"},
    "healing": {"fullHeal"},
    "money": {"bankTo", "deposit", "withdraw", "ACCT_TEST"},
    "pclib": {"resurrectPlayer"},
    "respec": {"getCombatLevel", "autoLevelPlayer", "earnProfessionSkillsViaNpc"},
    "skill": {"recalcPlayerPools", "setPlayerStatsForLevel"},
    "static_item": {"createNewItemFunction", "MASTER_ITEM_TABLE"},
    "utils": {"getPlayerProfession", "getInventoryContainer", "fullExpertiseReset"},
}
API_BASE = {
    # guard (copied from agent_fixture.java)
    "getConfigSetting", "isIdValid", "exists", "isPlayer", "getPlayerFullName", "getPlayerStationId", "isGod",
    "getLocation", "getTopMostContainer", "getContainedBy", "getWorldLocation", "getCurrentSceneName", "getDistance",
    # family
    "getAttrib", "getMaxAttrib", "setAttrib", "setMaxAttrib", "getLevel", "getCashBalance", "getBankBalance",
    "getTotalMoney", "pvpGetAlignedFaction", "pvpGetType", "pvpSetAlignedFaction", "pvpMakeNeutral", "pvpMakeCovert",
    "pvpMakeDeclared", "pvpMakeOnLeave", "getPosture", "setPosture", "setPostureClientImmediate", "isIncapacitated",
    "isDead", "getSkillTemplate", "setSkillTemplate", "getSkillListingForPlayer", "revokeSkill", "hasSkill",
    "grantSkill", "dataTableGetInt", "dataTableSearchColumnForString", "getStringCrc", "equip", "putIn",
    "getTemplateName", "hasObjVar", "getStringObjVar", "setObjVar",
}
JAVA_WORDS = {"if", "for", "while", "switch", "return", "catch", "new", "super", "this", "synchronized", "throw",
              "valueOf", "max", "min", "format", "matches", "equals", "startsWith", "length", "charAt", "split",
              "trim", "substring", "parseLong", "parseInt", "parseFloat", "isNaN", "arraycopy", "toString",
              "append", "getBytes", "toUpperCase", "forDigit", "compile", "matcher", "floatValue", "getObjId",
              "isAuthoritative", "toUnsignedLong"}


def line(op, args=None, scenario=None, worker=7):
    sample_args, sample_scenario = SAMPLES[op]
    return af.command(worker, BOT, op, sample_args if args is None else args,
                      scenario=sample_scenario if scenario is None else scenario)


def parse(text):
    """Local reply parser for this family (sources/interface.md allows one)."""
    head, *rest = text.split()
    prefix, _, status = head.partition("=")
    fields = dict(t.split("=", 1) for t in rest if "=" in t and not t.startswith("row="))
    return prefix, status, fields, [t[4:] for t in rest if t.startswith("row=")]


# --- Java text helpers --------------------------------------------------------------------

def private_body(text, name):
    match = re.search(r"\n    private [^\n=;]*?\b" + re.escape(name) + r"\(", text)
    if not match:
        return None
    depth, index = 0, text.index("{", match.end())
    for index in range(index, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            break
    return " ".join(text[match.start():index + 1].split())


def public_methods(text):
    """op -> body text of each `public String op(String value)` method."""
    methods = {}
    for m in re.finditer(r"public String (\w+)\(String value\) throws InterruptedException \{", text):
        depth, index = 0, m.end() - 1
        for index in range(index, len(text)):
            depth += {"{": 1, "}": -1}.get(text[index], 0)
            if depth == 0:
                break
        methods[m.group(1)] = text[m.end():index]
    return methods


def helpers(text):
    return {m.group(1): private_body(text, m.group(1))
            for m in re.finditer(r"\n    private (?:static )?[\w\[\]<>.]+ (\w+)\(", text)}


def java_constant(text, name):
    m = re.search(r"private static final String " + name + r"=\"((?:[^\"\\]|\\.)*)\";", text)
    return None if m is None else m.group(1).replace("\\\\", "\\")


def java_list(text, name):
    m = re.search(r"private static final String\[\] " + name + r"=\{([^}]*)\}", text)
    return None if m is None else tuple(re.findall(r"\"([^\"]*)\"", m.group(1)))


def parity(text, registry):
    """Problems between agent_character.java and the family's ops; empty when they agree."""
    problems = []
    ops = {op for op, owner in registry.fixture_of.items() if owner == ch.FIXTURE}
    methods = public_methods(text)
    for op in sorted(ops - set(methods)):
        problems.append("no Java method for " + op)
    for name in sorted(set(methods) - ops):
        problems.append("Java method without an op: " + name)
    known = helpers(text)
    for op in sorted(ops & set(methods)):
        spec = registry.ops[op][0]
        extra = 1 if op in registry.scenario_ops else 0
        need = len([k for k in spec if not k.endswith("?")]) + extra
        first = re.match(r"\s*Object\[\] q=request\(value,\"(\w+)\",(\d+),(\d+)\);", methods[op])
        if not first or first.groups() != (op, str(need), str(len(spec) + extra)):
            problems.append(op + " does not start with request(value,\"%s\",%d,%d)" % (op, need, len(spec) + extra))
        body = methods[op] + "".join(b for n, b in known.items() if re.search(r"\b" + n + r"\(", methods[op]))
        kinds = [k.rstrip("?") for k in spec] + (["scenario"] if extra else [])
        for kind in kinds:
            if not re.search(r"(?<![A-Za-z0-9_])" + re.escape(JAVA_VALIDATOR[kind]), body):
                problems.append(f"{op} does not re-validate its {kind} argument")
    for kind, const in JAVA_REGEX.items():
        if java_constant(text, const) != registry.types[kind]:
            problems.append(f"Java {const} differs from the Python {kind} regex")
    for kind, (const, values) in JAVA_LIST.items():
        if java_list(text, const) != values or registry.types[kind] != "|".join(values):
            problems.append(f"Java {const} differs from the Python {kind} allow-list")
    for const, value in CAPS.items():
        if not re.search(r"private static final int " + const + "=" + str(value) + ";", text):
            problems.append(f"Java cap {const} differs from Python {value}")
    for const, value in (("STANDING_MIN", ch.STANDING_MIN), ("STANDING_MAX", ch.STANDING_MAX)):
        if not re.search(r"private static final float " + const + "=" + re.escape(f"{float(value)}f;"), text):
            problems.append(f"Java {const} differs from Python {value}")
    if not re.search(r"public class agent_character extends (script\.)?base_script \{", text):
        problems.append("class header")
    if re.search(r"\bnew\s+\w+\s*\([^)]*\)\s*\{|\b(class|interface|enum)\s+\w+[^\n]*\{", text.split("{", 1)[1]):
        problems.append("nested or anonymous type")
    return problems


def guard_problems(text):
    return [n for n in GUARD if private_body(text, n) is None or private_body(text, n) != private_body(REFERENCE, n)]


def calls(text):
    """Library calls lib.member and bare base calls of the class (string literals removed)."""
    code = re.sub(r"\"(?:[^\"\\]|\\.)*\"", "\"\"", re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S))
    lib = {}
    for m in re.finditer(r"\b(" + "|".join(API_LIB) + r"|[a-z_]+)\.([A-Za-z_]\w*)\b", code):
        lib.setdefault(m.group(1), set()).add(m.group(2))
    defined = {m.group(1) for m in re.finditer(r"\n    (?:private|public) [^\n=;(]*?\b(\w+)\(", code)}
    bare = {m.group(1) for m in re.finditer(r"(?<![.\w])([a-z]\w*)\s*\(", code)} - defined - JAVA_WORDS
    return lib, bare


class ModuleShapeTests(unittest.TestCase):
    def test_interface_names_only(self):
        public = {n for n in vars(ch) if not n.startswith("_") and n.isupper() or n == "check"}
        family_names = public & af.FAMILY_NAMES
        self.assertEqual(ch.FIXTURE, "agent_character")
        self.assertTrue({"FIXTURE", "TYPES", "OPS"} <= family_names)
        self.assertEqual(set(ch.SCENARIO_OPS), {"giveStaticCount"})
        self.assertFalse(hasattr(ch, "ROLE_ARGS"))

    def test_merges_into_the_real_registry(self):
        for op in ch.OPS:
            self.assertEqual(af.REGISTRY.fixture_of[op], "agent_character")
            self.assertEqual(af.OPS[op], ch.OPS[op])
        self.assertIn("agent_character", af.REGISTRY.fixtures)
        self.assertEqual(af.merge([("character", ch)]).families, {"character": "agent_character"})

    def test_every_numeric_kind_has_a_named_cap(self):
        numeric = {k for k, r in ch.TYPES.items() if r.startswith(("[0-9]", "-?[0-9]"))}
        self.assertEqual(numeric, set(ch.RANGES))
        for kind, (low, high) in ch.RANGES.items():
            self.assertLess(low, high, kind)

    def test_seeded_fault_a_clashing_kind_is_refused(self):
        class Broken:
            FIXTURE, TYPES, OPS = ch.FIXTURE, dict(ch.TYPES, oid=r"[0-9]+"), ch.OPS
        with self.assertRaises(ValueError):
            af.merge([("character", Broken)])


class ConsoleLineTests(unittest.TestCase):
    def test_every_op_has_a_sample(self):
        self.assertEqual(set(SAMPLES), set(ch.OPS))

    def test_exact_lines(self):
        expected = {
            "stats": f"game 7 runScript fixture.agent_character stats {IDENT}",
            "buffs": f"game 7 runScript fixture.agent_character buffs {IDENT} me_buff_health_1",
            "standing": f"game 7 runScript fixture.agent_character standing {IDENT} Imperial",
            "setHealth": f"game 7 runScript fixture.agent_character setHealth {IDENT} 2500",
            "setAction": f"game 7 runScript fixture.agent_character setAction {IDENT} 1800",
            "setMaxHealth": f"game 7 runScript fixture.agent_character setMaxHealth {IDENT} 12000",
            "setMaxAction": f"game 7 runScript fixture.agent_character setMaxAction {IDENT} 9000",
            "healFull": f"game 7 runScript fixture.agent_character healFull {IDENT}",
            "incapacitate": f"game 7 runScript fixture.agent_character incapacitate {IDENT}",
            "revive": f"game 7 runScript fixture.agent_character revive {IDENT}",
            "setPosture": f"game 7 runScript fixture.agent_character setPosture {IDENT} prone",
            "setLevel": f"game 7 runScript fixture.agent_character setLevel {IDENT} 90",
            "setProfession": f"game 7 runScript fixture.agent_character setProfession {IDENT} commando_1a 50",
            "revokeSkills": f"game 7 runScript fixture.agent_character revokeSkills {IDENT} class_commando_phase1_.*",
            "resetExpertise": f"game 7 runScript fixture.agent_character resetExpertise {IDENT}",
            "setBank": f"game 7 runScript fixture.agent_character setBank {IDENT} 1000000",
            "setCash": f"game 7 runScript fixture.agent_character setCash {IDENT} 25000",
            "depositCash": f"game 7 runScript fixture.agent_character depositCash {IDENT} 5000",
            "withdrawCash": f"game 7 runScript fixture.agent_character withdrawCash {IDENT} 5000",
            "setFaction": f"game 7 runScript fixture.agent_character setFaction {IDENT} Rebel",
            "setStanding": f"game 7 runScript fixture.agent_character setStanding {IDENT} Rebel 4500.5",
            "setPvpType": f"game 7 runScript fixture.agent_character setPvpType {IDENT} declared",
            "applyBuff": f"game 7 runScript fixture.agent_character applyBuff {IDENT} me_buff_health_1 600",
            "removeBuff": f"game 7 runScript fixture.agent_character removeBuff {IDENT} me_buff_health_1",
            "equipItem": f"game 7 runScript fixture.agent_character equipItem {IDENT} 987654321",
            "unequipItem": f"game 7 runScript fixture.agent_character unequipItem {IDENT} 987654321",
            "giveStaticCount":
                f"game 7 runScript fixture.agent_character giveStaticCount {IDENT} loadout_1 item_stimpack_a_01 10",
        }
        self.assertEqual(set(expected), set(ch.OPS))
        for op, text in expected.items():
            with self.subTest(op=op):
                self.assertEqual(line(op), text)

    def test_optional_arguments(self):
        self.assertEqual(line("buffs", []), f"game 7 runScript fixture.agent_character buffs {IDENT}")
        self.assertEqual(line("setProfession", ["medic_1a"]),
                         f"game 7 runScript fixture.agent_character setProfession {IDENT} medic_1a")

    def test_step_validation_and_plan(self):
        suite = {"format": "swg-test-studio", "schema_version": 1, "id": "char_probe", "title": "Character probe",
                 "category": "regression", "roles": ["actor"],
                 "review": {"approved": True, "recording": None, "unsupported": []},
                 "steps": [{"id": "lvl", "action": "agent_fixture",
                            "options": {"role": "actor", "op": "setLevel", "args": ["90"]}},
                           {"id": "look", "action": "agent_fixture",
                            "options": {"role": "actor", "op": "stats", "args": [], "expect": {"level": "90"}}}]}
        model.validate(suite)
        af.validate({"role": "actor", "op": "giveStaticCount", "args": ["item_x", "3"], "scenario": "s1"}, ["actor"])

    def test_reply_parsing(self):
        prefix, status, fields, rows = parse("agent_character=ok player=1 level=90 cash=25000 row=a,1.0 rows=1 truncated=false")
        self.assertEqual((prefix, status, fields["level"], rows), ("agent_character", "ok", "90", ["a,1.0"]))
        reply = af.parse("agent_character=ok level=90", "agent_character")
        self.assertIsNone(af.check(reply, {"level": "90"}))
        # Seeded fault: a reply of another class is not accepted for a character op.
        self.assertEqual(af.parse("agent_fixture=ok level=90", "agent_character")["status"], "unrecognized")

    def test_seeded_fault_a_wrong_line_is_caught(self):
        self.assertNotEqual(line("setLevel", ["89"]), f"game 7 runScript fixture.agent_character setLevel {IDENT} 90")


class TypedRefusalTests(unittest.TestCase):
    BAD = {
        "setHealth": ["0", "500001", "-5", "1e3", "12;game", "$(id)", "1 2", ""],
        "setMaxAction": ["0", "500001", "9999999"],
        "setLevel": ["0", "91", "100", "-1", "5.5"],
        "setBank": ["10000001", "-1", "99999999", "1,000"],
        "setCash": ["10000001", "abc"],
        "depositCash": ["10000001"],
        "withdrawCash": ["-100"],
        "setStanding": None,  # two arguments; below
        "applyBuff": None,
        "setProfession": None,
        "setFaction": ["imperial", "rebel", "God", "Hutt", "Imperial;x", "Neutral "],
        "setPvpType": ["gm", "Declared", "admin", "neutral;"],
        "setPosture": ["dead", "incapacitated", "Upright", "flying"],
        "standing": ["9faction", "Imp erial", "a" * 49, "Rebel'"],
        "removeBuff": ["Bad_Name", "buff name", "../x", "a" * 65],
        "equipItem": ["0", "-1", "12345678901234567890", "1a"],
        "revokeSkills": ["(a+)+", "a*b*c*", "a?b?c?d?", "x{1,9}", "\\d+", "a b", "(", "[a-"],
    }

    def refuse(self, op, args, scenario=None):
        with self.assertRaises(ValueError, msg=f"{op} {args}"):
            af.validate(dict({"role": "actor", "op": op, "args": args},
                             **({"scenario": scenario} if scenario else {})), ["actor"])

    def test_single_argument_refusals(self):
        for op, values in self.BAD.items():
            for value in values or ():
                with self.subTest(op=op, value=value):
                    self.refuse(op, [value])

    def test_two_argument_refusals(self):
        for args in (["Rebel", "-5001"], ["Rebel", "50001"], ["Rebel", "1.234"], ["Neutral", "10"],
                     ["Reb el", "10"], ["Rebel"]):
            self.refuse("setStanding", args)
        for args in (["me_buff_health_1", "0"], ["me_buff_health_1", "86401"], ["Me_Buff", "10"],
                     ["me_buff_health_1", "10.5"], ["me_buff_health_1"]):
            self.refuse("applyBuff", args)
        for args in (["admin_1a"], ["jedi_1a"], ["commando_2a"], ["commando_1a", "0"], ["commando_1a", "91"],
                     ["COMMANDO_1A"], ["commando_1a", "50", "x"]):
            self.refuse("setProfession", args)

    def test_scenario_rules(self):
        self.refuse("giveStaticCount", ["item_x", "3"])                    # no scenario
        self.refuse("giveStaticCount", ["item_x", "3"], "Bad-Id")           # malformed id
        self.refuse("giveStaticCount", ["item_x", "0"], "s1")
        self.refuse("giveStaticCount", ["item_x", "26"], "s1")
        self.refuse("giveStaticCount", ["Item X", "3"], "s1")
        self.refuse("stats", [], "s1")                                      # a read op takes no scenario
        with self.assertRaises(ValueError):
            af.command(7, BOT, "giveStaticCount", ["item_x", "3"])

    def test_argument_counts(self):
        self.refuse("stats", ["x"])
        self.refuse("healFull", ["1"])
        self.refuse("setHealth", [])
        self.refuse("setHealth", ["10", "20"])

    def test_every_sample_is_accepted(self):
        for op, (args, scenario) in SAMPLES.items():
            with self.subTest(op=op):
                af.validate(dict({"role": "actor", "op": op, "args": args},
                                 **({"scenario": scenario} if scenario else {})), ["actor"])

    def test_seeded_fault_widened_regex_would_admit_injection(self):
        loose = dict(ch.TYPES, char_pool=r"[0-9;a-z ]{1,9}")

        class Loose:
            FIXTURE, OPS, RANGES = ch.FIXTURE, ch.OPS, {}
            TYPES = loose
        registry = af.merge([("character", Loose)])
        af.arguments("setHealth", ["12;game"], registry)      # the widened kind lets it through ...
        with self.assertRaises(ValueError):                    # ... which the real family refuses
            af.arguments("setHealth", ["12;game"])


class JavaParityTests(unittest.TestCase):
    def test_java_matches_python(self):
        self.assertEqual(parity(JAVA, af.REGISTRY), [])

    def test_guard_is_copied_verbatim(self):
        self.assertEqual(guard_problems(JAVA), [])
        self.assertIn('private static final String P="agent_character=";', JAVA)

    def test_core_parity_rules_hold_too(self):
        # The same rule CORE applies to every family class: first statement request(value,"op",min,max).
        for op, body in public_methods(JAVA).items():
            self.assertRegex(body, r"^\s*Object\[\] q=request\(value,\"" + op + r"\",\d+,\d+\);")

    def test_seeded_faults_are_detected(self):
        self.assertIn("no Java method for setLevel", parity(JAVA.replace("public String setLevel(", "public String setLvl("), af.REGISTRY))
        self.assertTrue(any("setLevel does not start" in p for p in
                            parity(JAVA.replace('request(value,"setLevel",1,1)', 'request(value,"setLevel",1,2)'), af.REGISTRY)))
        self.assertTrue(any("giveStaticCount does not start" in p for p in
                            parity(JAVA.replace('request(value,"giveStaticCount",3,3)', 'request(value,"giveStaticCount",2,2)'), af.REGISTRY)))
        self.assertIn("setBank does not re-validate its char_credits argument",
                      parity(JAVA.replace("Integer target=bounded(args[0],CREDITS_RE,0,CREDITS_MAX);\n        if(target==null) return invalidArgs(\"credits\");\n        int bank",
                                          "Integer target=Integer.valueOf(args[0]);\n        int bank"), af.REGISTRY))
        self.assertIn("Java POOL_RE differs from the Python char_pool regex",
                      parity(JAVA.replace('POOL_RE="[0-9]{1,6}"', 'POOL_RE="[0-9]{1,7}"'), af.REGISTRY))
        self.assertIn("Java cap LEVEL_MAX differs from Python 90", parity(JAVA.replace("LEVEL_MAX=90;", "LEVEL_MAX=99;"), af.REGISTRY))
        self.assertIn("Java PROFESSIONS differs from the Python char_profession allow-list",
                      parity(JAVA.replace('"spy_1a",', '"spy_1a","jedi_1a",'), af.REGISTRY))
        self.assertIn("nested or anonymous type",
                      parity(JAVA.replace("extends base_script {", "extends base_script {\n    static class X {}"), af.REGISTRY))
        self.assertEqual(guard_problems(JAVA.replace('schema.matches("WGC_[A-F0-9]{12}")', 'schema.matches("WGC_.*")')), ["request"])
        self.assertEqual(guard_problems(JAVA.replace("if(isPlayer(c)) return", "if(false) return")), ["scope"])


class SafetyTests(unittest.TestCase):
    FORBIDDEN = ("setGod", "setAdmin", "grantCommand", "sendConsoleCommand", "attachScript", "detachScript",
                 "Runtime.getRuntime", "ProcessBuilder", "Class.forName", "getClass", "reflect", "setGodMode", "executeCommand",
                 "queueCommand", "grantSkillToPlayer", "admin", "java.io.File")

    def code(self, text):
        return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)

    def problems(self, text):
        code = self.code(text)
        found = [w for w in self.FORBIDDEN if w in code]
        found += [f"grantSkill({m})" for m in re.findall(r"\bgrantSkill\(bot,([^)]*)\)", code) if m != '"expertise"']
        if len(re.findall(r"\bisGod\(", code)) != 1:
            found.append("isGod outside the guard")
        if "setObjVar(item,SCENARIO_VAR,scenario)" not in code or "setObjVar(item,OWNER_VAR,bot)" not in code:
            found.append("created items are not tagged")
        for name in ("POOL_MAX", "LEVEL_MAX", "CREDITS_MAX", "BUFF_SECONDS_MAX", "GIVE_COUNT_MAX", "REVOKE_MAX",
                     "STANDING_MAX"):
            if not re.search(r"\b" + name + r"\b(?!=)", code.split(name + "=", 1)[-1]):
                found.append(name + " unused")
        return found

    def test_no_god_admin_free_form_or_untagged_creation(self):
        self.assertEqual(self.problems(JAVA), [])
        self.assertIn('fixture.scenario_open', JAVA)

    def test_seeded_faults_are_detected(self):
        self.assertIn("setGod", self.problems(JAVA.replace("pvpMakeNeutral(bot);\n        pvpSetAlignedFaction",
                                                           "setGod(bot,true);pvpMakeNeutral(bot);\n        pvpSetAlignedFaction")))
        self.assertIn('grantSkill("admin")', [p.replace("bot,", "") for p in
                      self.problems(JAVA.replace('grantSkill(bot,"expertise")', 'grantSkill(bot,"admin")'))])
        self.assertIn("created items are not tagged", self.problems(JAVA.replace("setObjVar(item,OWNER_VAR,bot);", "")))


class ApiClosureTests(unittest.TestCase):
    """Every call goes to the closed API lists above (listed per op in docs/fixture-character.md)."""

    def test_calls_are_in_the_closed_lists(self):
        lib, bare = calls(JAVA)
        libraries = {k: v for k, v in lib.items() if k in API_LIB}
        for name, members in libraries.items():
            self.assertLessEqual(members, API_LIB[name], name)
        self.assertLessEqual(bare, API_BASE)
        self.assertEqual(set(libraries), set(API_LIB))

    def test_notes_list_every_api_function(self):
        notes = (ROOT / "docs" / "fixture-character.md").read_text(encoding="utf-8")
        for name in sorted(API_BASE | {m for v in API_LIB.values() for m in v}):
            self.assertIn(name, notes)
        for op in ch.OPS:
            self.assertIn(f"`{op}`", notes)

    def test_seeded_fault_an_unlisted_call_is_found(self):
        _, bare = calls(JAVA.replace("pvpMakeNeutral(bot);\n        pvpSetAlignedFaction",
                                     "setInvulnerable(bot,true);pvpMakeNeutral(bot);\n        pvpSetAlignedFaction"))
        self.assertIn("setInvulnerable", bare - API_BASE)


@unittest.skipUnless(HAVE_TREE, "needs SWG_RESTORATION_TREE (the gate provides it)")
class ServerTreeGroundingTests(unittest.TestCase):
    """The API, allow-lists and caps against the Dec 2011 server tree."""

    def library(self, name):
        return (TREE / SCRIPT / "library" / (name + ".scriptlib")).read_text(encoding="ISO-8859-1")

    def base(self):
        return "".join((TREE / SCRIPT / f).read_text(encoding="ISO-8859-1") for f in ("base_class.java", "base_script.java"))

    def missing(self, lib, base):
        gone = []
        for name, members in lib.items():
            text = self.library(name)
            for member in members:
                if not re.search(r"(?m)^[ \t]*(?:const[ \t]+)?[\w\[\]]+[ \t]+" + member + r"[ \t]*(\(|=)", text):
                    gone.append(f"{name}.{member}")
        text = self.base()
        for member in base:
            if not re.search(r"public static (?:final )?(?:native )?[\w\[\]]+\s+" + member + r"\s*[(=]", text):
                gone.append(member)
        return gone

    def test_every_call_exists(self):
        self.assertEqual(self.missing(API_LIB, API_BASE), [])

    def test_roadmaps_are_gm_get_roadmap_list(self):
        text = self.library("gm")
        body = text[text.index("getRoadmapList()"):]
        body = body[:body.index("}")]
        self.assertEqual(tuple(re.findall(r"\"([a-z_0-9]+)\"", body)), ch.PROFESSIONS)

    def test_factions_levels_and_caps(self):
        rows = [r.split("\t") for r in (TREE / "dsrc/sku.0/sys.server/compiled/game/datatables/faction/faction.tab")
                .read_text(encoding="ISO-8859-1").splitlines()[2:]]
        table = {r[0]: r for r in rows if r and r[0]}
        for name in ("Imperial", "Rebel"):
            self.assertEqual(table[name][1], "1")          # playerAllowed
            self.assertTrue(table[name][4])               # pvpFaction
        self.assertNotEqual(table["Neutral"][1], "1")
        levels = (TREE / "dsrc/sku.0/sys.shared/compiled/game/datatables/player/player_level.tab") \
            .read_text(encoding="ISO-8859-1").splitlines()[2:]
        self.assertEqual(len([r for r in levels if r.strip()]), ch.LEVEL_MAX)
        self.assertIn("FACTION_RATING_MIN", self.library("factions"))
        self.assertRegex(self.library("factions"), r"FACTION_RATING_MIN\s*=\s*" + str(ch.STANDING_MIN))
        self.assertRegex(self.library("money"), r"ACCT_TEST\s*=\s*\"testing\"")

    def test_seeded_fault_a_missing_function_is_reported(self):
        self.assertEqual(self.missing({"respec": {"setLevelDirectly"}}, {"setGodModeNow"}),
                         ["respec.setLevelDirectly", "setGodModeNow"])


if __name__ == "__main__":
    unittest.main()
