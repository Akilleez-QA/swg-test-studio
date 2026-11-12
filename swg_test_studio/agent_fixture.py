"""Typed arrange/assert calls into the server-side fixture classes `script.fixture.agent_*`.

The fixtures (devtools/zones/fixtures/agent_*.java) run only on an isolated client
fixture (GameServer.clientIsolationFixture=1, a WGC_ copied schema) and act only on
one exact registered non-god test bot. This module is their host side:

* OPS is the closed list of methods and their argument types: the core fixture's own
  methods merged with every op family found in `swg_test_studio/fixture_ops/` (one
  module and one Java class per family; see docs/fixture-core.md). Nothing else is sent;
  there is no free-form console command, script name or expression.
* The console message is a ConGenericMessage sent to the CentralServer console port
  of the fixture's private Docker network, framed as the server's TcpClient expects.
* The game server that owns the bot is found with the existing driver's bot query.

Steps use it as  {"action": "agent_fixture", "options": {"role": R, "op": OP,
"args": [...], "scenario": ID?, "expect": {key: value}}}.  `expect` compares exact
strings in the fixture's reply; the step fails on any status other than `ok` or a
mismatch. `scenario` is required by (and only allowed for) a family's SCENARIO_OPS and
is sent as the first argument after the identity.

`python3 -m swg_test_studio.agent_fixture refresh` regenerates the README op table and
the bundled-tool hashes of every devtools/zones/fixtures/agent_*.java; `--check` only
reports whether either is stale.
"""
import importlib
import ipaddress
import pkgutil
import re
import socket
import struct
import time
from types import MappingProxyType

FIXTURE = "agent_fixture"
SCRIPT = "fixture." + FIXTURE
CONSOLE_PORT = 61000

_NUMBER = r"-?[0-9]{1,5}(\.[0-9]{1,6})?"  # the fixture's NUM_RE
ROLE_KIND, ROLE_RE = "role", r"[a-z][a-z0-9_]{0,31}"
SCENARIO_KIND, SCENARIO_RE = "scenario", r"[a-z][a-z0-9_]{0,31}"
# The core tables are read-only, and Registry copies a snapshot taken here, before any family
# module is imported: a family can neither edit nor rebind the core kinds, ranges or ops.
CORE_TYPES = MappingProxyType({
    "oid": r"[1-9][0-9]{0,18}",
    "oids": r"[1-9][0-9]{0,18}(,[1-9][0-9]{0,18}){0,31}",
    "coord": _NUMBER,
    "yaw": r"-?[0-9]{1,3}(\.[0-9]{1,6})?",
    "radius": r"[0-9]{1,3}(\.[0-9]{1,2})?",
    "scale": r"[0-9]{1,2}(\.[0-9]{1,6})?",
    "trees": r"[0-9]{1,3}(,[0-9]{1,3}){0,63}",
    "name": r"[a-z0-9_]{1,64}",
    "names": r"[a-z0-9_]{1,64}(,[a-z0-9_]{1,64}){0,31}",
    "cell": r"[A-Za-z0-9_]{1,64}",
    "tag": r"[A-Za-z0-9_*]{1,64}",
    "regex": r"[A-Za-z0-9_.*^$|()\[\]+?-]{1,64}",
    "mods": r"[a-z0-9_]{1,64}=-?[0-9]{1,5}(,[a-z0-9_]{1,64}=-?[0-9]{1,5}){0,31}",
    # Shared kinds of the op families (sources/interface.md): a family may reuse them only verbatim.
    ROLE_KIND: ROLE_RE,
    SCENARIO_KIND: SCENARIO_RE,
})

# Numeric limits the fixture enforces (agent_fixture.java); checked here so a bad step fails at validation.
CORE_RANGES = MappingProxyType({"yaw": (-360.0, 360.0), "scale": (0.05, 20.0), "radius": (0.0, 128.0)})

# name -> (argument types, mutates). Optional trailing arguments are written "type?".
CORE_OPS = MappingProxyType({
    "inspect": ((), False),
    "nearby": (("radius",), False),
    "cells": (("oid",), False),
    "contents": (("oid",), False),
    "describe": (("oid",), False),
    "items": ((), False),
    "structure": (("oid",), False),
    "countIn": (("oid",), False),
    "tryPut": (("oid", "oid"), True),
    "place": (("oid", "cell", "coord", "coord", "coord", "yaw"), True),
    "warp": (("coord", "coord", "coord"), True),
    "moveInto": (("oid", "oid", "cell", "coord", "coord", "coord"), True),
    "transform": (("oid", "coord", "coord", "yaw"), True),
    "setDown": (("oid", "cell", "coord", "coord", "coord", "oids"), True),
    "scale": (("oid", "scale"), True),
    "grantExpertise": (("trees?",), True),
    "grantSkills": (("regex",), True),
    "grantSchematics": ((), True),
    "itemBonuses": (("oid", "mods"), True),
    "giveStatic": (("names",), True),
    "give": (("oid",), True),
    "completeCollection": (("name",), True),
    "clearDecor": (("oid", "tag"), True),
})
_CORE = (dict(CORE_TYPES), dict(CORE_RANGES), dict(CORE_OPS))

