"""Op family `multi`: ops that involve a second registered fixture bot (docs/fixture-multi.md).

Java class `script.fixture.agent_multi` (devtools/zones/fixtures/agent_multi.java). The other bot
is named in a suite by its ROLE; the runner replaces that role with the bot's registered identity
`oid:station:Cap...` and the Java side checks it exactly as it checks the acting bot.
"""

FIXTURE = "agent_multi"

# Kind names are namespaced so they can never clash with another family's kinds.
TYPES = {
    "role": r"[a-z][a-z0-9_]{0,31}",                # shared kind, identical to agent_fixture.ROLE_RE
    "oid": r"[1-9][0-9]{0,18}",                     # shared kind, identical to agent_fixture CORE_TYPES
    "bring_offset": r"[0-9]{1,2}(\.[0-9]{1,2})?",   # metres from the acting bot (Java OFFSET_RE)
    "snapshot_name": r"[a-z][a-z0-9_]{0,23}",       # Java SNAPSHOT_RE
    "pay_amount": r"[1-9][0-9]{0,6}",               # Java AMOUNT_RE
}

# Java BRING_OFFSET_MIN/MAX and PAY_MAX (a test keeps them equal).
RANGES = {"bring_offset": (0.5, 16.0), "pay_amount": (1, 1000000)}

OPS = {
    "bring": (("role", "bring_offset?"), True),
    "distanceTo": (("role",), False),
    "groupOf": (("role?",), False),
    "groupLeave": (("role?",), True),
    "creditsOf": (("role",), False),
    "accountOf": (("role",), False),
    "tradeState": (("role?",), False),
    "snapshot": (("snapshot_name", "role?"), True),
    "diff": (("snapshot_name", "role?"), False),
    "snapshotDrop": (("snapshot_name", "role?"), True),
    "giveTo": (("role", "oid"), True),
    "payTo": (("role", "pay_amount"), True),
}

ROLE_ARGS = {
    "bring": (0,), "distanceTo": (0,), "groupOf": (0,), "groupLeave": (0,), "creditsOf": (0,),
    "accountOf": (0,), "tradeState": (0,), "snapshot": (1,), "diff": (1,), "snapshotDrop": (1,),
    "giveTo": (0,), "payTo": (0,),
}

# Nothing here creates world objects (snapshots are objvars on the bots themselves), so no op
# needs an open scenario, and no op moves a bot to another scene.
SCENARIO_OPS = frozenset()
SCENE_CHANGING = frozenset()
