# SWG Test Studio

A standalone local desktop application and CLI for SWG test authoring, existing
ELF64 protocol-driver execution and opt-in server-side gameplay observations.
The Windows game client is unchanged.

Version 0.2 adds a focused record-to-test compiler and connected-session replay
for Tansaari/Gamma shuttle confirmations and cancellations. Recorded terminal
requests, offered dialogs, matching callbacks and authored arrivals become a
typed journey, using fresh runtime target/page identities during replay. Users
review the captured expectations before approving a draft. Unsupported actions
remain blocked. The Ord action sequence adds launch, landing and two-role
groups. General movement, flight paths, other terminals and larger groups remain
open. On November 8, 2026, automated live capture,
explicit clip export and replay passed for cancellation and both shuttle
directions. A connected-session round trip also passed. Human Windows-client
recording and visual acceptance remain pending.

## Start

Python 3.10+ is required. The desktop also needs Tk (included with standard
Windows Python; Linux distributions may package `python3-tk` separately). No
third-party Python runtime dependencies or HTTP listener are used.

From this repository:

```powershell
python swg-tests.py gui
python swg-tests.py list
python swg-tests.py validate gamma_shuttle
```

The root `swg-tests.ps1` forwards the same arguments. Optional installation:

```text
python -m pip install -e .
swg-tests gui
```

For an offline source application bundle, run
`python build_release.py --output dist/swg-test-studio-0.2.0.zip`, extract it,
then use `python swg-tests.py gui`. This requires Python/Tk, not a separate game
client modification. Wheel packaging requires the normal `setuptools` and
`wheel` build dependencies; it was not validated on the initial host because
Windows lacked `wheel` and the WSL Python lacked `pip`.

Start in **Library**. Select an example to see what it checks and which
characters it needs. **Open** and **Validate** work offline. **Copy example**
creates an editable saved test. Use **Help** for the workflow and **Set up
environment** when you are ready to preview, run or record.

## Reusable regression collections

A collection is one versioned JSON file holding multiple complete suites. Use
**Library → Import JSON** to open it, then **Save collection as** to make your
own copy. Search by title or ID. Open a suite to edit it, or choose **New test**
to add a draft. Review the draft and click **Save** to add it to the open
collection. You can also import an individual test or record a draft and save
it into the collection. **Export test** writes the current suite to a separate
JSON file.

The full SWG regression collection ships with Studio at
`swg_test_studio/collections/swg-regression-collection.json`. It includes Studio
examples and exact copies of the original saved driver manifests. Studio runs
the Studio entries. Driver entries can be inspected, edited and exported in
their original format for the server harness. Their backend validation,
fixture requirements and authorization remain with the server harness.
Opening a collection runs nothing.

Use the same collection in CI. Run a Studio suite by ID with the environment
for that job's isolated fixture.

```bash
python3 swg-tests.py --collection swg-regression-collection.json list
python3 swg-tests.py --collection swg-regression-collection.json validate ord_round_trip
python3 swg-tests.py --collection swg-regression-collection.json run ord_round_trip --environment environment.json
```

To take a fresh baseline snapshot, export to a new filename. Keep any edited
collections in version control and bring forward your additions separately.

```bash
python3 swg-tests.py export-regression --server-checkout /path/to/whitengold --output swg-regression-new.json
```

## Organize and run groups

In **Library**, use **New group** and drag tests onto group rows. Open or
collapse a group with its disclosure arrow. Drop a test onto **Ungrouped**
to take it out of a group. Removing a group returns its tests to Ungrouped.
Groups are stored in the open collection or in the local Library workspace.

Right-click a test in **Library**, or focus it and press **Shift+F10**, to open
its actions. **Run this test** and **Preview run** use that saved test without
changing the editor or the checked tests. Use the same menu to open, validate,
export, or move the test to a group. **Remove from Studio** hides the test
without deleting its file. Turn on **Show removed tests** to restore it.

Click a checkbox in the **Run** column to check a whole group or an
individual test. A partially checked group shows a mixed checkbox. You can
check tests across multiple groups and use **Run selected** to run exactly
that selection. Server tests still use the original SWG server tools.

Selected Studio tests share one Docker server startup and run in Library
order. **Run & Results** shows elapsed time and completed tests. The Library
shows a spinner for the active test, a green check on pass, and a red X on
failure. The run retains combined and per-test reports.

