# The `restoration` server profile

Studio's live runs were written for one server tree (WhiteNGold) and its prepared
fixture. A **server profile** names the tree and fixture Studio is driving:

| profile | meaning |
|---|---|
| `whitengold` (default) | the original behaviour, unchanged |
| `restoration` | a server built from a tree without zone instances, capacity consoles or the Test Studio recorder (for example a Dec 2011 restoration of the public SWG-Source tree) |

Select it with an optional key in the environment file:

```json
{"schema_version": 1, "name": "Restoration fixture", "profile": "restoration",
 "server_checkout": "/path/to/server-checkout",
 "folder": "/tmp/swg-cold-test-0123abcd/client-012345abcdef",
 "binary": "/tmp/swg-driver64/driver", "bindings": {"actor": "tester"}}
```

Without the key the environment is a `whitengold` one (`swg_test_studio/backend.py:37`).
The profile is bound once per process (`swg_test_studio/backend.py:113`) and handed to
tool subprocesses in `SWG_STUDIO_SERVER_PROFILE` (`devtools/zones/server_profile.py:14`,
`:169`). All constants live in `devtools/zones/server_profile.py`.

**Status: nothing here has run against a live server.** No restoration test server
exists yet; the profile is covered by offline tests and a compile check only.

## What changes under `restoration`

| area | whitengold | restoration | where |
|---|---|---|---|
| per-run source hashes | fixed WhiteNGold list, raises on a missing file | the profile's own list; a missing file is recorded as `"absent"` | `devtools/zones/protocol_test_sets.py:31`, `:43`; lists at `devtools/zones/server_profile.py:55`, `:118` |
| bot fixture script | `fixtures/protocol_bot.java` | `fixtures/restoration/protocol_bot.java` (read-only `inspect`; `instance=none`) | `devtools/zones/fixtures/restoration/protocol_bot.java:40`, `:53` |
| bot query transport | `/fixture/protocol-bot-console` binary in the central container | one typed `ConGenericMessage` from the host to Central's private console port | `devtools/zones/protocol_driver.py:143`; `devtools/zones/restoration_console.py:32` |
| game servers considered | scenes in the instance catalog | every `Adding server N for scene X` line | `devtools/zones/protocol_driver.py:133` |
| saved-state query | reads `objects.zone_instance_id` | no such column; `instance` is the constant `none` | `devtools/zones/protocol_driver.py:113` |
| readiness | capacity console (`capacityScenes`/`capacityInstances`) or the stage 5 preload check | login ready line, then a registered game server for each bound bot's saved scene | `swg_test_studio/docker_runtime.py:225`, `:338` |
| start of a stopped server | journal maintenance first | no journal step | `swg_test_studio/docker_runtime.py:359` |
| install root in containers | `/opt/whitengold` | `/opt/restoration` | `devtools/zones/server_profile.py:134` |
| checkout sub-folder (lock, image pins, registered setups) | `StarWarsGalaxies` | `StudioTestServer` | `devtools/zones/server_profile.py:134`; `swg_test_studio/setup.py:14` |
| `install-agent-fixture` | compiles `agent_fixture.java` | compiles the lean `protocol_bot.java` and `agent_fixture.java` | `swg_test_studio/agent_fixture.py:329` |

Not changed by the profile: every isolation check below.

## Supported tests

`plan`, `run`, `run-selected` and batches refuse anything else before a server is touched
(`swg_test_studio/backend.py:76`); `validate <test> --profile restoration` gives the same
answer without an environment (`swg_test_studio/cli.py:57`). The driver repeats the refusal
for its own options (`devtools/zones/protocol_driver.py:448`).

- `session` steps with only `role`, `create`, `disconnect`, `expect_scene`
  (`devtools/zones/server_profile.py:138`): the bundled `login_relogin` and `create_character`.
- `agent_fixture` steps (`devtools/zones/server_profile.py:137`).

- `client` steps (held sessions, group, secure trade and tell; `docs/fixture-client-actions.md`): `client_action`
  is in `case_kinds` and every client kind in `client_kinds` (`devtools/zones/server_profile.py:137-140`). The
  bundled `trade_between_accounts`, `group_with_fixture_asserts`, `scenario_concert`, `trade_two_accounts_client`
  and `group_invite_accept_client` plan under this profile.

Group steps of the older kinds (`action_sequence`, `ship_group`, `group_affinity_*`) stay refused for a real
reason: they need the Tansaari station or an Ord ship and whitengold-only staging
(`devtools/zones/studio_actions.py:99-103`). The typed `client` group steps need no station.

