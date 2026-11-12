# Fixture core: dispatcher, runner and installer of the agent fixture families

The server-side fixture grows from one class (`script.fixture.agent_fixture`) into op
families. Each family is one Python module `swg_test_studio/fixture_ops/<family>.py` and one
Java class `devtools/zones/fixtures/agent_<family>.java` (`script.fixture.agent_<family>`).
This note covers the host side that finds, validates, routes, runs and installs them:
`swg_test_studio/agent_fixture.py`, the runner in `swg_test_studio/backend.py` and the
`scenario-end` command in `swg_test_studio/cli.py`.

**Status: nothing here has run against a live server.** Everything below is covered by
offline unit tests (`tests/test_fixture_core.py`, `tests/test_agent_fixture.py`) only.

## Dispatcher

At import, `agent_fixture` discovers every public module of `swg_test_studio.fixture_ops`
(`discover`) and merges it into one `Registry` (`merge`). It works with zero, one or any
number (at most 16) of families. A module is refused, and Studio does not start, when:

- the module name is not `[a-z][a-z_]{0,23}` (letters and `_`: the one family-name rule that the
  Java source name `agent_<family>.java` and the `reloadScript fixture.agent_<family>` line also
  use), `FIXTURE` is not `"agent_<module name>"`, or the module is called `fixture`;
- `TYPES` or a non-empty `OPS` dict is missing; a kind is not `[a-z][a-z0-9_]{0,31}`, its regex
  does not compile, or it redefines an existing kind (core or another family) with a different
  regex. Reusing a kind with the identical regex is allowed;
- `RANGES` names an undeclared kind, is not `(low, high)` with `low <= high`, changes the
  bounds of an existing kind, or bounds a core kind the core leaves unbounded (`coord`, `oid`,
  `role`, ...);
- an op name is not `[a-z][A-Za-z0-9]{0,31}`, already exists (core or another family), uses an
  undeclared kind, has an optional `"kind?"` before a required one, or its mutating flag is not
  a bool;
- `ROLE_ARGS` names an op it does not define, or a position that is not a `role` argument;
- `SCENARIO_OPS` or `SCENE_CHANGING` is not a set of its own ops; `check` is not callable.

`CORE_TYPES`, `CORE_RANGES` and `CORE_OPS` are read-only mappings, and `Registry` starts from a
copy taken before any family module is imported, so a family can neither edit nor rebind the
core at import. The merged tables are `agent_fixture.TYPES`, `RANGES` and `OPS` (same objects as
before, now including the families) and `agent_fixture.REGISTRY` (`fixture_of`, `role_args`,
`scenario_ops`, `scene_changing`, `checks`, `families`, `fixtures`).

Core kinds added for the families (sources/interface.md): `role` = `[a-z][a-z0-9_]{0,31}`,
`scenario` = `[a-z][a-z0-9_]{0,31}`.

## Steps

```json
{"id": "spawn_target", "action": "agent_fixture",
 "options": {"role": "actor", "op": "<family op>", "args": ["..."],
             "scenario": "arena_1", "expect": {"key": "value"}}}
```

`agent_fixture.validate` (called by `model.validate` for every `agent_fixture` step) checks:

- `op` is in the merged OPS; argument count and every argument against its kind's regex and
  range; then the family's `check(op, args)`.
- Every argument is also one token of at most 512 bytes of the fixed safe class
  `[A-Za-z0-9_.,:/*^$|()\[\]+?=-]` (`TOKEN`, the union of what the core and family kinds need),
  whatever the family regex allows: no whitespace or control byte can split the console line, and
  no quote, backslash, `;`, backtick, `&`, `<`, `>`, `#`, `%`, `!`, `@`, `~`, `{` or `}` reaches it.
- An argument that is not a `ROLE_ARGS` position must not contain a bot identity
  (`oid:station:Cap...`, `IDENTITY`): identities reach the console only through role substitution.
- A `ROLE_ARGS` argument must be another role of the suite, never the acting role.
- `scenario` is required for an op in `SCENARIO_OPS` and refused for every other op.

## Console line and reply

```
game <worker> runScript fixture.<FIXTURE of the op> <op> <oid:station:Cap...> [<scenario>] <args...>
```

- The class is the op's family class (`fixture.agent_fixture` for core ops).
- For a `SCENARIO_OPS` op the step's scenario id is the first argument after the identity;
  its Java method therefore calls `request(value, op, required + 1, total + 1)`.
- Each `ROLE_ARGS` argument is replaced by that role's registered identity
  `oid:station:Cap...`, read from `<folder>/protocol-driver/<registry>.json` of the role's
  binding. An unbound role, a malformed identity or the acting bot's own identity is refused.

`parse(text, fixture)` accepts the reply prefix of the op's own class only
(`agent_<family>=<status> ...`); without `fixture` any known class. A reply of another class is
`unrecognized` and fails the step. A key that appears twice (other than `row`) makes the reply
`malformed`, never last-key-wins.

## Runner

`backend.run_suite` passes the run's role bindings to `agent_fixture.run_live`, which:

1. validates the step against the bound roles;
2. resolves the acting bot's game server with the existing bot query (`driver.bot_query`),
   fresh for every step;