For a failed test, right-click it in **Library** and choose **View latest
result**. From **Run & Results**, select a run and click **View test
results**. The viewer opens on the first failed step and shows its reason,
log, and file location. Tests with recorded shuttle, launch, landing, or
group actions also identify the failed action when the run captured it.
**Open saved report** can reopen a `result.json` or `batch-result.json`
from an earlier run. Keep the report alongside its logs.

The same selection can be called from CI by listing the test IDs:

```bash
python3 swg-tests.py --collection swg-regression-collection.json run-selected \
  --suite login_relogin --suite ord_round_trip --environment environment.json
```

## Run suites concurrently

From **Library** or **Edit**, submit another run while a test is active. Studio
starts compatible runs immediately and queues tests that share a Docker test
server or source checkout. A driver unit test can run alongside gameplay
because it uses no characters. For parallel gameplay, choose a different
source checkout and its own prepared Docker test server before submitting.
Studio retains the source, server, and test selection from each submission.
Use the **Run** selector in **Run & Results** to see each run’s progress and
reports separately. The desktop starts up to eight operations at a time.
Desktop evidence is grouped under `desktop-runs/` in the Studio workspace.
In **Library**, each test’s **Result** column shows its spinner, green check,
or red X. Click a group’s disclosure arrow or double-click its name to expand
or collapse it.

In **Run & Results**, select **Save batch template**, fill in each run's suite
ID and environment filename, then choose **Preview batch** or **Run batch**.
Select your collection first when the suites are stored there. Each profile
path can be relative to the batch file or an absolute Linux path.

```bash
python3 swg-tests.py batch-template > batch.json
python3 swg-tests.py --collection swg-regression-collection.json plan-batch --file batch.json --jobs 2
python3 swg-tests.py --workspace "$RUNNER_TEMP/studio" --collection swg-regression-collection.json run-batch --file batch.json --jobs 2
```

The limit is 1–8 workers and the CLI defaults to one. Suites sharing a server
checkout or a fixture project run in file order. A failure is reported while
the remaining suites are still run. Real overlap requires separate prepared
fixture projects and independent server checkouts. For GitHub Actions, a
matrix with one isolated runner and fixture per shard also provides
parallelism while retaining the existing management lock on each runner.

Batch output is under the workspace's `batches/<operation>/` directory.
Archive `batch-result.json`, `batch-junit.xml` and each suite's JSON, JUnit and
logs from there. A failed suite makes the batch exit nonzero. Driver-only
manifests remain in the original harness.

## Set up the desktop app

Install and start Docker. On Windows, enable Docker Desktop's integration
with the WSL distribution used by Studio (`Ubuntu-24.04` by default).

1. Click **Choose source folder** and select the WhiteNGold server checkout or
   its `src` folder. Studio remembers it and finds verified Docker test servers.
   Studio loads its pinned tools directly from its own `devtools/`.
2. Click **Find or start test server** to refresh the list. If no verified
   server is running, Studio starts one prepared server and leaves it
   available for testing. Select another verified server if needed.
   Studio picks prepared test characters for the selected test.
3. Click **Preview run** or **Run**. If Studio starts a stopped server, it
   stops its game containers when the run finishes, unless **Keep test server
   running** is selected. A server that was already running is reused.

You can create and validate tests offline. **Remove from Studio** hides a test
in the current workspace and preserves the file. Turn on **Show removed tests**
to restore it. **Server test** identifies a test for the original SWG test tools.

### Pinned server tools

Studio's repository and source ZIP include the WhiteNGold runners, their
dependencies and the test recipes Studio uses. Studio resolves these files
from its own `devtools/` directory, including when the selected server checkout
has a different tools version. Choose the matching server checkout for its
native source, authored data and local release and fixture records. Live runs
also need the matched ELF64 protocol peer and an isolated prepared Docker server.

`devtools/studio-tools.json` records the WhiteNGold base revision and each
bundled file's SHA-256. The fixture contracts retain the upstream producer
hashes for the modules adapted to separate tool and server paths. Run reports
record the actual bundled bytes alongside the server source evidence.

An environment file may name a server profile (`"profile": "restoration"`) to drive a
server built from a tree without zone instances; the default is `whitengold`. See
`docs/restoration-profile.md` for what that profile supports and requires.

