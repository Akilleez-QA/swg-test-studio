# agent_fixture notes

`script.fixture.agent_fixture` is the server-side fixture for ARRANGE and ASSERT steps on
ordinary (non-god) protocol bots. It is ported from our personal-play console script
`developer.claude.cli` (plus `give_static`). The trust in a hard-coded god character is
gone. The guards follow the `identity()`/`player()` pattern in `protocol_bot.java`.

Call: `game <serverId> runScript fixture.agent_fixture <method> <oid>:<stationId>:<characterName> [args...]`

Reply: one line, `agent_fixture=<status> key=value ...`. Values are percent-encoded: any
byte outside `[A-Za-z0-9._~/:-]` becomes `%XX`, so spaces and commas are encoded too. An
empty value is written as `none`. List methods add repeated `row=a,b,c` keys, at most 200,
and end with `rows=N truncated=true|false`.

## Statuses

| status | meaning |
|---|---|
| `ok` | done. For `tryPut`, check `result=put|refused` |
| `invalid-scope` | not an isolation fixture, or the identity triple is malformed |
| `not-here` | the bot oid is not loaded or not authoritative on this game server. Try the next one |
| `invalid-identity` | authoritative here, but not a player, wrong name or station, or a god character |
| `invalid-args reason=...` | wrong argument count, or an argument failed its typed parser |
| `out-of-scope reason=...` | target not loaded, too far, in another scene, another player or something they carry, the bot itself, a cell, or not carried (`itemBonuses`) |
| `refused reason=...` | the engine call returned false, no such cell, `not-owner`, `no-inventory`, `interior-scene`, `not-outdoors` |
| `unavailable` | `grantSchematics` found no compiled schematic tree |

## Methods

| method | args | effect | kind |
|---|---|---|---|
| inspect | – | scene, world x/y/z, yaw, building and template, cell oid and name, cell-local x/y/z, level, profession template, god | read-only |
| nearby | `<radius 0.1..128>` | rows of oid, distance, template within the radius of the bot (`getObjectsInRange`) | read-only |
| cells | `<buildingOid>` | `count=`, `cells=` comma list of cell names | read-only |
| contents | `<buildingOid>` | rows of cell name, oid, template for each object directly in each cell | read-only |
| describe | `<objectOid>` | template, container, name; rows `objvar,<name>` and `contains,<oid>,<template>` (recursive) | read-only |
| items | – | rows of oid, template, container for everything the bot carries or wears (recursive) | read-only |
| structure | `<structureOid>` | template, owner, `bot_is_owner`, `bot_is_admin` | read-only |
| countIn | `<containerOid>` | direct and recursive counts, container type | read-only |
| tryPut | `<objectOid> <containerOid>` | `putIn` plus item volume, box free volume and container types. Changes something only when the put succeeds (cli semantics) | read-only unless put |
| place | `<buildingOid> <cellName> <x> <y> <z> <yawDeg>` | puts the bot at a cell-local spot and sets its yaw (cli `lookFrom`) | mutating |
| warp | `<x> <y> <z>` | `setLocation` of the bot to a world point in its current scene. Refused in `dungeon*`, `space_*` and `tutorial*` scenes | mutating |
| moveInto | `<objectOid> <buildingOid> <cellName> <x> <y> <z>` | moves an object to a cell-local spot | mutating |
| transform | `<objectOid> <x> <z> <yawDeg>` | moves an outdoor top-level object (a building carries its contents) onto terrain height, within 256 m of the bot, and sets its yaw | mutating |
| setDown | `<buildingOid> <cellName> <x> <y> <z> <oid,...>` | up to 32 objects in a row along +x, 1 m apart; one row each, `placed` or `refused` | mutating |
| scale | `<objectOid> <0.05..20>` | `setScale` | mutating |
| grantExpertise | `[treeId,...]` (integers, at most 64) | grants every expertise box in the given trees, or all trees except test tree 99, ordered by tier then rank | mutating |
| grantSkills | `<regex>` | grants every skill in `skills.iff` whose name fully matches, in table order; failed skills listed as rows | mutating |
| grantSchematics | – | grants every `object/draft_schematic/**.iff` in the compiled data tree (at most 50 000 files) | mutating |
| itemBonuses | `<itemOid> <mod=value,...>` | replaces `skillmod.bonus.*` objvars on an item the bot carries or wears (at most 32 mods, -10000..10000) | mutating |
| giveStatic | `<name,...>` (at most 25) | `static_item.createNewItemFunction` into the bot's inventory, only for names found in `master_item.iff` | mutating |
| give | `<objectOid>` | `putIn` of an in-scope object into the bot's inventory | mutating |
| completeCollection | `<bookName>` | completes every slot of one book from the cli allow-list of 14 player books | mutating |
| clearDecor | `<buildingOid> <tag or *>` | destroys objects directly in the building's cells whose `claude.decor` objvar equals the tag (`*` = any tagged object). The bot must own the building. At most 500 per call | mutating |

