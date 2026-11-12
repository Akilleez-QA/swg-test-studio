"""Per-op guards of the family fixture classes, each pinned with its effect (offline).

Each row of CHECKS names one guard: the Java method or helper it lives in and the exact
statement that checks and refuses (the guard WITH its effect, so deleting the refusal or
weakening the condition is caught). MUTANTS are seeded faults: each is the old or a weakened
behaviour of one guard, and the test asserts that its check catches it. The Python mirrors of
the Java allow-lists and their grounding in the server tree are checked here too.
"""
import os
from pathlib import Path
import re
import unittest

from swg_test_studio import agent_fixture as af
from swg_test_studio.fixture_ops import character as ch
from swg_test_studio.fixture_ops import scenario as sc

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "devtools" / "zones" / "fixtures"
CLASSES = ("agent_fixture", "agent_character", "agent_scenario", "agent_multi")
TEXTS = {name: (FIXTURES / (name + ".java")).read_text(encoding="ISO-8859-1") for name in CLASSES}
TREE = Path(os.environ.get("SWG_RESTORATION_TREE") or "/nonexistent/restoration-tree")
HAVE_TREE = (TREE / "src/engine/server/application/CentralServer/Makefile.am").is_file()
SERVER = TREE / "dsrc/sku.0/sys.server/compiled/game"
SHARED = TREE / "dsrc/sku.0/sys.shared/compiled/game"