### Prepare a Docker test server

The existing SWG server build and staging tools produce the matching
64-bit binaries, Docker game roles and an isolated database copy. Connect a
prepared test server to its source checkout once, using a private runner
profile that lists only the test characters available for Studio.

```bash
python3 swg-tests.py register-test-server --environment /path/to/private-profile.json
```

Studio stores that registration in the checkout's local logs and verifies
the Docker container identities and image pins before presenting the server.
A source folder alone does not provide the server's native build dependencies,
game data or database preparation. This release starts or reuses prepared
server containers. See the server checkout's `docs/protocol-driver64.md`
for its build and test-server preparation.

### CLI and GitHub Actions

Studio CI builds the app in a temporary Docker image, runs its component
tests, and uploads the build log, test log and result. It can run on pull
requests or from **Actions → Studio CI → Run workflow**. Run the same check locally:

```bash
python3 swg-tests.py docker-check
```

For live gameplay in CI, use an isolated Linux runner with a prepared SWG test
server. The explicit environment input for `plan`, `run` and batch commands
continues to work. It contains paths and test character bindings.

```text
python swg-tests.py environment-template
```

Save and edit the output as a private `environment.json`. Set `server_checkout`,
`folder` and `binary` to absolute **Linux/WSL** paths. Bind suite roles to existing
dedicated registries. The fixture must satisfy the original driver's schema,
labels, runtime, image, identity, authentication and provenance checks. An
environment file contains paths/bindings, never passwords or authentication tokens.

```powershell
python swg-tests.py plan gamma_shuttle --environment environment.json
python swg-tests.py run gamma_shuttle --environment environment.json
```

Windows live operations dispatch to WSL through argument arrays, using the
`SWG_WSL_DISTRO` environment variable or `Ubuntu-24.04`. The application source or
installed pure-Python package must be visible through WSL's mounted filesystem.
The GUI uses these same CLI services in a background process.

Run output retains the original driver logs/receipts plus application and server
source hashes, the exact suite and compiled execution manifest, JSON and JUnit.
Failure stops subsequent cases. Cleanup and full-unload assertions remain
owned by the original driver. Studio removes its exact temporary app check
image after the tests. The test-server controls operate on verified existing
containers and preserve their database volume.

Default local storage is `%LOCALAPPDATA%/SWGTestStudio` on Windows and
`$XDG_STATE_HOME/SWGTestStudio` (normally `~/.local/state/SWGTestStudio`) on Linux.
Set `--workspace PATH` before the command to use a different location. Recordings,
user suites, run evidence and the local operation lock live there. Keep run logs
private: inherited server diagnostics can contain sensitive fields.

## Bundled examples

| Test | Prerequisites and behavior |
| --- | --- |
| `login_relogin` | Existing dedicated character; two complete login/logout/save lifecycles |
| `create_character` | Explicit dedicated creation; respects existing eight-registry budget; separate lifecycle from travel |
| `gamma_shuttle` | Actor prepared at Tansaari; explicit terminal-proximity setup; original menus/dialogs, Gamma and correct return hangar |
| `ord_round_trip` | Portable sequence from the accepted live recording of Ord launch and landing |
| `ord_group_sequence` | Editable typed sequence for two solo Tansaari actors: form a group, promote, launch, land and disband |
| `ship_and_group` | Two prepared station actors, required original ships/pilot fixture; normal launch, landing and group journey |
| `group_disband` | Three retained roles and the existing reviewed linked Rryatt/Ord fixture; disband, solo behavior and new-group affinity |
| `driver_guards` | Existing driver's unit regressions; no live game actions |
| `terminal_journey` | Connected-session Gamma round trip with fresh terminal/dialog resolution, exact authored rooms and full logout/save |
| `shuttle_recorded_cases` | Three portable cases derived from accepted live recording: cancel, travel to Gamma, return to the correct station hangar; each has its own setup/login/logout/save lifecycle |

Roles used by each example must be present in the environment. At most five
distinct actors execute. Saved-suite adapters expose an explicit ordinary-action
allowlist; they do not expose historical deliberate-fault suites.

