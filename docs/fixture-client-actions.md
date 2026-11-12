# Client-side actions in concert with the agent fixture

**Status: nothing here has run.** No test server exists. The step kinds, their order rules and their grounding in
the server tree are checked offline (`tests/test_client_actions.py`). Every client action below is **unrun**, and
the held-session runner and the peer commands for trade are **not implemented yet** (see "What is still missing").
Until they land, Studio refuses `client` steps under both profiles before it touches a server.

## How Studio runs several roles today

| question | answer | where |
|---|---|---|
| sessions held across cases? | No. A `session` case logs one bot in, acts, logs out and waits until the bot is fully unloaded, all inside one driver process. The peer is closed in `finally`. | `devtools/zones/protocol_driver.py:494`, `:582-584`, `:593-596` |
| one peer per role, or one for all? | One peer process per bot and per case. A new login first waits until the bot is unloaded. | `devtools/zones/protocol_driver.py:474-475`, `:494` |
| how cases run | One after another, and the run stops at the first failure. | `swg_test_studio/backend.py:182-222` |
| limit on concurrent sessions | A suite declares at most 5 roles. An environment binds at most 5. The driver keeps at most 8 retained bot identities. | `swg_test_studio/model.py:202`; `swg_test_studio/backend.py:55`; `devtools/zones/protocol_driver.py:467` |
| two-role group sequences | `action_sequence` runs `protocol_scenarios.py --studio-actions` with both peers open inside that one tool process. | `swg_test_studio/action_sequence.py:57-61`; `devtools/zones/studio_actions.py:94-120` |
| `agent_fixture` on a session's bot | Refused when the bot is not loaded. No step leaves a bot loaded, so a fixture step can't act on a bot that an earlier `session` step logged in. | `swg_test_studio/agent_fixture.py:552` |

What the protocol peer can do (`devtools/zones/protocol_driver64.cpp`):

- Group: `invite`, `join`, `makeLeader` and `dismissGroupMember` toward a roster companion (`:283-287`), plus `leaveGroup` and `disband` (`:301`).
- Other actions: `attack`, `peace`, `stand`, `unstick`, `converse`, object menus and SUI answers.
- Missing: tells, mail, friends, bank and secure trade.

### Why the restoration profile refuses group steps today

- Group steps compile to `studio_action_sequence` or to the `ship_group` and `group_affinity_*` recipes. None of these is in the profile's `case_kinds` (`devtools/zones/server_profile.py:112`).
- The refusal is real, not a zone-instance or capacity check. `studio_actions.execute` requires each actor to be at the Tansaari station or in its tracked Ord ship (`devtools/zones/studio_actions.py:99-103`). Getting there uses whitengold-only staging (`stage_station`, the `botPrepare` terminal setup) that the restoration bot fixture does not provide.
- The group commands themselves (`invite`, `join` and the others) are ordinary command-table rows in the server tree. The typed `client` steps below use them without any station staging.
- Every other existing action is either supported under restoration already (plain sessions and `agent_fixture`) or depends on a whitengold-only feature (station, shuttle, ship, zone instance or recorder). No existing case kind could be widened safely, so `case_kinds` is unchanged.

## The `client` step

```json
{"id": "invite", "action": "client", "options": {"role": "leader", "kind": "group_invite", "peer": "member"}}
```

A `client` step compiles to one `client_action` case (`swg_test_studio/model.py:298`). `role` and `peer` are
declared roles of the suite, and `peer` is never the step's own role. No other fields exist. There is no free-form
command, target name or message.

