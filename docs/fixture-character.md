# Fixture family `character` (`agent_character`)

Everything about the test character itself: read-backs of pools, level, credits, faction,
posture, profession and buffs, and setters for the same. Python side
`swg_test_studio/fixture_ops/character.py`; Java side `devtools/zones/fixtures/agent_character.java`
(`script.fixture.agent_character`); tests `tests/test_fixture_character.py`.

**Status: nothing here has run against a live server.** All claims are offline: unit tests,
Python/Java parity checks and grounding of every call in a Dec 2011 script tree and the server tree.

Call: `game <serverId> runScript fixture.agent_character <op> <oid>:<stationId>:<characterName> [args...]`

Reply: `agent_character=<status> key=value ...`, encoded as in `agent_fixture` (statuses `ok`,
`invalid-scope`, `not-here`, `invalid-identity`, `invalid-args reason=...`, `out-of-scope reason=...`,
`refused reason=...`). The guard (`request`, `refusal`, `num`, `integer`, `oid`, `name`, `cellName`,
`list`, `botBuilding`, `scope`, `enc`, `start`, `kv`, `row`, `end`, `fail`, `invalidArgs`) is copied
verbatim from `agent_fixture.java`; a test checks the bodies are identical. Every op acts only on
the one exact registered non-god bot; nothing grants god mode or an admin level, attaches a script,
queues a command or runs free-form text.

## Named caps

| cap | value | used by |
|---|---|---|
| `POOL_MAX` | 500000 | health and action, current and max (minimum 1) |
| `LEVEL_MAX` | 90 | `setLevel`, `setProfession` (rows of `player_level`) |
| `CREDITS_MAX` | 10000000 | `setBank`, `setCash`, `depositCash`, `withdrawCash` (minimum 0) |
| `STANDING_MIN`/`STANDING_MAX` | -5000 / 50000 | `setStanding` (`factions.FACTION_RATING_MIN`; the library clamps to the rank cap) |
| `BUFF_SECONDS_MAX` | 86400 | `applyBuff` (minimum 1 s) |
| `GIVE_COUNT_MAX` | 25 | `giveStaticCount` (minimum 1) |
| `REVOKE_MAX` | 500 | `revokeSkills` skills per call |

Argument kinds (Python regex = Java constant, checked by a test): `char_pool` `[0-9]{1,6}`,
`char_level` `[0-9]{1,2}`, `char_credits` `[0-9]{1,8}`, `char_faction` `[A-Za-z][A-Za-z0-9_]{0,47}`,
`char_standing` `-?[0-9]{1,5}(\.[0-9]{1,2})?`, `char_seconds` `[0-9]{1,5}`, `char_count` `[0-9]{1,2}`,
and the allow-lists `char_profession`, `char_aligned` (`Imperial|Rebel|Neutral`), `char_pvp`
(`neutral|covert|declared|onleave`), `char_posture` (`upright|crouched|prone|sitting|knocked_down`).
Core kinds reused verbatim: `name`, `oid`, `regex`, `scenario`.

## Accepted professions

Exactly `gm.getRoadmapList()` of the Dec 2011 script tree (a test compares it with the server
tree): `smuggler_1a`, `bounty_hunter_1a`, `officer_1a`, `commando_1a`, `force_sensitive_1a`,
`medic_1a`, `spy_1a`, `entertainer_1a`, `trader_0a`, `trader_0b`, `trader_0c`, `trader_0d`.
The Java side re-checks membership in `gm.getRoadmapList()` at run time.

## Ops

