"""Resolve a source selection into a prepared, isolated SWG test server."""
from pathlib import Path
import re

from .backend import driver_modules, environment, validate_environment
from .model import exact
from .store import read_json, write_json


SETUPS = Path("StarWarsGalaxies/logs/studio-setups")
PROJECT = re.compile(r"swg-cold-test-[a-f0-9]{8}\Z")


def source_folder(path):
    path = Path(path).resolve()
    if path.name.casefold() == "src":
        path = path.parent
    if not ((path / "src").is_dir() and (path / "devtools/zones/protocol_driver.py").is_file()):
        raise ValueError("Choose the SWG source folder that contains src and devtools. You can also choose its src folder.")
    return path


def saved_source(workspace):
    path = Path(workspace) / "source.json"
    if path.is_file():
        data = read_json(path)
        exact(data, ("schema_version", "server_checkout"), "saved source")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError("Choose the SWG source folder again to update the saved selection.")
        value = data["server_checkout"]
        if not isinstance(value, str) or not Path(value).is_absolute() and not value.startswith("/"):
            raise ValueError("Choose the SWG source folder again to correct the saved selection.")
        return value
    legacy = Path(workspace) / "environment.json"
    return environment(legacy)["server_checkout"] if legacy.is_file() else None


def select_source(workspace, path):
    source = source_folder(path)
    write_json(Path(workspace) / "source.json", {"schema_version": 1, "server_checkout": str(source)}, replace=True)
    return str(source)


def checked_setup(env):
    env = validate_environment(env)
    folder = Path(env["folder"])
    if folder.resolve(strict=True) != folder:
        raise ValueError("The test server folder no longer matches its saved setup.")
    driver, _ = driver_modules(env)
    root, _, volume = driver.target_root(folder.parent)
    schema = "WGC_" + folder.name[7:].upper()
    proof = read_json(folder / "schema-report.json")
    runtime = read_json(folder / "runtime/report.json")
    stage = read_json(folder / "runtime/stage5-report.json")
    if (proof.get("passed") is not True or proof.get("schema") != schema or proof.get("volume") != volume or
            any(report.get("schema") != schema or report.get("project") != root.name
                for report in (runtime, stage)) or stage.get("stage") != 5 or
            stage.get("central_freeze_debugger") or not driver.local_auth((folder / "runtime/runtime.cfg").read_text())):
        raise ValueError("Studio needs a verified SWG test server prepared for ordinary gameplay tests.")
    driver.validate_binary(Path(env["binary"]))
    roster = {}
    identities = {field: set() for field in ("account", "character", "player", "station")}
    for key in env["bindings"].values():
        path = folder / "protocol-driver" / (key + ".json")
        if path.is_symlink():
            raise ValueError("The test character setup contains an unexpected link.")
        bot = driver.identity(read_json(path)) if path.is_file() else {}
        if bool(bot.get("player")) != bool(bot.get("station")):
            raise ValueError("A test character has incomplete setup. Ask the test server maintainer to check it.")
        for field, used in identities.items():
            if field in bot:
                if bot[field] in used:
                    raise ValueError("The test setup assigns the same character or account more than once.")
                used.add(bot[field])
        roster[key] = bool(bot.get("player"))
    return driver, folder, root, volume, schema, stage, roster


def register_setup(path, *, replace=False):
    env = environment(path)
    source = source_folder(env["server_checkout"])
    env = dict(env, server_checkout=str(source))
    _, _, root, _, _, _, _ = checked_setup(env)
    destination = source / SETUPS / (root.name + ".json")
    write_json(destination, env, replace=replace)
    return destination


def available_setups(workspace):
    saved = saved_source(workspace)
    if not saved:
        raise ValueError("Choose the SWG source folder first.")
    source = source_folder(saved)
    registered = {}
    for path in sorted((source / SETUPS).glob("swg-cold-test-*.json")):
        env = environment(path)
        if (PROJECT.fullmatch(path.stem) and Path(env["server_checkout"]).resolve() == source and
                Path(env["folder"]).parent.name == path.stem):
            registered[path.stem] = env
    if not registered:
        legacy = Path(workspace) / "environment.json"
        if legacy.is_file():
            env = environment(legacy)
            if source_folder(env["server_checkout"]) == source:
                registered[Path(env["folder"]).parent.name] = dict(env, server_checkout=str(source))
    if not registered:
        raise ValueError("No Docker test server is connected to this source folder yet. Ask the test server maintainer "
                         "to prepare one for this source. You can still create and check tests offline.")
    return registered


def assign_roles(preferred, roster, roles, *, creation_roles=()):
    roles = list(roles)
    creation_roles = set(creation_roles)
    assigned = {}
    used = set()
    for role in roles:
        key = preferred.get(role)
        if key in roster and roster[key] == (role not in creation_roles):
            assigned[role] = key
            used.add(key)
    for role in roles:
        if role in assigned:
            continue
        ready = role not in creation_roles
        key = next((key for key, existing in roster.items() if existing == ready and key not in used), None)
        if key is None:
            if not ready:
                raise ValueError("This test creates a character, but this test server has no unused character slot.")
            count = len(set(roles) - creation_roles)
            raise ValueError(f"This test needs {count} prepared test characters. "
                             f"This server has {sum(roster.values())} available for Studio.")
        assigned[role] = key
        used.add(key)
    return {role: assigned[role] for role in roles}


def automatic_environment(workspace, roles, *, project=None, creation_roles=(), recording=False):
    registered = available_setups(workspace)
    if not project and len(registered) == 1:
        project = next(iter(registered))
    if project not in registered:
        raise ValueError("Select one of the verified Docker test servers for this source folder.")
    env = registered[project]
    try:
        _, _, _, _, _, stage, roster = checked_setup(env)
    except (ValueError, OSError, ImportError, KeyError) as exc:
        raise ValueError("Studio could not verify this Docker test server against the selected source. "
                         "Ask the test server maintainer to refresh its setup.") from exc
    if recording and (stage.get("test_studio_recording") is not True or
                      len(roles) > 1 and stage.get("test_studio_action_capture") != 1):
        raise ValueError("Recording is unavailable on this test server. Select one prepared for recording.")
    return dict(env, bindings=assign_roles(env["bindings"], roster, roles, creation_roles=creation_roles))


def creation_roles(suite):
    return {step["options"]["role"] for step in suite["steps"]
            if step["action"] == "session" and step["options"].get("create") is True}
