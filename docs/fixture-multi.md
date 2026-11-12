# Fixture family `multi`: several test bots on different accounts

`script.fixture.agent_multi` (`devtools/zones/fixtures/agent_multi.java`) and
`swg_test_studio/fixture_ops/multi.py` are the op family for ops that involve a **second
registered fixture bot**. They arrange and assert grouping, secure trade and
account-to-account behaviour from the server side, between client steps
(docs/fixture-client-actions.md). Routing, role substitution and the reply parser are CORE's
(docs/fixture-core.md).

**Status: nothing here has run against a live server.** Offline checks only:
`tests/test_fixture_multi.py`, the family checks in `tests/test_fixture_core.py`, and a JDK 21
compile of the class against a Dec 2011 script tree (job gate).

## The second bot

A step names the other bot by its suite **role**. The runner replaces the role with that bot's
registered identity `oid:station:Cap...` before it builds the console line. The acting role
itself, a role the suite doesn't declare, and an unbound role are refused before anything is
sent.

```
game <worker> runScript fixture.agent_multi <op> <actingIdentity> [args with the partner's identity...]
```

In Java, `partner()` checks that identity with exactly the clauses `request()` uses for the
acting bot. A test keeps the clauses identical:

| check | refusal |
|---|---|
| triple shape: `[1-9][0-9]{0,18}`, `[1-9][0-9]{0,9}`, `Cap[a-z]{12}`; numeric overflow | `invalid-args reason=partner` |
| valid, authoritative on **this** game server, exists | `out-of-scope reason=partner-not-here` |
| a player, exact full name, exact unsigned station id, not god | `invalid-identity reason=partner` |
| the acting bot itself | `invalid-args reason=partner-is-self` |

So any player who isn't a registered fixture bot is refused. Both bots must be loaded on the same
game server: in a fixture, that means the same scene.

The guard and helpers (`request`, `refusal`, `num`, `integer`, `oid`, `list`, `botBuilding`,
`scope`, `enc`, `start`, `kv`, `row`, `end`, `fail`, `invalidArgs`) are verbatim copies of
`agent_fixture.java`. Replies are `agent_multi=<status> key=value ... [row=...] [rows=N truncated=B]`.
Every key matches the `expect` key rule `[a-z][a-zA-Z0-9_]{0,31}`.

## Ops

Argument kinds:
- `role`: the shared kind `[a-z][a-z0-9_]{0,31}`; Java receives the identity triple.
- `oid`: the core kind.
- `bring_offset`: `[0-9]{1,2}(\.[0-9]{1,2})?`, 0.5 to 16 m.
- `snapshot_name`: `[a-z][a-z0-9_]{0,23}`.
- `pay_amount`: `[1-9][0-9]{0,6}`, 1 to 1,000,000.

A trailing `?` means optional.

