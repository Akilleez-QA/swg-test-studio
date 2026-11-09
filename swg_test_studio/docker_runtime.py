"""Docker operations restricted to a registered SWG test server."""
import contextlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from .setup import available_setups, checked_setup
from .store import read_json


def docker(*args, timeout=60):
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
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


def container_set(env):
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
    if set(rows) != expected:
        raise ValueError("This Docker test server is incomplete. Ask the test server maintainer to prepare it.")
    driver.validate(rows["oracle"], root, volume)
    if rows["oracle"]["State"].get("Running") is not True:
        raise ValueError("The test database is stopped. Start it before starting the test server.")
    state = {row["State"]["Status"] for role, row in rows.items() if role != "oracle"}
    if state == {"running"}:
        status = "Running"
    elif state <= {"created", "exited"}:
        status = "Stopped"
    else:
        raise ValueError("This Docker test server is partly started. Ask its maintainer to check it.")
    return driver, folder, rows, status, stage, roster


def list_servers(workspace):
    require_docker()
    registered = available_setups(workspace)
    servers = []
    for project, env in registered.items():
        try:
            _, _, _, state, stage, roster = container_set(env)
        except (OSError, RuntimeError, ValueError, KeyError, ImportError):
            continue
        servers.append({"id": project, "name": env["name"], "state": state,
                        "characters": sum(roster.values()), "recording": bool(stage.get("test_studio_recording"))})
    if not servers:
        raise ValueError("No verified Docker test server is available for this source. "
                         "Ask the test server maintainer to check the installation.")
    return sorted(servers, key=lambda server: (server["state"] != "Running", server["name"]))


def wait_for_login(rows, project):
    login = rows["login"]["Id"]
    since = docker("inspect", "--format", "{{.State.StartedAt}}", login).strip()
    pattern = re.compile(r"Cluster " + re.escape(project) + r" is (ready|not ready) for players\.")
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        states = pattern.findall(docker("logs", "--since", since, login))
        if states and states[-1] == "ready":
            return
        time.sleep(3)
    raise ValueError("The Docker test server started, but login did not become ready in four minutes.")


def stop_started(rows, started):
    # Do not stop any service that was already running when Studio began.
    for role in ("central", "taskmanager"):
        if role in started:
            docker("stop", "--time", "90", rows[role]["Id"], timeout=110)
    remaining = [rows[role]["Id"] for role in started if role not in ("central", "taskmanager")]
    if remaining:
        docker("stop", "--time", "90", *remaining, timeout=120)


@contextlib.contextmanager
def active_server(env, *, keep_running, emit):
    require_docker()
    driver, folder, _, _, _, _ = container_set(env)
    lock = driver.REPO / "StarWarsGalaxies"
    started = []
    with driver.operation_lock(lock):
        _, _, rows, state, _, _ = container_set(env)
        project = folder.parent.name
        emit({"event": "test_server", "state": state, "project": project})
        if state == "Stopped":
            try:
                # Role containers were fully identified above. No Compose recreation or image pull.
                for role in ("log", "taskmanager", "database", "chat", "local_chat", "planet", "game",
                             "connection", "login", "metrics", "commodities", "central"):
                    started.append(role)
                    docker("start", rows[role]["Id"])
                wait_for_login(rows, project)
                driver.fixture(folder)
            except BaseException:
                stop_started(rows, started)
                raise
        else:
            driver.fixture(folder)
    try:
        yield
    finally:
        if started and not keep_running:
            with driver.operation_lock(lock):
                stop_started(rows, started)
                emit({"event": "test_server", "state": "Stopped", "project": project})
