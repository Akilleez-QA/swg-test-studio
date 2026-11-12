# Fixture family `scenario`: the world around the bot, and teardown

Family module `swg_test_studio/fixture_ops/scenario.py`, Java class
`devtools/zones/fixtures/agent_scenario.java` (`script.fixture.agent_scenario`). It arranges the world
around one registered fixture bot (objects, creatures, quest state, test objvars, scene and heading)
and removes everything it created by scenario id. Dispatch, steps, the `scenario` step field, the
plan bookkeeping and the `scenario-end` cleanup command are CORE's (`docs/fixture-core.md`).

**Status: nothing here has run against a live server.** It is covered by offline unit tests
(`tests/test_fixture_scenario.py`) and the job gate's JDK 21 compile against a generated Dec 2011
script tree. See "Unrun" at the end.

Console line: `game <worker> runScript fixture.agent_scenario <op> <oid:station:Cap...> [<scenario>] <args...>`.
Reply: `agent_scenario=<status> key=value ... [row=... rows=N truncated=B]`, encoded as in
`agent_fixture` (statuses `ok`, `invalid-scope`, `not-here`, `invalid-identity`, `invalid-args`,
`out-of-scope`, `refused`, and `partial` for a `scenarioEnd` that left objects behind; the runner
treats every status but `ok` as a failed step).

## Guard and reach

The isolation and identity guard (`request`, `refusal`, `num`, `integer`, `oid`, `list`,
`botBuilding`, `scope`, `enc`, `start`, `kv`, `row`, `end`, `fail`, `invalidArgs`) is a verbatim copy
of `agent_fixture.java`; both CORE's and this family's tests compare the bodies. Every op calls
`request(value,"<op>",min,max)` first and then re-parses each argument with the Java parser of its
kind, with the same regex and bounds as the Python kind (a test checks, per op and per argument, that
the exact parser call is present, and that the Java constants equal the Python regexes and ranges).

Objects are reached only through the existing rule: in the bot's scene within 256 m, or inside the
bot or the building it stands in; never a player or anything a player other than the bot carries.
Destroying and controlling ops act only on objects **tagged by the fixture for this bot**.

## Scenario tagging (the interface's rules; this family owns them)

| objvar | on | value |
|---|---|---|
| `fixture.scenario` | every object or creature a fixture op creates | scenario id, `[a-z][a-z0-9_]{0,31}` |
| `fixture.owner` | the same | obj_id of the bot |
| `fixture.scenario_open` | the bot | the open scenario id (set by `scenarioBegin`) |
| `fixture.scenario_created` | the bot | objects created under the open id (cap `SCENARIO_CREATE_MAX` = 100) |
| `fixture.scenario_ids` | the bot | ids the open scenario created and has not destroyed (at most 100, one objvar array) |
| `fixture.scenario_scene` | the bot | the scene the scenario was opened in |
| `fixture.t.<name>` | the bot or a fixture-created object | test objvars of a suite |

A creating op (`SCENARIO_OPS`: `createAt`, `createInCell`, `createInInventory`, `spawnCreature`)
receives the step's scenario id as its first argument and refuses (`refused reason=scenario-not-open`)
unless that id is the bot's open scenario, or when the per-scenario cap would be exceeded. It tags the
new object at once and records its id; an object that cannot be tagged or recorded is destroyed again
and the op is refused. A test checks that every `createObject`/`createCreature` call sits in a
scenario op next to `mayCreate` and `tag`. The character family's `giveStaticCount` uses verbatim
copies of `openScenario`, `mayCreate`, `liveIds`, `storeIds`, `tag` and `forget`, so its items count
against the same cap and are recorded the same way. The multi family's `giveTo` refuses an item a
fixture op created (or a container holding one): handing it to another bot would put it out of the
creating bot's `scenarioEnd` reach.

One scenario is open per bot at a time: `scenarioBegin` with another id while one is open is refused
(`reason=other-scenario-open open=<id>`); the same id again is `ok already=true`.

## Ops

