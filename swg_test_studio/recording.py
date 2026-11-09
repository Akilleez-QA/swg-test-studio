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
    roles = [role] if isinstance(role, str) else role
    if (not isinstance(roles, list) or not 1 <= len(roles) <= 2 or
            any(not isinstance(key, str) or key not in env["bindings"] for key in roles) or
            len(set(roles)) != len(roles) or type(seconds) is not int or not 30 <= seconds <= 3600):
        raise ValueError("Select one or two distinct bound roles and duration of 30–3600 seconds")
    driver, _ = driver_modules(env)
    with studio_lock(workspace), driver.operation_lock(driver.REPO / "StarWarsGalaxies"):
        project, schema, services = driver.fixture(Path(env["folder"]))
        root = root_for(env)
        mount = next((m for m in services["game"]["Mounts"] if m["Destination"] == "/fixture"), None)
        capture_mount = next((m for m in services["game"]["Mounts"] if m["Destination"] == "/teststudio-capture"), None)
        if (not mount or mount.get("RW") is not False or
                Path(mount["Source"]).resolve() != Path(env["folder"]) / "fixture" or
                not capture_mount or Path(capture_mount["Source"]).resolve() != root or not capture_mount.get("RW")):
            raise ValueError("Recording requires the exact dedicated writable capture mount")
        profile = read_json(Path(env["folder"]) / "runtime/stage5-report.json")
        if profile.get("test_studio_recording") is not True:
            raise ValueError("Prepare the fixture with the explicit --test-studio-recording option")
        if len(roles) > 1 and profile.get("test_studio_action_capture") != 1:
            raise ValueError("Two-role recording requires the matching action-capture server build")
        section, enabled = "", None
        for raw in (Path(env["folder"]) / "runtime/config/game.cfg").read_text().splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
            elif section == "GameServer" and "=" in line and not line.startswith(("#", ";", "//")):
                key, value = line.split("=", 1)
                if key.strip() == "testStudioRecorder":
                    enabled = value.strip()
        if enabled not in ("true", "1"):
            raise ValueError("Recorder disabled: install the matched server build and explicitly enable testStudioRecorder in this fixture")
        bots = {}
        for key in roles:
            registry = Path(env["folder"]) / "protocol-driver" / (env["bindings"][key] + ".json")
            bot = driver.identity(read_json(registry))
            if "player" not in bot or "station" not in bot:
                raise ValueError("Recording requires existing fully registered test characters")
            bots[key] = bot
        for field in ("player", "account", "station"):
            if len({bot[field] for bot in bots.values()}) != len(roles):
                raise ValueError("Recording roles must bind distinct characters and accounts")
        root.mkdir(mode=0o700, exist_ok=True)
        if any(root.glob("*.control")):
            raise ValueError("Stop the existing recording first; expired controls require explicit Stop")
        token, expiry = secrets.token_hex(16), int(time.time()) + seconds
        (root / token).mkdir(mode=0o700)
        # Keep the event file owned by the host operator even when the native
        # worker runs under a different container UID.
        with (root / token / "events.jsonl").open("x", encoding="utf-8") as events:
            os.chmod(events.name, 0o600)
        controls = {
            bot["player"]: f"SWGTS1 {token} {expiry} {bot['station']} {bot['character']}\n"
            for bot in bots.values()
        }
        actors = {
            bot["player"]: {"role": key, "station": bot["station"], "character": bot["character"]}
            for key, bot in bots.items()
        }
        meta = {"schema_version": 1, "id": token, "state": "recording", "expires": expiry,
                "environment": env, "project": project, "schema": schema,
                "actors": actors, "controls": controls, "started": int(time.time())}
        path = Path(workspace) / "recordings" / (token + ".json")
        write_json(path, meta)
        created = []
        try:
            for player, control in controls.items():
                control_path = root / (player + ".control")
                with control_path.open("x", encoding="ascii") as output:
                    created.append(control_path)
                    os.chmod(output.name, 0o600)
                    output.write(control)
        except Exception:
            for control_path in created:
                control_path.unlink(missing_ok=True)
            meta["state"] = "failed"
            write_json(path, meta, replace=True)
            raise
        roster = [{"role": key, "account": bot["account"], "character": bot["character"]}
                  for key, bot in bots.items()]
        armed = {"id": token, "state": "armed_waiting_for_server_events", "expires": expiry, "actors": roster}
        if len(roster) == 1:
            armed.update(roster[0])
        return armed