| op | args | effect | reply keys | API used |
|---|---|---|---|---|
| `stats` | – | read-back | `player health health_max action action_max level combat_level cash bank total_credits faction faction_id pvp_type standing_imperial standing_rebel posture incapacitated dead profession_id template skills` | getAttrib, getMaxAttrib, getLevel, respec.getCombatLevel, getCashBalance, getBankBalance, getTotalMoney, pvpGetAlignedFaction, factions.getFactionNameByHashCode, pvpGetType, factions.getFactionStanding, getPosture, isIncapacitated, isDead, utils.getPlayerProfession, getSkillTemplate, getSkillListingForPlayer |
| `buffs` | `[name]` | read-back: one row per buff `name,secondsLeft`; with a name also `has` | `count buff has rows truncated` | buff.getAllBuffs, buff.getBuffNameFromCrc, buff.getBuffTimeRemaining, buff.hasBuff |
| `standing` | `<faction>` | read-back of one faction table row | `faction standing max` | factions.getFactionNumber, factions.getFactionStanding, factions.getFactionMax |
| `setHealth` | `<1..500000>` | current health; refused above the current max | `pool current max` | setAttrib, getAttrib, getMaxAttrib |
| `setAction` | `<1..500000>` | current action; refused above the current max | `pool current max` | setAttrib, getAttrib, getMaxAttrib |
| `setMaxHealth` | `<1..500000>` | maximum health | `pool current max` | setMaxAttrib |
| `setMaxAction` | `<1..500000>` | maximum action | `pool current max` | setMaxAttrib |
| `healFull` | – | heals shock wounds and pools, then health and action to max; refused while down | as `stats` | healing.fullHeal, setAttrib, getMaxAttrib |
| `incapacitate` | – | sets the incapacitated posture (what pclib.clearEffectsForDeath does) | `posture incapacitated` | setPosture, isIncapacitated, isDead |
| `revive` | – | resurrects a dead bot (clears death effects, full heal); stands an incapacitated bot up | `was_down` + `stats` keys | pclib.resurrectPlayer, setPostureClientImmediate |
| `setPosture` | `<posture>` | posture, shown to clients immediately; refused while down | `posture` | setPostureClientImmediate, getPosture |
| `setLevel` | `<1..90>` | the respec library's level grant (raises or lowers along the current roadmap), then pool recalculation | `requested before level template` | respec.autoLevelPlayer, skill.recalcPlayerPools, skill.setPlayerStatsForLevel, getSkillTemplate, getLevel |
| `setProfession` | `<roadmap> [1..90]` | the NPC respec path: `setSkillTemplate`, then `respec.earnProfessionSkillsViaNpc` (revokes all skills and experience, removes buffs, levels the new roadmap). Level defaults to the current one | `before requested_level` + `stats` keys | gm.getRoadmapList, setSkillTemplate, respec.earnProfessionSkillsViaNpc |
| `revokeSkills` | `<pattern>` | revokes every held skill whose name fully matches; same pattern limits as the core `grantSkills` (no quantified group, at most two `*`/`+` and three quantifiers), at most 500 | rows `revoked,<skill>` / `failed,<skill>`, `revoked failed capped` | getSkillListingForPlayer, revokeSkill, hasSkill |
| `resetExpertise` | – | the NPC reallocation reset (`utils.fullExpertiseReset`), then grants the `expertise` skill back if it went | `expertise_skills has_expertise` | utils.fullExpertiseReset, hasSkill, grantSkill |
| `setBank` | `<0..10000000>` | moves the difference from or to the `money.ACCT_TEST` ("testing") named account | `target bank_before pending cash bank` | money.bankTo, money.ACCT_TEST, getBankBalance |
| `setCash` | `<0..10000000>` | deposits the surplus, or withdraws the shortfall when the bank holds it | `target cash_before pending cash bank` | money.deposit, money.withdraw, getCashBalance, getBankBalance |
| `depositCash` | `<0..10000000>` | cash to bank, at most the cash held | `amount pending cash bank` | money.deposit |
| `withdrawCash` | `<0..10000000>` | bank to cash, at most the bank balance | `amount pending cash bank` | money.withdraw |
| `setFaction` | `<Imperial\|Rebel\|Neutral>` | neutral and unaligned, or aligned to the faction table's `pvpFaction` and covert (the engine calls `factions.joinFaction` and the resignation path use) | `faction faction_id pvp_type` | factions.getFactionNumber, dataTableGetInt, factions.FACTION_TABLE, pvpMakeNeutral, pvpSetAlignedFaction, pvpMakeCovert |
| `setStanding` | `<faction> <-5000..50000>` | standing in a faction whose table row has `playerAllowed=1` | `faction requested standing` | factions.setFactionStanding, factions.getFactionNumber, dataTableGetInt |
| `setPvpType` | `<neutral\|covert\|declared\|onleave>` | PvP status; anything but neutral needs an aligned faction | `requested pvp_type faction` | pvpMakeNeutral, pvpMakeCovert, pvpMakeDeclared, pvpMakeOnLeave |
| `applyBuff` | `<name> <1..86400>` | applies a buff the buff table knows for that many seconds | `buff has seconds_left` | buff.getBuffNameFromCrc, getStringCrc, buff.applyBuff, buff.hasBuff, buff.getBuffTimeRemaining |
| `removeBuff` | `<name>` | removes it | `buff had removed has` | buff.hasBuff, buff.removeBuff |
| `equipItem` | `<itemOid>` | equips an item that is directly in the bot's inventory | `item template worn` | utils.getInventoryContainer, getContainedBy, equip, getTemplateName |
| `unequipItem` | `<itemOid>` | puts an item the bot wears back into its inventory | `item worn` | getContainedBy, utils.getInventoryContainer, putIn |
| `giveStaticCount` | scenario id, `<name> <1..25>` | that many copies of one `master_item` static item in the inventory, each tagged `fixture.scenario`=id and `fixture.owner`=bot; needs that id open on the bot (`fixture.scenario_open`) | rows of item oids, `scenario name created failed` | hasObjVar, getStringObjVar, dataTableSearchColumnForString, static_item.MASTER_ITEM_TABLE, static_item.createNewItemFunction, setObjVar |