Kinds: `scenario` `[a-z][a-z0-9_]{0,31}` (core); `yaw` -360..360, `oid`, `cell` (core);
`objtemplate` `object/<allowed subtree>/([a-z0-9_]{1,64}/){0,6}[a-z0-9_]{1,64}\.iff` (subtrees below),
at most 200 characters, never containing `/shared_`, `/player/`, `/terminal/`, `/spawning/`, `/gm/`,
`/deed/`, `character_builder` or `admin`; `worldxz` -8192..8192; `worldy` -1000..10000;
`celllocal` -512..512; `spawnoffset` -64..64 (metres from the bot); `spawnlevel` 1..90;
`spawncount` 1..10; `creaturename` `[a-z0-9_]{1,64}`; `onoff` `on|off`; `questname`
`[a-z0-9_]{1,64}(/[a-z0-9_]{1,64}){0,3}`; `questsignal` `[A-Za-z0-9_]{1,64}`; `vartarget`
`self|<oid>`; `varname` `[a-z0-9_]{1,32}(\.[a-z0-9_]{1,32}){0,3}`; `vartype` `int|float|string`;
`varvalue` `[A-Za-z0-9_.:,/+-]{1,128}` (an `int` is `-?[0-9]{1,9}` within ±999999999, a `float`
the fixture number within ±100000); `scenename` one of the scenes below.

