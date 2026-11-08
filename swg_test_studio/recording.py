"""Fixture-scoped semantic capture; observations export as unapproved drafts."""
import os
from pathlib import Path
import re
import secrets
import time

from .backend import driver_modules, studio_lock, validate_environment
from .model import FORMAT, identifier, loads
from .store import read_json, write_json


def session_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid recording ID")
    return value


def root_for(env):
    root = Path(env["folder"]) / "fixture/teststudio"
    if root.is_symlink() or root.parent.is_symlink() or root.resolve() != root:
        raise ValueError("Unexpected recording mount path")
    return root


def start(env, workspace, role, seconds=600):
    if role not in env["bindings"] or type(seconds) is not int or not 30 <= seconds <= 3600:
        raise ValueError("Select a bound role and duration of 30–3600 seconds")
    driver, _ = driver_modules(env)
    with studio_lock(workspace), driver.operation_lock(driver.REPO / "StarWarsGalaxies"):
        project, schema, services = driver.fixture(Path(env["folder"]))
        mount = next((m for m in services["game"]["Mounts"] if m["Destination"] == "/fixture"), None)
        if not mount or Path(mount["Source"]).resolve() != Path(env["folder"]) / "fixture" or not mount.get("RW"):
            raise ValueError("Recording requires the verified writable fixture mount")
        section, enabled = "", None
        for raw in (Path(env["folder"]) / "runtime/runtime.cfg").read_text().splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
            elif section == "GameServer" and "=" in line and not line.startswith(("#", ";", "//")):
                key, value = line.split("=", 1)
                if key.strip() == "testStudioRecorder":
                    enabled = value.strip()
        if enabled not in ("true", "1"):
            raise ValueError("Recorder disabled: install the matched server build and explicitly enable testStudioRecorder in this fixture")
        registry = Path(env["folder"]) / "protocol-driver" / (env["bindings"][role] + ".json")
        bot = driver.identity(read_json(registry))
        if "player" not in bot or "station" not in bot:
            raise ValueError("Recording requires an existing fully registered test character")
        root = root_for(env)
        root.mkdir(mode=0o700, exist_ok=True)
        if any(root.glob("*.control")):
            raise ValueError("Stop the existing recording first; expired controls require explicit Stop")
        token, expiry = secrets.token_hex(16), int(time.time()) + seconds
        (root / token).mkdir(mode=0o700)
        control = f"SWGTS1 {token} {expiry} {bot['station']} {bot['character']}\n"
        meta = {"schema_version": 1, "id": token, "state": "recording", "expires": expiry,
                "environment": env, "project": project, "schema": schema,
                "actors": {bot["player"]: {"role": role, "station": bot["station"], "character": bot["character"]}},
                "controls": {bot["player"]: control}, "started": int(time.time())}
        path = Path(workspace) / "recordings" / (token + ".json")
        write_json(path, meta)
        try:
            with (root / (bot["player"] + ".control")).open("x", encoding="ascii") as output:
                os.chmod(output.name, 0o600)
                output.write(control)
        except Exception:
            meta["state"] = "failed"
            write_json(path, meta, replace=True)
            raise
        return {"id": token, "state": "armed_waiting_for_server_events", "expires": expiry,
                "character": bot["character"], "role": role}


def load(workspace, token):
    token = session_id(token)
    path = Path(workspace) / "recordings" / (token + ".json")
    meta = read_json(path)
    if meta.get("schema_version") != 1 or meta.get("id") != token:
        raise ValueError("Recording metadata identity changed")
    env = validate_environment(meta["environment"])
    return path, meta, root_for(env)


def status(workspace, token):
    _, meta, root = load(workspace, token)
    folder = root / token
    if folder.is_symlink():
        raise ValueError("Recording directory is a symbolic link")
    path, events, errors = folder / "events.jsonl", [], []
    if (folder / "capture.error").exists():
        errors.append("Server reported an incomplete capture")
    if path.exists():
        if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Invalid recording event file")
        for index, line in enumerate(path.read_bytes().splitlines(keepends=True)):
            if len(line) > 4096 or not line.endswith(b"\n"):
                errors.append("Incomplete event line; poll again or preserve failed capture")
                break
            event = loads(line.decode("utf-8"))
            if (set(event) != {"schema_version", "sequence", "session", "actor", "event", "time", "data"} or
                    event["schema_version"] != 1 or type(event["sequence"]) is not int or event["sequence"] != index + 1 or
                    event["session"] != token or event["actor"] not in meta["actors"] or
                    not isinstance(event["data"], dict) or not isinstance(event["event"], str)):
                raise ValueError("Recording event gap, identity or schema mismatch")
            events.append(event)
            if event["event"] == "overflow" or len(events) > 4096:
                errors.append("Recording event limit exceeded")
                break
    return {"id": token, "state": meta["state"], "expired": time.time() >= meta["expires"],
            "events": events, "errors": errors, "replayable": False,
            "notice": "Map observations to supported recipes and explicit expected results before replay"}


def finish_writers(events):
    import fcntl
    if events.exists():
        fd = os.open(events, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        finally:
            os.close(fd)


def stop(workspace, token):
    with studio_lock(workspace):
        path, meta, root = load(workspace, token)
        for actor, expected in meta["controls"].items():
            if not re.fullmatch(r"[1-9][0-9]{0,18}", actor):
                raise ValueError("Invalid recorded actor")
            control = root / (actor + ".control")
            if control.exists():
                if control.is_symlink() or control.read_text(encoding="ascii") != expected or token not in expected:
                    raise ValueError("Recording control ownership changed; refusing removal")
                control.unlink()
        meta["state"], meta["stopped"] = "stopped", int(time.time())
        # Fence any writer that already acquired its append lock before Stop.
        finish_writers(root / token / "events.jsonl")
        write_json(path, meta, replace=True)
    return status(workspace, token)


def draft(workspace, token, name, title):
    identifier(name)
    _, meta, _ = load(workspace, token)
    capture = status(workspace, token)
    if capture["state"] != "stopped" or capture["errors"] or not capture["events"]:
        raise ValueError("Stop a nonempty, complete recording before exporting")
    steps = [{"id": "observe_" + str(e["sequence"]), "action": "recorded_observation",
              "options": {"summary": e["event"] + ": " + str(e["data"].get("scene", "unknown scene"))}}
             for e in capture["events"][:32]]
    return {"format": FORMAT, "schema_version": 1, "id": name, "title": title,
            "category": "regression", "roles": [v["role"] for v in meta["actors"].values()], "steps": steps,
            "review": {"approved": False, "recording": token,
                       "unsupported": ["Map observations to supported driver recipes; review every expected outcome"]}}