Each `session` is a **complete login/action/logout/save lifecycle**. A `journey`
keeps one existing dedicated actor connected for 1–16 typed terminal actions,
then proves normal logout, full unload and its saved point. `saved_suite`
reuses a reviewed existing scenario. Expectations such as `expect_scene` and
`expect_family` are typed options. Unknown fields, executable commands and stale
dialog IDs are rejected. Examples demonstrate format/semantics; validation is
not fresh live acceptance.

## Recording normal gameplay

Server integration lives in the SWG server repository:
`devtools/teststudio_server/README.md` and the `TestStudioRecorder` / capture
headers under `serverGame`. A matched native build is required. Only an isolated
fixture with `GameServer.clientIsolationFixture=1`, its matching copied `WGC_`
schema and explicit `GameServer.testStudioRecorder=true` can collect events.
Record never changes configuration or starts/restarts services. The native flag
defaults to false; production role configuration must leave it false.

Prepare the isolated fixture with the explicit `--test-studio-recording` option
and its matching native contract. This supplies a dedicated writable
`/teststudio-capture` bind; the existing `/fixture` tools mount remains read-only.
Record checks the prepared profile, effective game-role flag and exact mount.
It accepts only exact registered non-god test character
name, actor ID and station ID. The recorder accepts one selected role, or two with the action-capture profile,
for 30–3600 seconds, with 4096 events/8 MiB bounds and visible incomplete-capture
errors. It records scene publication, menu requests, offered pages, movement
markers, command hashes/target IDs and validated SUI callbacks. It does not record passwords, tokens, arbitrary command
parameters, chat/mail, raw packets or arbitrary dialog text.

```powershell
python swg-tests.py record-start --environment environment.json --role actor
# Play normally with the dedicated character in the unchanged Windows client.
python swg-tests.py record-status --recording RECORDING_ID
python swg-tests.py record-stop --recording RECORDING_ID
python swg-tests.py record-draft --recording RECORDING_ID --id my_journey --title "My journey"
```

The Record view exposes the same controls and an event timeline. Stop removes
only this session's exact owned subscription and fences in-flight appenders;
subscriptions also expire. Expired subscriptions require explicit Stop before
another recording. Recordings persist across the character's zone changes and
logout/relogin while the subscription remains active. Recording does not grant
developer-command access or alter gameplay eligibility.
Start displays the dedicated test account and character to use in the normal
Windows client. Stop recording, log that character out and wait for full unload
before replay; Studio does not disconnect a human client to take over its actor.

Draft export refuses empty, corrupt, missing-sequence and overflow captures.
Complete supported shuttle interactions export as a `journey` containing
`radial_dialog` actions, source states and expected destination states. A new
`sui_presented` observation must precede its matching callback; confirmation
must have an observed arrival in the authored opposite-family entrance.
Cancel expects the same copy, cell and coordinates and waits for the server
callback to consume its pending dialog. Incomplete interactions, old capture
contracts, walking, unknown commands and unrelated dialogs stay unsupported.
Unsupported captures remain inspectable as observation drafts; approving a test
never makes observation-only steps executable.

You can choose completed actions from a longer recording using explicit clips.
In Record, enter inclusive sequence ranges such as `6:8, 16:21` from your own
timeline before Export draft. The CLI accepts repeated `--range FIRST:LAST`
options. Each clip becomes a separate journey case with declared start setup;
the original recording ID and selected ranges stay in the review metadata.
The full raw timeline remains available. Unsupported or incomplete interactions
inside a selected clip block approval, and corruption anywhere in the capture
blocks export. Blank selection uses the entire recording. Nothing is trimmed
automatically; starting a new recording clears the previous clip selection.

In Edit, review expectations, use **Approve reviewed expectations**, then Save,
Preview and Run. Approval cannot clear unresolved unsupported actions. Replay
resolves the unique current-copy terminal through the read-only fixture helper
and answers a newly offered matching dialog. Old target IDs, page IDs and
instance numbers never become executable selectors.

