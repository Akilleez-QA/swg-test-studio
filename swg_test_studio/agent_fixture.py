"""Typed arrange/assert calls into the server-side fixture `script.fixture.agent_fixture`.

The fixture (devtools/zones/fixtures/agent_fixture.java) runs only on an isolated
client fixture (GameServer.clientIsolationFixture=1, a WGC_ copied schema) and acts
only on one exact registered non-god test bot. This module is its host side:

* OPS is the closed list of methods and their argument types. Nothing else is sent;
  there is no free-form console command, script name or expression.
* The console message is a ConGenericMessage sent to the CentralServer console port
  of the fixture's private Docker network, framed as the server's TcpClient expects.
* The game server that owns the bot is found with the existing driver's bot query.

Steps use it as  {"action": "agent_fixture", "options": {"role": R, "op": OP,
"args": [...], "expect": {key: value}}}.  `expect` compares exact strings in the
fixture's reply; the step fails on any status other than `ok` or a mismatch.
"""
import ipaddress
import re
import socket
import struct

SCRIPT = "fixture.agent_fixture"
CONSOLE_PORT = 61000

_NUMBER = r"-?[0-9]{1,5}(\.[0-9]{1,6})?"  # the fixture's NUM_RE
TYPES = {
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
}

# Numeric limits the fixture enforces (agent_fixture.java); checked here so a bad step fails at validation.
RANGES = {"yaw": (-360.0, 360.0), "scale": (0.05, 20.0), "radius": (0.0, 128.0)}

# name -> (argument types, mutates). Optional trailing arguments are written "type?".
OPS = {
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
}

IDENTITY = re.compile(r"[1-9][0-9]{0,18}:[1-9][0-9]{0,9}:Cap[a-z]{12}")


def validate(options, roles):
    """Static validation for a Studio step; raises ValueError."""
    if not isinstance(options, dict) or set(options) - {"role", "op", "args", "expect"} or \
            not {"role", "op", "args"} <= set(options):
        raise ValueError("agent_fixture requires role, op and args (and optional expect)")
    if options["role"] not in roles:
        raise ValueError("Unknown agent_fixture role")
    arguments(options["op"], options["args"])
    expect = options.get("expect", {})
    if (not isinstance(expect, dict) or len(expect) > 32 or
            any(not re.fullmatch(r"[a-z][a-zA-Z0-9_]{0,31}", k) or not isinstance(v, str) or
                not re.fullmatch(r"[^\s]{0,200}", v) for k, v in expect.items())):
        raise ValueError("expect maps reply keys to exact single-token strings")
    return options


def arguments(op, args):
    if op not in OPS:
        raise ValueError("Unknown agent_fixture operation; only typed fixture methods are allowed")
    spec, _ = OPS[op]
    if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
        raise ValueError("agent_fixture args must be a list of strings")
    required = [t for t in spec if not t.endswith("?")]
    if not len(required) <= len(args) <= len(spec):
        raise ValueError(f"{op} takes {len(required)}-{len(spec)} arguments")
    for kind, value in zip(spec, args):
        kind = kind.rstrip("?")
        if not re.fullmatch(TYPES[kind], value):
            raise ValueError(f"{op}: invalid {kind} argument")
        low, high = RANGES.get(kind, (None, None))
        if low is not None and not low <= float(value) <= high:
            raise ValueError(f"{op}: {kind} must be within {low}..{high}")
        if kind == "mods" and any(abs(int(pair.split("=")[1])) > 10000 for pair in value.split(",")):
            raise ValueError(f"{op}: item bonus values must be within -10000..10000")
    return list(args)


def command(worker, bot, op, args):
    """The exact console line; refuses anything outside OPS and the identity contract."""
    if type(worker) is not int or not 0 < worker <= 2147483647:
        raise ValueError("Invalid game server id")
    ident = f"{bot['player']}:{bot['station']}:{bot['character']}"
    if not IDENTITY.fullmatch(ident):
        raise ValueError("Bot identity does not match the fixture contract")
    return " ".join(["game", str(worker), "runScript", SCRIPT, op, ident, *arguments(op, args)])


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


def parse(text):
    """`agent_fixture=<status> key=value ... row=...` -> dict with status, fields, rows."""
    first, _, _ = text.strip().partition("\n")
    tokens = first.split()
    if not tokens or not tokens[0].startswith("agent_fixture="):
        return {"status": "unrecognized", "fields": {}, "rows": [], "raw": text[:500]}
    fields, rows = {}, []
    for token in tokens[1:]:
        key, sep, value = token.partition("=")
        if not sep:
            continue
        if key == "row":
            rows.append(value)
        else:
            fields[key] = value
    return {"status": tokens[0].split("=", 1)[1], "fields": fields, "rows": rows}


def check(reply, expect):
    if reply["status"] != "ok":
        return f"fixture status {reply['status']}"
    for key, value in (expect or {}).items():
        if reply["fields"].get(key) != value:
            return f"{key}: expected {value!r}, got {reply['fields'].get(key)!r}"
    return None