## Guard rules (every public method)

1. Environment: `GameServer.clientIsolationFixture == "1"` and `dbProcess.schemaOwner`
   must match `WGC_[A-F0-9]{12}`. Otherwise `invalid-scope`.
2. Identity: the first token is `oid:station:name`, checked with the protocol_bot regexes
   `[1-9][0-9]{0,18}`, `[1-9][0-9]{0,9}` and `Cap[a-z]{12}`. A numeric overflow is caught
   and gives `invalid-scope`. The oid must be valid, exist and be authoritative here
   (otherwise `not-here`). It must be a player whose full name matches exactly, whose
   unsigned station id matches exactly, and who is not god (otherwise `invalid-identity`).
   A leading `<method> ` is stripped first, as in protocol_bot.
3. Arguments: the whole parameter string is at most 4096 characters, and each method checks
   its exact argument count. Typed parsers:
   - oid: `[1-9][0-9]{0,18}`
   - number: `-?[0-9]{1,5}(\.[0-9]{1,6})?`, then a range check (cell-local ±512, world
     ±8192, yaw ±360)
   - integer: `-?[0-9]{1,9}`
   - name: `[a-z0-9_]{1,64}`
   - cell: `[A-Za-z0-9_]{1,64}`
   - decor tag: `[A-Za-z0-9_:]{1,64}` or exactly `*`
   - lists: comma-separated, bounded count
   - grantSkills regex: at most 64 characters from `[A-Za-z0-9_.*+?|()[]^$-]`. No
     backslash, so no back-references or escapes. No `{}`. No quantifier straight after
     `)`. At most two `*`/`+` and three quantifiers in all. Compile errors are caught.

   The fixture never executes commands, attaches or detaches scripts, calls
   `sendConsoleCommand`, or creates objects from free-form templates.
4. Object scope: a target must exist and be authoritative here, and must be one of:
   - contained (recursively, depth 64) by the bot
   - contained by the building the bot stands in
   - in the bot's scene within 256 m of the bot's world position

   On the way up the containment chain, any player other than the bot makes the target
   out of scope. That rules out other bots and everything in their inventories. Mutating
   object methods (`moveInto`, `transform`, `setDown`, `give`, the `tryPut` item) also
   refuse every player, including the bot, and every `object/cell/*`. Buildings named as
   destinations (`place`, `moveInto`, `setDown`) and inspected buildings must pass the same
   scope check. `transform` also requires the destination to be within 256 m of the bot.
5. Output: one line with no spaces inside values. Rows are bounded to 200 with `truncated`.

## Differences from cli.java and why

- `give_static` was an attached task script because static item creation was said to need
  an owning script context. Reading `static_item.createNewItemFunction` in our Dec 2011
  tree shows no use of `getSelf()` and no god check. So `giveStatic` calls it directly from
  the console method, after checking that the name is a row of `master_item.iff`.
  Unverified at runtime: if creation fails without a script context, every name comes back
  as a `failed` row.
- `grantSchematics` keeps cli's walk of the filesystem. It tries cli's absolute
  `/home/swg/swg-main/...` path, then `../../data/sku.0/...` and `data/sku.0/...` relative
  to the game server working directory. In the WhiteNGold/Test Studio image the compiled
  tree may live somewhere else (the overlay copies to
  `/opt/whitengold/data/sku.0/sys.server/compiled/game/`). In that case it returns
  `unavailable`. Adding `/opt/whitengold/data/sku.0/sys.server/compiled/game/object/draft_schematic`
  is a one-line change if wanted.