| kind | fields | server-tree grounding | what it does |
|---|---|---|---|
| `session_hold` | - | peer login, as `session` | log the role's bot in and keep its peer open across later steps |
| `session_release` | - | `LogoutMessage` | log out and prove the bot is fully unloaded |
| `group_invite` | `peer` | command `invite` | invite the peer's character |
| `group_join` | `peer` (the inviter) | command `join` | accept the open invitation |
| `group_decline` | - | command `decline` | decline the open invitation |
| `group_uninvite` | `peer` | command `uninvite` | withdraw this role's invitation |
| `group_leave` | - | command `leaveGroup` | leave the group |
| `group_disband` | - | command `disband` | leader disbands the group |
| `group_make_leader` | `peer` | command `makeLeader` | leader hands leadership to the peer |
| `group_dismiss` | `peer` | command `dismissGroupMember` | leader removes the peer |
| `trade_request` | `peer` | `MessageQueueSecureTrade` `TMI_RequestTrade` on `CM_secureTrade` | ask the peer to trade |
| `trade_accept` | - | `MessageQueueSecureTrade` `TMI_AcceptTrade` | accept the request |
| `trade_deny` | - | `MessageQueueSecureTrade` `TMI_DeniedTrade` | refuse the request |
| `trade_add_item` | `item`: object ID `[1-9][0-9]{0,18}` | `AddItemMessage` | put an item in the trade window |
| `trade_credits` | `amount`: integer 1 to 1,000,000 (`TRADE_CREDITS_MAX`) | `GiveMoneyMessage` | set the credits offered |
| `trade_offer` | - | `AcceptTransactionMessage` | accept the current offer |
| `trade_unoffer` | - | `UnAcceptTransactionMessage` | withdraw the acceptance |
| `trade_verify` | - | `VerifyTradeMessage` | verify; when both traders verify, the trade completes |
| `trade_reject` | - | `DenyTradeMessage` | reject the offer during verification |
| `trade_cancel` | - | `AbortTradeMessage` | cancel the trade |

Grounding, all checked by `ClientGroundingTests` against the server tree:

- The command names are rows of `datatables/command/command_table.tab`.
- The message classes are declared in `sharedNetworkMessages/.../SecureTradeMessages.h` and handled by the game server's `Client.cpp` (`isType("...")`).
- The three `TMI_*` ids are cases of `CreatureController::handleSecureTradeMessage`.
- `MessageQueueSecureTrade` is registered with `CONTROLLER_MESSAGE_ALLOW_FROM_CLIENT_IMPLEMENTATION` on `CM_secureTrade`.
- The reference client sends exactly these messages: `TMI_RequestTrade` with the recipient, and `TMI_AcceptTrade` and `TMI_DeniedTrade` with invalid ids (`ClientSecureTradeManager.cpp`).

### Order rules (checked when a suite is validated, `client_order`, `model.py:64`)

- A role needs `session_hold` before any client action, and so does the peer it names. A held role can't run a plain `session` step until it is released.
- Groups:
  - `group_join` and `group_decline` need an open invitation to the actor. `group_join` must name the inviter.
  - `group_uninvite` needs the actor's own open invitation.
  - `group_disband`, `group_make_leader` and `group_dismiss` are for the current leader only, and the peer must be in the leader's group.
  - A group of fewer than two members dissolves.
- Trades:
  - Each role trades with one peer at a time.
  - Only the requested peer answers a request.
  - Items, credits, offers and verification need an accepted trade.
  - Adding items or credits, `trade_unoffer` and `trade_reject` clear both offers.
  - `trade_verify` needs both traders to have offered. Both verifying completes the trade.
- `session_release` is refused while the role has an open trade. Held sessions still open at the end of a suite are released by the runner (follow-up below).

These rules model the server's state only statically. The live server can still refuse, for example for range or a
busy peer. The step then fails on the peer's event or the fixture's assertion.

### Interleaving with server-side assertions

`agent_fixture` steps go between client steps in the order written:

```json
[{"id": "hold_leader", "action": "client", "options": {"role": "leader", "kind": "session_hold"}},
 {"id": "hold_member", "action": "client", "options": {"role": "member", "kind": "session_hold"}},
 {"id": "invite", "action": "client", "options": {"role": "leader", "kind": "group_invite", "peer": "member"}},
 {"id": "join", "action": "client", "options": {"role": "member", "kind": "group_join", "peer": "leader"}},
 {"id": "grouped", "action": "agent_fixture", "options": {"role": "leader", "op": "groupOf", "args": ["member"]}},
 {"id": "request", "action": "client", "options": {"role": "leader", "kind": "trade_request", "peer": "member"}},
 {"id": "accept", "action": "client", "options": {"role": "member", "kind": "trade_accept"}},
 {"id": "pay", "action": "client", "options": {"role": "member", "kind": "trade_credits", "amount": 500}},
 {"id": "offer_a", "action": "client", "options": {"role": "leader", "kind": "trade_offer"}},
 {"id": "offer_b", "action": "client", "options": {"role": "member", "kind": "trade_offer"}},
 {"id": "verify_a", "action": "client", "options": {"role": "leader", "kind": "trade_verify"}},
 {"id": "verify_b", "action": "client", "options": {"role": "member", "kind": "trade_verify"}},
 {"id": "paid", "action": "agent_fixture", "options": {"role": "leader", "op": "creditsOf", "args": ["member"]}},
 {"id": "disband", "action": "client", "options": {"role": "leader", "kind": "group_disband"}},
 {"id": "release_leader", "action": "client", "options": {"role": "leader", "kind": "session_release"}},
 {"id": "release_member", "action": "client", "options": {"role": "member", "kind": "session_release"}}]
```