## What a prepared restoration test server must provide

Studio prepares nothing; it only verifies. All of these are the same checks the
whitengold profile makes, unless marked *(profile)*.

**Folders and files**

- Test root `/tmp/swg-cold-test-<8 hex>` with `compose.json`: project name equal to the
  folder name, exactly one volume `oracle_data` = external `<project>_oracle26_data`, an
  `oracle` service with no ports, not privileged, label `whitengold.test.kind=cold-start`
  (`devtools/zones/prepare_client_fixture_schema.py:35-46`).
- Client folder `<root>/client-<12 hex>`; the environment's `folder` must match
  `/tmp/swg-cold-test-<8 hex>/client-<12 hex>` (`swg_test_studio/backend.py:52`).
- `<folder>/schema-report.json` with `passed: true`, `schema`, `volume`;
  `<folder>/runtime/report.json` and `<folder>/runtime/stage5-report.json` with the same
  `schema` and `project`; the stage report has `stage: 5` and no `central_freeze_debugger`
  (`swg_test_studio/setup.py:52-55`; `devtools/zones/protocol_driver.py:78-84`).
- `<folder>/runtime/runtime.cfg` with `[LoginServer] doSessionLogin=false` and
  `validateStationKey=false` (`devtools/zones/protocol_driver.py:43-53`).
- `<folder>/runtime/compose.json` naming the same services, volume and project-scoped
  networks as the running containers, for a Studio-started server
  (`swg_test_studio/docker_runtime.py:251-290`).
- `<checkout>/StudioTestServer/instance-release.json` *(profile)*: `{"roles": {<service>:
  {"image_id": ...}}}` pinning every non-Oracle service image
  (`devtools/zones/protocol_driver.py:88`; `swg_test_studio/docker_runtime.py:48`). Studio
  also takes its lock at `<checkout>/StudioTestServer/management.lock`
  (`devtools/zones/protocol_driver.py:454`) and registers setups in
  `<checkout>/StudioTestServer/logs/studio-setups/` (`swg_test_studio/setup.py:81`).
- The driver binary (ELF64 x86-64) with a `<binary>.build.json` whose hashes match the
  bundled `protocol_driver64.cpp` and `ProtocolCompanionRoster.h`
  (`devtools/zones/protocol_driver.py:392-403`). It runs inside the game container with
  `LD_LIBRARY_PATH=/opt/restoration/lib:/opt/restoration/jvm/lib/server:/opt/restoration/jvm/lib`
  *(profile)* (`devtools/zones/protocol_driver.py:256`).
- Bots: `<folder>/protocol-driver/<key>.json`, account `capbot_<7 hex>`, character
  `Cap<12 letters>` (`devtools/zones/protocol_driver.py:32-40`).

**Containers** (Compose project = test root name; names `<project>-<service>-1`)

- `oracle`: image `gvenzl/oracle-free:23.26.3-slim-faststart`, label
  `whitengold.test.kind=cold-start`, the project volume mounted at `/opt/oracle/oradata`,
  no `starwarsgalaxies_*` mount, running (`devtools/docker/disposable_database.py:6-22`;
  `swg_test_studio/docker_runtime.py:72`). Queries connect as sysdba to `FREEPDB1`
  (`devtools/zones/instance_schema_upgrade.py:24-26`).
- Every pinned role (the code names `central`, `game`, `login`, `taskmanager`, `chat`, and
  `connection`/`planet` on the shutdown path): running, image id equal to its pin, label
  `whitengold.test.client=<schema>`, not privileged, no added capabilities
  (`devtools/zones/protocol_driver.py:89-95`; `swg_test_studio/docker_runtime.py:52-62`).
- `local_chat` with image `starwarsgalaxies/local-chat:local` and the same client label
  (`swg_test_studio/docker_runtime.py:63-68`).
- For a Studio-started server, role images are tagged `starwarsgalaxies/<role>:<tag>` and
  carry the Compose config hash (`swg_test_studio/docker_runtime.py:284-288`).
- `central` has exactly one private IPv4 address, and its console listens there on port
  61000 (`devtools/zones/restoration_console.py:13`, `:49-61`).
- `central` writes `/opt/restoration/exe/linux/runtime.log` *(profile)* containing
  `Adding server <id> for scene <scene>` (`devtools/zones/protocol_driver.py:164`); `login`
  logs `Cluster <project> is ready for players.` (`swg_test_studio/docker_runtime.py:118`).