IDENTITY = re.compile(r"[1-9][0-9]{0,18}:[1-9][0-9]{0,9}:Cap[a-z]{12}")
# Every argument, whatever its family regex, must be one bounded token of this fixed safe class
# (the union of what the core and family kinds need): no whitespace (it would split the console
# line), no control bytes, no quotes, backslash, semicolon, backtick, '&', '<', '>', '#', '%',
# '!', '@', '~', '{' or '}'.
TOKEN = re.compile(r"[A-Za-z0-9_.,:/*^$|()\[\]+?=-]{1,512}")

# --- Op families --------------------------------------------------------------------------

FAMILY_PACKAGE = __package__ + ".fixture_ops"
# One family-name rule for discovery, the Java source name and the reload line: letters and '_'.
FAMILY_RE = r"[a-z][a-z_]{0,23}"
FAMILY_NAME = re.compile(FAMILY_RE)
OP_NAME = re.compile(r"[a-z][A-Za-z0-9]{0,31}")
KIND_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
FAMILY_NAMES = frozenset({"FIXTURE", "TYPES", "RANGES", "OPS", "ROLE_ARGS", "check", "SCENARIO_OPS",
                          "SCENE_CHANGING"})
SCENARIO_BEGIN, SCENARIO_END = "scenarioBegin", "scenarioEnd"
MAX_FAMILIES = 16
# Bounded wait for the bot to be found again on a game server after a SCENE_CHANGING op.
RELOCATE_SECONDS = 90.0
RELOCATE_INTERVAL = 1.0


class Registry:
    """The merged, validated op table: core ops plus every family's ops."""

    def __init__(self):
        types, ranges, ops = _CORE
        self.types = dict(types)
        self.ranges = dict(ranges)
        self.ops = dict(ops)
        self.fixture_of = {op: FIXTURE for op in ops}
        self.role_args = {}
        self.scenario_ops = set()
        self.scene_changing = set()
        self.checks = {}
        self.families = {}  # family name -> fixture class name

    @property
    def fixtures(self):
        return (FIXTURE, *sorted(self.families.values()))

    def script(self, op):
        return "fixture." + self.fixture_of[op]


def _family(name, module, registry):
    """Validate one family module against sources/interface.md and merge it; raises ValueError."""
    def bad(why):
        raise ValueError(f"Fixture op family {name!r}: {why}")

    if not FAMILY_NAME.fullmatch(name) or name == "fixture":
        bad("module name must be a lowercase family name other than 'fixture'")
    values = {key: getattr(module, key) for key in FAMILY_NAMES if hasattr(module, key)}
    fixture, types, ops = values.get("FIXTURE"), values.get("TYPES"), values.get("OPS")
    if fixture != "agent_" + name:
        bad("FIXTURE must be 'agent_" + name + "'")
    if fixture in registry.families.values():
        bad("duplicate fixture class")
    if not isinstance(types, dict) or not isinstance(ops, dict) or not ops:
        bad("TYPES and a non-empty OPS dict are required")
    ranges = values.get("RANGES", {})
    role_args = values.get("ROLE_ARGS", {})
    scenario_ops = values.get("SCENARIO_OPS", frozenset())
    scene_changing = values.get("SCENE_CHANGING", frozenset())
    check = values.get("check")
    if not isinstance(ranges, dict) or not isinstance(role_args, dict):
        bad("RANGES and ROLE_ARGS must be dicts")
    if not isinstance(scenario_ops, (set, frozenset)) or not isinstance(scene_changing, (set, frozenset)):
        bad("SCENARIO_OPS and SCENE_CHANGING must be sets")
    if check is not None and not callable(check):
        bad("check must be a function")
    types_after = dict(registry.types)
    for kind, regex in types.items():
        if not isinstance(kind, str) or not KIND_NAME.fullmatch(kind) or not isinstance(regex, str):
            bad("argument kinds are lowercase names mapped to regex strings")
        try:
            re.compile(regex)
        except re.error:
            bad(f"kind {kind!r} has an invalid regex")
        if kind in types_after and types_after[kind] != regex:
            bad(f"kind {kind!r} redefined with a different regex")
        types_after[kind] = regex
    ranges_after = dict(registry.ranges)
    for kind, bounds in ranges.items():
        if (kind not in types_after or not isinstance(bounds, tuple) or len(bounds) != 2 or
                any(type(b) not in (int, float) for b in bounds) or not bounds[0] <= bounds[1]):
            bad(f"range for {kind!r} must be (low, high) on a declared kind")
        if kind in ranges_after and tuple(ranges_after[kind]) != tuple(bounds):
            bad(f"range for {kind!r} redefined with different bounds")
        if kind in _CORE[0] and kind not in _CORE[1]:
            bad(f"range for core kind {kind!r}: a family may not bound a core kind")
        ranges_after[kind] = bounds
    for op, entry in ops.items():
        if not isinstance(op, str) or not OP_NAME.fullmatch(op):
            bad(f"op name {op!r} is not a lowerCamel method name")
        if op in registry.ops:
            bad(f"op {op!r} is already defined by {registry.fixture_of[op]}")
        if (not isinstance(entry, tuple) or len(entry) != 2 or not isinstance(entry[0], tuple) or
                type(entry[1]) is not bool):
            bad(f"op {op!r} must map to ((kind, ...), mutating_bool)")
        optional = False
        for kind in entry[0]:
            if not isinstance(kind, str) or kind.rstrip("?") not in types_after or kind.count("?") > 1 or \
                    ("?" in kind and not kind.endswith("?")):
                bad(f"op {op!r} uses an undeclared argument kind {kind!r}")
            if optional and not kind.endswith("?"):
                bad(f"op {op!r}: optional arguments must be trailing")
            optional = optional or kind.endswith("?")
    for op, positions in role_args.items():
        if op not in ops or not isinstance(positions, tuple) or not positions or \
                len(set(positions)) != len(positions):
            bad(f"ROLE_ARGS for {op!r} must be a tuple of distinct positions of one of its ops")
        for index in positions:
            spec = ops[op][0]
            if type(index) is not int or not 0 <= index < len(spec) or spec[index].rstrip("?") != ROLE_KIND:
                bad(f"ROLE_ARGS position {index!r} of {op!r} is not a 'role' argument")
    for label, chosen in (("SCENARIO_OPS", scenario_ops), ("SCENE_CHANGING", scene_changing)):
        if not set(chosen) <= set(ops):
            bad(label + " names ops the family does not define")
    registry.types = types_after
    registry.ranges = ranges_after
    for op, entry in ops.items():
        registry.ops[op] = entry
        registry.fixture_of[op] = fixture
        if check is not None:
            registry.checks[op] = check
    registry.role_args.update(role_args)
    registry.scenario_ops |= set(scenario_ops)
    registry.scene_changing |= set(scene_changing)
    registry.families[name] = fixture