3. sends the line to the private CentralServer console and checks status and `expect` (a
   step needs status `ok`; any other status, `partial` included, fails it);
4. after an op in a family's `SCENE_CHANGING`, waits until the bot query finds the bot again
   (`relocate`): at most `RELOCATE_SECONDS` = 90 s, one query per `RELOCATE_INTERVAL` = 1 s,
   until one game server reports the bot and, when the reply carries `scene=<name>`, reports it
   in that scene. A double census during the hand-off is retried. The artifact records
   `relocated = {worker, scene, moved_server, seconds}`.

The run report's `application_sha256` also covers `fixture_ops/*.py`.

## Plan

For a suite with `agent_fixture` steps, `plan` adds to `effects` (plans of other suites are
unchanged):

| key | meaning |
|---|---|
| `agent_fixture_changes` | mutating ops used (as before, now over all families) |
| `agent_fixture_classes` | fixture classes the suite calls |
| `agent_fixture_partner_roles` | roles named as another bot by `ROLE_ARGS` |
| `agent_fixture_scenarios` | one row per (role, scenario id): `id`, `role`, steps that begin, end and use it (`begun`, `ended`, `used`) and `problems` |
| `agent_fixture_scenarios_all_ended` | every scenario begun or used is ended in the suite |

A `scenarioBegin`/`scenarioEnd` step's id is its `scenario` field if that op is in
`SCENARIO_OPS`, otherwise its first argument. `scenario_ids` walks the steps in order per role
and lists each problem as `"<step>: <kind>"`: `end-before-begin` (ended while not open for that
role), `use-without-begin` (a creating op whose id the role has not open), `ended-by-other-role`
(another role has the id open; the Java side ends only the acting bot's scenario),
`begun-twice`, `begin-while-other-open` (the Java side refuses a second open id),
`scene-change-while-open` (a `SCENE_CHANGING` op of a role with a scenario open) and
`never-ended`.

## Cleanup command

```
python3 swg-tests.py scenario-end --environment environment.json --role actor --id arena_1
```

Sends the scenario family's `scenarioEnd` for the role's bot under the Studio operation lock and
prints the reply status and fields. It refuses when no family provides `scenarioEnd`, for a role
the environment does not bind and for an invalid id, before anything is sent. It exits 0 only for a
clean end (`ok`, `was_open=true`, `leaked=0`); a `partial` reply, a leak or `was_open=false` (a
mistyped id or role) exits 1. It needs the role's bot logged in on the game server of the
scenario's scene, within reach of what it created; there is no offline cleanup
(`docs/fixture-scenario.md`).

## Installer

`install-agent-fixture` installs, in order, the profile's own fixtures (the lean bot fixture
first), then every other `devtools/zones/fixtures/agent_*.java`. Each source must be listed in
`devtools/studio-tools.json` (so it is hash-verified), every discovered family must have its
Java class, and each source must compile (`javac --release <server's>`, `-implicit:none`) to
exactly one class file. Each class is written to the fixture overlay, copied into the game
container and reloaded on every registered game server (`game <id> reloadScript fixture.<class>`).

## Generated files: one command

```
python3 -m swg_test_studio.agent_fixture refresh          # rewrite
python3 -m swg_test_studio.agent_fixture refresh --check  # report only, exit 1 if stale
```

It regenerates the README op table between the `agent-fixture-ops` markers from the merged OPS
and adds or refreshes the `devtools/studio-tools.json` hash of every
`devtools/zones/fixtures/agent_*.java`. Tests fail while either is stale. `fixture_ops/*.py`
are application files, not bundled server tools; the manifest's path rule does not admit them
and they are hashed per run instead (see Runner).

## Java: API used

This atom adds no Java op and changes nothing in `agent_fixture.java`. The guard and helpers the
families copy (`request`, `refusal`, `num`, `integer`, `oid`, `list`, `botBuilding`, `scope`,
`enc`, `kv`, `row`, `end`) are unchanged. `tests/test_fixture_core.py` checks for every present
family class: one public method per op and none extra, each starting with
`request(value,"<op>",min,max)` with the Python arity (plus one for a scenario op), the class
header, no nested or anonymous class, and those helper bodies textually identical
(whitespace-normalised) to `agent_fixture.java`. The same check runs over `agent_fixture.java`
against the core ops.

Not possible from script: nothing was left out of this atom's scope for lack of script API.

## Where this differs from sources/interface.md

- A family's `check(op, args)` sees the arguments before role names are replaced by identities.
- `scenarioBegin`/`scenarioEnd` carry their id as an ordinary first argument of kind `scenario`
  unless the family lists them in `SCENARIO_OPS`; both shapes are handled.
- The relocation wait matches a target scene only when the scene-changing op's reply carries
  `scene=<name>`; families should return it.
- The extra `TOKEN` and identity rules apply to every argument of every family.

## Unrun (offline only)

- No console line was sent; no reply of any family class has been seen from a real server.
- `relocate` after a real cross-scene warp: the hand-off timing and the 90 s bound are untested.
- Role identity substitution against bots registered by a real driver.
- `install-agent-fixture` with several classes: javac against a running server's classes,
  `docker cp`, and `reloadScript` per class.
- `scenario-end` against a server; whether it finds everything the scenario created.
- The compile check of the family classes runs in the job gate, not in these unit tests.