Generated journeys explicitly set `prepare_start=true`. Preview reports this
fixture setup: if needed, normal shuttle travel restores the recorded starting
family, then the existing fixture-only terminal-proximity setup positions the
actor. Setup is separate from measured actions. It requires an ungrouped, quiet
actor already in a supported public station family and never resets quest data.
Set `prepare_start=false` to require the actor's current saved source/proximity.
The `terminal_journey` example also declares `prepare_between_actions=true`:
Gamma's authored arrival is outside the return terminal's eight-metre interaction
range, so the existing fixture-only proximity setup is explicitly repeated.
This option defaults to false. It requires the expected source, solo membership
and no combat; it does not infer or replay walking.
Ordinary access, combat and ownership rules remain active on the server.
Same-world room transfers use the existing driver's loading-complete handshake
after the authored destination is observed, followed by independent native
settlement and protection-expiry checks. The matching server observes completed
loading and publishes granted public-cell placement before the scene. It retains
the original private/group access boundary.


The server fixture needs the new `terminal_metadata=2` helper, version-2 native
capture fields and `retained_peer` adapter. Old helpers are refused. Captures
retain their full raw history; 32 observation steps are only a draft preview.
Arbitrary gameplay replay remains pending.

## Ord travel and two-character groups

The matching server build records the original launch-terminal selection,
validated station landing response, resolved invitation and join, and
authoritative group changes. It also records applied local teleports. A move
without a matching supported initiating action stays in the timeline for review.

Bind two distinct dedicated roles and enter both names separated by a comma in
Record. The CLI accepts a repeated `--role`. Two-role recording requires the
action-capture fixture profile. Begin solo and include both invitation and join
in the same clip as the group's observed membership. A group action sequence can
also include leadership changes, dismissal, leaving and disbanding. A solo Ord
launch and landing sequence needs only one role.

Draft export checks the actual travel destination and group state before making
a typed `action_sequence`. The existing protocol driver opens the live launch
menu and landing conversation. It checks ownership, pilot, the authored station
hangar and group membership with fresh identities. The run preview lists the
pilot reward and proximity preparation used by the fixture and the possible
cleanup of its own two-character group. During launch setup, an actor without a
ship receives the original starter ship. The land setup puts the ship within
normal comm range. The replay report separates setup from measured actions.

Use explicit timeline clips to separate independent actions and omit setup
transitions. A clip containing unsupported activity remains unapproved. The
coverage inventory in the server repository tracks other player travel,
gameplay and client-side entry points.

The live Ord recording and replay gate passed for one dedicated pilot. Group
recording and replay have component coverage. Live group acceptance requires a
second available dedicated actor.

## Arrange and inspect with the agent fixture

`agent_fixture` steps set up and check server state around ordinary-action steps:
put the bot in a room facing a direction, move a building or a piece of furniture,
grant expertise, skills or schematics, give static items, and read back rooms,
contents and objects. The test character itself still acts only through the
protocol driver; the fixture prepares and inspects, it never plays for the bot.

```json
{"id": "in_the_study", "action": "agent_fixture",
 "options": {"role": "actor", "op": "place",
             "args": ["<buildingOid>", "r2", "1.5", "0", "-2.0", "90"],
             "expect": {"cell": "r2"}}}
```