| op | args (after the identity) | effect | API used |
|---|---|---|---|
| `scenarioBegin` | `<scenario>` | records the open id and its scene on the bot, resets the created count and the id record; reply `scene`, `cap` | hasObjVar, getStringObjVar, setObjVar, removeObjVar, getCurrentSceneName |
| `scenarioEnd` | `<scenario>` | destroys every reachable object tagged with the id for this bot (at most 1000 per call), removes the bot's `fixture.t.*` and `fixture.snapshot.*`; for the open id, counts the recorded ids it could not remove as `leaked` (below). Reply `destroyed`, `with_container`, `failed`, `leaked`, `leaked_ids` (first 32), `truncated`, `was_open`, `open`, `test_vars_cleared`, `snapshots_cleared`, `scene`. Status `ok` only for a clean end, which alone clears the open record; `partial` when something leaked (the scenario stays open, its cap still counts); `refused` when a destroy failed or the 1000 cap truncated the run | utils.getContents, getObjectsInRange, getTopMostContainer, getLocation, getObjIdObjVar, getObjIdArrayObjVar, getStringObjVar, hasObjVar, exists, destroyObject, removeObjVar, setObjVar |
| `scenarioList` | `<scenario>` | read-only: `open`, `count`, `created`, `live` (recorded ids of the open id), `scene`; rows oid, template, `carried`/`building`/`world`, distance | as scenarioEnd (without destroy), getTemplateName, getDistance |
| `createAt` | `[scenario] <objtemplate> <x> <z> <yaw>` | object on the terrain at a world point of the bot's scene, within 256 m of the bot | createObject(String, location), getHeightAtLocation, getWorldLocation, getDistance, setYaw, getYaw, setObjVar |
| `createInCell` | `[scenario] <objtemplate> <buildingOid> <cell> <x> <y> <z> <yaw>` | object at a cell-local spot of an in-reach building | getCellId, getLocation, createObject(String, location), setYaw, setObjVar |
| `createInInventory` | `[scenario] <objtemplate> [count]` | 1..10 objects in the bot's inventory; rows oid | utils.getInventoryContainer, createObject(String, obj_id, String), setObjVar |
| `destroyCreated` | `<oid>` | destroys one fixture-created object or creature and drops it from the id record | destroyObject |
| `spawnCreature` | `[scenario] <creaturename> <dx> <dz> [level]` | a `creatures.tab` creature at the bot's position plus (dx, dz) (in the bot's cell when indoors, on the terrain outdoors), with AI, at the given level or its table level. Refused (`scripted-creature`) for a row whose `scripts` column is not empty: those scripts (AI roles, conversations, spawners, theme parks) may create adds that would not be tagged; 4069 of the 6743 rows of the server tree's table have no scripts | dataTableSearchColumnForString (`creatureName` of `create.CREATURE_TABLE`), dataTableGetString (`scripts`), create.createCreature(name, location, level, withAi, isPet), getHeightAtLocation, getLevel, isPlayer |
| `creatureAttack` | `<creatureOid>` | the creature starts combat with the bot | isDead, setWantSawAttackTriggers, startCombat |
| `creaturePassive` | `<creatureOid>` | stops its combat, ignores attack triggers, stands still | stopCombat, setWantSawAttackTriggers, ai_lib.setDefaultCalmBehavior (BEHAVIOR_SENTINEL), stop |
| `creatureInvulnerable` | `<creatureOid> <on\|off>` | sets invulnerability; reply reads it back | setInvulnerable, isInvulnerable |
| `creatureMove` | `<creatureOid> <dx> <dz>` | the creature paths (AI movement) to the bot's position plus (dx, dz) | pathTo(obj_id, location) |
| `creatureKill` | `<creatureOid>` | kills it; reply `dead` | kill, isDead |
| `creatureDespawn` | `<creatureOid>` | destroys it and drops it from the id record | destroyObject |
| `questGrant` | `<questname>` | activates a ground quest without the acceptance window (as `groundquests.grantQuestNoAcceptUI`); refused for an unknown or disabled quest; `already=true` when active | groundquests.isValidQuestName, groundquests.getQuestIdFromString, groundquests.isQuestDisabled, questIsQuestActive, questActivateQuest |
| `questComplete` | `<questname>` | completes an active quest; reply `complete` | questIsQuestActive, questCompleteQuest, questIsQuestComplete |
| `questClear` | `<questname>` | clears the quest, active or completed; reply `had`, `active`, `complete` | questIsQuestActive, questIsQuestComplete, questClearQuest |
| `questSignal` | `<questsignal>` | sends a ground quest signal to the bot (`delivery=message`: handled after the reply) | groundquests.sendSignal |
| `quests` | – | read-only: counts `active`, `completed`; rows `active,<name>` and `completed,<name>` (at most 200 together) | questGetAllActiveQuestIds, questGetAllCompletedQuestIds, questGetQuestName |
| `setTestVar` | `<self\|oid> <varname> <int\|float\|string> <value>` | sets `fixture.t.<varname>` on the bot or a fixture-created object | setObjVar (int, float, String) |
| `clearTestVar` | `<self\|oid> <varname>` | removes `fixture.t.<varname>`; reply `had` | hasObjVar, removeObjVar |
| `getTestVar` | `<self\|oid> [varname]` | read-only: `present`, `type`, `value` of one; without a name, rows name, type, value of every `fixture.t.*` | hasObjVar, getObjVarList, obj_var_list.getObjVar, obj_var.getName, obj_var.getData |
| `warpScene` | `<scenename> <x> <y> <z>` | warps the bot to a world point of a ground scene; reply `scene` (target), `from`, `requested=true`, `open_scenario`. Refused (`scenario-open`) while the open scenario still has created objects and the target is not the scenario's own scene (returning there is allowed): those objects would stay behind out of `scenarioEnd`'s reach. In `SCENE_CHANGING`: the runner waits until the bot query finds the bot in `scene`; the plan flags a scene-changing step inside an open scenario | warpPlayer(obj_id, String, float, float, float, obj_id, float, float, float), getCurrentSceneName |
| `face` | `<yaw>` | sets the bot's heading | setYaw, getYaw |

Every op also uses the guard's calls: getConfigSetting, obj_id.getObjId, isIdValid, isAuthoritative,
exists, isPlayer, getPlayerFullName, getPlayerStationId, isGod, getLocation, getWorldLocation,
getTopMostContainer, getContainedBy, getCurrentSceneName, getDistance; created-object checks use
hasObjVar, getObjIdObjVar, getStringObjVar and isMob.

### Template subtrees

Only these subtrees of the server tree's `object/` directory are allowed (each exists there; a
grounding test checks): `tangible/container`, `tangible/furniture`, `tangible/food`,
`tangible/medicine`, `tangible/loot`, `tangible/wearables`, `tangible/component`,
`tangible/instrument`, `tangible/painting`, `weapon/melee`, `weapon/ranged`, `static/item`,
`static/structure`, `static/flora`. They hold inert items and props a test arranges (furniture and
containers for placement and containment, food, medicine, loot, clothing, components, instruments and
paintings as inventory items, weapons to equip, static props and scenery). Where their templates
attach scripts at all, those are item behaviours (no-move, auto-stack, food, city furniture), not
spawners.