- `grantExpertise` and `grantSkills`: the cli comment says god mode ignores expertise
  points, tiers and profession locks. Whether the native `grantSkill` enforces them for a
  non-god character is unverified, so expect a non-zero `failed` on bots.
- `setItemBonuses` became `itemBonuses`, `setDownInCell` became `setDown`,
  `completeCollectionBook` became `completeCollection`, `structureInfo` became `structure`,
  `buildingContents` became `contents`, `grantSkillsMatching` became `grantSkills`,
  `grantAllSchematics` became `grantSchematics`, `giveToPlayer` became `give` and
  `lookFrom` became `place`. `whereInside` and `info` were folded into `inspect`.
  `getMaxHousingLots` does not exist in our tree, so lots are not reported.
- `scale` no longer has a read-only form: the value is required. The reply's `scale=` is
  read back with `getScale` after the set.
- `nearby` takes only a radius (at most 128 m). The cli `x z` centre form was dropped.
- `clearDecor` keeps cli's owner requirement and adds a cap of 500 destroys.

## Deliberately left out of v1

exec (free-form client command), the Mandalorian helpers (giveBlackMando, colorMando,
mandoZones), offloadItems, sortInventory, removeRewardDuplicates, fillStorage, labelStorage,
stockResources, storageSummary, maxStations, attachToPlayer and detachFromPlayer, probe
(script name and objvar probe), give_missing (prepareGiveMissing, missingReport),
collection_rewards, ship outfitting (prepareShips, makeShip, shipReport), house placement
(preparePlacement, place_house), layouts (prepareLayout, place_layout), portals
(spawnPortal, configurePortal), terrainCheck, locate.

## v2 candidates

- `terrainCheck <x> <z> <radius>`: read-only and harmless; only the bounds need adding.
- `probe` limited to a fixed allow-list of script and objvar names. A read-only assert
  helper.
- `layout`: port place_layout as a method that takes a layout from an allow-listed
  fixture directory (never a free path) into a building the bot owns, tagging pieces with
  `claude.decor` so `clearDecor` can undo them.
- `spawnPortal` / `configurePortal`: need the portal script attached to a created object.
  That conflicts with the no-attach rule unless the template and script come from a
  fixed allow-list.
- House placement: needs the place_house task script, which runs in the player's own
  script context.
- `shipReport` (read-only) and ship creation from an allow-listed list of ship names.
- `storageSummary` and `labelStorage` with bounded labels.
- give_missing and collection_rewards, once their task-script context needs are
  understood.
- The compiled schematic root from a config key instead of fixed candidate paths.

## Compile check

Against `/home/akilleez/work/swg-wod-atmo-01/scriptgate-probe/gen-head-modern` with JDK 21
`javac -nowarn -implicit:none`, output is one `agent_fixture.class` with no nested classes.

- The prescribed command, with `-encoding utf8`, fails before reaching our file. The
  failure is in the tree's own `script/base_class.java:25358`: an unmappable byte 0x85
  (a Windows-1252 ellipsis in a comment). protocol_bot.java hits the same error.
- With an overlay copy of `base_class.java` where that byte is replaced, prepended to
  `-sourcepath` and still using `-encoding utf8`, agent_fixture compiles with 0 errors.
- With `-encoding ISO-8859-1` on the unmodified tree it also compiles with 0 errors.
  agent_fixture.java is pure ASCII.
- protocol_bot.java does not compile against our tree: 106 errors, all from
  WhiteNGold-only APIs. These are `getZoneInstanceId`, `getCurrentZoneInstanceId`,
  `getPrivateInstanceSession`, `getPrivateInstanceSequence`, the instance overload of
  `warpPlayerToInstance`, `requestZoneInstance`, `isSoloInstanceEligible`,
  `isPrivateInstanceEntryEligible`, `isManagedRryattGroupEnabled`,
  `isManagedHostedPrivateEntryEnabled`, `preparePublicStationTravel`,
  `requestPublicStationTravel`, `sampleManagedPublicEntrance`,
  `fixtureEncounterOrigin`, `fixtureUnloadEncounterObject`,
  `space_dungeon.isCurrentRryattTrailController` and `REQUEST_QUERY`. Its
  `identity()`/`player()` guard uses only APIs present in our tree; agent_fixture
  uses none of the WhiteNGold-only APIs.