def merge(families):
    """Merge (name, module) pairs into one Registry; refuses any interface violation."""
    families = list(families)
    if len(families) > MAX_FAMILIES:
        raise ValueError("Too many fixture op families")
    registry = Registry()
    for name, module in sorted(families, key=lambda item: item[0]):
        _family(name, module, registry)
    return registry


def discover(package=FAMILY_PACKAGE):
    """(name, module) for every public module of the fixture_ops package."""
    root = importlib.import_module(package)
    return [(info.name, importlib.import_module(package + "." + info.name))
            for info in sorted(pkgutil.iter_modules(root.__path__), key=lambda i: i.name)
            if not info.name.startswith("_") and not info.ispkg]


# The merged tables. Defined first with the core entries so a family module may import them
# while it is itself being discovered; filled in place with the families below.
TYPES = dict(CORE_TYPES)
RANGES = dict(CORE_RANGES)
OPS = dict(CORE_OPS)
REGISTRY = merge(discover())
TYPES.update(REGISTRY.types)
RANGES.update(REGISTRY.ranges)
OPS.update(REGISTRY.ops)


def validate(options, roles, registry=None):
    """Static validation for a Studio step; raises ValueError.

    `roles` are the suite's roles. An op's ROLE_ARGS must name another of them (never the
    acting role); a family's SCENARIO_OPS require a `scenario` id and no other op takes one.
    """
    registry = registry or REGISTRY
    if not isinstance(options, dict) or set(options) - {"role", "op", "args", "expect", "scenario"} or \
            not {"role", "op", "args"} <= set(options):
        raise ValueError("agent_fixture requires role, op and args (and optional scenario, expect)")
    if options["role"] not in roles:
        raise ValueError("Unknown agent_fixture role")
    args = arguments(options["op"], options["args"], registry)
    for index in registry.role_args.get(options["op"], ()):
        if index < len(args):
            if args[index] not in roles:
                raise ValueError(f"{options['op']}: role {args[index]!r} is not a role of this test")
            if args[index] == options["role"]:
                raise ValueError(f"{options['op']}: name another bot's role, not the acting role")
    if options["op"] in registry.scenario_ops:
        if not isinstance(options.get("scenario"), str) or not re.fullmatch(SCENARIO_RE, options["scenario"]):
            raise ValueError(f"{options['op']} creates world state: give its scenario id")
    elif "scenario" in options:
        raise ValueError(f"{options['op']} takes no scenario id")
    expect = options.get("expect", {})
    if (not isinstance(expect, dict) or len(expect) > 32 or
            any(not re.fullmatch(r"[a-z][a-zA-Z0-9_]{0,31}", k) or not isinstance(v, str) or
                not re.fullmatch(r"[^\s]{0,200}", v) for k, v in expect.items())):
        raise ValueError("expect maps reply keys to exact single-token strings")
    return options