Everything else under `object/tangible/` is left out, among it `terminal/` (including the admin
`terminal_character_builder`), `spawning/`, `creature_spawner/`, `lair/`, `ground_spawning/`,
`deed/`, `gm/`, `item/`, `veteran_reward/`, `mission/` and `npe/` (objects whose scripts create
children, grant things or act as admin tools; their children would not be tagged). Inside the allowed
subtrees a path containing `/terminal/` (for example `tangible/furniture/terminal/`), `/spawning/`,
`/gm/`, `/deed/`, `character_builder`, `admin`, `/shared_` or `/player/` is refused as well. Also left
out: `object/creature/` and `object/mobile/` (creatures come from `spawnCreature` by `creatures.tab`
name), `object/player/`, `object/cell/`, `object/intangible/`, `object/building/`,
`object/installation/` and `object/ship/`. Java (`TEMPLATE_RE`, `TEMPLATE_DENY`) and Python
(`TEMPLATE_SUBTREES`, `TEMPLATE_DENY` in `check`) hold the same lists; a test compares them.

### Scenes accepted by `warpScene`

The open-world ground scenes of the server tree's `datatables/region/planets.tab`: corellia,
dantooine, dathomir, endor, kashyyyk_main, lok, mustafar, naboo, rori, talus, tatooine, yavin4.
Left out from that table: `tutorial`, `dungeon1`, `adventure1`, `adventure2` and the Kashyyyk
sub-zones (`kashyyyk_dead_forest`, `kashyyyk_hunting`, `kashyyyk_rryatt_trail`,
`kashyyyk_south_dungeons`, `kashyyyk_pob_dungeons`), which are entered through their own travel
or instance scripts, and every `space_*` scene. A prepared test server must actually run the scene it
is asked for; the restoration profile's servers may run fewer.

## scenarioEnd: repeat, leaks and what it cannot reach