| op | args | changes state | reply keys | API used |
|---|---|---|---|---|
| `bring` | `role`, `bring_offset?` (default 2) | yes | `partner scene offset cell distance` | isDead, isIncapacitated, getState (`STATE_COMBAT`), getCurrentSceneName, getLocation, getWorldLocation, getHeightAtLocation, setLocation, getDistance, isIdValid |
| `distanceTo` | `role` | no | `partner distance same_scene bot_scene partner_scene same_building same_cell` | getWorldLocation, getLocation, getDistance, getTopMostContainer (botBuilding) |
| `groupOf` | `role?` | no | `group size pc_size leader leader_is partner_group same_group`; rows `member,name,who,identity` | getGroupObject, getGroupLeaderId, getGroupSize, getPCGroupSize, getGroupMemberIds, getGroupMemberNames, getPlayerStationId, getPlayerFullName |
| `groupLeave` | `role?` | yes | `who group queued` | getGroupObject, getGroupLeaderId, getGroupMemberIds, group.leaveGroup |
| `creditsOf` | `role` | no | `partner cash bank total bot_cash bot_bank bot_total` | getCashBalance, getBankBalance, getTotalMoney |
| `accountOf` | `role` | no | `bot_station partner_station same_account bot_name partner_name partner_identity` | getPlayerStationId, getPlayerFullName |
| `tradeState` | `role?` | no | `bot_items_in_trade partner_items_in_trade`; rows `bot\|partner,oid,template` | utils.getContents, isInSecureTrade, getTemplateName |
| `snapshot` | `snapshot_name`, `role?` | yes (objvars on the bots) | `snapshot items cash bank partner_items partner_cash partner_bank` | utils.getContents, getCashBalance, getBankBalance, setObjVar, removeObjVar, getIntObjVar |
| `diff` | `snapshot_name`, `role?` | no | see below | hasObjVar, getIntObjVar, getObjIdArrayObjVar, utils.getContents, getCashBalance, getBankBalance, getTemplateName |
| `snapshotDrop` | `snapshot_name`, `role?` | yes | `snapshot removed partner_removed` | hasObjVar, removeObjVar |
| `giveTo` | `role`, `oid` | yes | `object partner container` | utils.getInventoryContainer, getContainedBy, isPlayer, hasObjVar, utils.getContents, isInSecureTrade, putIn (plus `scope`) |
| `payTo` | `role`, `pay_amount` | yes | `partner amount requested bot_cash_before partner_cash_before` | getCashBalance, getBankBalance, money.cashTo |

Details:

- **bring** moves the *partner* next to the acting bot along +x. Indoors it goes in the bot's
  cell; outdoors at terrain height. It refuses when the partner is in another scene
  (`out-of-scope reason=partner-scene`), in `space_*` scenes (`refused reason=space-scene`), and
  when the partner is dead or incapacitated (`refused reason=partner-down`) or in combat
  (`refused reason=partner-in-combat`): moving a downed or fighting player would hide what the
  test is about to assert.
- **groupOf** describes the acting bot's group. `leader_is` is `bot`, `partner`, `other` or
  `none`. `group=none` with `size=0` means solo. With a role it also gives `partner_group` and
  `same_group`. Member rows carry the `oid:station:name` identity for the bot and the partner;
  other members get `none`.
- **groupLeave** calls the server's own `group.leaveGroup`, which queues the `leaveGroup`
  command. The effect is asynchronous, so assert it with a later `groupOf`. A bot that is
  already solo answers `ok queued=false`, so a suite can use the op to arrange a solo start.
  It refuses (`refused reason=would-hand-leadership member=<oid>`) when the one leaving leads a
  group of more than two that has a member other than the acting bot and the named partner: the
  group would pass leadership to a player the fixture does not control. Without a role only the
  acting bot counts as known, so name the partner role when it is in the group too.