`groupOf` and `creditsOf` belong to the multi family; their argument shapes are defined there. N roles can hold N
sessions at once, up to the five-role limit.

## What is still missing (coordinator follow-up)

`devtools/zones/protocol_driver.py`, `protocol_driver64.cpp` and `server_profile.py` are hash-pinned in
`devtools/studio-tools.json`, which this atom does not own. Changing them without refreshing that manifest fails
every tool load. An earlier round did exactly that and was reverted. They are therefore unchanged here. The following
changes must land together with a manifest refresh, by whoever owns `devtools/studio-tools.json`:

1. `protocol_driver.py`: a `Held` manager with one `Session` per role, a bounded lifetime per peer (for example 900 s), and at most `MAX_HELD_SESSIONS`.
   - `perform(case)` sends one peer command per kind and waits for its peer event.
   - `close()` cancels any open trade, disbands, then logs out and calls `unloaded` for every held bot.
2. `protocol_driver64.cpp`: new peer commands.
   - `decline` and `uninvite` toward a roster companion, sent with the existing command-queue request path (`:283-287`).
   - `tradeRequest <companion>`: an `ObjControllerMessage` with `CM_secureTrade` carrying `MessageQueueSecureTrade(TMI_RequestTrade, invalid, recipient)`.
   - `tradeAccept` and `tradeDeny`: the same message with `TMI_AcceptTrade` or `TMI_DeniedTrade`.
   - `tradeItem <oid>`, `tradeCredits <n>`, `tradeOffer`, `tradeUnoffer`, `tradeVerify`, `tradeReject` and `tradeCancel`: the matching `SecureTradeMessages.h` messages sent with `game->message`.
   - Read `BeginTradeMessage`, `BeginVerificationMessage`, `TradeCompleteMessage`, `AbortTradeMessage`, `AddItemFailedMessage` and the `CM_secureTrade` `TMI_TradeRequested` and `TMI_Denied*` replies into peer events.
   - This C++ is uncompiled. It needs a syntax-only compile against the server tree's sharedNetworkMessages headers.
3. `server_profile.py`: add `client_action` to restoration's `case_kinds` once 1 and 2 exist. No whitengold-only feature is involved. `ClientProfileTests` already shows the widened profile accepting it.
4. CORE (`backend.py`):
   - `run_suite` creates one `Held` per run, sends `client_action` cases to it, and calls `close()` in `finally`. It also leaves `client_action` out of `legacy.validate`, which today refuses it (`devtools/zones/protocol_test_sets.py:385`, "Unknown test backend").
   - `plan` sets `group_cleanup_possible` for `group_*` kinds and excludes `client_action` from `fixture_proximity_setup`.
5. CORE (`agent_fixture.validate`, optional): refuse an `agent_fixture` step whose role is not held at that point, when the suite uses `session_hold`.
6. Examples owner: add a `group_and_trade.json` example from the sequence above once the multi family's op shapes are final.

## Left out, with what each would need

- **Removing a trade item.** `RemoveItemMessage` exists, but the server's `ServerSecureTrade::removeItem` cancels the whole trade (checked by a test). Use `trade_cancel`.
- **Tells, mail and friends.** These go through the chat server (`ChatInstantMessageToCharacter`, `ChatPersistentMessageToServer`, `ChatAddFriend` in sharedNetworkMessages). The peer has no chat-server connection.
- **Bank.** Banking is a terminal SUI flow. It would need a typed step that answers a named SUI page with an amount.
- **Account-to-account functions beyond trade and group.** Checking them server-side is the multi family's job. No further client message is grounded here.

## Unrun

Every kind in the table, the order rules against a live server, the held-session runner, the trade peer commands
and the restoration profile running `client_action`.