`giveStaticCount` is the family's only `SCENARIO_OPS` op: the step needs `"scenario": "<id>"`
and its Java method takes the id as its first argument (`request(value,"giveStaticCount",3,3)`).
The scenario family's `scenarioEnd` finds the items in the bot's inventory by their tag.

Guard API (all ops): getConfigSetting, isIdValid, exists, isPlayer, getPlayerFullName,
getPlayerStationId, isGod, and for `equipItem`/`unequipItem` the reach rule's getLocation,
getTopMostContainer, getContainedBy, getWorldLocation, getCurrentSceneName, getDistance.

## Not possible from script

- **Clear cooldowns.** Command cooldowns live in the engine's command queue; the script API of a
  Dec 2011 script tree has no call that reads or resets them (`sendCooldownGroupTimingOnly` only
  sends a timing message to the client). Needed: an engine method exposed to script that resets a
  cooldown group on a creature (for example in the command queue of `CreatureObject`).
- **Set cash directly.** Cash has no setter; credits move only through the bank transfer calls, which
  complete asynchronously. `setCash` and `setBank` therefore report `pending=true`; assert the result
  with a later `stats` step.
- **A single stacked item with a count.** `static_item.createNewItemFunction` creates one item (its
  `charges` overload sets uses, not a stack size), so `giveStaticCount` creates that many copies.

## Where this differs from sources/interface.md

- The interface calls the equip op "equip"; the methods are `equipItem`/`unequipItem` so they do not
  overload the inherited `equip(obj_id, obj_id)` by name.
- `incapacitate` sets the posture only, as the death-effects path of `pclib` does; it does not drain
  pools the way combat does.

## Unrun (offline only)

Every behaviour below is unrun: no console line of this class has reached a server.

- All replies of every op; the exact key values (`combat_level` is `-1` until the respec level array
  exists on the character).
- `setMaxHealth`/`setMaxAction` against later skill or level recalculations, which may recompute the
  maximum; whether a set current pool survives regeneration until the next step.
- `setLevel` lowering a level (the library revokes roadmap skills) and the pool recalculation after it.
- `setProfession` end to end: skills and items of the new roadmap, the level raised to at least 5 by
  the library, the respec bookkeeping objvars the NPC flow sets that this op does not.
- `revokeSkills` and `resetExpertise` effects on derived skill mods and abilities.
- Credit transfers: completion, ordering of two quick transfers, the `testing` named account
  behaviour.
- `setFaction`/`setPvpType`/`setStanding` effects on the client's faction flags and on factional NPCs.
- `incapacitate`, `revive` and `healFull` as seen by the client and by combat.
- `applyBuff`/`removeBuff` for every buff class (group, debuff, stance), durations and stacking.
- `equipItem`/`unequipItem` slot handling, refusals for items the bot cannot wear.
- `giveStaticCount` inventory-full behaviour and removal by `scenarioEnd`.
- The JDK 21 compile of this class runs in the job gate, not in these unit tests.