- **snapshot** records cash, bank and the ids of everything the bot carries or wears
  (recursive, at most `SNAPSHOT_ITEMS_MAX` = 100, otherwise `refused reason=too-many-items`; the
  ids go into one `obj_id[]` objvar, and 100 keeps that well inside an objvar's size)
  under objvar `fixture.snapshot.<name>` on the bot, and on the partner when given. It replaces
  an older snapshot of the same name.
- **diff** compares against that snapshot (`refused reason=no-snapshot` when absent):
  - For the bot: `gained lost cash_delta bank_delta gained_ids lost_ids` (the first 32 ids,
    comma-joined; the comma is encoded as `%2C`).
  - With a role, also `partner_gained partner_lost partner_cash_delta partner_bank_delta`.
  - The trade checks:
    - `moved_to_partner`, `moved_from_partner`, and their `*_ids`.
    - `duplicated`: items carried by both bots now.
    - `items_conserved`: everything that left one bot is carried by the other, nothing new
      appeared, and nothing is duplicated.
    - `credits_conserved`: the four credit deltas sum to 0.

  Rows list every lost and gained id. A step asserts a trade like this:

  ```json
  {"op": "diff", "args": ["trade1", "buyer"],
   "expect": {"cash_delta": "500", "partner_cash_delta": "-500", "moved_to_partner": "1",
              "lost_ids": "<oid>", "items_conserved": "true", "credits_conserved": "true", "duplicated": "0"}}
  ```
- **giveTo** moves an item the acting bot carries in its inventory into the partner's
  inventory. The item's containment chain must reach the bot through the bot's inventory
  container (directly or inside a bag); a worn item, anything in the datapad, bank or mission
  bag, the inventory itself and anything not carried is `out-of-scope reason=not-in-inventory`.
  It refuses an item in a secure trade (`refused reason=in-trade`) and an item a fixture op
  created, or a container holding one (`refused reason=fixture-created`): such items belong to
  the giver's open scenario, and in the partner's inventory the giver's `scenarioEnd` could not
  reach them (it would report them as leaked). Arrange a partner's items with the partner's own
  creating ops instead.
- **payTo** also refuses when the partner's cash plus bank plus the amount would exceed
  `CREDITS_MAX` (10,000,000, the character family's cap; `refused reason=credits-cap`).
- **payTo** moves cash with the money library the server itself uses for cash transfers
  (`money.cashTo` → `transferCashTo`). The transfer is asynchronous: `requested=true` only
  means the request was accepted. Assert the result with `creditsOf` or `diff`. It refuses when
  the bot has less cash than the amount.

Named caps: `BRING_OFFSET_MIN/MAX` 0.5 and 16 m, `PAY_MAX` 1,000,000, `CREDITS_MAX` 10,000,000,
`SNAPSHOT_ITEMS_MAX` 100,
`IDS_MAX` 32, `MAX_ROWS` 200.

None of these ops creates world objects, so none is in `SCENARIO_OPS`. Snapshots are objvars
on the bots themselves; remove them with `snapshotDrop` (the scenario family's `scenarioEnd` and the
character family's `resetCharacter` also clear every `fixture.snapshot.*` of their bot). No op changes scene
(`SCENE_CHANGING` is empty).

## Not possible from script

- **Server-side group join.** The script API in a Dec 2011 script tree can read groups and leave
  them (`group.leaveGroup`), but it cannot create one or add a member. Groups form only through
  the `invite`/`join` commands of a client, which are DRV's `group_invite` and `group_join`
  steps. A server-side join would need an engine function that adds a creature to a group
  object, and no such function exists.
- **Secure-trade window state.** The script API exposes only the per-item flag
  `isInSecureTrade`. Who trades with whom, the offered credits, and the accept or verify state
  live in the game server's `ServerSecureTrade` and are not visible to scripts. `tradeState`
  therefore reports items in trade only. Use `snapshot`/`diff` to assert a trade's outcome.
- **An account's characters.** A script sees only loaded characters. Listing every character on
  a station account needs the login server or database. `accountOf` reports the station ids
  and `same_account` for the two loaded bots only.
- **Credit transfer between banks of different accounts as one op.** `money.bankTo` exists, but
  the fixture keeps to cash (`payTo`) so that one capped op covers the arranging need. Bank
  deltas are still reported by `diff`.

## What a prepared test server must provide for multi-client suites

- One registered fixture bot per role:
  - Each bot is a non-god character named `Cap` plus 12 lowercase letters, registered by the
    driver (`<folder>/protocol-driver/<registry>.json`).
  - Two-role suites need **two bots on two different station accounts**, because
    `same_account=false` is asserted.
  - A suite declares at most 5 roles and an environment binds at most 5, so a server supports
    up to five concurrent bots, each on its own account.
- Environment bindings map each suite role to a distinct registry key:

  ```json
  "bindings": {"seller": "alpha", "buyer": "bravo", "leader": "gamma", "member": "delta", "actor": "echo"}
  ```

  Roles must match `[a-z]{3,16}`. Bind every role a suite declares, including the roles named
  only as the other bot of a multi op. `plan` lists those roles under
  `agent_fixture_partner_roles`.
- Both bots of a step must be loaded on the same game server (same scene) when a multi op runs.
  `bring` needs them in the same scene.
- `trade_between_accounts` needs the seller to hold at least 500 cash before `fund_buyer`.
- The agent fixture is installed with `install-agent-fixture`, which installs `agent_multi`
  along with the other classes.

## Example suites

All three use only core ops, multi ops and DRV's `client` steps, so they validate now (CHAR and
WORLD land in parallel). Each runs two roles that are asserted to be on different accounts.

- `trade_between_accounts`:
  1. Hold both sessions.
  2. `accountOf`, then `bring`, `payTo` and `creditsOf` to arrange.
  3. `snapshot`.
  4. Client trade: request, accept, credits, offer, verify.
  5. Assert with `tradeState` and `diff` (credits moved, nothing duplicated or lost), then `snapshotDrop`.
  6. Release both sessions.
- `group_with_fixture_asserts`:
  1. Hold both sessions.
  2. Arrange: `groupLeave` for both bots (solo start), `bring`, `distanceTo`.
  3. Assert solo with `groupOf`.
  4. Client invite and join, then `groupOf` (same group, size 2, `leader_is=bot`).
  5. Client `group_make_leader`, then `groupOf` (`leader_is=partner`).
  6. Client `group_leave`, then `groupOf` (dissolved).
  7. Release both sessions.
- `scenario_concert`:
  1. Hold both sessions.
  2. Arrange with `warp`, `bring`, `groupLeave` and `snapshot`.
  3. Client invite and join.
  4. `inspect` with `expect`, `groupOf`, `diff`.
  5. Client disband, then `snapshotDrop`.
  6. Release both sessions.

  The full concert asked for (`scenarioBegin`, character and scenario ops, `scenarioEnd`) is in
  `tests/test_fixture_multi.py` (`FULL_CONCERT`). It is validated there against stand-in
  character and scenario families, and is refused while those families are absent.
  **Follow-up:** once CHAR and WORLD are on the branch, move it into `scenario_concert.json`
  with their real op names.

Until DRV's held-session runner lands, every `client` step is refused at plan time: under the
restoration profile by `server_profile.require_supported`, under whitengold by the legacy
backend at run time. The suites validate, but they don't run yet
(docs/fixture-client-actions.md, "What is still missing").

## Where this differs from sources/interface.md and the contract

- The contract's `giveTo` (item or credits) is two ops: `giveTo` (item) and `payTo` (credits).
  Each has one typed argument and its own cap.
- `snapshotDrop` is an extra op, so a suite can remove its snapshot objvars.
- `groupLeave` is the "server-side leave" the contract allows. There is no server-side join
  (see above).
- `tradeState` reports item flags only (see above).
- Kind names are namespaced (`bring_offset`, `snapshot_name`, `pay_amount`) so they can't clash
  with another family's kinds. `role` and `oid` are reused verbatim.

## Unrun (offline only)

Every op has run only offline. In particular:

- `partner()` against real bots: proxies on another game server, station ids of loaded bots.
- `bring`'s `setLocation` of another player, indoors and outdoors, and the terrain height used.
- Group reads during the asynchronous invite and join, and `group.leaveGroup` queuing and its
  timing.
- `money.cashTo` completing, its callbacks on the bot's own scripts, and a refusal when the
  partner's cash would overflow.
- `isInSecureTrade` while a trade is open, and after it completes or is aborted.
- `snapshot` objvar storage of an `obj_id[]` of up to 100 ids, and `diff` across a real trade:
  do traded items keep their object id?
- `giveTo`'s `putIn` into another player's inventory, including a full inventory; the inventory
  chain walk for bags, the datapad and the bank.
- `bring`'s down and combat refusals (`getState(..., STATE_COMBAT)` of a loaded player), and
  `groupLeave`'s leadership check with members on another game server.
- All three example suites end to end, which also needs DRV's held-session runner and trade peer
  commands.
- The JDK 21 compile ran only in the job gate.