def load(workspace, token):
    token = session_id(token)
    path = Path(workspace) / "recordings" / (token + ".json")
    meta = read_json(path)
    if type(meta.get("schema_version")) is not int or meta["schema_version"] != 1 or meta.get("id") != token:
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
                    type(event["schema_version"]) is not int or event["schema_version"] != 1 or type(event["sequence"]) is not int or event["sequence"] != index + 1 or
                    event["session"] != token or event["actor"] not in meta["actors"] or
                    not isinstance(event["data"], dict) or not isinstance(event["event"], str)):
                raise ValueError("Recording event gap, identity or schema mismatch")
            events.append(event)
            if event["event"] == "overflow" or len(events) > 4096:
                errors.append("Recording event limit exceeded")
                break
    _, options, unsupported = compile_actions(events, meta["actors"])
    actions = options["actions"]
    return {"id": token, "state": meta["state"], "expired": time.time() >= meta["expires"],
            "events": events, "errors": errors, "replayable": False,
            "supported_actions": len(actions), "unsupported": unsupported,
            "notice": "Export supported actions, review the observed expectations and approve the draft before replay"}


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
        owned_controls = []
        for actor, expected in meta["controls"].items():
            if not re.fullmatch(r"[1-9][0-9]{0,18}", actor):
                raise ValueError("Invalid recorded actor")
            control = root / (actor + ".control")
            if control.exists():
                if control.is_symlink() or control.read_text(encoding="ascii") != expected or token not in expected:
                    raise ValueError("Recording control ownership changed; refusing removal")
                owned_controls.append(control)
        for control in owned_controls:
            control.unlink()
        meta["state"], meta["stopped"] = "stopped", int(time.time())
        # Fence any writer that already acquired its append lock before Stop.
        finish_writers(root / token / "events.jsonl")
        write_json(path, meta, replace=True)
    return status(workspace, token)


def compile_actions(events, actors):
    from .capture_compile import convert
    from .sequence_capture import applies, convert as convert_sequence

    if applies(events):
        options, problems = convert_sequence(events, actors)
        return "action_sequence", options, problems
    actions, problems = convert(events)
    participants = {event["actor"] for event in events if "actor" in event}
    if len(participants) > 1 or (not participants and len(actors) != 1):
        problems.append("A shuttle clip requires one recorded role")
    role = next(value["role"] for key, value in actors.items() if not participants or key in participants)
    return "journey", {"role": role, "prepare_start": True, "actions": actions}, problems


def draft(workspace, token, name, title, ranges=None):
    identifier(name)
    _, meta, _ = load(workspace, token)
    capture = status(workspace, token)
    if capture["state"] != "stopped" or capture["errors"] or not capture["events"]:
        raise ValueError("Stop a nonempty, complete recording before exporting")
    from .clips import validate_ranges
    spans = validate_ranges(ranges) if ranges is not None else [{"first": 1, "last": len(capture["events"])}]
    if spans[-1]["last"] > len(capture["events"]):
        raise ValueError("Recording clip extends beyond the captured events")
    roles = [v["role"] for v in meta["actors"].values()]
    steps, unsupported = [], []
    for index, span in enumerate(spans):
        events = capture["events"][span["first"] - 1:span["last"]]
        action, options, problems = compile_actions(events, meta["actors"])
        unsupported.extend((f"Clip {index + 1}: " if len(spans) > 1 else "") + p for p in problems)
        if options["actions"]:
            steps.append({"id": "recorded_journey" + (f"_{index + 1}" if len(spans) > 1 else ""),
                          "action": action, "options": options})
        else:
            steps.extend({"id": "observe_" + str(e["sequence"]), "action": "recorded_observation",
                          "options": {"summary": e["event"] + ": " + str(e["data"].get("scene", "unknown scene"))}}
                         for e in events[:32])
    review = {"approved": False, "recording": token, "unsupported": unsupported[:128]}
    if ranges is not None:
        review["capture_ranges"] = spans
    return {"format": FORMAT, "schema_version": 1, "id": name, "title": title,
            "category": "regression", "roles": roles, "steps": steps[:32], "review": review}