def central_host(project, inspect):
    """The central container's address on the fixture network (private by construction)."""
    rows = inspect(project + "-central-1")
    networks = rows[0]["NetworkSettings"]["Networks"]
    addresses = [n["IPAddress"] for n in networks.values() if n.get("IPAddress")]
    if len(addresses) != 1:
        raise RuntimeError("Cannot select one central fixture address")
    return private_address(addresses[0])


def run_live(options, env, registry):
    """Execute one agent_fixture step against the registered bot; returns an artifact dict."""
    import json
    import subprocess
    from pathlib import Path
    from .backend import driver_modules

    validate(options, [options["role"]])
    driver, _ = driver_modules(env)
    if not re.fullmatch("[a-z]{3,16}", registry):
        raise ValueError("A dedicated registry key is required")
    folder = Path(env["folder"]).resolve(strict=True)
    project, _schema, _services = driver.fixture(folder)
    bot = driver.identity(json.loads((folder / "protocol-driver" / (registry + ".json")).read_text()))
    current = driver.bot_query(project, bot)
    if not current:
        raise RuntimeError("The registered bot is not loaded on any fixture game server")

    def inspect(name):
        out = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    line = command(int(current["worker"]), bot, options["op"], options["args"])
    reply = parse(send(central_host(project, inspect), line))
    print("AGENT_FIXTURE", options["op"], reply["status"], json.dumps(reply["fields"], sort_keys=True), flush=True)
    failure = check(reply, options.get("expect"))
    if failure:
        raise RuntimeError(f"agent_fixture {options['op']}: {failure}")
    return {"op": options["op"], "mutates": OPS[options["op"]][1], "reply": reply}


# --- Installation into an isolated fixture --------------------------------------------------

RUNTIME_SCRIPTS = "/opt/whitengold/data/sku.0/sys.server/compiled/game/script"
RELEASE = {52: "8", 55: "11", 61: "17", 65: "21"}


def reload_command(worker):
    if type(worker) is not int or not 0 < worker <= 2147483647:
        raise ValueError("Invalid game server id")
    return f"game {worker} reloadScript {SCRIPT}"


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


def fixture_workers(project, run):
    """Game server ids the fixture's central server has registered (same source as the bot query)."""
    log = run(["docker", "exec", project + "-central-1", "cat", "/opt/whitengold/exe/linux/runtime.log"])
    workers = sorted({int(n) for n in re.findall(r"Adding server ([0-9]+) for scene \w+", log)})
    if not workers or len(workers) > 64:
        raise RuntimeError("Cannot bound current fixture game servers")
    return workers


def install(env, emit=print):
    """Compile the fixture against the running fixture's own script classes and load it.

    Writes <folder>/fixture/classes/script/fixture/agent_fixture.class, where the fixture
    overlay applies it at every game start, copies it into the running game container,
    and reloads it on each registered game server. Refuses anything but an isolated fixture.
    """
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    from .backend import driver_modules
    from .server_tools import verified_tool_root

    def run(argv, **kw):
        return subprocess.run(argv, capture_output=True, text=True, check=True, **kw).stdout

    driver, _ = driver_modules(env)
    folder = Path(env["folder"]).resolve(strict=True)
    project, schema, services = driver.fixture(folder)
    if not re.fullmatch(r"WGC_[A-F0-9]{12}", schema or ""):
        raise ValueError("The agent fixture installs only into an isolated copied-schema fixture")
    source = verified_tool_root() / "zones/fixtures/agent_fixture.java"
    game = services["game"]["Id"]
    with tempfile.TemporaryDirectory(prefix="swg-agent-fixture-") as tmp:
        tmp = Path(tmp)
        run(["docker", "cp", f"{game}:{RUNTIME_SCRIPTS}/.", str(tmp / "classpath" / "script")])
        release = class_release(tmp / "classpath" / "script" / "base_script.class")
        out = tmp / "out"
        run(["javac", "--release", release, "-encoding", "utf8", "-nowarn", "-implicit:none",
             "-cp", str(tmp / "classpath"), "-d", str(out), str(source)])
        built = out / "script" / "fixture" / "agent_fixture.class"
        target = folder / "fixture" / "classes" / "script" / "fixture"
        target.mkdir(parents=True, exist_ok=True, mode=0o755)
        shutil.copy2(built, target / "agent_fixture.class")
        run(["docker", "cp", str(built), f"{game}:{RUNTIME_SCRIPTS}/fixture/agent_fixture.class"])
    host = central_host(project, lambda name: json.loads(run(["docker", "inspect", name])))
    replies = {w: send(host, reload_command(w)).strip()[:200] for w in fixture_workers(project, run)}
    emit({"event": "agent_fixture_installed", "release": release, "class": str(target / "agent_fixture.class"),
          "reloads": replies})
    return replies