Install it once per prepared test server with
`python3 swg-tests.py install-agent-fixture --environment environment.json`: it compiles every fixture
class (`agent_fixture` and each `agent_<family>` present, plus the profile's bot fixture) against that
server's own script classes, one class file each, writes them where the fixture overlay re-applies them
on every game start, and reloads each on every game server without a restart.

The server side is `devtools/zones/fixtures/agent_fixture.java`
(`script.fixture.agent_fixture`), installed by the same fixture overlay as
`protocol_bot`. It shares that fixture's limits: it answers only on an isolated
fixture (`GameServer.clientIsolationFixture=1`, a `WGC_` copied schema), only for
one exact registered non-god bot (`oid:station:Cap…`), and only for objects in the
bot's scene within 256 m or inside the bot or its building. Every method is typed;
there is no command line, script name or expression to pass through.

Studio sends the call as one console message to the fixture's private CentralServer
console, on the game server the existing bot query reports for that bot, and fails
the step on any status other than `ok` or on an `expect` mismatch. The run plan lists
the mutating operations a suite uses under `agent_fixture_changes`.

Op families extend the fixture with more classes of the same shape, one Python module in
`swg_test_studio/fixture_ops/` and one Java class `devtools/zones/fixtures/agent_<family>.java`
each (see `docs/fixture-core.md`). Studio merges them into one op table and sends each op
to its own class. An op that names another bot takes that bot's **role** as an argument;
Studio replaces it with the role's registered identity, and refuses the acting role itself
or a role the test does not declare. Ops that create world state need a `scenario` id on
the step; everything they create is tagged with it, and the scenario family's
`scenarioEnd` destroys it again. The plan lists the ids under `agent_fixture_scenarios`
and whether each is ended in the suite. After a failed run, clean up with
`python3 swg-tests.py scenario-end --environment environment.json --role actor --id my_scenario`.
After an op that moves the bot to another scene, Studio waits (at most 90 s) until the bot
query finds the bot again before the next step.

The table below is generated from the merged op table. After adding or changing a family,
run `python3 -m swg_test_studio.agent_fixture refresh`; it also refreshes the bundled-tool
hashes of every `agent_*.java` (`--check` only reports what is stale).

<!-- agent-fixture-ops:begin (generated: python3 -m swg_test_studio.agent_fixture refresh) -->
| Operation | Fixture class | Arguments | Changes state | Scenario id |
|---|---|---|---|---|
| `inspect` | `agent_fixture` | - | no | - |
| `nearby` | `agent_fixture` | radius | no | - |
| `cells` | `agent_fixture` | oid | no | - |
| `contents` | `agent_fixture` | oid | no | - |
| `describe` | `agent_fixture` | oid | no | - |
| `items` | `agent_fixture` | - | no | - |
| `structure` | `agent_fixture` | oid | no | - |
| `countIn` | `agent_fixture` | oid | no | - |
| `tryPut` | `agent_fixture` | oid, oid | yes | - |
| `place` | `agent_fixture` | oid, cell, coord, coord, coord, yaw | yes | - |
| `warp` | `agent_fixture` | coord, coord, coord | yes | - |
| `moveInto` | `agent_fixture` | oid, oid, cell, coord, coord, coord | yes | - |
| `transform` | `agent_fixture` | oid, coord, coord, yaw | yes | - |
| `setDown` | `agent_fixture` | oid, cell, coord, coord, coord, oids | yes | - |
| `scale` | `agent_fixture` | oid, scale | yes | - |
| `grantExpertise` | `agent_fixture` | trees (optional) | yes | - |
| `grantSkills` | `agent_fixture` | regex | yes | - |
| `grantSchematics` | `agent_fixture` | - | yes | - |
| `itemBonuses` | `agent_fixture` | oid, mods | yes | - |
| `giveStatic` | `agent_fixture` | names | yes | - |
| `give` | `agent_fixture` | oid | yes | - |
| `completeCollection` | `agent_fixture` | name | yes | - |
| `clearDecor` | `agent_fixture` | oid, tag | yes | - |
| `stats` | `agent_character` | - | no | - |
| `buffs` | `agent_character` | name (optional) | no | - |
| `standing` | `agent_character` | char_faction | no | - |
| `setHealth` | `agent_character` | char_pool | yes | - |
| `setAction` | `agent_character` | char_pool | yes | - |
| `setMaxHealth` | `agent_character` | char_pool | yes | - |
| `setMaxAction` | `agent_character` | char_pool | yes | - |
| `healFull` | `agent_character` | - | yes | - |
| `incapacitate` | `agent_character` | - | yes | - |
| `revive` | `agent_character` | - | yes | - |
| `setPosture` | `agent_character` | char_posture | yes | - |
| `setLevel` | `agent_character` | char_level | yes | - |
| `setProfession` | `agent_character` | char_profession, char_level (optional) | yes | - |
| `revokeSkills` | `agent_character` | regex | yes | - |
| `resetExpertise` | `agent_character` | - | yes | - |
| `setBank` | `agent_character` | char_credits | yes | - |
| `setCash` | `agent_character` | char_credits | yes | - |
| `depositCash` | `agent_character` | char_credits | yes | - |
| `withdrawCash` | `agent_character` | char_credits | yes | - |
| `setFaction` | `agent_character` | char_aligned | yes | - |
| `setStanding` | `agent_character` | char_faction, char_standing | yes | - |
| `setPvpType` | `agent_character` | char_pvp | yes | - |
| `applyBuff` | `agent_character` | name, char_seconds | yes | - |
| `removeBuff` | `agent_character` | name | yes | - |
| `equipItem` | `agent_character` | oid | yes | - |
| `unequipItem` | `agent_character` | oid | yes | - |
| `giveStaticCount` | `agent_character` | name, char_count | yes | required |
| `resetCharacter` | `agent_character` | - | yes | - |
| `bring` | `agent_multi` | role, bring_offset (optional) (argument 1 is a role) | yes | - |
| `distanceTo` | `agent_multi` | role (argument 1 is a role) | no | - |
| `groupOf` | `agent_multi` | role (optional) (argument 1 is a role) | no | - |
| `groupLeave` | `agent_multi` | role (optional) (argument 1 is a role) | yes | - |
| `creditsOf` | `agent_multi` | role (argument 1 is a role) | no | - |
| `accountOf` | `agent_multi` | role (argument 1 is a role) | no | - |
| `tradeState` | `agent_multi` | role (optional) (argument 1 is a role) | no | - |
| `snapshot` | `agent_multi` | snapshot_name, role (optional) (argument 2 is a role) | yes | - |
| `diff` | `agent_multi` | snapshot_name, role (optional) (argument 2 is a role) | no | - |
| `snapshotDrop` | `agent_multi` | snapshot_name, role (optional) (argument 2 is a role) | yes | - |
| `giveTo` | `agent_multi` | role, oid (argument 1 is a role) | yes | - |
| `payTo` | `agent_multi` | role, pay_amount (argument 1 is a role) | yes | - |
| `scenarioBegin` | `agent_scenario` | scenario | yes | - |
| `scenarioEnd` | `agent_scenario` | scenario | yes | - |
| `scenarioList` | `agent_scenario` | scenario | no | - |
| `createAt` | `agent_scenario` | objtemplate, worldxz, worldxz, yaw | yes | required |
| `createInCell` | `agent_scenario` | objtemplate, oid, cell, celllocal, celllocal, celllocal, yaw | yes | required |
| `createInInventory` | `agent_scenario` | objtemplate, spawncount (optional) | yes | required |
| `destroyCreated` | `agent_scenario` | oid | yes | - |
| `spawnCreature` | `agent_scenario` | creaturename, spawnoffset, spawnoffset, spawnlevel (optional) | yes | required |
| `creatureAttack` | `agent_scenario` | oid | yes | - |
| `creaturePassive` | `agent_scenario` | oid | yes | - |
| `creatureInvulnerable` | `agent_scenario` | oid, onoff | yes | - |
| `creatureMove` | `agent_scenario` | oid, spawnoffset, spawnoffset | yes | - |
| `creatureKill` | `agent_scenario` | oid | yes | - |
| `creatureDespawn` | `agent_scenario` | oid | yes | - |
| `questGrant` | `agent_scenario` | questname | yes | - |
| `questComplete` | `agent_scenario` | questname | yes | - |
| `questClear` | `agent_scenario` | questname | yes | - |
| `questSignal` | `agent_scenario` | questsignal | yes | - |
| `quests` | `agent_scenario` | - | no | - |
| `setTestVar` | `agent_scenario` | vartarget, varname, vartype, varvalue | yes | - |
| `clearTestVar` | `agent_scenario` | vartarget, varname | yes | - |
| `getTestVar` | `agent_scenario` | vartarget, varname (optional) | no | - |
| `warpScene` | `agent_scenario` | scenename, worldxz, worldy, worldxz | yes | - (changes scene) |
| `face` | `agent_scenario` | yaw | yes | - |
<!-- agent-fixture-ops:end -->

## Verify and coverage limits

```text
python -m unittest discover -s tests -v
python tests/gui_smoke.py
```

The hidden-window smoke checks Studio's own widgets; it is not game rendering
acceptance. Protocol/server, unit/component and Windows visual outcomes remain
separate. The accepted live gate used one dedicated actor in the retained isolated
SWG fixture, a matched ELF64 server/driver and actual native recording events.
All three selected cases replayed with fresh offered dialogs, settled arrivals,
full unload and saved-position checks. The complete raw capture is retained;
login/setup transitions outside the explicit clips remain unsupported as whole-
timeline replay. Other bundled server recipes have schema/adapter coverage and
their own server acceptance history; they were not all rerun for this milestone.
Human recording, general movement, other terminal compilers and larger
recording rosters remain open. Stage 8 acceptance remains owned by the SWG server project
and is not changed by this application.