**Schema and configuration**

- Oracle schema owner `WGC_<12 HEX>` = the client folder suffix in upper case
  (`devtools/zones/protocol_driver.py:81`), with the tree's ordinary `objects` table
  (`object_id`, `scene_id`, `x`, `y`, `z`, `contained_by`, `deleted`); no
  `zone_instance_id` (`devtools/zones/protocol_driver.py:113-121`).
- Game server configuration keys the fixtures read: `[GameServer] clientIsolationFixture=1`
  and `[dbProcess] schemaOwner=WGC_<12 HEX>`
  (`devtools/zones/fixtures/restoration/protocol_bot.java:24-26`).
- Fixture classes: `script/fixture/protocol_bot.class` and `agent_fixture.class` under
  `/opt/restoration/data/sku.0/sys.server/compiled/game/script/fixture/`.
  `install-agent-fixture` compiles them against the running game container's own script
  classes, copies them in, reloads them, and leaves a copy in
  `<folder>/fixture/classes/script/fixture/` (`swg_test_studio/agent_fixture.py:304-352`).
  The game container must re-apply that folder at every start; the whitengold entrypoint
  that does this is `devtools/zones/fixture_overlay.py:46`.

## Missing or unverified

- **No live run.** Login, creation, logout, the saved-state query, readiness and the
  console request have not been exercised against a restoration server.
- **No preparation tooling.** The schema copy, stage report, Compose files, image pins
  and overlay entrypoint come from WhiteNGold tools that are not ported. Somebody has to
  produce a server meeting the list above.
- **Install root and deployment folder are our choice.** `/opt/restoration` and
  `StudioTestServer` are placeholders in one place (`devtools/zones/server_profile.py:134`);
  the `lib`/`jvm` layout under the root is assumed to mirror WhiteNGold's.
- **Driver peer.** Its build script is not in this bundle. The unmodified peer does not
  compile against the restoration tree (one error: that tree's `CreateProjectileMessage`
  takes a ship id first). Built with `-DSWG_STUDIO_PROFILE_RESTORATION`, which compiles out
  the ship `fire` action, it compiles and links against the tree's shared libraries
  (`docs/fixture-client-actions.md`, "Build and compile check"). It has not run against a server.
- **Fixture compile.** With JDK 21, `-sourcepath` on the tree's script sources alone
  fails: 126 of 168 libraries have no `.java` twin (only `.scriptlib`), so imports inside
  the existing library twins do not resolve (148 errors, none in the fixtures), and
  `base_class.java` is not UTF-8. With empty stub classes for the missing libraries and
  `-encoding ISO-8859-1`, both fixtures compile cleanly, and a seeded `getZoneInstanceId`
  call fails as expected. `agent_fixture.java`'s library calls (`utils`,
  `player_structure`, `static_item`) are checked against real twins. The real install
  compiles against the server's built classes instead.
- **Label and schema names** keep the `whitengold.test.*` and `WGC_` spelling so the
  isolation checks are literally the same code.
- **`agent_fixture.java`** still lists `/opt/whitengold/...` first when looking for draft
  schematics (`devtools/zones/fixtures/agent_fixture.java:50-55`); it falls back to
  relative paths, untested here. Only `grantSchematics` is affected.
- **Readiness** is weaker than the stage 5 preload check: a registered game server for a
  scene does not prove its preload finished.
- **GUI**: the profile is read from the environment file; there is no profile picker.

## Deliberately unsupported

Refused by `plan`/`validate` (`devtools/zones/server_profile.py:199`): shuttle and terminal
sessions (`stage_station`, `prepare_terminal`, `expect_family`, `answer`), journeys, action
sequences (ships, groups, launch/land), every saved recipe including `driver_unit`, and all
instance, capacity, encounter, retirement and hosted-content suites. Recording is refused
(`swg_test_studio/recording.py:34`). The lean fixture has no mutating method, so the
driver's setup commands (`botStation`, `botPrepare`, `botTerminals`, ...) cannot be sent
(`devtools/zones/restoration_console.py:14`).

## Bundle manifest

`devtools/studio-tools.json` lists the sha256 of every bundled tool and is checked on each
use (`devtools/zones/studio_tool_bundle.py`). It has no generator; after editing a bundled
file, set its entry to the file's sha256 and add new files in sorted order.
`upstream_contract_sha256` keeps the original hash of files Studio changed that fixture
receipts pin (unchanged by this work).
