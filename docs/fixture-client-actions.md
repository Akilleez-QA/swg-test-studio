# Client-side actions in concert with the agent fixture

**Status: nothing here has run against a game server.** Every client action below is **unrun**. The step kinds,
order rules, held-session runner and wire bytes are checked offline (`tests/test_client_actions.py`): the runner
against a fake peer (`tests/fake_client_peer.py`), the bytes against an independent reimplementation of the server
tree's pack code. The peer compiles against the restoration tree and links against that tree's shared libraries
(see "Build and compile check"). What a first live run must confirm is listed at the end.

## The existing client peer

`devtools/zones/protocol_driver64.cpp` is a headless client built from the server tree's own message classes. One
process is one account and one character.

| stage | what it sends / receives | where |
|---|---|---|
| start | reads `[ProtocolDriver64]` from the config file named by its only argument: `project`, `account`, `character`, up to 31 `companion`/`companionName` pairs, `ship`, `create`, `timeoutSeconds` (10-900, default 300). Identities must match the dedicated-bot patterns. | `protocol_driver64.cpp:481-497` |
| login | UDP connection to `login:45053`; sends `LoginClientId(account, ...)`; receives `LoginClientToken`, `LoginEnumCluster` (exactly one cluster named `project`), `LoginClusterStatus` (endpoint must be `127.0.0.1:45063`), `EnumerateCharacterId` (only the bot's own character) | `:494`, `:195-196`, `:262-281` |
| game | connects to `connection:45063`, sends `ClientIdMsg(token)`; on `ClientPermissionsMessage` sends `SelectCharacter`, or `ClientCreateCharacter` when `create=true` and no character exists | `:190-193`, `:197`, `:283-293` |
| scene | on `CmdStartScene` answers `CmdSceneReady`; after the character's `SceneEndBaselines` and the server's `CmdSceneReady` it sends `NewbieTutorialResponse("clientReady")` and reports `scene_ready` | `:294-305`, `:229-236` |
| actions | plain text lines on stdin, one per line: `invite`, `join`, `makeLeader`, `dismissGroupMember` toward a roster companion, `leaveGroup`, `disband`, `attack`, `peace`, `stand`, `unstick`, `converse`, `respond`, `menu`, `select`, `answer`, `fire`, `trackShip`, `holdArrival`, `releaseArrival`, `awaitReady`, `logout`, `quit`. Any other line fails the peer. Group and combat actions are command-table rows sent as `MessageQueueCommandQueueEnqueue` in an `ObjControllerMessage` (`CM_commandQueueEnqueue`). | `:395-479`; `command()` at `:184-188` |
| observations | one line per event on stdout: `DRIVER {"schema_version":1,"event":...}`; `command_result` (from `MessageQueueCommandQueueRemove`), `system_message` (`ChatSystemMessage` with its string id), `menu`, `sui`, conversation events, `teleport_ack`, `failure` | `:73-75`, `:306-372` |
| end | `logout` sits and sends `logoutServer`, then waits for `LogoutMessage` (`logout_accepted`); `quit` disconnects; end of stdin disconnects after 2 s; the `timeoutSeconds` deadline fails the peer | `:447-452`, `:393`, `:397`, `:244`, `:230` |

How Python runs it (`devtools/zones/protocol_driver.py`): `main` checks the fixture, waits until the bot is
unloaded (`:475`), writes the config (`:480`), copies the binary and config into the fixture's game container
(`:484-486`) and starts `docker exec -i <game> driver driver.cfg` through `Session` (`:249-331`, started at
`:494`). `Session` reads `DRIVER` lines on a thread and `wait`/`wait_any` block for a named event (`:282-303`).
The run logs in, does its one job, logs out, proves the bot unloaded and saved, and closes the peer in `finally`
(`:582-601`). A binary is accepted only with a `<binary>.build.json` recording the sha256 of the source, of
`ProtocolCompanionRoster.h` and of the binary (`:392-404`).

In a suite, every `session` step is one such process: `run_suite` runs `protocol_test_sets.py`'s argv for the case
in a subprocess (`swg_test_studio/backend.py`, the `else` branch of the case loop; `devtools/zones/protocol_test_sets.py:389`,
`:467`). So before this work no session outlived its step, and an `agent_fixture` step could never act on a bot an
earlier step had logged in. `protocol_scenarios.py` does hold several peers at once (`:817-829`), but only inside one
scenario process.

## Held sessions

A `client` step with `session_hold` starts one peer for its role and keeps it logged in; later `client` steps send
it typed requests; `agent_fixture` steps run in between against the loaded bot; `session_release` logs it out.
Existing `session` steps and every other case kind run exactly as before.

### Control channel

- Request: one stdin line `@<id> <verb> [companion-id] [value...]`, `id` 1-999999 and increasing per peer
  (`Driver::request`, `protocol_driver64.cpp:206-227`). Lines without `@` keep their original meaning; only `logout`
  and `quit` are used on a held peer, to close it.
- Reply: exactly one `DRIVER {"event":"reply","request":<id>,"verb":...,"accepted":true,"sequence":<n>}` after the
  message is queued, or `"accepted":false,"reason":...` (not companion, bad value, session not ready). A refused
  request does not stop the peer; the runner fails the step and tears down.
- Observations: further `DRIVER` events at any time (table below). The runner matches them by type, by fields and by
  arrival after the request was sent.
- Timeouts: reply 10 s (`HELD_REPLY_TIMEOUT`), observations 30 s per step (`timeout` option, 5-120 s), login 120 s,
  logout 40 s. The peer's own deadline (`timeoutSeconds=900`, its maximum) bounds a held session's life.
- Shutdown: `logout` and wait for `logout_accepted`; otherwise `quit`; then close stdin (the peer exits 2 s after end
  of input), `terminate`, `kill`; the live launcher then waits until the bot is unloaded.

### Python side (`swg_test_studio/backend.py`)

- `HeldPeer` (`:154`): one process, a reader thread, `find`/`wait` over all events, `request` (`:220`), `close` (`:239`) that never
  raises and always ends the process.
- `HeldPool` (`:293`): at most `model.MAX_HELD_SESSIONS` = 5 roles at once (one per declared role; the limit is the
  suite's role limit). `perform` (`:330`) runs one client case and returns the reply and every observation it
  waited for; `_apply` (`:463`) mirrors the proven group and trade state; `close` (`:505`) cancels an open trade,
  disbands or leaves groups, then logs every role out.
- `held_launcher` (`:529`): the live launcher. It checks the fixture and the binary's build record, copies the binary
  once into the game container, and per role waits until the bot is unloaded, writes a config naming every other
  bound role's bot as a companion, starts the peer, waits for `scene_ready` with the registered character and for
  `settled`. Bots must have logged in once before (their object IDs are the companions' IDs).
- `run_suite` creates the pool on the first `client_action` case, records each `agent_fixture` reply (for
  `item_from`), and closes the pool in `finally` whether the run passed or not: one failing role tears all roles
  down. A held session that does not close cleanly fails the run (`report["held_sessions"]`).
- No lock is held across steps: the management lock (`devtools/manage/service.py:93`) belongs to each `session`
  subprocess, which a held run may still contain for other roles.

## The `client` step

```json
{"id": "invite", "action": "client", "options": {"role": "leader", "kind": "group_invite", "peer": "member"}}
```

A `client` step compiles to one `client_action` case. `role` and `peer` are declared roles of the suite, and `peer`
is never the step's own role. Optional on every non-session kind: `timeout` (5-120 s) and `expect` (below). There
is no free-form command, target name or message beyond a bounded tell text.

### Actions, wire messages and observations

All rows: **unrun**. "Grounded" means the message is built with the tree's own class, in the field order of its pack
code, as the reference client builds it, and the bytes were checked (`ClientWireTests`). Tree paths are relative to
the server checkout; `SNM` = `src/engine/shared/library/sharedNetworkMessages/src/shared`, `SG` =
`src/engine/server/library/serverGame/src/shared`.

| kind (fields) | peer verb | message sent (pack code) | server handler | runner waits for | grounded |
|---|---|---|---|---|---|
| `session_hold` | (login) | as a `session` step | as above | `scene_ready` with the bot's character, then `settled` | yes (existing path) |
| `session_release` | `logout` line | `logoutServer` command, then `LogoutMessage` | as above | `logout_accepted`, exit 0, bot unloaded | yes (existing path) |
| `group_invite` (`peer`) | `groupInvite` | `MessageQueueCommandQueueEnqueue(seq, crc("invite"), invalid, peer name)` in `ObjControllerMessage(CM_commandQueueEnqueue)` (`SNM/clientGameServer/MessageQueueCommandQueueEnqueue.cpp:79`, `ObjectChannelMessages.cpp:119`) | `command_table.tab:801` → `SG/command/CommandCppFuncs.cpp:3881` | actor `command_result` for its sequence, status 0 | yes |
| `group_join` (`peer`) | `groupJoin` | same, `crc("join")`, target = inviter | `command_table.tab:823` → `CommandCppFuncs.cpp:4000` | same | yes |
| `group_decline` | `groupDecline` | same, `crc("decline")`, no target | `command_table.tab:632` → `CommandCppFuncs.cpp:4039` | same | yes |
| `group_uninvite` (`peer`) | `groupUninvite` | same, `crc("uninvite")`, target = peer | `command_table.tab:1064` → `CommandCppFuncs.cpp:3953` | same | yes |
| `group_leave` | `groupLeave` | same, `crc("leaveGroup")` | `command_table.tab:833` → `CommandCppFuncs.cpp:4085` | same | yes |
| `group_disband` | `groupDisband` | same, `crc("disband")` | `command_table.tab:642` → `CommandCppFuncs.cpp:4085` | same | yes |
| `group_make_leader` (`peer`) | `groupMakeLeader` | same, `crc("makeLeader")`, target = peer | `command_table.tab:849` → `CommandCppFuncs.cpp:4486` | same | yes |
| `group_dismiss` (`peer`) | `groupDismiss` | same, `crc("dismissGroupMember")`, target = peer | `command_table.tab:643` → `groupDisband` | same | yes |
| `trade_request` (`peer`) | `tradeRequest` | `MessageQueueSecureTrade(TMI_RequestTrade, invalid, peer)` in `ObjControllerMessage(CM_secureTrade)`: `int id, NetworkId initiator, NetworkId recipient` (`SNM/clientGameServer/MessageQueueSecureTrade.cpp:79`; client-allowed at `:18`); as `ClientSecureTradeManager.cpp:211` | `SG/controller/CreatureController.cpp:326`, `:1650`; recipient gets `TMI_TradeRequested` (`:1841`) | peer `secure_trade` `requested` from the actor; actor `busy`/`unreachable`/`denied` fails the step | yes |
| `trade_accept` | `tradeAccept` | same, `TMI_AcceptTrade, invalid, invalid` | `CreatureController.cpp:1807` → `ServerSecureTrade::beginTrading` (`SG/trading/ServerSecureTrade.cpp:536`) | both `trade_begun` naming the other | yes |
| `trade_deny` | `tradeDeny` | same, `TMI_DeniedTrade, invalid, invalid` | `CreatureController.cpp:1819` → `ServerSecureTradeManager.cpp:72` | requester `secure_trade` `denied` | yes |
| `trade_add_item` (`item` or `item_from`) | `tradeItem` | `AddItemMessage(NetworkId)` (`SNM/clientGameServer/SecureTradeMessages.cpp:52`) | `SG/core/Client.cpp:1323` → `ServerSecureTrade.cpp:411` | partner `trade_item_added` with the item; actor `trade_item_failed` fails the step | yes |
| `trade_credits` (`amount`) | `tradeCredits` | `GiveMoneyMessage(int)` (`SecureTradeMessages.cpp:122`) | `Client.cpp:1372` → `ServerSecureTrade.cpp:966` | partner `trade_credits` with the amount | yes |
| `trade_offer` | `tradeOffer` | `AcceptTransactionMessage` (no fields, `:160`) | `Client.cpp:1392` → `ServerSecureTrade.cpp:372` | partner `trade_offer_accepted`; when both offered, both `trade_verification` (`:559`) | yes |
| `trade_unoffer` | `tradeUnoffer` | `UnAcceptTransactionMessage` (`:179`) | `Client.cpp:1419` → `ServerSecureTrade.cpp:1149` | partner `trade_offer_withdrawn` if the actor had offered | yes |
| `trade_verify` | `tradeVerify` | `VerifyTradeMessage` (`:197`) | `Client.cpp:1439` → `ServerSecureTrade.cpp:1109` | partner `trade_verified`; when both verified, both `trade_complete` (`:603`) | yes |
| `trade_reject` | `tradeReject` | `DenyTradeMessage` (`:215`) | `Client.cpp:1458` → `ServerSecureTrade.cpp:1013` | partner `trade_rejected`, both `trade_begun` again | yes |
| `trade_cancel` | `tradeCancel` | `AbortTradeMessage` (`:35`) | `Client.cpp:1478` → `ServerSecureTrade.cpp:579` | both `trade_aborted` | yes |
| `tell` (`peer`, `text`) | `tell` | `ChatInstantMessageToCharacter(seq, ChatAvatarId("", "", peer name), text, "")`: `ChatAvatarId` (3 strings), message, out-of-band, `uint32 sequence` (`SNM/chat/ChatInstantMessageToCharacter.cpp:12`, `ChatAvatarIdArchive.cpp:24`); as `CuiInstantMessageManager.cpp:255` | forwarded to chat by `src/engine/server/application/ConnectionServer/src/shared/ClientConnection.cpp:645`; chat server answers `ChatOnSendInstantMessage` (`.../ChatServer/src/shared/ConnectionServerConnection.cpp:167`) and delivers `ChatInstantMessageToClient` (`ChatServer.cpp:2106`) | actor `tell_result` for its sequence, result 0; peer `tell_received` with the text from the actor | yes (bytes); delivery depends on a chat server |

Peer events added for these observations: `reply`, `secure_trade` (`trade` = `request`, `requested`, `accept`,
`denied`, `busy`, `unreachable`, `reversed`; `initiator`, `recipient`), `trade_begun`, `trade_item_added`,
`trade_item_failed`, `trade_item_removed`, `trade_credits`, `trade_offer_accepted`, `trade_offer_withdrawn`,
`trade_verification`, `trade_verified`, `trade_rejected`, `trade_complete`, `trade_aborted`, `tell_result`,
`tell_received` (`protocol_driver64.cpp:317-321`, `:374-392`). `command_result` gained a `sequence` field.

`expect` (optional, typed, exact strings like `agent_fixture` expectations): `status` (group kinds: the
`command_result` status to require instead of 0), `result` (tell: the chat result instead of 0),
`actor_message` / `peer_message` (a `system_message` string id `table:name` the actor, or the peer or trade partner,
must receive). A step whose observation contradicts it (another status, a busy partner, a refused item) fails at
once rather than timing out.

`trade_add_item` takes either `item` (a literal object ID) or `item_from: {"step": <id>, "row": 0-9}`: the first
comma field of that reply row of an earlier `createInInventory` step of the same role
(`swg_test_studio/fixture_ops/scenario.py`), so a suite can trade an object it created.

### Order rules (checked when a suite is validated, `client_order`, `swg_test_studio/model.py:120`)

- A role needs `session_hold` before any client action, and so does the peer it names. A held role can't run a plain
  `session` step until it is released.
- Groups: `group_join` and `group_decline` need an open invitation to the actor; `group_join` must name the inviter;
  `group_uninvite` needs the actor's own open invitation; `group_disband`, `group_make_leader` and `group_dismiss` are
  for the current leader only, and the peer must be in the leader's group; a group of fewer than two dissolves.
- Trades: each role trades with one peer at a time; only the requested peer answers a request; items, credits,
  offers and verification need an accepted trade; adding items or credits, `trade_unoffer` and `trade_reject` clear
  both offers; `trade_verify` needs both offers; both verifying completes the trade.
- `item_from` must name an earlier `createInInventory` step of the trading role.
- `session_release` is refused while the role has an open trade. Sessions still held at the end of a suite (or after
  a failure) are released by the runner.

These rules model the server statically. The live server can still refuse (range, a busy peer, an ignore list); the
step then fails on the observation, or on the fixture's assertion.

### Example suites

- `swg_test_studio/examples/trade_two_accounts_client.json`: two accounts; the seller creates a recording rod in a
  scenario, trades it for 250 credits; `tradeState` and `diff` assert the outcome; a tell; cleanup.
- `swg_test_studio/examples/group_invite_accept_client.json`: invite declined, `groupOf` shows no group, invite
  accepted, `groupOf` shows the group, a tell, disband, `groupOf` shows none.
- Earlier: `trade_between_accounts.json`, `group_with_fixture_asserts.json`, `scenario_concert.json`.

All validate and plan under both profiles.

## Profiles

`restoration` lists `client_action` in `case_kinds` and every client kind in `client_kinds`
(`devtools/zones/server_profile.py:137-140`); `unsupported` refuses a kind a profile does not list (`:193`). None
needs a zone instance, station, ship or recorder. The client sources are added to the restoration per-run source
hashes. Under `whitengold` nothing is refused, as before.

`plan` counters: a `client_action` case is no longer counted as a legacy proximity setup
(`fixture_proximity_setup`), and `group_invite`/`group_join` steps set `group_cleanup_possible`
(`swg_test_studio/backend.py:89`, `:107`). Plans of suites with client steps also report `client_held_roles`,
`client_actions`, `client_trade_possible` and `client_tells`; every other plan is byte-for-byte as before
(`DefaultPlanTests`).

## Build and compile check

The repository has no peer build script: `protocol_test_sets.py` hashes a `build_protocol_driver64.py` that is not
bundled, and `validate_binary` needs the `.build.json` record such a build writes. The check below was made by hand:

1. Flags: the `-D` defines and the `include/public` and `src/external` include directories of the tree's own CMake
   `compile_commands.json` (entries for `sharedNetworkMessages`, `sharedGame` and server sources), with
   `-std=gnu++17 -m64`.
2. The unmodified upstream `protocol_driver64.cpp` does **not** compile against the restoration tree: one error,
   `CreateProjectileMessage(int,int,int,int,Transform,uint32)` has no match; the tree's constructor takes a ship
   `NetworkId` first (`SNM/clientGameServer/CreateProjectileMessage.h:25`). This is pre-existing.
3. Fix behind the profile: build with `-DSWG_STUDIO_PROFILE_RESTORATION`, which compiles out the `fire` action
   (`protocol_driver64.cpp:404`); the restoration profile has no ships. Without the define the source is unchanged
   for the default build.
4. Result: the object compiles with the define, with no new warnings; without the define it still fails with exactly
   the pre-existing error. Linked against the tree's built shared libraries (plus the UDP library objects and
   ncurses), the binary's `--encode` mode printed the bytes in `tests/data/client_wire_bytes.json`.
5. Not checked: a build against the WhiteNGold tree, and a run against any server.

`driver --encode <character> <sequence> <verb> [companion-id] [name] [text...]` builds one client action with the
same function the held peer uses (`buildClientAction`, `protocol_driver64.cpp:127`; `encodeClientAction`, `:500`),
prints `ENCODED <verb> <hex>` and exits without config or network. Rebuild and re-record the bytes after changing the
peer; `ClientWireTests` checks the recorded source hash.

## Left out, with what each would need

- **Removing a trade item.** `RemoveItemMessage` exists, but `ServerSecureTrade::removeItem` cancels the whole trade
  (`ServerSecureTrade.cpp:1043`; checked by a test). Use `trade_cancel`. The peer still reports `trade_item_removed`.
- **Mail and friends.** Grounded messages exist (`ChatAddFriend` is forwarded to chat by `ClientConnection.cpp:638`;
  `ChatPersistentMessageToServer` is routed at `:804`) but have no typed step yet; their observations (`ChatOnSendPersistentMessage`,
  `ChatOnAddFriend`) are not decoded.
- **Bank and other terminal flows.** Banking is a terminal SUI flow; it would need a typed step answering a named
  SUI page with an amount.
- **`TMI_RequestTradeReversed` and server-only trade ids.** The server refuses them from a client
  (`SG/trading/SecureTradeIntegrity.h:315`).
- **Automatic open on first use.** A role is held only by an explicit `session_hold`; the order rules require it.

## What a first live run must confirm

1. A peer built from this source for the restoration tree (and, separately, for WhiteNGold) logs in, holds the scene
   for a whole suite and logs out cleanly; `timeoutSeconds=900` is accepted.
2. The new controller id and messages: the server applies `CM_secureTrade` from the peer (allowed from client) and
   the peer decodes `TMI_TradeRequested`/`TMI_Denied*` replies; `BeginTradeMessage` and the other trade messages
   arrive as listed, in that order.
3. `command_result` arrives for `invite`, `join`, `decline`, `uninvite`, `leaveGroup`, `disband`, `makeLeader` and
   `dismissGroupMember` with status 0, and which `system_message` string ids each side receives (none are asserted
   by default).
4. Trade range: the two bots must be within the server's trade range; `bring` in the examples is assumed to be
   enough.
5. A tell needs a running chat server and a chat avatar for each bot; whether `tell_received.from` is the character
   name the runner compares case-insensitively.
6. `createInInventory` reply rows start with the created object's ID, and `scenarioEnd` (run by the seller) finds the
   traded rod in the buyer's inventory; if not, the rod outlives the scenario.
7. The `diff` fields `lost`/`partner_gained` count one traded item; `tradeState` is clean after completion.
8. A failure mid-trade: teardown's `tradeCancel` aborts the trade for both, and every bot unloads.
