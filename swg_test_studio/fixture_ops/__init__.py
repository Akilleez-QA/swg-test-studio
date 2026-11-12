"""Op families of the server-side agent fixture.

Each public module here is one family: `<family>.py` pairs with the Java fixture class
`devtools/zones/fixtures/agent_<family>.java` (`script.fixture.agent_<family>`) and defines

    FIXTURE        "agent_<family>"
    TYPES          {kind: regex}       argument kinds it adds (core kinds may be reused only verbatim)
    RANGES         {kind: (low, high)} optional numeric bounds
    OPS            {op: ((kind, "kind?", ...), mutating)}
    ROLE_ARGS      {op: (index, ...)}  optional: positions of kind "role" naming another bot's role
    check(op, args)                    optional extra static validation (raise ValueError)
    SCENARIO_OPS   frozenset           optional: ops that need the step's `scenario` id
    SCENE_CHANGING frozenset           optional: ops that may move the bot to another game server

`swg_test_studio.agent_fixture` discovers and merges them at import and refuses a module
that breaks these rules (duplicate op name, kind redefined with another regex, ...).
See docs/fixture-core.md.
"""