def body(text, name):
    """A public op method or private helper, signature through closing brace, whitespace-normalised."""
    match = re.search(r"\n    (?:public|private) [^\n=;]*?\b" + re.escape(name) + r"\(", text)
    if not match:
        return None
    depth, index = 0, text.index("{", match.end())
    for index in range(index, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            break
    return " ".join(text[match.start():index + 1].split())


def java_list(text, name):
    match = re.search(r"private static final String\[\] " + name + r"=\{([^}]*)\}", text)
    return None if match is None else tuple(re.findall(r'"([^"]*)"', match.group(1)))


def java_int(text, name):
    match = re.search(r"private static final int " + name + r"=([0-9]+);", text)
    return None if match is None else int(match.group(1))


def norm(snippet):
    return " ".join(snippet.split())


# (check name, class, method or helper, statements that must all be present, normalised)
CHECKS = [
    # Character family
    ("equipItem scope", "agent_character", "equipItem",
     ["String s=scope(bot,item,false); if(s!=null) return fail(s);",
      'if(!inventory.equals(getContainedBy(item))) return fail("out-of-scope reason=not-in-inventory object="+item);']),
    ("unequipItem scope", "agent_character", "unequipItem", ["String s=scope(bot,item,false); if(s!=null) return fail(s);"]),
    ("giveStaticCount open scenario and cap", "agent_character", "giveStaticCount",
     ["String s=mayCreate(bot,scenario,count); if(s!=null) return fail(s);"]),
    ("giveStaticCount tags each item", "agent_character", "giveStaticCount",
     ["if(tag(bot,item,scenario)) {created++;row(sb,rc,item);} else failed++;"]),
    ("setCash bank check", "agent_character", "setCash",
     ['if(diff>bank) return fail("refused reason=bank-too-low bank="+bank+" needed="+diff);']),
    ("setCash credit cap", "agent_character", "setCash",
     ["String cap=creditCap((long)cash+bank); if(cap!=null) return fail(cap);"]),
    ("setBank credit cap", "agent_character", "setBank",
     ["String cap=creditCap((long)getCashBalance(bot)+target); if(cap!=null) return fail(cap);"]),
    ("depositCash credit cap", "agent_character", "depositCash",
     ["String cap=creditCap((long)getCashBalance(bot)+getBankBalance(bot)); if(cap!=null) return fail(cap);"]),
    ("withdrawCash credit cap", "agent_character", "withdrawCash",
     ["String cap=creditCap((long)getCashBalance(bot)+getBankBalance(bot)); if(cap!=null) return fail(cap);"]),
    ("creditCap compares the total with CREDITS_MAX", "agent_character", "creditCap",
     ['return total>CREDITS_MAX?"refused reason=credits-cap total="+total+" cap="+CREDITS_MAX:null;']),
    ("applyBuff allow-list", "agent_character", "applyBuff",
     ['if(!allowedBuff(n)) return fail("refused reason=buff-not-allowed buff="+n);',
      "Integer seconds=bounded(args[1],SECONDS_RE,1,BUFF_SECONDS_MAX);",
      "if(ok) setObjVar(bot,RESET_ROOT+\".buff.\"+n,1);"]),
    ("allowedBuff deny before prefix", "agent_character", "allowedBuff",
     ["for(String deny:BUFF_DENY) if(n.contains(deny)) return false;",
      "for(String prefix:BUFF_PREFIXES) if(n.startsWith(prefix)) return true; return false;"]),
    ("setProfession without roadmap items", "agent_character", "setProfession",
     ["respec.revokeAllSkillsAndExperience(bot);",
      "boolean ok=respec.autoLevelPlayer(bot,Math.max(RESPEC_LEVEL_MIN,level),false);"]),
    ("resetCharacter clears fixture objvars", "agent_character", "resetCharacter",
     ["removeObjVar(bot,TEST_VAR_ROOT); removeObjVar(bot,SNAPSHOT_ROOT); removeObjVar(bot,RESET_ROOT);",
      "if(n!=null && buff.hasBuff(bot,n) && buff.removeBuff(bot,n)) buffs++;",
      "skill.recalcPlayerPools(bot,true); setAttrib(bot,HEALTH,getMaxAttrib(bot,HEALTH)); "
      "setAttrib(bot,ACTION,getMaxAttrib(bot,ACTION));"]),
    ("setStanding records the original", "agent_character", "setStanding",
     ['if(!hasObjVar(bot,RESET_ROOT+".standing."+f)) setObjVar(bot,RESET_ROOT+".standing."+f,'
      "factions.getFactionStanding(bot,f));"]),
    # Scenario family
    ("template deny list", "agent_scenario", "template",
     ["if(s==null || s.length()>TEMPLATE_MAX || !s.matches(TEMPLATE_RE)) return null;",
      "for(String deny:TEMPLATE_DENY) if(s.contains(deny)) return null;"]),
    ("createAt destination distance", "agent_scenario", "createAt",
     ['if(b==null || getDistance(target,b)>SCOPE_RANGE) return fail("out-of-scope reason=destination-distance");',
      "String s=mayCreate(bot,id,1); if(s!=null) return fail(s);"]),
    ("createInCell scope and cap", "agent_scenario", "createInCell",
     ["String s=scope(bot,building,false); if(s==null) s=mayCreate(bot,id,1); if(s!=null) return fail(s);"]),
    ("createInInventory cap", "agent_scenario", "createInInventory",
     ["String s=mayCreate(bot,id,count); if(s!=null) return fail(s);"]),
    ("spawnCreature cap and scripted rows", "agent_scenario", "spawnCreature",
     ["String s=mayCreate(bot,id,1); if(s!=null) return fail(s);",
      'String scripts=dataTableGetString(create.CREATURE_TABLE,row,"scripts"); if(scripts!=null && '
      'scripts.trim().length()>0) return fail("refused reason=scripted-creature name="+enc(name));']),
    ("mayCreate open scenario", "agent_scenario", "mayCreate",
     ['if(!id.equals(openScenario(bot))) return "refused reason=scenario-not-open scenario="+id;']),
    ("mayCreate cap", "agent_scenario", "mayCreate",
     ['if(created+n>SCENARIO_CREATE_MAX) return "refused reason=scenario-cap cap="+SCENARIO_CREATE_MAX;']),
    ("tag records and destroys on failure", "agent_scenario", "tag",
     ["if(!setObjVar(o,TAG_SCENARIO,id) || !setObjVar(o,TAG_OWNER,bot)) {destroyObject(o);return false;}",
      "if(!storeIds(bot,ids)) {destroyObject(o);return false;}"]),
    ("scenarioEnd keeps a leaking scenario open", "agent_scenario", "scenarioEnd",
     ["if(exists(o) || !homeScene) leaked.add(o); else gone++;",
      "boolean clean=failed==0 && !truncated && leaked.isEmpty();",
      "if(wasOpen && clean) {removeObjVar(bot,OPEN_VAR);removeObjVar(bot,CREATED_VAR);",
      'StringBuilder sb=start(failed>0 || truncated?"refused":(leaked.isEmpty()?"ok":"partial"));',
      'kv(sb,"leaked",leaked.size());']),
    ("scenarioEnd clears snapshots", "agent_scenario", "scenarioEnd",
     ["if(snapshots) removeObjVar(bot,SNAPSHOT_ROOT);"]),
    ("destroyCreated forgets", "agent_scenario", "destroyCreated", ["if(ok) forget(bot,o);"]),
    ("creatureDespawn forgets", "agent_scenario", "creatureDespawn", ["if(ok) forget(bot,c);"]),
    ("warpScene keeps created objects reachable", "agent_scenario", "warpScene",
     ['if(!scene.equals(home)) return fail("refused reason=scenario-open open="+enc(open)+" home="+enc(home));']),
    # Multi family
    ("giveTo scope", "agent_multi", "giveTo", ["String s=scope(bot,item,false); if(s!=null) return fail(s);"]),
    ("giveTo carried in the inventory", "agent_multi", "giveTo",
     ['if(!inInventory(bot,item)) return fail("out-of-scope reason=not-in-inventory object="+item);']),
    ("giveTo refuses fixture-created items", "agent_multi", "giveTo",
     ['if(fixtureCreated(item)) return fail("refused reason=fixture-created object="+item);']),
    ("inInventory chain through the inventory", "agent_multi", "inInventory",
     ["if(c.equals(inventory)) return bot.equals(getContainedBy(inventory));",
      "if(c.equals(bot) || isPlayer(c)) return false;"]),
    ("bring same scene", "agent_multi", "bring",
     ["if(here==null || bw==null || pw==null || pw.area==null || !pw.area.equals(bw.area)) "
      'return fail("out-of-scope reason=partner-scene");']),
    ("bring partner down or in combat", "agent_multi", "bring",
     ['if(isDead(other) || isIncapacitated(other)) return fail("refused reason=partner-down");',
      'if(getState(other,STATE_COMBAT)!=0) return fail("refused reason=partner-in-combat");']),
    ("groupLeave leadership hand-off", "agent_multi", "groupLeave",
     ["if(isIdValid(m) && !m.equals(bot) && !m.equals(other)) "
      'return fail("refused reason=would-hand-leadership member="+m);']),
    ("payTo partner credit cap", "agent_multi", "payTo",
     ["String cap=creditCap((long)getCashBalance(other)+getBankBalance(other)+amount); if(cap!=null) return fail(cap);"]),
    ("snapshot size cap", "agent_multi", "carried", ["return ids.size()>SNAPSHOT_ITEMS_MAX?null:ids;"]),
]


def problems(texts):
    """Names of the CHECKS that do not hold in these class texts, plus class-wide rules."""
    found = []
    for name, cls, member, statements in CHECKS:
        text = body(texts[cls], member)
        if text is None or any(norm(s) not in text for s in statements):
            found.append(name)
    character, scenario, multi = texts["agent_character"], texts["agent_scenario"], texts["agent_multi"]
    if not {"/shared_", "/player/", "/terminal/", "/spawning/", "/gm/", "/deed/", "character_builder", "admin"} \
            <= set(java_list(scenario, "TEMPLATE_DENY") or ()):
        found.append("template deny list")
    if java_int(scenario, "SCENARIO_CREATE_MAX") != java_int(character, "SCENARIO_CREATE_MAX"):
        found.append("one scenario cap")
    if java_int(multi, "SNAPSHOT_ITEMS_MAX") is None or java_int(multi, "SNAPSHOT_ITEMS_MAX") > 100:
        found.append("snapshot size cap")
    if java_int(multi, "CREDITS_MAX") != java_int(character, "CREDITS_MAX"):
        found.append("payTo partner credit cap")
    if "earnProfessionSkillsViaNpc" in re.sub(r"/\*.*?\*/", "", character, flags=re.S):
        found.append("setProfession without roadmap items")
    for cls, text in texts.items():
        if re.search(r"String\.format\(\"", text):
            found.append("locale-independent numbers in " + cls)
        if "claude" in text:
            found.append("no private names in " + cls)
    return found


def mutate(cls, old, new, count=1):
    text = TEXTS[cls]
    if text.count(old) < count:
        raise AssertionError(f"mutant text not found in {cls}: {old[:60]}")
    return dict(TEXTS, **{cls: text.replace(old, new)})


# (check it must trip, class, old text, new text): seeded faults, the reviewers' mutants first.
MUTANTS = [
    ("equipItem scope", "agent_character",
     "        String s=scope(bot,item,false);\n        if(s!=null) return fail(s);\n        obj_id inventory=utils.getInventoryContainer(bot);\n        if(!isIdValid(inventory)) return fail(\"refused reason=no-inventory\");\n        if(!inventory.equals",
     "        obj_id inventory=utils.getInventoryContainer(bot);\n        if(!isIdValid(inventory)) return fail(\"refused reason=no-inventory\");\n        if(!inventory.equals"),
    ("giveStaticCount open scenario and cap", "agent_character",
     "        String s=mayCreate(bot,scenario,count);\n        if(s!=null) return fail(s);\n        if(dataTableSearchColumnForString(n,\"name\",static_item",
     "        if(dataTableSearchColumnForString(n,\"name\",static_item"),
    ("setCash bank check", "agent_character",
     "        if(diff>bank) return fail(\"refused reason=bank-too-low bank=\"+bank+\" needed=\"+diff);\n", ""),
    ("template deny list", "agent_scenario",
     '"/shared_","/player/","/terminal/"', '"/terminal/"'),
    ("template deny list", "agent_scenario",
     "        for(String deny:TEMPLATE_DENY) if(s.contains(deny)) return null;\n", ""),
    ("createAt destination distance", "agent_scenario",
     "        if(b==null || getDistance(target,b)>SCOPE_RANGE) return fail(\"out-of-scope reason=destination-distance\");\n", ""),
    ("mayCreate cap", "agent_scenario",
     "        if(created+n>SCENARIO_CREATE_MAX) return \"refused reason=scenario-cap cap=\"+SCENARIO_CREATE_MAX;\n", ""),
    ("giveTo scope", "agent_multi",
     "        String s=scope(bot,item,false);\n        if(s!=null) return fail(s);\n        if(!inInventory",
     "        if(!inInventory"),
    ("giveTo carried in the inventory", "agent_multi",
     "        if(!inInventory(bot,item)) return fail(\"out-of-scope reason=not-in-inventory object=\"+item);\n", ""),
    ("bring same scene", "agent_multi", " || !pw.area.equals(bw.area))", ")"),
    # Further weakenings of the guards added with them.
    ("giveStaticCount tags each item", "agent_character", "if(tag(bot,item,scenario)) {created++;",
     "if(isIdValid(item)) {created++;"),
    ("setBank credit cap", "agent_character", "String cap=creditCap((long)getCashBalance(bot)+target);",
     "String cap=creditCap(target);"),
    ("depositCash credit cap", "agent_character",
     "        if(amount>getCashBalance(bot)) return fail(\"refused reason=not-enough-cash cash=\"+getCashBalance(bot));\n        String cap=creditCap((long)getCashBalance(bot)+getBankBalance(bot));\n        if(cap!=null) return fail(cap);\n",
     "        if(amount>getCashBalance(bot)) return fail(\"refused reason=not-enough-cash cash=\"+getCashBalance(bot));\n"),
    ("creditCap compares the total with CREDITS_MAX", "agent_character", "return total>CREDITS_MAX?", "return total>2*CREDITS_MAX?"),
    ("applyBuff allow-list", "agent_character", "        if(!allowedBuff(n)) return fail(\"refused reason=buff-not-allowed buff=\"+n);\n", ""),
    ("allowedBuff deny before prefix", "agent_character", "        for(String deny:BUFF_DENY) if(n.contains(deny)) return false;\n", ""),
    ("setProfession without roadmap items", "agent_character",
     "        respec.revokeAllSkillsAndExperience(bot);\n        boolean ok=respec.autoLevelPlayer(bot,Math.max(RESPEC_LEVEL_MIN,level),false);",
     "        respec.earnProfessionSkillsViaNpc(bot,args[0],false,level);\n        boolean ok=true;"),
    ("resetCharacter clears fixture objvars", "agent_character", "        removeObjVar(bot,SNAPSHOT_ROOT);\n        removeObjVar(bot,RESET_ROOT);\n", ""),
    ("spawnCreature cap and scripted rows", "agent_scenario",
     "        if(scripts!=null && scripts.trim().length()>0) return fail(\"refused reason=scripted-creature name=\"+enc(name));\n", ""),
    ("mayCreate open scenario", "agent_scenario", "if(!id.equals(openScenario(bot))) return", "if(openScenario(bot)==null) return"),
    ("tag records and destroys on failure", "agent_scenario", "        if(!storeIds(bot,ids)) {destroyObject(o);return false;}\n", "        storeIds(bot,ids);\n"),
    ("scenarioEnd keeps a leaking scenario open", "agent_scenario", "boolean clean=failed==0 && !truncated && leaked.isEmpty();",
     "boolean clean=failed==0 && !truncated;"),
    ("scenarioEnd keeps a leaking scenario open", "agent_scenario", "if(exists(o) || !homeScene) leaked.add(o);",
     "if(exists(o)) leaked.add(o);"),
    ("scenarioEnd keeps a leaking scenario open", "agent_scenario", '(leaked.isEmpty()?"ok":"partial")', '"ok"'),
    ("scenarioEnd clears snapshots", "agent_scenario", "        if(snapshots) removeObjVar(bot,SNAPSHOT_ROOT);\n", ""),
    ("destroyCreated forgets", "agent_scenario", "        if(ok) forget(bot,o);\n", ""),
    ("creatureDespawn forgets", "agent_scenario", "        if(ok) forget(bot,c);\n", ""),
    ("warpScene keeps created objects reachable", "agent_scenario",
     "            if(!scene.equals(home)) return fail(\"refused reason=scenario-open open=\"+enc(open)+\" home=\"+enc(home));\n", ""),
    ("giveTo refuses fixture-created items", "agent_multi",
     "        if(fixtureCreated(item)) return fail(\"refused reason=fixture-created object=\"+item);\n", ""),
    ("inInventory chain through the inventory", "agent_multi", "            if(c.equals(bot) || isPlayer(c)) return false;\n", ""),
    ("bring partner down or in combat", "agent_multi",
     "        if(getState(other,STATE_COMBAT)!=0) return fail(\"refused reason=partner-in-combat\");\n", ""),
    ("groupLeave leadership hand-off", "agent_multi", "!m.equals(bot) && !m.equals(other)", "false"),
    ("payTo partner credit cap", "agent_multi", "String cap=creditCap((long)getCashBalance(other)+getBankBalance(other)+amount);",
     "String cap=creditCap(amount);"),
    ("snapshot size cap", "agent_multi", "SNAPSHOT_ITEMS_MAX=100;", "SNAPSHOT_ITEMS_MAX=500;"),
    ("locale-independent numbers in agent_multi", "agent_multi",
     'String.format(java.util.Locale.ROOT,"%.1f",getDistance(bot,other))', 'String.format("%.1f",getDistance(bot,other))'),
    ("no private names in agent_fixture", "agent_fixture", 'DECOR_TAG_VAR="fixture.decor"', 'DECOR_TAG_VAR="claude.decor"'),
    ("one scenario cap", "agent_character", "SCENARIO_CREATE_MAX=100;", "SCENARIO_CREATE_MAX=200;"),
]


class GuardTableTests(unittest.TestCase):
    def test_every_guard_holds(self):
        self.assertEqual(problems(TEXTS), [])

    def test_every_mutant_is_caught(self):
        for name, cls, old, new in MUTANTS:
            with self.subTest(check=name, mutant=old[:60]):
                self.assertIn(name, problems(mutate(cls, old, new)))

    def test_every_check_has_a_mutant(self):
        checked = {name for name, *_ in CHECKS}
        self.assertLessEqual(checked - {"unequipItem scope", "createInCell scope and cap", "createInInventory cap",
                                        "setCash credit cap", "withdrawCash credit cap",
                                        "setStanding records the original"},
                             {name for name, *_ in MUTANTS})


class SharedHelperTests(unittest.TestCase):
    SCENARIO_HELPERS = ("openScenario", "mayCreate", "liveIds", "storeIds", "tag", "forget")

    def test_scenario_bookkeeping_is_one_copy(self):
        for name in self.SCENARIO_HELPERS:
            with self.subTest(helper=name):
                self.assertIsNotNone(body(TEXTS["agent_scenario"], name))
                self.assertEqual(body(TEXTS["agent_character"], name), body(TEXTS["agent_scenario"], name))
        for const in ("TAG_SCENARIO", "TAG_OWNER", "OPEN_VAR", "CREATED_VAR", "IDS_VAR", "SCENARIO_CREATE_MAX"):
            line = re.search(r"private static final \w+ " + const + r"=.*;", TEXTS["agent_scenario"]).group(0)
            self.assertIn(line, TEXTS["agent_character"], const)
        self.assertEqual(body(TEXTS["agent_multi"], "creditCap"), body(TEXTS["agent_character"], "creditCap"))
        # Seeded fault: a cap edited in one copy only.
        edited = TEXTS["agent_character"].replace("if(created+n>SCENARIO_CREATE_MAX)", "if(created>SCENARIO_CREATE_MAX)")
        self.assertNotEqual(body(edited, "mayCreate"), body(TEXTS["agent_scenario"], "mayCreate"))

    def test_python_caps_match_java(self):
        self.assertEqual(java_int(TEXTS["agent_scenario"], "SCENARIO_CREATE_MAX"), sc.SCENARIO_CREATE_MAX)
        self.assertEqual(java_int(TEXTS["agent_character"], "BUFF_SECONDS_MAX"), ch.BUFF_SECONDS_MAX)
        self.assertLessEqual(ch.BUFF_SECONDS_MAX, 6 * 3600)
        self.assertEqual(ch.RANGES["char_seconds"], (1, ch.BUFF_SECONDS_MAX))


class TemplateAllowListTests(unittest.TestCase):
    def test_java_and_python_hold_the_same_lists(self):
        self.assertEqual(java_list(TEXTS["agent_scenario"], "TEMPLATE_DENY"), sc.TEMPLATE_DENY)
        regex = re.search(r'TEMPLATE_RE="(.*?)";', TEXTS["agent_scenario"]).group(1).replace("\\\\", "\\")
        self.assertEqual(regex, sc.TYPES["objtemplate"])
        for subtree in sc.TEMPLATE_SUBTREES:
            self.assertIn(subtree.split("/")[1], regex)

    def check(self, template, registry=None):
        return af.arguments("createAt", [template, "1", "2", "0"], registry)

    def test_admin_spawner_and_deny_listed_templates_are_refused(self):
        refused = ["object/tangible/terminal/terminal_character_builder.iff",
                   "object/tangible/spawning/spawn_egg.iff", "object/tangible/gm/x.iff",
                   "object/tangible/deed/player_house_deed/x.iff", "object/tangible/creature_spawner/x.iff",
                   "object/tangible/lair/x.iff", "object/tangible/item/x.iff", "object/tangible/x.iff",
                   "object/tangible/furniture/terminal/terminal_serving_droid.iff",
                   "object/tangible/furniture/all/admin_chair.iff",
                   "object/tangible/loot/misc/character_builder_x.iff",
                   "object/tangible/loot/gm/x.iff", "object/tangible/loot/deed/x.iff",
                   "object/tangible/loot/spawning/x.iff", "object/tangible/loot/misc/shared_x.iff",
                   "object/weapon/creature/x.iff", "object/static/terrain/x.iff"]
        for template in refused:
            with self.subTest(template=template), self.assertRaises(ValueError):
                self.check(template)
        for template in ("object/tangible/furniture/all/frn_all_chair_wooden_s1.iff",
                         "object/tangible/container/drum/treasure_drum.iff", "object/weapon/ranged/rifle/x.iff",
                         "object/static/item/item_x.iff"):
            self.check(template)

    def test_seeded_fault_python_check_without_the_deny_list(self):
        unchecked = af.merge([("scenario", sc)])
        unchecked.checks = {}
        self.assertEqual(self.check("object/tangible/furniture/terminal/terminal_serving_droid.iff", unchecked)[0],
                         "object/tangible/furniture/terminal/terminal_serving_droid.iff")


class BuffAllowListTests(unittest.TestCase):
    def test_java_and_python_hold_the_same_lists(self):
        self.assertEqual(java_list(TEXTS["agent_character"], "BUFF_PREFIXES"), ch.BUFF_PREFIXES)
        self.assertEqual(java_list(TEXTS["agent_character"], "BUFF_DENY"), ch.BUFF_DENY)

    def test_rule(self):
        for name in ("me_buff_health_1", "drink_jawa_beer", "dish_rations", "dessert_felbar", "foraged_bugs"):
            af.arguments("applyBuff", [name, "60"])
        for name in ("me_stasis_1", "me_evasion_1", "player_root_immunity", "boss_snare_immunity", "testlongbuff",
                     "drink_god_x", "dish_gm_x", "foraged_admin", "invis_x", "set_bonus_x"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                af.arguments("applyBuff", [name, "60"])
        # Seeded fault: without the family check every buff-table name passes the core kind.
        loose = af.merge([("character", ch)])
        loose.checks = {}
        self.assertEqual(af.arguments("applyBuff", ["me_stasis_1", "60"], loose)[0], "me_stasis_1")


@unittest.skipUnless(HAVE_TREE, "needs SWG_RESTORATION_TREE (the gate provides it)")
class ServerTreeGroundingTests(unittest.TestCase):
    def test_template_subtrees_exist_and_deny_targets_are_real(self):
        for subtree in sc.TEMPLATE_SUBTREES:
            self.assertTrue((SERVER / "object" / subtree).is_dir(), subtree)
        self.assertTrue((SERVER / "object/tangible/terminal/terminal_character_builder.tpf").is_file())
        self.assertTrue(any((SERVER / "object/tangible/furniture/terminal").glob("*.tpf")))

    def test_allowed_buffs_are_plain_stat_consumables(self):
        rows = (SHARED / "datatables/buff/buff.tab").read_text(encoding="ISO-8859-1").splitlines()
        head = rows[0].split("\t")
        col = {name: head.index(name) for name in ("NAME", "DURATION", "STATE", "CALLBACK")}
        params = [i for i, name in enumerate(head) if name.endswith("_PARAM")]
        allowed = []
        for row in rows[2:]:
            cells = row.split("\t") + [""] * len(head)
            name = cells[col["NAME"]]
            if name.startswith(ch.BUFF_PREFIXES) and not any(d in name for d in ch.BUFF_DENY):
                allowed.append(name)
                self.assertEqual((cells[col["STATE"]], cells[col["CALLBACK"]]), ("", ""), name)
                effects = {cells[i] for i in params}
                self.assertFalse({e for e in effects if "immun" in e or "invuln" in e}, name)
                self.assertLessEqual(float(cells[col["DURATION"]] or 0), ch.BUFF_SECONDS_MAX, name)
        self.assertGreaterEqual(len(allowed), 100)
        self.assertIn("me_buff_health", allowed)
        self.assertIn("drink_jawa_beer", allowed)
        self.assertNotIn("me_stasis_1", allowed)

    def test_creature_rows_have_a_scripts_column(self):
        head = (SERVER / "datatables/mob/creatures.tab").read_text(encoding="ISO-8859-1").splitlines()[0].split("\t")
        self.assertIn("scripts", head)
        self.assertIn("creatureName", head)


if __name__ == "__main__":
    unittest.main()