- **Twice:** the second call finds nothing tagged and replies `ok destroyed=0 was_open=false open=none`
  (the CLI's `scenario-end` treats `was_open=false` as a failure: nothing was open under that id).
- **Reach:** it searches the bot's contents (recursive), the building the bot stands in (recursive) and
  `getObjectsInRange(bot, 256)` on the server that is authoritative for the bot.
- **Leaks:** for the open id it then walks the recorded ids (`fixture.scenario_ids`). An id it did not
  just remove is *leaked* when the object is still loaded on this server (it is out of reach: more than
  256 m away, or inside another player's container) or when the bot is no longer in the scenario's
  scene (the object cannot be checked from here). A recorded id that is no longer loaded while the bot
  is in the scenario's own scene counts as removed (`with_container`): the game destroyed it (a
  consumed stack, a recycled corpse) or it went with a destroyed container. While anything leaked the
  reply is `partial`, the scenario stays open with only the leaked ids recorded, its created count and
  cap stay, and the bot cannot open another scenario; move the bot within reach (core `warp`, or
  `warpScene` back to the scenario's scene, which is always allowed) and call `scenarioEnd` again.
- **Scene changes** while objects exist are refused by `warpScene` (see the op); other travel still
  leaves objects behind, and they are reported as leaked until the bot returns. World objects created
  here are not made persistent by this family, so a restart of that scene's game server also removes
  them (the next call from that scene then counts them as removed).
- **Assumption (unverified):** one game server holds a whole scene in the fixture, so an id that is not
  loaded on the bot's server in the scenario's scene no longer exists. On a scene split across game
  servers such an object would be miscounted as removed.
- It does not undo quest state, the bot's heading or position: clear quests with `questClear`; the
  character family's `resetCharacter` undoes buffs, faction, pools and posture.

### Cleanup after a failed run (`scenario-end`)

`python3 swg-tests.py scenario-end --environment <env.json> --role <role> --id <scenario>` sends
`scenarioEnd` for the role's bot under the Studio lock. For it to work: the environment binds that
role to the registry key of the bot that opened the scenario; that bot is logged in (held by a
client session) on the fixture's game server that runs the scenario's scene; and it is within reach of
what the scenario created (the creating spot, or the objects in its inventory). The command exits 0
only for `ok` with `was_open=true` and `leaked=0`; `partial`, `refused`, a leak or `was_open=false`
(a mistyped id or role) exit 1 with the reply fields. Offline cleanup is not possible: with no bot
loaded there is no authoritative server to run the class on, and objects are only destroyed by
the game server that holds them (restarting it removes non-persistent world objects; inventory items
stay with the character).

## Not possible from script (left out)

- **Teleport a creature** instantly: `setLocation` works on any object but bypasses the AI's own
  movement; `creatureMove` uses `pathTo` so the AI stays consistent. An instant creature teleport would
  need a decision that AI desync is acceptable.
- **A synchronous quest signal result:** `groundquests.sendSignal` delivers by `messageTo`; the fixture
  can only report that it sent it. Assert with a later `quests` step.
- **A synchronous scene arrival:** `warpPlayer` hands the bot to another game server after the reply;
  the reply cannot confirm arrival. The runner's relocation wait (CORE) does.
- **Structures** (houses, installations) as scenario objects: they need the player-structure placement
  path (lots, ownership, permissions), not `createObject`; not offered.

## Where this differs from sources/interface.md

- `scenarioBegin`, `scenarioEnd` and `scenarioList` take the id as their own first argument (kind
  `scenario`), not as the step's `scenario` field; only creating ops are in `SCENARIO_OPS`. CORE's plan
  bookkeeping and `scenario-end` command handle this shape.
- `scenarioEnd` also removes the bot's `fixture.t.*` test objvars (test objvars on created objects go
  with the objects).
- The per-scenario creation counter, the id record and the scenario's scene live on the bot in
  `fixture.scenario_created`, `fixture.scenario_ids` and `fixture.scenario_scene` (extra objvars under
  the same prefix). `scenarioEnd` also clears `fixture.snapshot.*` and may answer `partial`.

## Tests (offline)

`tests/test_fixture_scenario.py`: the module merges through the real dispatcher and a clashing copy is
refused; the exact console line of every op; scenario-id rules; injection in every argument position;
out-of-range and disallowed values (player, creature, building and shared templates, path traversal,
unlisted scenes, typed objvar values); Java parity per op and per argument (the exact parser call),
Java constants equal to the Python kinds, ranges, caps and scene list; guard helpers verbatim; no
nested classes or lambdas; no privileged or free-form calls; everything created is tagged; destroying
and controlling ops only touch fixture-created objects; a seeded fault in every class.
`tests/test_fixture_guards.py` pins each guard of the three family classes with its effect (template
deny list, destination distance, cap, open-scenario check, leak bookkeeping, scene-change refusal,
scripted creature refusal) against seeded mutants, compares the Java and Python allow-lists and grounds
the template subtrees and the creature `scripts` column in the server tree.

## Unrun (offline only)

- No op has run on a server; no `agent_scenario` reply has been seen.
- Object creation for each allowed subtree, tagging, and `scenarioEnd` destroying them; whether a
  world object created by `createObject` outlives a game server restart in a prepared test server.
- The id record: `setObjVar` with a 100-entry `obj_id[]`, `exists()` right after `destroyObject` and
  for objects destroyed by the game, and the `partial`/leak accounting in each case above.
- `spawnCreature` for a real `creatures.tab` row and level; creature AI after `creatureAttack`,
  `creaturePassive`, `creatureMove`; `creatureInvulnerable` and `creatureKill` effects.
- `questGrant`/`questComplete`/`questClear`/`questSignal` against real quests, and `quests` names.
- `setTestVar`/`getTestVar` type round trip.
- `warpScene` to each listed scene, the relocation wait after it, and `scenarioEnd` from the new scene.
- `face` on a moving or seated bot.
- The JDK 21 compile runs in the job gate against a generated Dec 2011 script tree, not in the unit tests.
