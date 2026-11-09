"""Docker operations restricted to a registered SWG test server."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from .setup import available_setups, checked_setup
from .server_tools import tool_environment, verified_tool_root
from .store import read_json

REUSE_ROLES = ("chat", "local_chat", "game")
STOPPED = {"created", "exited"}


def docker(*args, timeout=60):
    try:
        # Explicit fixture Compose commands must not inherit unrelated project options.
        env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")} if args[0] == "compose" else None
        result = subprocess.run(["docker", *args], capture_output=True, text=True, errors="replace",
                                timeout=timeout, env=env)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Studio requires Docker. Install Docker, start it, and try again.") from exc
    if result.returncode:
        raise ValueError(f"Docker could not complete {args[0]}. Check that Docker is running and retry.")
    return result.stdout + result.stderr if args[0] == "logs" else result.stdout


def require_docker():
    if not shutil.which("docker"):
        raise ValueError("Studio requires Docker for tests. Install and start Docker, then try again.")
    endpoint = os.environ.get("DOCKER_HOST") if not os.environ.get("DOCKER_CONTEXT") else None
    if not endpoint:
        endpoint = docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}", timeout=10).strip()
    if not endpoint.startswith("unix://"):
        raise ValueError("Studio needs a local Docker engine. Switch Docker to a local context and try again.")
    docker("version", "--format", "{{.Server.Version}}", timeout=10)


def container_set(env, *, during_start=False):
    driver, folder, root, volume, schema, stage, roster = checked_setup(env)
    release = read_json(Path(env["server_checkout"]) / "StarWarsGalaxies/instance-release.json")
    pins = release["roles"]
    expected = set(pins) | {"oracle", "local_chat"}
    rows = {}
    for row in driver.inspect_project(root.name):
        labels = row["Config"]["Labels"]
        role = labels.get("com.docker.compose.service")
        if (role not in expected or role in rows or labels.get("com.docker.compose.project") != root.name or
                row.get("Name") != f"/{root.name}-{role}-1" or
                not re.fullmatch("[a-f0-9]{64}", row.get("Id", "")) or
                row["HostConfig"].get("Privileged") or row["HostConfig"].get("CapAdd")):
            raise ValueError("This Docker test server contains unverified containers.")
        if role in pins and (labels.get("whitengold.test.client") != schema or
                             row["Image"] != pins[role]["image_id"]):
            raise ValueError("This Docker test server does not match the source folder’s approved build.")
        if role == "local_chat":
            if (labels.get("whitengold.test.client") != schema or
                    row["Config"].get("Image") != "starwarsgalaxies/local-chat:local" or
                    row["Image"] != docker("image", "inspect", "--format", "{{.Id}}",
                                           "starwarsgalaxies/local-chat:local").strip()):
                raise ValueError("This Docker test server has an unexpected private chat image.")
        rows[role] = row
    if set(rows) != expected and not during_start:
        raise ValueError("This Docker test server is incomplete. Ask the test server maintainer to prepare it.")
    driver.validate(rows["oracle"], root, volume)
    if rows["oracle"]["State"].get("Running") is not True:
        raise ValueError("The test database is stopped. Start it before starting the test server.")
    state = {row["State"]["Status"] for role, row in rows.items() if role != "oracle"}
    if state == {"running"}:
        status = "Running"
    elif state <= STOPPED:
        status = "Stopped"
    elif during_start:
        status = "Starting"
    elif (state <= STOPPED | {"running"} and
          all(rows[role]["State"]["Status"] in STOPPED for role in ("central", "taskmanager"))):
        status = "Needs startup"
    else:
        raise ValueError("This Docker test server is partly started. Ask its maintainer to check it.")
    return driver, folder, rows, status, stage, roster


def list_servers(workspace, *, start_if_needed=False, emit=print):
    require_docker()
    registered = available_setups(workspace)
    servers = []
    rejected = []
    for project, env in registered.items():
        try:
            _, _, _, state, stage, roster = container_set(env)
        except (OSError, RuntimeError, ValueError, KeyError, ImportError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "Could not read or verify its prepared setup."
            rejected.append(f"{project} · {reason}")
            continue
        servers.append({"id": project, "name": env["name"], "state": state,
                        "characters": sum(roster.values()), "recording": bool(stage.get("test_studio_recording"))})
    if not servers:
        raise ValueError("No verified Docker test server is available. " + " ".join(rejected))
    servers.sort(key=lambda server: (server["state"] != "Running", server["name"], server["id"]))
    if start_if_needed and servers[0]["state"] != "Running":
        # Reuse an existing verified server and retain it for the next Run.
        server = servers[0]
        with active_server(registered[server["id"]], keep_running=True, emit=emit):
            server["state"] = "Running"
    return servers


def wait_for_login(rows, project):
    login = rows["login"]["Id"]
    since = docker("inspect", "--format", "{{.State.StartedAt}}", login).strip()
    pattern = re.compile(r"Cluster " + re.escape(project) + r" is (ready|not ready) for players\.")
    deadline = time.monotonic() + 240
    retried = False
    while time.monotonic() < deadline:
        if docker("inspect", "--format", "{{.State.Running}}", login).strip() != "true":
            if retried:
                raise ValueError("The Docker test server’s login service stopped during startup.")
            time.sleep(5)
            docker("start", login)
            since = docker("inspect", "--format", "{{.State.StartedAt}}", login).strip()
            retried = True
        states = pattern.findall(docker("logs", "--since", since, login))
        if states and states[-1] == "ready":
            return
        time.sleep(3)
    raise ValueError("The Docker test server started, but login did not become ready in four minutes.")


def prepare_restart(driver, folder, rows, stage):
    # Reuse the server's normal stopped-generation fence for this private copy.
    from fixture_journal_maintenance import ACK, command
    from prepare_stage5_client_fixture64 import state_definitions

    if stage.get("existing_journals_only") is not True:
        raise ValueError("This stopped server needs the SWG test server’s existing-journal setup before Studio can start it.")
    overlay = Path(stage["overlay"]).resolve(strict=True)
    if (overlay.parts[:2] != ("/", "tmp") or
            not re.fullmatch(r"[a-f0-9]{64}", stage.get("overlay_manifest_sha256", "")) or
            hashlib.sha256((overlay / "manifest.json").read_bytes()).hexdigest() != stage["overlay_manifest_sha256"]):
        raise ValueError("The saved Docker test server build no longer matches its preparation.")
    image = rows["central"]["Config"]["Image"]
    if (not re.fullmatch(r"starwarsgalaxies/central:[A-Za-z0-9_.-]+", image) or
            docker("image", "inspect", "--format", "{{.Id}}", image).strip() != rows["central"]["Image"]):
        raise ValueError("The test server’s pinned Central image is unavailable.")
    definitions = state_definitions(stage["policy"])
    for journal, option in ACK.items():
        argv = command(folder / "runtime", journal, option,
                       definitions if journal.endswith("/instances") else [], overlay, image)
        docker(*argv[1:], timeout=90)


def wait_for_preload(driver, folder):
    verifier = verified_tool_root() / "zones/inspect_client_fixture.py"
    deadline = time.monotonic() + 480
    detail = ""
    with tempfile.TemporaryDirectory(prefix="swg-studio-ready-") as directory:
        for attempt in range(60):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            output = Path(directory) / f"ready-{attempt}.json"
            try:
                result = subprocess.run(
                    [sys.executable, str(verifier), "--folder", str(folder), "--output", str(output),
                     "--stage5", "--expected-instances", "1"],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                    timeout=min(300, remaining), env=tool_environment(driver.REPO))
            except subprocess.TimeoutExpired:
                detail = "The native readiness check timed out."
                continue
            if output.is_file():
                report = read_json(output)
                if result.returncode == 0 and report.get("ready") is True:
                    return
                running = [row for row in report["instances"] if row["state"] not in ("stopped", "retired")]
                ready = sum(row["ready"] == "1" for row in running)
                detail = f"{ready} of {len(running)} active game instances reported ready."
            elif "Fresh native content snapshot unavailable" in result.stderr:
                detail = "The game servers did not return a complete readiness snapshot."
            time.sleep(5)
    raise ValueError("Login was ready, but the game-world checks did not pass. " + detail)


def wait_for_login_hosts(driver, folder, central, bindings):
    """Require native readiness for the exact saved hosts used by plain login tests."""
    from inspect_client_fixture import rows

    project, schema, _ = driver.fixture(folder)
    hosts = set()
    for key in bindings.values():
        bot = driver.identity(read_json(folder / "protocol-driver" / (key + ".json")))
        saved = driver.saved(project, schema, bot["player"])
        hosts.add((saved["scene"], saved["instance"]))

    def query(name):
        return rows(docker("exec", central, "/fixture/client-console", "127.0.0.1", name, timeout=15))

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            scenes = {(row["scene"], row["instance"]) for row in query("capacityScenes")
                      if row["connected"] == "1" and row["preload"] == "finished" and row["heartbeat_fresh"] == "1"}
            worlds = {(row["definition"], row["instance"]) for row in query("capacityInstances")
                      if row["state"] == "running" and row["ready"] == "1"}
            if hosts <= scenes and all(instance == "0" or (scene, instance) in worlds for scene, instance in hosts):
                return
        except (RuntimeError, ValueError):
            pass
        time.sleep(3)
    raise ValueError("Login is ready, but the test characters’ saved worlds did not finish loading.")


def plain_login(suite):
    return all(step["action"] == "session" and set(step["options"]) == {"role"} for step in suite["steps"])


def verified_compose(folder, rows, directory):
    runtime = folder / "runtime"
    project = folder.parent.name
    original = runtime / "compose.json"
    if original.resolve(strict=True) != original:
        raise ValueError("The prepared test server configuration is no longer in its expected location.")
    # Use one private copy for both the comparison and the start.
    config = directory / "compose.json"
    config.write_bytes(original.read_bytes())
    definition = read_json(config)
    if (definition.get("name") != project or set(definition["services"]) != set(rows) or
            definition.get("volumes") != {"oracle_data": {"external": True, "name": project + "_oracle26_data"}}):
        raise ValueError("The saved Docker settings do not match this isolated test server.")
    network_names = {project + "_" + key for key in definition["networks"]}
    attached = {name for row in rows.values() for name in row["NetworkSettings"]["Networks"]}
    if network_names != attached or any(
            options.get("external") or options.get("name", project + "_" + key) != project + "_" + key
            for key, options in definition["networks"].items()):
        raise ValueError("The test server configuration names an unexpected network.")
    for key in definition["networks"]:
        name = project + "_" + key
        labels = docker("network", "inspect", "--format", "{{json .Labels}}", name)
        labels = json.loads(labels)
        if labels.get("com.docker.compose.project") != project or labels.get("com.docker.compose.network") != key:
            raise ValueError("An expected test-server network could not be verified.")
    compose = ("compose", "--project-name", project, "--project-directory", str(runtime),
               "--env-file", "/dev/null", "-f", str(config))
    hashes = dict(line.split() for line in docker(*compose, "config", "--hash=*").splitlines())
    roles = [role for role in rows if role not in ("oracle", *REUSE_ROLES)]
    for role in roles:
        row = rows[role]
        service = definition["services"][role]
        image = row["Config"]["Image"]
        if (not re.fullmatch(r"starwarsgalaxies/" + role + r":[A-Za-z0-9_.-]+", image) or
                service.get("image") != image or service.get("build") or
                hashes.get(role) != row["Config"]["Labels"].get("com.docker.compose.config-hash") or
                not re.fullmatch("[a-f0-9]{64}", hashes.get(role, "")) or
                docker("image", "inspect", "--format", "{{.Id}}", image).strip() != row["Image"]):
            raise ValueError(f"The saved settings or image for {role} differ from the verified test container.")
    return compose, roles


def recreate_games(env, folder, rows):
    with tempfile.TemporaryDirectory(prefix="swg-studio-restart-") as temporary:
        directory = Path(temporary)
        compose, roles = verified_compose(folder, rows, directory)
        # Keep the installed test-only Java helpers and the chat sidecar's
        # container network attachment.
        for role in REUSE_ROLES:
            docker("start", rows[role]["Id"])
        start = (*compose, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate")
        docker(*start, *(role for role in roles if role != "login"), timeout=180)
        docker(*start, "login", timeout=120)
        _, _, current, _, _, _ = container_set(env, during_start=True)
        return current


def stop_started(rows, started):
    # Do not stop any service that was already running when Studio began.
    for role in ("central", "taskmanager"):
        if role in started:
            docker("stop", "--time", "90", rows[role]["Id"], timeout=110)
    remaining = [rows[role]["Id"] for role in started if role not in ("central", "taskmanager")]
    if remaining:
        docker("stop", "--time", "90", *remaining, timeout=120)


def finish_incomplete_shutdown(rows):
    """Only finish a partial shutdown if the coordinator and game processes are gone."""
    workers = {"game": "SwgGameServer", "planet": "PlanetServer", "connection": "ConnectionServer"}
    running = [role for role, row in rows.items() if role != "oracle" and row["State"]["Running"]]
    for role, binary in workers.items():
        if role in running:
            processes = docker("top", rows[role]["Id"], "-eo", "pid,args")
            if re.search(r"\b" + binary + r"\b", processes):
                raise ValueError(f"The test server is partly stopped but {binary} is still active. "
                                 "Studio needs its workers to finish shutting down before restarting.")
    stop_started(rows, running)


@contextlib.contextmanager
def active_server(env, *, keep_running, emit, login_only=False):
    require_docker()
    driver, folder, _, _, _, _ = container_set(env)
    lock = driver.REPO / "StarWarsGalaxies"
    started = []
    with driver.operation_lock(lock):
        _, _, rows, state, stage, _ = container_set(env)
        project = folder.parent.name
        emit({"event": "test_server", "state": state, "project": project})
        if state == "Needs startup":
            emit({"event": "test_server", "state": "Finishing shutdown", "project": project})
            finish_incomplete_shutdown(rows)
            _, _, rows, state, stage, _ = container_set(env)
            if state != "Stopped":
                raise ValueError("The test server did not finish shutting down.")
        if state == "Stopped":
            try:
                emit({"event": "test_server", "state": "Preparing", "project": project})
                prepare_restart(driver, folder, rows, stage)
                started = [role for role in rows if role != "oracle"]
                rows = recreate_games(env, folder, rows)
                emit({"event": "test_server", "state": "Loading", "project": project})
                wait_for_login(rows, project)
                driver.fixture(folder)
                if login_only:
                    wait_for_login_hosts(driver, folder, rows["central"]["Id"], env["bindings"])
                else:
                    wait_for_preload(driver, folder)
                emit({"event": "test_server", "state": "Ready", "project": project})
            except BaseException:
                if started:
                    _, _, current, _, _, _ = container_set(env, during_start=True)
                    stop_started(current, [role for role in started if role in current and current[role]["State"]["Running"]])
                raise
        else:
            driver.fixture(folder)
            if login_only:
                wait_for_login_hosts(driver, folder, rows["central"]["Id"], env["bindings"])
    try:
        yield
    finally:
        if started and not keep_running:
            with driver.operation_lock(lock):
                stop_started(rows, started)
                emit({"event": "test_server", "state": "Stopped", "project": project})
