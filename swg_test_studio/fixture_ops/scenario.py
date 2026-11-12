"""Op family `scenario` (Java class script.fixture.agent_scenario): the world around the bot, and teardown.

Objects and creatures, quest state, test objvars, cross-scene warp and facing; everything an op
creates is tagged with the scenario id and removed again by `scenarioEnd`. Notes, bounds, the
script API each op relies on and what is unrun: docs/fixture-scenario.md.
"""
import re

FIXTURE = "agent_scenario"

_NUMBER = r"-?[0-9]{1,5}(\.[0-9]{1,6})?"  # the fixture's NUM_RE

# Object template categories a scenario may create (see docs/fixture-scenario.md for why these).
TEMPLATE_CATEGORIES = ("tangible", "weapon", "static")
TEMPLATE_MAX = 200

# Open-world ground scenes of the server tree's datatables/region/planets.tab (no tutorial,
# instanced dungeon, adventure or Kashyyyk sub-zone scenes).
SCENES = ("corellia", "dantooine", "dathomir", "endor", "kashyyyk_main", "lok",
          "mustafar", "naboo", "rori", "talus", "tatooine", "yavin4")

TYPES = {
    "objtemplate": r"object/(" + "|".join(TEMPLATE_CATEGORIES) + r")/([a-z0-9_]{1,64}/){0,7}[a-z0-9_]{1,64}\.iff",
    "creaturename": r"[a-z0-9_]{1,64}",
    "spawnlevel": r"[0-9]{1,2}",
    "spawncount": r"[0-9]{1,2}",
    "worldxz": _NUMBER,
    "worldy": _NUMBER,
    "celllocal": _NUMBER,
    "spawnoffset": _NUMBER,
    "onoff": r"on|off",
    "questname": r"[a-z0-9_]{1,64}(/[a-z0-9_]{1,64}){0,3}",
    "questsignal": r"[A-Za-z0-9_]{1,64}",
    "vartarget": r"self|[1-9][0-9]{0,18}",
    "varname": r"[a-z0-9_]{1,32}(\.[a-z0-9_]{1,32}){0,3}",
    "vartype": r"int|float|string",
    "varvalue": r"[A-Za-z0-9_.:,/+-]{1,128}",
    "scenename": "|".join(SCENES),
}

RANGES = {
    "spawnlevel": (1, 90),
    "spawncount": (1, 10),
    "worldxz": (-8192.0, 8192.0),
    "worldy": (-1000.0, 10000.0),
    "celllocal": (-512.0, 512.0),
    "spawnoffset": (-64.0, 64.0),
}

# Values a typed test objvar may hold (agent_scenario.java VAR_INT_MAX / VAR_FLOAT_MAX).
VAR_INT_MAX = 999999999
VAR_FLOAT_MAX = 100000.0
SCENARIO_CREATE_MAX = 200
SCENARIO_END_MAX = 1000

# name -> (argument kinds, mutates). For SCENARIO_OPS the scenario id is sent first (not listed here).
OPS = {
    "scenarioBegin": (("scenario",), True),
    "scenarioEnd": (("scenario",), True),
    "scenarioList": (("scenario",), False),
    "createAt": (("objtemplate", "worldxz", "worldxz", "yaw"), True),
    "createInCell": (("objtemplate", "oid", "cell", "celllocal", "celllocal", "celllocal", "yaw"), True),
    "createInInventory": (("objtemplate", "spawncount?"), True),
    "destroyCreated": (("oid",), True),
    "spawnCreature": (("creaturename", "spawnoffset", "spawnoffset", "spawnlevel?"), True),
    "creatureAttack": (("oid",), True),
    "creaturePassive": (("oid",), True),
    "creatureInvulnerable": (("oid", "onoff"), True),
    "creatureMove": (("oid", "spawnoffset", "spawnoffset"), True),
    "creatureKill": (("oid",), True),
    "creatureDespawn": (("oid",), True),
    "questGrant": (("questname",), True),
    "questComplete": (("questname",), True),
    "questClear": (("questname",), True),
    "questSignal": (("questsignal",), True),
    "quests": ((), False),
    "setTestVar": (("vartarget", "varname", "vartype", "varvalue"), True),
    "clearTestVar": (("vartarget", "varname"), True),
    "getTestVar": (("vartarget", "varname?"), False),
    "warpScene": (("scenename", "worldxz", "worldy", "worldxz"), True),
    "face": (("yaw",), True),
}

# Ops that create world state: they need the step's scenario id (sent as the first argument).
SCENARIO_OPS = frozenset({"createAt", "createInCell", "createInInventory", "spawnCreature"})

# Ops after which the bot may be on another game server (the runner re-finds it).
SCENE_CHANGING = frozenset({"warpScene"})

_INT = re.compile(r"-?[0-9]{1,9}")
_FLOAT = re.compile(_NUMBER)


def check(op, args):
    """Static rules beyond the per-kind regexes; raises ValueError."""
    if op in ("createAt", "createInCell", "createInInventory"):
        template = args[0]
        if len(template) > TEMPLATE_MAX:
            raise ValueError(f"{op}: template longer than {TEMPLATE_MAX} characters")
        if "/shared_" in template or "/player/" in template:
            raise ValueError(f"{op}: shared (client) and player templates are refused")
    if op == "setTestVar":
        kind, value = args[2], args[3]
        if kind == "int" and (not _INT.fullmatch(value) or abs(int(value)) > VAR_INT_MAX):
            raise ValueError(f"setTestVar: an int value is -?[0-9]{{1,9}} within +/-{VAR_INT_MAX}")
        if kind == "float" and (not _FLOAT.fullmatch(value) or abs(float(value)) > VAR_FLOAT_MAX):
            raise ValueError(f"setTestVar: a float value is {_NUMBER} within +/-{VAR_FLOAT_MAX:g}")