def arguments(op, args, registry=None):
    registry = registry or REGISTRY
    if not isinstance(op, str) or op not in registry.ops:
        raise ValueError("Unknown agent_fixture operation; only typed fixture methods are allowed")
    spec, _ = registry.ops[op]
    if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
        raise ValueError("agent_fixture args must be a list of strings")
    required = [t for t in spec if not t.endswith("?")]
    if not len(required) <= len(args) <= len(spec):
        raise ValueError(f"{op} takes {len(required)}-{len(spec)} arguments")
    roles = registry.role_args.get(op, ())
    for index, (kind, value) in enumerate(zip(spec, args)):
        kind = kind.rstrip("?")
        if not TOKEN.fullmatch(value) or not re.fullmatch(registry.types[kind], value):
            raise ValueError(f"{op}: invalid {kind} argument")
        if index not in roles and IDENTITY.search(value):
            raise ValueError(f"{op}: a bot identity may only arrive through a role argument")
        low, high = registry.ranges.get(kind, (None, None))
        if low is not None and not low <= float(value) <= high:
            raise ValueError(f"{op}: {kind} must be within {low}..{high}")
        if kind == "mods" and any(abs(int(pair.split("=")[1])) > 10000 for pair in value.split(",")):
            raise ValueError(f"{op}: item bonus values must be within -10000..10000")
    if op in registry.checks:
        registry.checks[op](op, list(args))
    return list(args)


def identity_text(bot):
    ident = f"{bot['player']}:{bot['station']}:{bot['character']}"
    if not IDENTITY.fullmatch(ident):
        raise ValueError("Bot identity does not match the fixture contract")
    return ident


def command(worker, bot, op, args, *, scenario=None, identities=None, registry=None):
    """The exact console line; refuses anything outside OPS and the identity contract.

    `identities` maps each role named by the op's ROLE_ARGS to that role's registered bot;
    the role name is replaced by its `oid:station:Cap...` identity. A SCENARIO_OPS op gets
    `scenario` as its first argument after the acting identity.
    """
    registry = registry or REGISTRY
    if type(worker) is not int or not 0 < worker <= 2147483647:
        raise ValueError("Invalid game server id")
    ident = identity_text(bot)
    values = arguments(op, args, registry)
    for index in registry.role_args.get(op, ()):
        if index < len(values):
            other = (identities or {}).get(values[index])
            if other is None:
                raise ValueError(f"{op}: role {values[index]!r} has no registered bot")
            values[index] = identity_text(other)
            if values[index] == ident:
                raise ValueError(f"{op}: the other bot must not be the acting bot")
    if op in registry.scenario_ops:
        if not isinstance(scenario, str) or not re.fullmatch(SCENARIO_RE, scenario):
            raise ValueError(f"{op} requires a scenario id")
        values.insert(0, scenario)
    elif scenario is not None:
        raise ValueError(f"{op} takes no scenario id")
    return " ".join(["game", str(worker), "runScript", registry.script(op), op, ident, *values])


def scenario_ids(steps, registry=None):
    """Scenario bookkeeping of a suite's agent_fixture steps (plan), in step order.

    One row per (role, scenario id): `begun`, `ended`, `used` (step ids) and `problems`, where
    each problem is "<step>: <kind>" for end-before-begin, use-without-begin, ended-by-other-role
    (another role has that id open; the Java side ends only the acting bot's scenario),
    begun-twice, begin-while-other-open, scene-change-while-open (a SCENE_CHANGING op of a role
    with a scenario open) or never-ended.
    """
    registry = registry or REGISTRY
    found, open_of, opened_by = {}, {}, {}  # (role, id) -> row; role -> the id it has open, and the step

    def entry(role, name):
        return found.setdefault((role, name), {"id": name, "role": role, "begun": [], "ended": [], "used": [],
                                               "problems": []})

    for step in steps:
        options = step.get("options", {})
        op, role = options.get("op"), options.get("role")
        if op in (SCENARIO_BEGIN, SCENARIO_END):
            name = options.get("scenario") if op in registry.scenario_ops else (options.get("args") or [None])[0]
            if not name:
                continue
            row = entry(role, name)
            if op == SCENARIO_BEGIN:
                row["begun"].append(step["id"])
                if open_of.get(role) == name:
                    row["problems"].append(step["id"] + ": begun-twice")
                elif open_of.get(role):
                    row["problems"].append(step["id"] + ": begin-while-other-open")
                else:
                    open_of[role], opened_by[role] = name, step["id"]
            else:
                row["ended"].append(step["id"])
                if open_of.get(role) == name:
                    del open_of[role]
                elif any(other != role and opened == name for other, opened in open_of.items()):
                    row["problems"].append(step["id"] + ": ended-by-other-role")
                else:
                    row["problems"].append(step["id"] + ": end-before-begin")
        elif options.get("scenario"):
            row = entry(role, options["scenario"])
            row["used"].append(step["id"])
            if open_of.get(role) != options["scenario"]:
                row["problems"].append(step["id"] + ": use-without-begin")
        if op in registry.scene_changing and open_of.get(role):
            entry(role, open_of[role])["problems"].append(step["id"] + ": scene-change-while-open")
    for role, name in open_of.items():
        found[(role, name)]["problems"].append(opened_by[role] + ": never-ended")
    return sorted(found.values(), key=lambda row: (row["id"], row["role"] or ""))


