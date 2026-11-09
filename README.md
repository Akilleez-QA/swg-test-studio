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

The full SWG regression collection is supplied in the server checkout at
`devtools/teststudio_server/swg-regression-collection.json`. It includes Studio
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

## Run suites concurrently

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

## Environments and execution

An environment profile tells Studio which server checkout, test fixture and
driver to use. It also maps the test's role names to dedicated character
registries in that fixture. The desktop form explains each field, shows an
example and saves the JSON for you. **Open profile** loads an existing file.
Studio reopens the profile named `environment.json` in its workspace at launch.

The SWG server checkout, matched ELF64 driver, WSL/Linux runtime and prepared
isolated fixture are external dependencies. No server/client source, libraries,
assets or credentials are copied into this repository.

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
Failure stops subsequent cases. Cleanup/full-unload assertions remain owned by
the original driver; no link-dead state is counted as unloaded. No service,
database, image, fault or privilege operation is generated by Studio.

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