def scenario_end_options(role, scenario, registry=None):
    """The scenarioEnd step options for one scenario id (CLI scenario-end)."""
    registry = registry or REGISTRY
    if SCENARIO_END not in registry.ops:
        raise ValueError("No fixture op family provides scenarioEnd; the scenario family is not installed")
    if not isinstance(scenario, str) or not re.fullmatch(SCENARIO_RE, scenario):
        raise ValueError("Invalid scenario id")
    if SCENARIO_END in registry.scenario_ops:
        options = {"role": role, "op": SCENARIO_END, "args": [], "scenario": scenario}
    else:
        options = {"role": role, "op": SCENARIO_END, "args": [scenario]}
    validate(options, [role], registry)
    return options


# --- ConGenericMessage framing (sharedNetworkMessages ConsoleChannelMessages) -------------

def _crc_table():
    table = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) if c & 0x80000000 else (c << 1)
        table.append(c & 0xFFFFFFFF)
    return table


_TABLE = _crc_table()


def crc(text):
    """sharedFoundation Crc::calculate: MSB-first CRC-32, init and final xor 0xFFFFFFFF."""
    value = 0xFFFFFFFF
    for byte in text.encode("latin-1"):
        value = (_TABLE[((value >> 24) ^ byte) & 0xFF] ^ (value << 8)) & 0xFFFFFFFF
    return value ^ 0xFFFFFFFF


def pack(message, msg_id=1):
    """GameNetworkMessage AutoByteStream: uint16 count, uint32 type crc, string, uint32 id."""
    body = message.encode("latin-1")
    if len(body) >= 65535:
        raise ValueError("Console message too long")
    payload = struct.pack("<HIH", 3, crc("ConGenericMessage"), len(body)) + body + struct.pack("<I", msg_id)
    return struct.pack("<i", len(payload)) + payload


def unpack(payload):
    """Return the console text if this payload is a ConGenericMessage, else None."""
    if len(payload) < 6:
        return None
    count, kind = struct.unpack_from("<HI", payload)
    if kind != crc("ConGenericMessage") or count != 3 or len(payload) < 8:
        return None
    (size,) = struct.unpack_from("<H", payload, 6)
    if len(payload) < 8 + size:
        return None
    return payload[8:8 + size].decode("latin-1")


def private_address(host):
    address = ipaddress.ip_address(host)
    if not (address.is_loopback or address.is_private) or address.version != 4:
        raise ValueError("Use the fixture's private CentralServer IPv4; never a public console")
    return str(address)


def send(host, line, *, timeout=12.0, connect=socket.create_connection):
    """One console request and its reply (zero-length keepalive frames are skipped)."""
    with connect((private_address(host), CONSOLE_PORT), timeout=timeout) as conn:
        conn.sendall(pack(line))
        for _ in range(16):
            header = _read(conn, 4)
            (size,) = struct.unpack("<i", header)
            if size == 0:
                continue
            if not 6 <= size <= 2 * 1024 * 1024:
                break
            text = unpack(_read(conn, size))
            if text is not None:
                return text
    raise RuntimeError("No complete console response within bounds")


def _read(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise RuntimeError("Console connection closed")
        data += chunk
    return data


def parse(text, fixture=None, registry=None):
    """`agent_<family>=<status> key=value ... row=...` -> dict with fixture, status, fields, rows.

    Accepts the reply prefix of `fixture` only, or of any known fixture class when None.
    """
    registry = registry or REGISTRY
    allowed = (fixture,) if fixture else registry.fixtures
    first, _, _ = text.strip().partition("\n")
    tokens = first.split()
    prefix = tokens[0].split("=", 1)[0] if tokens and "=" in tokens[0] else None
    if prefix not in allowed:
        return {"fixture": None, "status": "unrecognized", "fields": {}, "rows": [], "raw": text[:500]}
    fields, rows = {}, []
    for token in tokens[1:]:
        key, sep, value = token.partition("=")
        if not sep:
            continue
        if key == "row":
            rows.append(value)
        elif key in fields:  # never last-key-wins: an ambiguous reply satisfies no expectation
            return {"fixture": prefix, "status": "malformed", "fields": {}, "rows": [],
                    "error": "duplicate reply key " + key[:64], "raw": text[:500]}
        else:
            fields[key] = value
    return {"fixture": prefix, "status": tokens[0].split("=", 1)[1], "fields": fields, "rows": rows}


def check(reply, expect, accept=("ok",)):
    """None when the reply's status is one of `accept` and every expected field matches."""
    if reply["status"] not in accept:
        return f"fixture status {reply['status']}"
    for key, value in (expect or {}).items():
        if reply["fields"].get(key) != value:
            return f"{key}: expected {value!r}, got {reply['fields'].get(key)!r}"
    return None


def central_host(project, inspect):
    """The central container's address on the fixture network (private by construction)."""
    rows = inspect(project + "-central-1")
    mode = rows[0].get("HostConfig", {}).get("NetworkMode", "")
    if mode.startswith("container:"):
        # Central in its TaskManager's network namespace (network_mode service:X): same project only.
        owner = inspect(mode[len("container:"):])
        label = "com.docker.compose.project"
        if not rows[0]["Config"]["Labels"].get(label) or owner[0]["Config"]["Labels"].get(label) != \
                rows[0]["Config"]["Labels"].get(label):
            raise RuntimeError("Central shares the network of a container outside its fixture project")
        rows = owner
    networks = rows[0]["NetworkSettings"]["Networks"]
    addresses = [n["IPAddress"] for n in networks.values() if n.get("IPAddress")]
    if len(addresses) != 1:
        raise RuntimeError("Cannot select one central fixture address")
    return private_address(addresses[0])


def relocate(query, before=None, scene=None, *, timeout=RELOCATE_SECONDS, interval=RELOCATE_INTERVAL,
             sleep=time.sleep, clock=time.monotonic):
    """After a scene-changing op: wait (bounded) until the bot query finds the bot again.

    Done when exactly one game server reports the bot and, when the op's reply named the
    target `scene`, that server reports the bot in that scene. A census that sees the bot on
    two servers during the hand-off raises inside the query and is retried. Read-only.
    """
    started = clock()
    last = None
    while True:
        try:
            current = query()
        except RuntimeError as exc:  # transient double census during the hand-off
            current, last = None, str(exc)
        if current and (scene is None or current.get("scene") == scene):
            return {"worker": int(current["worker"]), "scene": current.get("scene"),
                    "moved_server": before is not None and int(current["worker"]) != int(before["worker"]),
                    "seconds": round(clock() - started, 3)}
        if clock() - started >= timeout:
            raise RuntimeError(f"The bot was not found again in scene {scene or 'any'} within {timeout:.0f} s"
                               + (f" ({last})" if last else ""))
        sleep(interval)


def _registered_bot(driver, folder, key):
    if not isinstance(key, str) or not re.fullmatch("[a-z]{3,16}", key):
        raise ValueError("A dedicated registry key is required")
    import json
    return driver.identity(json.loads((folder / "protocol-driver" / (key + ".json")).read_text()))


def run_live(options, env, registry, bindings=None, *, accept=("ok",)):
    """Execute one agent_fixture step against the registered bot; returns an artifact dict.

    `registry` is the acting role's registry key; `bindings` maps every role of the run to its
    registry key (needed for ops that name another role's bot). A reply status outside `accept`
    fails the step.
    """
    import json
    import subprocess
    from pathlib import Path
    from .backend import driver_modules

    bindings = dict(bindings or {options["role"]: registry})
    if bindings.get(options["role"], registry) != registry:
        raise ValueError("The acting role is bound to a different registry")
    bindings[options["role"]] = registry
    validate(options, list(bindings))
    op = options["op"]
    driver, _ = driver_modules(env)
    folder = Path(env["folder"]).resolve(strict=True)
    project, _schema, _services = driver.fixture(folder)
    bot = _registered_bot(driver, folder, registry)
    others = {options["args"][i] for i in REGISTRY.role_args.get(op, ()) if i < len(options["args"])}
    identities = {role: _registered_bot(driver, folder, bindings[role]) for role in sorted(others)}
    current = driver.bot_query(project, bot)
    if not current:
        raise RuntimeError("The registered bot is not loaded on any fixture game server")

    def inspect(name):
        out = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    line = command(int(current["worker"]), bot, op, options["args"], scenario=options.get("scenario"),
                   identities=identities)
    fixture = REGISTRY.fixture_of[op]
    reply = parse(send(central_host(project, inspect), line), fixture)
    print("AGENT_FIXTURE", fixture, op, reply["status"], json.dumps(reply["fields"], sort_keys=True), flush=True)
    failure = check(reply, options.get("expect"), accept)
    if failure:
        raise RuntimeError(f"{fixture} {op}: {failure}")
    artifact = {"fixture": fixture, "op": op, "mutates": OPS[op][1], "reply": reply}
    if options.get("scenario"):
        artifact["scenario"] = options["scenario"]
    if op in REGISTRY.scene_changing:
        # The next call must reach the bot's new game server: wait until the bot query finds it.
        artifact["relocated"] = relocate(lambda: driver.bot_query(project, bot), current,
                                         reply["fields"].get("scene"))
        print("AGENT_FIXTURE_RELOCATED", json.dumps(artifact["relocated"], sort_keys=True), flush=True)
    return artifact


def scenario_end(env, role, scenario):
    """Clean up one scenario after a failed run: scenarioEnd for the role's bot.

    Works only while that bot is logged in, on the game server of the scene the scenario was
    opened in, and within reach of what it created (docs/fixture-scenario.md). A `partial` reply
    is returned, not raised, so the caller can report what leaked (scenario_end_failure).
    """
    bindings = env["bindings"]
    if role not in bindings:
        raise ValueError("The environment binds no registry to role " + str(role))
    return run_live(scenario_end_options(role, scenario), env, bindings[role], bindings, accept=("ok", "partial"))


def scenario_end_failure(reply):
    """Why a scenarioEnd reply is not a clean end (None when it is): partial, leaked or nothing open."""
    fields = reply.get("fields", {})
    if reply.get("status") != "ok":
        return f"scenarioEnd status {reply.get('status')}: leaked={fields.get('leaked', '?')} " \
               f"leaked_ids={fields.get('leaked_ids', '?')} open={fields.get('open', '?')}"
    if fields.get("leaked") != "0":
        return f"scenarioEnd left leaked={fields.get('leaked', '?')} objects"
    if fields.get("was_open") != "true":
        return "No scenario with this id was open on the bot (was_open=false); check the id and role"
    return None


# --- Installation into an isolated fixture --------------------------------------------------

RUNTIME_SCRIPTS = "/opt/whitengold/data/sku.0/sys.server/compiled/game/script"
RELEASE = {52: "8", 55: "11", 61: "17", 65: "21"}
FIXTURE_SOURCE = re.compile(r"agent_" + FAMILY_RE + r"\.java")


def reload_command(worker, script=SCRIPT):
    if type(worker) is not int or not 0 < worker <= 2147483647:
        raise ValueError("Invalid game server id")
    if not re.fullmatch(r"fixture\.[a-z_]{1,32}", script):
        raise ValueError("Only fixture scripts are reloaded")
    return f"game {worker} reloadScript {script}"


def class_release(path):
    """javac --release matching an existing server class file's major version."""
    with open(path, "rb") as stream:
        header = stream.read(8)
    if header[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("Not a Java class file: " + str(path))
    major = int.from_bytes(header[6:8], "big")
    if major not in RELEASE:
        raise ValueError(f"Unsupported server class version {major}")
    return RELEASE[major]


def fixture_workers(project, run, runtime_log="/opt/whitengold/exe/linux/runtime.log"):
    """Game server ids the fixture's central server has registered (same source as the bot query)."""
    log = run(["docker", "exec", project + "-central-1", "cat", runtime_log])
    workers = sorted({int(n) for n in re.findall(r"Adding server ([0-9]+) for scene \w+", log)})
    if not workers or len(workers) > 64:
        raise RuntimeError("Cannot bound current fixture game servers")
    return workers


def fixture_sources(tools, profile_fixtures, manifest_files, registry=None):
    """Fixture sources (relative to devtools/zones) to install, in order.

    The profile's own fixtures first (the lean bot fixture before anything that could use a
    newer helper), then every other fixtures/agent_*.java. Each must be a verified bundled
    tool, and every discovered op family must have its Java class present.
    """
    registry = registry or REGISTRY
    names = list(profile_fixtures)
    present = sorted(p.name for p in (tools / "zones" / "fixtures").glob("agent_*.java"))
    for name in present:
        if not FIXTURE_SOURCE.fullmatch(name):
            raise ValueError("Unexpected fixture source name: " + name)
        if "fixtures/" + name not in names:
            names.append("fixtures/" + name)
    for fixture in registry.fixtures:
        if fixture + ".java" not in present:
            raise ValueError(f"Op family class {fixture} has no fixtures/{fixture}.java")
    for name in names:
        if "zones/" + name not in manifest_files:
            raise ValueError(f"zones/{name} is not in devtools/studio-tools.json; "
                             "run `python3 -m swg_test_studio.agent_fixture refresh`")
    return names


def install(env, emit=print):
    """Compile every fixture class against the running fixture's own script classes and load it.

    Writes <folder>/fixture/classes/script/fixture/<class>.class for each fixture source, where
    the fixture overlay applies it at every game start, copies it into the running game
    container, and reloads it on each registered game server. Each source must compile to
    exactly one class file. Refuses anything but an isolated fixture.
    """
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    from .backend import driver_modules
    from .server_tools import profile_of, verified_tool_root, _bundle

    def run(argv, **kw):
        return subprocess.run(argv, capture_output=True, text=True, check=True, **kw).stdout

    driver, _ = driver_modules(env)
    folder = Path(env["folder"]).resolve(strict=True)
    project, schema, services = driver.fixture(folder)
    if not re.fullmatch(r"WGC_[A-F0-9]{12}", schema or ""):
        raise ValueError("The agent fixture installs only into an isolated copied-schema fixture")
    profile = profile_of(env)
    tools = verified_tool_root()
    names = fixture_sources(tools, profile.fixtures, _bundle.verify(tools))
    sources = [tools / "zones" / name for name in names]
    scripts = profile.runtime_scripts
    game = services["game"]["Id"]
    classes = []
    with tempfile.TemporaryDirectory(prefix="swg-agent-fixture-") as tmp:
        tmp = Path(tmp)
        # docker cp creates the last path element only; its parent must exist.
        (tmp / "classpath").mkdir()
        run(["docker", "cp", f"{game}:{scripts}/.", str(tmp / "classpath" / "script")])
        release = class_release(tmp / "classpath" / "script" / "base_script.class")
        target = folder / "fixture" / "classes" / "script" / "fixture"
        target.mkdir(parents=True, exist_ok=True, mode=0o755)
        for index, source in enumerate(sources):
            out = tmp / f"out{index}"
            run(["javac", "--release", release, "-encoding", "utf8", "-nowarn", "-implicit:none",
                 "-cp", str(tmp / "classpath"), "-d", str(out), str(source)])
            built = out / "script" / "fixture" / (source.stem + ".class")
            if sorted(out.rglob("*.class")) != [built]:
                raise RuntimeError(f"{source.name} must compile to exactly one class file")
            shutil.copy2(built, target / built.name)
            run(["docker", "cp", str(built), f"{game}:{scripts}/fixture/{built.name}"])
            classes.append(str(target / built.name))
    host = central_host(project, lambda name: json.loads(run(["docker", "inspect", name])))
    workers = fixture_workers(project, run, profile.runtime_log)
    replies = {}
    for source in sources:
        for w in workers:
            key = w if source.stem == FIXTURE else f"{w}:{source.stem}"
            replies[key] = send(host, reload_command(w, "fixture." + source.stem)).strip()[:200]
    emit({"event": "agent_fixture_installed", "release": release, "classes": classes, "reloads": replies})
    return replies


# --- Generated documentation and bundled-tool hashes ------------------------------------

README_BEGIN = "<!-- agent-fixture-ops:begin (generated: python3 -m swg_test_studio.agent_fixture refresh) -->"
README_END = "<!-- agent-fixture-ops:end -->"


def op_table(registry=None):
    """The README op table, generated from the merged OPS."""
    registry = registry or REGISTRY
    lines = ["| Operation | Fixture class | Arguments | Changes state | Scenario id |", "|---|---|---|---|---|"]
    for op, (spec, mutates) in registry.ops.items():
        kinds = ", ".join(k[:-1] + " (optional)" if k.endswith("?") else k for k in spec) or "-"
        role = registry.role_args.get(op)
        if role:
            kinds += " (" + ", ".join(f"argument {i + 1} is a role" for i in role) + ")"
        lines.append(f"| `{op}` | `{registry.fixture_of[op]}` | {kinds} | {'yes' if mutates else 'no'} | "
                     f"{'required' if op in registry.scenario_ops else '-'}"
                     f"{' (changes scene)' if op in registry.scene_changing else ''} |")
    return "\n".join(lines) + "\n"


def readme_with_table(text, registry=None):
    head, sep, rest = text.partition(README_BEGIN)
    _, sep2, tail = rest.partition(README_END)
    if not sep or not sep2:
        raise ValueError("README lacks the generated op table markers")
    return head + README_BEGIN + "\n" + op_table(registry) + README_END + tail


def manifest_with_fixtures(text, tools):
    """studio-tools.json with every zones/fixtures/agent_*.java hash added or refreshed."""
    import hashlib
    import json
    data = json.loads(text)
    files = dict(data["files"])
    for path in sorted((tools / "zones" / "fixtures").glob("agent_*.java")):
        if not FIXTURE_SOURCE.fullmatch(path.name):
            raise ValueError("Unexpected fixture source name: " + path.name)
        files["zones/fixtures/" + path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    data["files"] = dict(sorted(files.items()))
    return json.dumps(data, indent=2) + "\n"


def refresh(root, check_only=False):
    """Regenerate the README op table and the agent_*.java manifest hashes; returns stale paths."""
    from pathlib import Path
    root = Path(root)
    targets = {root / "README.md": lambda t: readme_with_table(t),
               root / "devtools" / "studio-tools.json": lambda t: manifest_with_fixtures(t, root / "devtools")}
    stale = []
    for path, make in targets.items():
        old = path.read_text(encoding="utf-8")
        new = make(old)
        if new != old:
            stale.append(path.relative_to(root).as_posix())
            if not check_only:
                path.write_text(new, encoding="utf-8")
    return stale


def main(argv=None):
    import argparse
    import sys
    from pathlib import Path
    parser = argparse.ArgumentParser(prog="python3 -m swg_test_studio.agent_fixture")
    parser.add_argument("command", choices=("refresh",))
    parser.add_argument("--check", action="store_true", help="only report stale files; exit 1 if any")
    args = parser.parse_args(argv)
    stale = refresh(Path(__file__).resolve().parents[1], check_only=args.check)
    print(("stale: " if args.check else "refreshed: ") + (", ".join(stale) or "nothing"))
    return int(args.check and bool(stale))


if __name__ == "__main__":
    raise SystemExit(main())
