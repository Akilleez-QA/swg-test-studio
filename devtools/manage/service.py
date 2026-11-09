"""Local management API. No web listener, shell strings, or arbitrary commands.

The CLI and a future authenticated UI can share Manager.plan/execute and the
versioned event stream. All mutating callers must hold operation_lock.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "devtools/docker"))
from zones import available_zones, cfg_zones, save_zones, select_zones, validate_zones
from configure import NODES
from multiserver_scenario import NAME as CROWDED_SCENARIO, high_configs, expected_workers
sys.path.insert(0, str(REPO / "devtools/zones"))
from capacity import load_catalog, load_policy, preview as capacity_preview, content_inventory
from instance_definitions import definitions as zone_instance_definitions
from observe import collect as collect_capacity_observation, report as capacity_status
import runtime_policy
import retirement_inventory
import instance_maintenance
import stage7_canonical_runtime
import docker_storage

START = ("log", "metrics", "login", "central", "connection", "database",
         "commodities", "planet", "game", "chat", "taskmanager")
# Central must be gone before any workers, otherwise it schedules replacements.
STOP = ("central", "taskmanager", "connection", "login", "planet", "game",
        "chat", "commodities", "database", "metrics", "log")
ORACLE = "starwarsgalaxies-oracle-1"
ORACLE_STORAGE = {
    "gvenzl/oracle-xe:11.2.0.2-slim-faststart":
        ("starwarsgalaxies_oracle_data", "/u01/app/oracle/oradata"),
    "gvenzl/oracle-free:23.26.3-slim-faststart":
        ("starwarsgalaxies_oracle26_data", "/opt/oracle/oradata"),
}


class ManagementError(RuntimeError):
    pass


def verified_retirement_release(release):
    """Require the Stage 7 acceptance record before enabling live retirement."""
    if (release.get("release_stage") != 7 or not re.fullmatch(
            r"[a-f0-9]{64}", release.get("overlay_manifest_sha256", ""))):
        raise ManagementError("Package the verified Stage 7 ELF64 release before enabling retirement")


@dataclass
class Request:
    """Allowlisted input shape for a future local UI adapter."""
    command: str
    operation: str = None
    name: str = None
    target: str = None
    files: list = field(default_factory=list)
    configure: bool = False
    with_oracle: bool = False
    growth_percent: int = 50
    maximum_instances: int = 4
    ord_maximum_instances: int = 4
    ord_capacity: int = 50
    public_world_capacity: int = 1024
    rryatt_capacity: int = 80
    rryatt_maximum_instances: int = 8
    rryatt_growth_percent: int = 75
    test_volumes: list = field(default_factory=list)
    images: bool = False
    build_cache: bool = False
    max_test_databases: int = None
    test_budget_gib: int = None
    minimum_free_gib: int = None
    cache_budget_gib: int = None
    cache_age_hours: int = None
    protect_test_projects: list = field(default_factory=list)
    unprotect_test_projects: list = field(default_factory=list)


@contextmanager
def operation_lock(deployment):
    import fcntl
    deployment.mkdir(parents=True, exist_ok=True)
    with (deployment / "management.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ManagementError("Another management operation is running. Wait for it to finish.") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def update_zone_config(text, selected, game=False):
    """Touch only existing zone/load keys, preserving addresses and other options."""
    section = ""
    written = False
    result = []
    for line in text.splitlines():
        if line.startswith("["):
            section = line.strip()
        if section == "[CentralServer]" and line.startswith("startPlanet="):
            if not written:
                result.extend("startPlanet=" + zone for zone in selected)
                written = True
            continue
        if game and section == "[TaskManager]" and line.startswith("maximumLoad="):
            crowded = f"[ClusterScenario]\nname={CROWDED_SCENARIO}\n" in text
            required = sum(expected_workers(selected).values()) if crowded else len(selected)
            line = "maximumLoad=" + str(max(3, required + 1))
        result.append(line)
    if not written:
        raise ManagementError("Missing startPlanet entries; regenerate the deployment before applying zones")
    return "\n".join(result) + "\n"


class Manager:
    def __init__(self, repo=REPO, emit=None, timeout=600):
        self.repo = Path(repo)
        self.deployment = self.repo / "StarWarsGalaxies"
        self.emit = emit or (lambda *args, **kwargs: None)
        self.timeout = timeout
        self.log = None
        self.profile = self.runtime_profile()
        self.env = dict(os.environ, WG_RUNTIME_IMAGE=self.profile["runtime_image"])

    def chat_sidecar_enabled(self):
        if self.profile["override"] != "release64.compose.json":
            return False
        compose = json.loads((self.deployment / "release64.compose.json").read_text())
        return "local_chat" in compose.get("services", {})

    def start_services(self):
        if not self.chat_sidecar_enabled():
            return START
        return START[:-1] + ("local_chat",) + START[-1:]

    def stop_services(self):
        if not self.chat_sidecar_enabled():
            return STOP
        index = STOP.index("chat") + 1
        return STOP[:index] + ("local_chat",) + STOP[index:]

    def start_service_command(self, role):
        args = ["up", "-d", "--no-deps", "--no-build"]
        if role == "local_chat":
            # Its network namespace points at the current chat container.
            args.append("--force-recreate")
        return self.compose(*args, role)

    def runtime_profile(self):
        path = self.deployment / "active-compose.json"
        if not path.is_file():
            return {"override": "diagnostic.compose.json",
                    "runtime_image": "starwarsgalaxies/native32:cluster-services"}
        profile = json.loads(path.read_text())
        if (not isinstance(profile, dict) or set(profile) != {"override", "runtime_image"}
                or profile["override"] != "release64.compose.json"
                or not isinstance(profile["runtime_image"], str)
                or not re.fullmatch(r"starwarsgalaxies/native64:[a-zA-Z0-9_.-]+",
                                    profile["runtime_image"])):
            raise ManagementError("Invalid active-compose.json release profile")
        return profile

    def settings(self):
        # Defaults match the recovered host. All are replaceable in this ignored
        # local file; no path is injected into original game source/config.
        settings = {
            "build_root": "/tmp/whitengold-native-config32",
            "source_root": "/tmp/whitengold-recovery-native/src",
            "install_root": "/tmp/whitengold-native-dev32",
            "oracle_home": "/tmp/whitengold-oracle10home",
            "work_root": "/tmp/StarWarsGalaxies/management-builds",
            "jdk32": "/tmp/StarWarsGalaxies/java/zulu8.96.0.205-ca-jdk8.0.504-linux_i686",
            "jobs": 4,
        }
        path = self.deployment / "management.json"
        if path.exists():
            custom = json.loads(path.read_text())
            if not isinstance(custom, dict) or set(custom) - set(settings):
                raise ManagementError("management.json contains unsupported settings")
            settings.update(custom)
        if not isinstance(settings["jobs"], int) or not 1 <= settings["jobs"] <= 64:
            raise ManagementError("jobs must be an integer between 1 and 64")
        for name, value in settings.items():
            if name == "jobs":
                continue
            if not isinstance(value, str):
                raise ManagementError(f"{name} must be a directory string")
            path = Path(value)
            if not path.is_absolute() or str(path.resolve()).startswith("/mnt/") or path.resolve() == Path("/"):
                raise ManagementError(f"{name} must be an absolute Linux-native directory")
        return settings

    def capabilities(self):
        return {"schema_version": 1, "commands": ["start", "stop", "restart", "status", "check", "zones", "zone", "capacity", "storage", "scenario", "build", "deploy", "settings"],
                "storage_actions": ["status", "policy", "cleanup"],
                "capacity_actions": ["catalog", "definitions", "preview", "status", "runtime", "falcon-enable", "falcon-disable", "falcon-instances", "npe-instances", "instance-schema"],
                "capacity_runtime_control": True,
                "zone_actions": ["enable", "disable", "start", "stop", "restart", "apply"],
                "build_targets": ["native", "scripts", "assets", "images"],
                "deploy_targets": ["scripts", "assets", "images"],
                "zone_live_change_effect": "game_cluster_restart",
                "stop_order": list(self.stop_services()), "oracle_stop_requires_explicit_option": True,
                "preview_option": "--dry-run", "structured_output": "--json (JSON Lines)",
                "authentication": "local OS permissions; no network listener"}

    def compose(self, *args):
        if self.profile["override"] == "release64.compose.json":
            return ["docker", "compose", "-p", "starwarsgalaxies", "-f",
                    str(self.deployment / "release64.compose.json"), *args]
        return ["docker", "compose", "-p", "starwarsgalaxies", "-f", str(self.deployment / "compose.json"),
                "-f", str(self.deployment / self.profile["override"]), *args]

    def command(self, argv, *, capture=False, tolerate=False):
        argv = list(map(str, argv))
        if capture:
            result = subprocess.run(argv, cwd=self.repo, env=self.env, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode and not tolerate:
                raise ManagementError(f"{argv[0]} query failed (exit {result.returncode}); check Docker/WSL availability")
            return result
        self.emit("progress", message=f"Running {Path(argv[0]).name}; details: {self.log}")
        with self.log.open("a") as output:
            output.write("\n" + json.dumps(argv) + "\n")
            output.flush()
            child = subprocess.Popen(argv, cwd=self.repo, env=self.env, stdout=output, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            try:
                while True:
                    try:
                        code = child.wait(timeout=20)
                        break
                    except subprocess.TimeoutExpired:
                        self.emit("progress", message=f"Still working; details: {self.log}")
            except BaseException:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                raise
        if code and not tolerate:
            raise ManagementError(f"Command failed (exit {code}); see {self.log}. Later steps were not run.")
        return code

    def zones(self):
        selected = select_zones(self.deployment)
        return {"zones": [{"number": i, "name": zone, "enabled": zone in selected}
                          for i, zone in enumerate(available_zones(), 1)],
                "live_apply_effect": "game_cluster_restart", "oracle_stopped": False}

    def capacity(self, operation="preview"):
        if operation == "definitions":
            return zone_instance_definitions(self.repo)
        if operation == "retirement":
            source = retirement_inventory.inventory()
            selected = set(select_zones(self.deployment))
            scenes = source["scenes"]
            canonical = {row["definition"] for row in scenes}
            reviewed = {row["definition"] for row in scenes if row["retirement"] == "reviewed"}
            automatic = ("space_ord_mantell", "kashyyyk_rryatt_trail")
            if (len(scenes) != 46 or len(canonical) != source["canonical_definitions"] or
                    reviewed != set(automatic) | {"space_npe_falcon"}):
                raise ManagementError("Retirement preview requires complete reviewed scene coverage")
            config = self.deployment / "config/central.cfg"
            enabled = []
            section = ""
            if config.exists():
                for line in config.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("[") and line.endswith("]"):
                        section = line
                    elif section == "[CentralServer]" and line.startswith("capacityAutomaticRetirementEnabled="):
                        value = line.split("=", 1)[1].strip().lower()
                        if value not in ("true", "false", "1", "0"):
                            raise ManagementError("Invalid automatic retirement config value")
                        enabled.append(value in ("true", "1"))
            if len(set(enabled)) > 1:
                raise ManagementError("Conflicting automatic retirement config values")
            selected_definitions = {row["definition"] for row in scenes if row["scene"] in selected}
            return {"schema_version": 1, "mode": "retirement_preview", "live_state_checked": False,
                    "runtime_control_available": False, "apply_effect": "game_cluster_restart",
                    "automatic_retirement_configured": enabled[-1] if enabled else False,
                    "config_present": config.exists(), "scene_coverage": len(scenes),
                    "canonical_definitions": len(canonical), "hosted_content_types": len(source["hosted_content"]),
                    "automatic_eligible": [{"definition": name, "selected": name in selected_definitions,
                                            "unit": "whole_linked_world" if name == "kashyyyk_rryatt_trail" else "world"}
                                           for name in automatic],
                    "authored_timer": ["space_npe_falcon"],
                    "pinned_definitions": sorted(canonical - reviewed)}
        if operation == "runtime":
            selected = select_zones(self.deployment)
            state = runtime_policy.load(self.deployment, selected)
            return {**runtime_policy.report(state, selected), "policy": state,
                    "live_state_checked": False, "apply_effect": "game_cluster_restart"}
        if operation not in ("catalog", "preview", "status"):
            raise ManagementError("Capacity supports read-only catalog, preview, status, runtime and retirement only")
        catalog = load_catalog()
        if operation == "catalog":
            return {**catalog, "content": content_inventory(self.repo, catalog),
                    "runtime_control_available": False}
        policy = load_policy(self.deployment / "zone-capacity.json", catalog)
        proposal = capacity_preview(select_zones(self.deployment), catalog, policy)
        if operation == "status":
            return capacity_status(collect_capacity_observation(), proposal)
        return proposal

    def status(self):
        rows = self.command(["docker", "ps", "-a", "--filter",
                             "label=com.docker.compose.project=starwarsgalaxies",
                             "--format", "{{.Label \"com.docker.compose.service\"}}|{{.State}}"], capture=True).stdout
        states = dict(line.split("|", 1) for line in rows.splitlines() if "|" in line)
        return {"scenario": self.current_scenario(),
                "services": {role: states.get(role, "missing") for role in (*self.start_services(), "oracle")},
                "readiness_checked": False, "hint": "Use check for native-process and zone readiness."}

    def current_scenario(self):
        path = self.deployment / "scenarios/active.json"
        if not path.exists():
            return "low"
        state = json.loads(path.read_text())
        if state != {"name": CROWDED_SCENARIO}:
            raise ManagementError("Invalid active scenario state")
        return CROWDED_SCENARIO

    def scenario_status(self):
        selected = select_zones(self.deployment)
        return {"active": self.current_scenario(), "selected_zones": selected,
                "crowded_workers_if_selected": sum(expected_workers(selected).values()),
                "low_workers_if_selected": len(selected),
                "target_connections": 20000, "capacity_validated": False}

    def scenario_manifest(self):
        path = self.deployment / "scenarios" / CROWDED_SCENARIO / "manifest.json"
        if not path.is_file():
            raise ManagementError("Prepare the crowded scenario table and local planet image first")
        manifest = json.loads(path.read_text())
        if manifest.get("scenario") != CROWDED_SCENARIO or manifest.get("table") != "datatables/planet_server/preload_list_crowded20000.iff":
            raise ManagementError("Invalid crowded scenario manifest")
        return manifest

    def scenario_preflight(self, target):
        if self.profile["override"] != "release64.compose.json":
            raise ManagementError("Scenario switching requires the ELF64 release profile")
        if target == CROWDED_SCENARIO:
            manifest = self.scenario_manifest()
            image = manifest.get("planet_image")
            if not isinstance(image, str) or not re.fullmatch(r"starwarsgalaxies/planet:[a-zA-Z0-9_.-]+", image):
                raise ManagementError("Invalid local scenario planet image")
            table = self.deployment / "scenarios" / CROWDED_SCENARIO / "preload_list_crowded20000.iff"
            import hashlib
            if not table.is_file() or hashlib.sha256(table.read_bytes()).hexdigest() != manifest.get("table_sha256"):
                raise ManagementError("Compiled scenario table changed; prepare it again")
            selected = select_zones(self.deployment)
            if not set(("naboo", "tatooine", "rori", "corellia")) <= set(selected):
                raise ManagementError("Crowded scenario requires Naboo, Tatooine, Rori and Corellia enabled")
            compose = json.loads((self.deployment / "release64.compose.json").read_text())
            if compose["services"]["planet"]["image"] != manifest.get("planet_base_image"):
                raise ManagementError("Current planet image differs from the scenario base; prepare again")
            game_image = manifest.get("game_image")
            if (not isinstance(game_image, str) or
                    not re.fullmatch(r"starwarsgalaxies/game:[a-zA-Z0-9_.-]+", game_image) or
                    compose["services"]["game"]["image"] != manifest.get("game_base_image")):
                raise ManagementError("Current game image differs from the scenario base; prepare again")
            path = "/opt/whitengold/data/sku.0/sys.server/compiled/game/" + manifest["table"]
            result = self.command(["docker", "run", "--rm", "--network", "none", "--entrypoint", "/bin/sh",
                                   image, "-c", 'sha256sum "$1" "$2"', "sh", path,
                                   "/opt/whitengold/launch-role"], capture=True)
            hashes = [line.split()[0] for line in result.stdout.splitlines()]
            if hashes != [manifest["table_sha256"], manifest.get("launcher_sha256")]:
                raise ManagementError("Scenario planet image contains a different table or launcher")
            crc_path = "/opt/whitengold/data/sku.0/sys.server/built/game/misc/object_template_crc_string_table.iff"
            wrappers = manifest.get("game_wrappers", {})
            shared = manifest.get("game_shared_templates", {})
            if len(wrappers) != 24 or len(shared) != 24:
                raise ManagementError("Scenario game overlay must contain 24 recovered wrappers and shared templates")
            wrapper_paths = ["/opt/whitengold/data/sku.0/sys.server/compiled/game/" + name
                             for name in sorted(wrappers)]
            shared_paths = ["/opt/whitengold/data/sku.0/sys.shared/compiled/game/" + name
                            for name in sorted(shared)]
            result = self.command(["docker", "run", "--rm", "--network", "none", "--entrypoint", "/bin/sh",
                                   game_image, "-c", 'sha256sum "$@"', "sh", crc_path,
                                   *wrapper_paths, *shared_paths], capture=True)
            hashes = [line.split()[0] for line in result.stdout.splitlines()]
            if hashes != [manifest.get("game_catalog_sha256"),
                          *(wrappers[name] for name in sorted(wrappers)),
                          *(shared[name] for name in sorted(shared))]:
                raise ManagementError("Scenario game image contains a different catalog or template")
        else:
            backup = self.deployment / "scenarios" / CROWDED_SCENARIO / "low-backup"
            for name in ("planet.cfg", "game.cfg", "login.cfg", "connection.cfg", "release64.compose.json"):
                if not (backup / name).is_file():
                    raise ManagementError(f"Cannot restore low scenario: missing saved {name}")

    def switch_scenario(self, target, selected):
        folder = self.deployment / "scenarios" / CROWDED_SCENARIO
        marker = self.deployment / "scenarios/active.json"
        planet = self.deployment / "config/planet.cfg"
        game = self.deployment / "config/game.cfg"
        login = self.deployment / "config/login.cfg"
        connection = self.deployment / "config/connection.cfg"
        compose_path = self.deployment / "release64.compose.json"
        backup = folder / "low-backup"
        self.require_stopped()
        if target == CROWDED_SCENARIO:
            backup.mkdir(parents=True, exist_ok=True)
            for source, name in ((planet, "planet.cfg"), (game, "game.cfg"),
                                 (login, "login.cfg"), (connection, "connection.cfg"),
                                 (compose_path, "release64.compose.json")):
                shutil.copy2(source, backup / name)
            high_planet, high_game, high_login, high_connection = high_configs(
                planet.read_text(), game.read_text(), login.read_text(), connection.read_text(), selected)
            high_compose = json.loads(compose_path.read_text())
            high_compose["services"]["planet"]["image"] = self.scenario_manifest()["planet_image"]
            high_compose["services"]["game"]["image"] = self.scenario_manifest()["game_image"]
            high_text = json.dumps(high_compose, indent=2) + "\n"
            review = folder / "high-profile"
            review.mkdir(exist_ok=True)
            for name, value in (("planet.cfg", high_planet), ("game.cfg", high_game),
                                ("login.cfg", high_login), ("connection.cfg", high_connection),
                                ("release64.compose.json", high_text)):
                (review / name).write_text(value)
            planet.write_text(high_planet)
            game.write_text(high_game)
            login.write_text(high_login)
            connection.write_text(high_connection)
            compose_path.write_text(high_text)
            atomic_json(marker, {"name": CROWDED_SCENARIO})
        else:
            for destination, name in ((planet, "planet.cfg"), (game, "game.cfg"),
                                      (login, "login.cfg"), (connection, "connection.cfg"),
                                      (compose_path, "release64.compose.json")):
                shutil.copy2(backup / name, destination)
            marker.unlink(missing_ok=True)

    def runtime_data(self):
        override = json.loads((self.deployment / "diagnostic.compose.json").read_text())
        roots = {item["source"] for service in override["services"].values()
                 for item in service.get("volumes", []) if isinstance(item, dict)
                 and item.get("target") == "/opt/whitengold/data"}
        if len(roots) != 1:
            raise ManagementError("Expected one shared staged-data root in diagnostic.compose.json")
        root = Path(roots.pop()).resolve()
        if not root.is_dir() or str(root).startswith("/mnt/"):
            raise ManagementError("Staged Linux data is missing or on Windows storage; restore it before starting")
        return root

    def preflight(self, selected):
        state = runtime_policy.load(self.deployment, selected)
        if runtime_policy.instances(state):
            if state and state.get("schema_version")==4:self.instance_preflight(require_npe=True,require_rryatt=True)
            else:self.instance_preflight(require_npe=runtime_policy.npe_instances(state))
        for name in ("compose.json", self.profile["override"], "runtime.cfg", "metricsAuthentication.cfg"):
            if not (self.deployment / name).is_file():
                raise ManagementError(f"Missing deployment file {name}; see StarWarsGalaxies/STARTUP.md")
        compose = json.loads((self.deployment / "compose.json").read_text())
        if compose.get("name") != "starwarsgalaxies":
            raise ManagementError("This manager controls only the canonical starwarsgalaxies project")
        oracle = compose.get("services", {}).get("oracle", {})
        storage = ORACLE_STORAGE.get(oracle.get("image"))
        if storage is None:
            raise ManagementError("Unsupported Oracle image in canonical Compose")
        volume = compose.get("volumes", {}).get("oracle_data", {})
        if (volume != {"name": storage[0], "external": True}
                or oracle.get("volumes") != ["oracle_data:" + storage[1]]):
            raise ManagementError("Oracle must use its matching external persistent volume")
        required = [f"sku.0/sys.shared/compiled/game/terrain/{zone}.trn" for zone in selected]
        required += ["sku.0/sys.server/compiled/game/script/base_class.class",
                     "sku.0/sys.server/compiled/game/object/planet/planet.iff",
                     "sku.0/sys.server/built/game/misc/object_template_crc_string_table.iff"]
        if self.profile["override"] == "release64.compose.json":
            override = json.loads((self.deployment / self.profile["override"]).read_text())
            if override.get("name") != "starwarsgalaxies":
                raise ManagementError("Invalid release64.compose.json project")
            if (override.get("services", {}).get("oracle") != oracle or
                    override.get("volumes", {}).get("oracle_data") != volume):
                raise ManagementError("Release profile Oracle storage differs from base Compose")
            if "local_chat" in override["services"]:
                sidecar = override["services"]["local_chat"]
                if (override["volumes"].get("chat_data") !=
                        {"name": "starwarsgalaxies_chat_data", "external": True}
                        or sidecar.get("network_mode") != "service:chat"
                        or sidecar.get("volumes") != [{"type": "volume", "source": "chat_data",
                                                      "target": "/var/lib/local-chat"}]
                        or override["services"]["chat"].get("image") !=
                        "starwarsgalaxies/chat:text-gated"):
                    raise ManagementError("Local ChatAPI sidecar has an invalid isolation or storage plan")
                self.command(["docker", "volume", "inspect", "starwarsgalaxies_chat_data"], capture=True)
            image = override["services"]["game"]["image"]
            self.command(["docker", "run", "--rm", "--network", "none", "--entrypoint", "/bin/sh",
                          image, "-c", 'for file do test -s "$file" || exit 1; done', "sh",
                          *("/opt/whitengold/data/" + name for name in required)], capture=True)
        else:
            data = self.runtime_data()
            for name in required:
                if not (data / name).is_file() or (data / name).stat().st_size == 0:
                    raise ManagementError(f"Required runtime input missing: {name}")
        # Validate all edits before shutdown; never discover malformed configs mid-stop.
        for role in START:
            update_zone_config((self.deployment / f"config/{role}.cfg").read_text(), selected, role == "game")

    def plan(self, args):
        action = args.command
        if action == "storage":
            return self.storage_plan(args)
        if type(getattr(args, "with_oracle", False)) is not bool or type(getattr(args, "configure", False)) is not bool:
            raise ManagementError("with_oracle and configure must be booleans")
        if action not in ("build", "deploy", "zone", "scenario", "capacity", "start", "stop", "restart", "check"):
            raise ManagementError(f"Unsupported operation: {action}")
        if action == "capacity":
            if args.operation == "instance-schema":
                self.instance_preflight(allow_schema_270=True)
                steps = [{"action": "preflight_docker"}]
                steps.extend({"action": "command", "argv": self.compose("stop", role)} for role in self.stop_services())
                steps += [{"action": "start_oracle"}, {"action": "instance_schema"}]
                return {"summary": "Stop ALL game services, export and verify the existing schema, then upgrade 270 to 271. Leave game services stopped for coordinated instance activation. Preserve Oracle storage and saved characters.",
                        "effects": {"game_services_restarted": False, "game_services_stopped": True, "oracle_stopped": False, "schema_upgraded": True}, "steps": steps}
            if args.operation in ("retirement-enable", "retirement-disable"):
                if self.profile["override"] != "release64.compose.json" or self.current_scenario() != "low":
                    raise ManagementError("Automatic retirement requires the ELF64 low scenario")
                selected = select_zones(self.deployment)
                old = runtime_policy.load(self.deployment, selected)
                if not old or old.get("schema_version") != 4:
                    raise ManagementError("Automatic retirement requires the existing linked Rryatt instance policy")
                state = dict(old, automatic_retirement=args.operation == "retirement-enable")
                capacity = runtime_policy.report(state, selected)
                self.instance_preflight(require_npe=True, require_rryatt=True,
                                        require_retirement=state["automatic_retirement"])
                self.preflight(selected)
                preview_compose = runtime_policy.mounts(json.loads((self.deployment / "release64.compose.json").read_text()), install=True)
                stage7_canonical_runtime.mounts(preview_compose, state["automatic_retirement"], NODES, install=True)
                steps = [{"action": "preflight_docker"}]
                steps.extend({"action": "command", "argv": self.compose("stop", role)} for role in self.stop_services())
                steps += [{"action": "start_oracle"},
                          {"action": "instance_prepare", "initialize": False, "state": state},
                          {"action": "capacity_policy", "state": state},
                          {"action": "apply_zones", "zones": selected},
                          {"action": "sync_release_config"}]
                steps.extend({"action": "command", "argv": self.start_service_command(role)} for role in self.start_services())
                steps.append({"action": "ready"})
                return {"summary": "Set automatic empty-world retirement " +
                        ("on" if state["automatic_retirement"] else "off") +
                        "; restart ALL game services and disconnect players. Preserve existing capacity budgets, Oracle and journals.",
                        "capacity": capacity,
                        "effects": {"game_services_restarted": True, "oracle_stopped": False}, "steps": steps}
            if args.operation not in ("falcon-enable", "falcon-disable", "falcon-instances", "npe-instances", "rryatt-instances"):
                raise ManagementError("Unsupported capacity mutation")
            if self.profile["override"] != "release64.compose.json" or self.current_scenario() != "low":
                raise ManagementError("Falcon growth requires the ELF64 low scenario")
            selected = select_zones(self.deployment)
            old = runtime_policy.load(self.deployment, selected)
            if runtime_policy.instances(old) and args.operation not in ("falcon-instances", "npe-instances", "rryatt-instances"):
                raise ManagementError("Canonical instance saves require the instance policy; reverting to suffixed worlds needs an offline migration")
            if runtime_policy.npe_instances(old) and args.operation not in ("npe-instances", "rryatt-instances"):
                raise ManagementError("Ord instance saves require the NPE instance policy; reverting needs an offline migration")
            if old and old.get("schema_version")==4 and args.operation!="rryatt-instances":
                raise ManagementError("Rryatt instance saves require the linked-set policy; reverting needs an offline migration")
            percent = getattr(args, "growth_percent", 50)
            if type(percent) is not int or not 1 <= percent <= 99:
                raise ManagementError("growth_percent must be an integer from 1 to 99")
            state = {"schema_version": 1, "mode": "falcon_growth" if args.operation == "falcon-enable" else "eager",
                     "growth_percent": percent, "epoch": old["epoch"] if old else uuid.uuid4().hex}
            if args.operation in ("falcon-instances", "npe-instances", "rryatt-instances"):
                state.update(schema_version=2, mode="falcon_instances", maximum_instances=getattr(args, "maximum_instances", 4))
                self.instance_preflight()
                if args.operation in ("npe-instances", "rryatt-instances"):
                    state.update(schema_version=3, mode="npe_instances", ord_maximum_instances=getattr(args, "ord_maximum_instances", 4),
                                 ord_capacity=getattr(args, "ord_capacity", 50), public_world_capacity=getattr(args, "public_world_capacity", 1024))
                    self.instance_preflight(require_npe=True)
                if args.operation=="rryatt-instances":
                    state.update(schema_version=4,rryatt_capacity=args.rryatt_capacity,rryatt_maximum_instances=args.rryatt_maximum_instances,rryatt_growth_percent=args.rryatt_growth_percent)
                    self.instance_preflight(require_npe=True,require_rryatt=True)
            runtime_policy.report(state, selected)
            self.preflight(selected)
            runtime_policy.mounts(json.loads((self.deployment / "release64.compose.json").read_text()), install=True)
            steps = [{"action": "preflight_docker"}]
            steps.extend({"action": "command", "argv": self.compose("stop", role)} for role in self.stop_services())
            if runtime_policy.instances(state):
                steps.append({"action": "start_oracle"})
                steps.append({"action": "instance_prepare", "initialize": not runtime_policy.instances(old), "state": state,
                              "initialize_admission": runtime_policy.npe_instances(state) and not runtime_policy.npe_instances(old)})
            steps += [{"action": "capacity_policy", "state": state}, {"action": "apply_zones", "zones": selected},
                      {"action": "sync_release_config"}, {"action": "start_oracle"}]
            steps.extend({"action": "command", "argv": self.start_service_command(role)} for role in self.start_services())
            steps.append({"action": "ready"})
            return {"summary": "Apply " + state["mode"] + "; restart ALL game services and disconnect players. Preserve Oracle and journal records.",
                    "capacity": runtime_policy.report(state, selected),
                    "effects": {"game_services_restarted": True, "oracle_stopped": False}, "steps": steps}
        if action == "build":
            if args.target not in ("native", "scripts", "assets", "images"):
                raise ManagementError("Unsupported build target")
            return self.build_plan(args)
        if action == "deploy":
            if args.target not in ("scripts", "assets", "images"):
                raise ManagementError("Unsupported deployment target")
            return self.deploy_plan(args.target)
        if action == "scenario":
            target = args.name
            if target not in ("low", CROWDED_SCENARIO):
                raise ManagementError("Scenario must be low or crowded20000")
            current = self.current_scenario()
            if target == current:
                return {"summary": f"Scenario {target} is already active; no services change.",
                        "effects": {"game_services_restarted": False, "oracle_stopped": False}, "steps": []}
            selected = select_zones(self.deployment)
            if runtime_policy.instances(runtime_policy.load(self.deployment, selected)):
                raise ManagementError("Canonical instance hosting currently requires the low scenario")
            self.preflight(selected)
            self.scenario_preflight(target)
            steps = [{"action": "preflight_docker"}, {"action": "scenario_preflight", "target": target}]
            steps.extend({"action": "command", "argv": self.compose("stop", role)} for role in self.stop_services())
            steps += [{"action": "switch_scenario", "target": target, "zones": selected},
                      {"action": "apply_zones", "zones": selected},
                      {"action": "sync_release_config"}, {"action": "start_oracle"}]
            steps.extend({"action": "command", "argv": self.start_service_command(role)}
                         for role in self.start_services())
            steps.append({"action": "ready"})
            return {"summary": f"Switch to {target}; restart ALL game services and disconnect players. Oracle remains running.",
                    "effects": {"game_services_restarted": True, "oracle_stopped": False}, "steps": steps}
        selected = select_zones(self.deployment) if action in ("zone", "start", "restart") else []
        steps = []
        effects = {"game_services_restarted": False, "oracle_stopped": False}
        if action == "zone":
            operation, name = args.operation, args.name
            if name is not None and not isinstance(name, str):
                raise ManagementError("Zone name/catalog number must be a string")
            if operation not in ("enable", "disable", "start", "stop", "restart", "apply"):
                raise ManagementError("Unsupported zone operation")
            if operation == "apply":
                if name:
                    raise ManagementError("zone apply does not take a zone name")
            else:
                names = available_zones()
                if name and name.isdigit() and 1 <= int(name) <= len(names):
                    name = names[int(name) - 1]
                if name == "all" and operation in ("enable", "start"):
                    selected = list(dict.fromkeys(selected + names))
                else:
                    validate_zones([name])
                    if operation in ("enable", "start") and name not in selected:
                        selected.append(name)
                    elif operation in ("disable", "stop"):
                        selected = [zone for zone in selected if zone != name]
                    elif operation == "restart" and name not in selected:
                        raise ManagementError("Cannot restart a disabled zone; use zone start")
                    validate_zones(selected)
            if operation in ("enable", "disable"):
                return {"summary": "Save zone selection for the next start/apply; running services are unchanged.",
                        "effects": effects, "steps": [{"action": "save_zones", "zones": selected}]}
            action = "restart"
        if action in ("start", "restart"):
            self.preflight(selected)
            steps.append({"action": "preflight_docker"})
        if action in ("stop", "restart"):
            steps.extend({"action": "command", "argv": self.compose("stop", role)} for role in self.stop_services())
            if getattr(args, "with_oracle", False):
                steps.append({"action": "stop_oracle"})
                effects["oracle_stopped"] = True
        if action in ("start", "restart"):
            if action == "start" and selected != cfg_zones(self.deployment / "config/central.cfg"):
                steps.append({"action": "require_stopped"})
            if runtime_policy.instances(runtime_policy.load(self.deployment, selected)):
                steps.append({"action": "start_oracle"})
                steps.append({"action": "instance_prepare", "initialize": False})
            steps.append({"action": "apply_zones", "zones": selected})
            if self.profile["override"] == "release64.compose.json":
                steps.append({"action": "sync_release_config"})
            if not any(step["action"] == "start_oracle" for step in steps):
                steps.append({"action": "start_oracle"})
            steps.extend({"action": "command", "argv": self.start_service_command(role)}
                         for role in self.start_services())
            steps.append({"action": "ready"})
            effects["game_services_restarted"] = action == "restart"
        if action == "check":
            steps.append({"action": "ready"})
        summary = {"start": "Start selected zones and wait for readiness; reuse the existing Oracle database.",
                   "stop": "Stop CentralServer FIRST, then the other game roles.",
                   "restart": "Restart ALL game services to apply the selected zones; players will disconnect.",
                   "check": "Check native processes, ports, Oracle storage and all selected zones."}[action]
        if not effects["oracle_stopped"]:
            summary += " Oracle is not stopped."
        return {"summary": summary, "effects": effects, "steps": steps}

    def oracle(self):
        result = self.command(["docker", "inspect", ORACLE], capture=True)
        item = json.loads(result.stdout)[0]
        storage = ORACLE_STORAGE.get(item["Config"]["Image"])
        if storage is None:
            raise ManagementError("Existing Oracle container uses an unsupported image")
        volume_name, mount_path = storage
        if not any(m.get("Type") == "volume" and m.get("Name") == volume_name
                   and m.get("Destination") == mount_path for m in item["Mounts"]):
            raise ManagementError("Existing Oracle container does not have the required persistent volume")
        return item

    def require_stopped(self):
        states = self.status()["services"]
        if any(states[role] == "running" for role in self.start_services()):
            raise ManagementError("Game services are running. Use restart or zone apply to apply the saved selection.")

    def instance_preflight(self, allow_schema_270=False, require_npe=False,require_rryatt=False,
                           require_retirement=False):
        """Refuse a partial schema/protocol cutover before stopping services."""
        if self.profile["override"] != "release64.compose.json" or self.current_scenario() != "low":
            raise ManagementError("Canonical instances require the ELF64 low scenario")
        runtime = (self.deployment / "runtime.cfg").read_text()
        if re.findall(r"(?m)^expectedDBVersion=(\d+)[ \t]*$", runtime) != (["270"] if allow_schema_270 else ["271"]):
            raise ManagementError("Stage the coordinated schema 271/native release before enabling canonical instances")
        compose = json.loads((self.deployment / "release64.compose.json").read_text())
        release_path = self.deployment / "instance-release.json"
        if not release_path.is_file():
            raise ManagementError("Package the verified coordinated instance release before cutover")
        release = json.loads(release_path.read_text())
        if (release.get("schema_version") != 1 or release.get("database_version") != 271 or
                set(release.get("roles", {})) != set(START)):
            raise ManagementError("Invalid coordinated instance release record")
        tags = []
        expected_ids = []
        for role in START:
            entry = release["roles"][role]
            if entry.get("image") != compose["services"][role]["image"] or not re.fullmatch(r"sha256:[a-f0-9]{64}", entry.get("image_id", "")):
                raise ManagementError("Instance release image selection changed: " + role)
            tags.append(entry["image"])
            expected_ids.append(entry["image_id"])
        actual = self.command(["docker", "image", "inspect", *tags, "--format", "{{.Id}}"], capture=True).stdout.splitlines()
        if actual != expected_ids:
            raise ManagementError("Instance role image IDs differ from the verified coordinated release")
        image = compose["services"]["central"]["image"]
        result = self.command(["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
                               "--entrypoint", "/opt/whitengold/bin/instance-journal", image, "--capabilities"], capture=True)
        old_capabilities = "instance-journal=1 schema=271 stopped-generation-resume=1 stopped-login-loads=1"
        capabilities = result.stdout.strip()
        npe_capabilities = old_capabilities + " npe-group-transfers=1 family-login-admission=1"
        rryatt_capabilities=npe_capabilities+" rryatt-linked-instances=1"
        if capabilities not in (old_capabilities,npe_capabilities,rryatt_capabilities) or (require_npe and capabilities not in (npe_capabilities,rryatt_capabilities)) or (require_rryatt and capabilities!=rryatt_capabilities):
            raise ManagementError("Central image lacks the verified instance maintenance utility")
        if require_retirement:
            verified_retirement_release(release)
            probe = self.command(["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
                                  "--entrypoint", "/bin/sh", image, "-c",
                                  'grep -aFq "$1" "$2"', "sh", "capacityAutomaticRetirementEnabled",
                                  "/opt/whitengold/bin/CentralServer"], capture=True, tolerate=True)
            if probe.returncode:
                raise ManagementError("Canonical Central image lacks automatic retirement; package the verified ELF64 release before activation")

    def prepare_instances(self, initialize=False, state=None, initialize_admission=False):
        """All mutating callers hold operation_lock; preserve every durable ID."""
        compose = runtime_policy.mounts(json.loads((self.deployment / "release64.compose.json").read_text()), install=initialize)
        volume = runtime_policy.JOURNALS["central"][1]
        def inspect_matching(filter_value):
            result = self.command(["docker", "ps", "-aq", "--filter", filter_value], capture=True)
            ids = result.stdout.split()
            return json.loads(self.command(["docker", "inspect", *ids], capture=True).stdout) if ids else []
        containers = inspect_matching("label=com.docker.compose.project=starwarsgalaxies")
        attached = [item for row in runtime_policy.JOURNALS.values() for item in inspect_matching("volume=" + row[1])]
        proof = instance_maintenance.prove_stopped(compose, containers, attached, initialize=initialize)
        oracle = self.oracle()
        if oracle["Config"]["Image"] != "gvenzl/oracle-free:23.26.3-slim-faststart" or not oracle["State"]["Running"]:
            raise ManagementError("Start the existing Oracle26 database before journal reconciliation")
        proof["database_idle"] = instance_maintenance.database_idle(ORACLE, self.log.parent / "login-stop-oracle.json")
        atomic_json(self.log.parent / "instance-stop-proof.json", proof)
        image = compose["services"]["central"]["image"]
        state = state or runtime_policy.load(self.deployment, select_zones(self.deployment))
        if initialize:
            # First activation may provision this journal volume only. Existing
            # state is opened strictly; missing state is never repaired on start.
            self.command(["docker", "volume", "create", "--name", volume], capture=True)
            exists = self.command(["docker", "run", "--rm", "--pull", "never", "--network", "none",
                                   "--volume", volume + ":/capacity-journal:ro", "--entrypoint", "/bin/sh", image,
                                   "-c", 'test -e "$1" || test -L "$1"', "sh", runtime_policy.INSTANCE_ROOT], tolerate=True) == 0
            if not exists:
                self.command(instance_maintenance.command(image, initialize=True))
        else:
            self.command(["docker", "volume", "inspect", volume], capture=True)
        self.command(["docker", "volume", "inspect", runtime_policy.JOURNALS["database"][1]], capture=True)
        # Keep receipts in the operation log. Any error leaves workers stopped.
        self.command(instance_maintenance.login_command(image))
        self.command(instance_maintenance.command(image, state=state))
        if runtime_policy.automatic_retirement(state):
            self.command(stage7_canonical_runtime.initialize_command(image, NODES))
        if runtime_policy.npe_instances(state):
            if state.get("schema_version")==4:self.instance_preflight(require_npe=True,require_rryatt=True)
            else:self.instance_preflight(require_npe=True)
            for family_logins, root in ((False, runtime_policy.ADMISSION_ROOT), (True, "/capacity-journal/family-logins")):
                if initialize_admission:
                    exists = self.command(["docker", "run", "--rm", "--pull", "never", "--network", "none",
                                           "--volume", volume + ":/capacity-journal:ro", "--entrypoint", "/bin/sh", image,
                                           "-c", 'test -e "$1" || test -L "$1"', "sh", root], tolerate=True) == 0
                    if not exists:
                        self.command(instance_maintenance.admission_command(image, initialize=True, family_logins=family_logins))
                self.command(instance_maintenance.admission_command(image, family_logins=family_logins))

    def apply_zones(self, selected):
        state = runtime_policy.load(self.deployment, selected)
        paths = [self.deployment / f"config/{role}.cfg" for role in START]
        edited = {p: stage7_canonical_runtime.config(
                    runtime_policy.config(update_zone_config(p.read_text(), selected, p.stem == "game"), p.stem, state, selected),
                    p.stem, runtime_policy.automatic_retirement(state), NODES)
                  for p in paths}
        changed = [p for p in paths if p.read_text() != edited[p]]
        if changed:
            self.require_stopped()
            backup = self.log.parent / "config-before"
            backup.mkdir()
            for path in changed:
                shutil.copy2(path, backup / path.name)
                path.write_text(edited[path])
        save_zones(self.deployment, selected)

    def ready(self):
        checks = [self.repo / "devtools/docker/check_diagnostic_cluster.py",
                  self.repo / "devtools/docker/check_zones.py"]
        state = runtime_policy.load(self.deployment, select_zones(self.deployment))
        if runtime_policy.automatic_retirement(state):
            checks[1] = self.repo / "devtools/docker/check_zones_stage7.py"
        if self.current_scenario() == CROWDED_SCENARIO:
            checks.append(self.repo / "devtools/docker/check_multiserver_scenario.py")
        deadline = time.monotonic() + self.timeout
        while True:
            process_ok = self.command([sys.executable, checks[0], "--wait-seconds", "0"], tolerate=True) == 0
            zones_ok = process_ok and self.command([sys.executable, checks[1]], tolerate=True) == 0
            scenario_ok = zones_ok and (len(checks) == 2 or
                                        self.command([sys.executable, checks[2]], tolerate=True) == 0)
            if scenario_ok:
                return
            if time.monotonic() >= deadline:
                raise ManagementError(f"Readiness timed out. Containers were left available for diagnosis; see {self.log}")
            self.emit("progress", message="Waiting for native services and selected zones to finish loading...")
            time.sleep(5)

    def execute(self, plan):
        run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        folder = self.deployment / "logs/management" / run
        folder.mkdir(parents=True)
        self.log = folder / "operation.log"
        atomic_json(folder / "plan.json", plan)
        self.emit("started", operation_id=run, message=f"Operation {run}; log: {self.log}")
        try:
            for step in plan["steps"]:
                action = step["action"]
                if action == "storage_cleanup":
                    deleted = docker_storage.execute_cleanup(self.repo, step["selection"], folder/"storage", command=self.command)
                    self.emit("progress", message=f"Removed {len(deleted['test_volumes'])} test databases and {len(deleted['image_ids'])} unused SWG images; reports preserved.")
                elif action == "storage_policy":
                    atomic_json(self.deployment/"storage-policy.json", docker_storage.validate_policy(step["policy"]))
                elif action == "command":
                    self.command(step["argv"])
                elif action == "preflight_docker":
                    self.command(self.compose("config", "--quiet"))
                    self.oracle()  # Refuse to initialize a replacement database.
                    override = json.loads((self.deployment / self.profile["override"]).read_text())
                    for service in override["services"].values():
                        self.command(["docker", "image", "inspect", service["image"]], capture=True)
                elif action == "start_oracle":
                    if not self.oracle()["State"]["Running"]:
                        self.command(["docker", "start", ORACLE])
                    deadline = time.monotonic() + self.timeout
                    while self.command(["docker", "exec", ORACLE, "healthcheck.sh"], tolerate=True):
                        if time.monotonic() >= deadline:
                            raise ManagementError("Oracle did not become ready; game services were not started")
                        time.sleep(5)
                elif action == "stop_oracle":
                    self.oracle()
                    self.command(["docker", "stop", "--time", "120", ORACLE])
                elif action == "save_zones":
                    save_zones(self.deployment, step["zones"])
                elif action == "apply_zones":
                    self.apply_zones(step["zones"])
                elif action == "capacity_policy":
                    self.require_stopped()
                    compose_path = self.deployment / "release64.compose.json"
                    compose = runtime_policy.mounts(json.loads(compose_path.read_text()), install=True)
                    compose = stage7_canonical_runtime.mounts(
                        compose, runtime_policy.automatic_retirement(step["state"]), NODES, install=True)
                    shutil.copy2(compose_path, folder / "compose-before.json")
                    atomic_json(compose_path, compose)
                    atomic_json(self.deployment / "capacity-runtime.json", step["state"])
                elif action == "instance_prepare":
                    self.prepare_instances(step["initialize"], state=step.get("state"), initialize_admission=step.get("initialize_admission", False))
                elif action == "instance_schema":
                    from instance_schema_upgrade import upgrade
                    upgrade(self)
                elif action == "sync_release_config":
                    self.command([sys.executable, self.repo / "devtools/docker/stage_release64_configs.py"])
                elif action == "require_stopped":
                    self.require_stopped()
                elif action == "scenario_preflight":
                    self.scenario_preflight(step["target"])
                elif action == "switch_scenario":
                    self.switch_scenario(step["target"], step["zones"])
                elif action == "ready":
                    self.ready()
                elif action == "sync_native":
                    self.sync_native(step["source_root"])
                elif action == "assets":
                    self.build_assets(step)
                elif action == "record_build":
                    atomic_json(self.deployment / ("latest-" + step["target"] + ".json"), step)
                elif action == "deploy_build":
                    self.deploy_build(step)
                else:
                    raise ManagementError(f"Unknown operation step: {action}")
        except BaseException:
            atomic_json(folder / "result.json", {"ok": False, "operation_id": run, "log": str(self.log)})
            raise
        result = {"ok": True, "operation_id": run, "log": str(self.log), "effects": plan["effects"]}
        atomic_json(folder / "result.json", result)
        return result

    def storage(self, operation="status"):
        if operation == "status":
            return docker_storage.collect(self.repo)
        if operation == "policy":
            return docker_storage.policy(self.repo)
        raise ManagementError("Unknown storage inspection")

    def storage_plan(self, args):
        if args.operation == "policy":
            value = dict(docker_storage.policy(self.repo))
            for source, target, multiplier in (
                    ("max_test_databases", "max_test_databases", 1),
                    ("test_budget_gib", "test_budget_bytes", docker_storage.GIB),
                    ("minimum_free_gib", "minimum_free_bytes", docker_storage.GIB),
                    ("cache_budget_gib", "cache_budget_bytes", docker_storage.GIB),
                    ("cache_age_hours", "cache_age_hours", 1)):
                proposed = getattr(args, source, None)
                if proposed is not None:
                    if type(proposed) is not int:
                        raise ManagementError("Storage limits must be integers")
                    value[target] = proposed * multiplier
            protected = set(value["protected_test_projects"])
            for field, remove in (("protect_test_projects", False), ("unprotect_test_projects", True)):
                projects = getattr(args, field, [])
                if not isinstance(projects, list) or any(not isinstance(p, str) or not docker_storage.PROJECT.fullmatch(p) for p in projects):
                    raise ManagementError("Invalid protected fixture selection")
                protected.difference_update(projects) if remove else protected.update(projects)
            value["protected_test_projects"] = sorted(protected)
            docker_storage.validate_policy(value)
            return {"summary": "Save Docker storage limits and protected test fixtures; no services or storage are removed.",
                    "effects": {"game_services_restarted": False, "oracle_stopped": False},
                    "steps": [{"action": "storage_policy", "policy": value}]}
        if args.operation != "cleanup":
            raise ManagementError("Unknown storage mutation")
        volumes = getattr(args, "test_volumes", [])
        images = getattr(args, "images", False)
        cache = getattr(args, "build_cache", False)
        if not volumes and not images and not cache:
            raise ManagementError("Choose exact --test-volume names, --images, or --build-cache")
        selection = docker_storage.cleanup_plan(docker_storage.collect(self.repo), volumes, images, cache)
        return {"summary": "Remove only selected unused labelled SWG test databases/images and optionally aged private SWG build cache. Preserve canonical/legacy SWG volumes and retained fixture reports. Only verified SWG resources are eligible.",
                "effects": {"game_services_restarted": False, "oracle_stopped": False,
                            "test_database_deletions": selection["test_volumes"],
                            "image_deletions": selection["image_ids"], "swg_build_cache_cleanup": cache},
                "steps": [{"action": "storage_cleanup", "selection": selection}]}

    def build_plan(self, args):
        s = self.settings()
        if not isinstance(args.files, list) or any(not isinstance(name, str) for name in args.files):
            raise ManagementError("Build files must be a list of repository-relative path strings")
        run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        output = Path(s["work_root"]) / (args.target + "-" + run)
        docker = self.repo / "devtools/docker"
        command = lambda argv: {"action": "command", "argv": list(map(str, argv))}
        if args.files and args.target not in ("assets", "scripts"):
            raise ManagementError("File selection applies only to scripts and assets")
        if args.configure and args.target != "native":
            raise ManagementError("--configure applies only to native builds")
        files = []
        for name in args.files:
            path = (self.repo / name.replace("\\", "/")).resolve(strict=True)
            if not path.is_relative_to((self.repo / "dsrc").resolve()) or not path.is_file():
                raise ManagementError("Build inputs must be files within this checkout's dsrc tree")
            files.append(path)
        steps = []
        if args.target == "native":
            source = Path(s["source_root"]).resolve()
            if source.is_relative_to(self.repo.resolve()) or source.name != "src":
                raise ManagementError("source_root must be a separate Linux-native src snapshot")
            if not (source / "configure").is_file():
                raise ManagementError("Native source snapshot missing; use the documented initial WSL build setup")
            steps.append({"action": "sync_native", "source_root": str(source)})
            argv = ["bash", self.repo / "devtools/wsl/build_linux32_wsl.sh", "--source-root", source,
                    "--build-root", s["build_root"], "--install-root", s["install_root"], "--oracle-home", s["oracle_home"],
                    "--oracle-env-file", str(Path(s["oracle_home"]) / "whitengold-oracle10.env"),
                    "--skip-oracle", "--jobs", str(s["jobs"])]
            if not args.configure:
                argv += ["--skip-bootstrap", "--skip-configure"]
            steps.append(command(argv))
            output = Path(s["build_root"])
        elif args.target == "scripts":
            argv = [sys.executable, docker / "compile_scripts.py", "--output", output,
                    "--regeneration-plan", docker / "script-regeneration-plan.json"]
            for path in files:
                if path.suffix not in (".script", ".scriptlib", ".java"):
                    raise ManagementError("Script inputs must be .script, .scriptlib or .java")
                if path.suffix != ".java":
                    argv += ["--regenerate", path.relative_to(self.repo / "dsrc/sku.0/sys.server/compiled/game").with_suffix(".java").as_posix()]
            steps.append(command(argv))
        elif args.target == "assets":
            if any(p.suffix not in (".tpf", ".tab", ".xml", ".mif", ".txt") for p in files):
                raise ManagementError("Asset inputs must be .tpf, .tab, .xml, .mif or resource .txt files")
            argv = ["bash", self.repo / "devtools/wsl/build_wsl_runtime_assets.sh", "--engine-build-root",
                    str(Path(s["build_root"]) / "engine"), "--output-root", output, "--skip-build-tools",
                    "--collect-template-errors", "--template-exclusions", self.repo / "devtools/wsl/runtime-template-exclusions.tsv"]
            for path in files:
                argv += ["--source", str(path)]
            steps.append({"action": "assets", "argv": list(map(str, argv)), "output": str(output)})
        else:
            native = "starwarsgalaxies/native32:build-" + run.lower()
            suffix = "build-" + run.lower()
            steps += [command([sys.executable, docker / "package_native.py", "--build-root", s["build_root"],
                               "--source-root", s["source_root"], "--oracle-home", s["oracle_home"],
                               "--jdk", s["jdk32"], "--output", output]),
                      command(["docker", "build", "-t", native, output]),
                      command([sys.executable, docker / "build_role_images.py", "--runtime-image", native,
                               "--tag-suffix", suffix])]
        record = {"action": "record_build", "target": args.target, "output": str(output)}
        if args.target == "images":
            record.update(runtime_image=native, tag_suffix=suffix)
        steps.append(record)
        return {"summary": f"Build {args.target}; keep running servers and staged runtime data unchanged. Output: {output}",
                "effects": {"game_services_restarted": False, "oracle_stopped": False, "deploys_changes": False},
                "steps": steps}

    def sync_native(self, source):
        # Copy only versioned/new source inputs; do not overwrite case-sensitive
        # generated headers in the Linux snapshot with incidental Windows outputs.
        rows = self.command(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "src/"], capture=True).stdout
        names = sorted(set(p for p in rows.split("\0") if p and (self.repo / p).is_file()
                           and not p.endswith("/Makefile.in")))
        manifest = self.log.parent / "native-inputs.txt"
        manifest.write_bytes(b"\0".join(p.removeprefix("src/").encode() for p in names) + b"\0")
        # Do not preserve old mtimes on changed input: make must see it as newer
        # than existing objects, including after a branch checkout or restore.
        self.command(["rsync", "-rlc", "--from0", "--files-from=" + str(manifest),
                      str(self.repo / "src") + "/", str(source) + "/"])
        native = Path(source).resolve()
        previous = native.parent / ".swg-native-inputs.json"
        owned = set(json.loads(previous.read_text())) if previous.exists() else set()
        deleted = self.command(["git", "ls-files", "--deleted", "-z", "src/"], capture=True).stdout
        removed = (owned - set(names)) | {p for p in deleted.split("\0") if p}
        for name in removed:
            target = native / Path(name).relative_to("src")
            if not target.resolve().is_relative_to(native):
                raise ManagementError("Removed source path escapes native snapshot")
            if target.is_file() and not name.endswith("/Makefile.in"):
                target.unlink()
        atomic_json(previous, names)

    def build_assets(self, step):
        # The legacy helper owns repo/data. Preserve any recovery output in place
        # instead of --force (deletes it) or --resume (skips changed sources).
        scratch = self.repo / "data"
        backup = self.repo / (".swg-data-backup-" + self.log.parent.name)
        if scratch.is_symlink():
            raise ManagementError("Refusing to move a symlink at repo/data")
        had_data = scratch.exists()
        if had_data:
            scratch.rename(backup)
        try:
            self.command(step["argv"])
        finally:
            if scratch.exists():
                failed = self.repo / (".swg-data-failed-" + self.log.parent.name)
                scratch.rename(failed)
                self.emit("progress", message=f"Preserved incomplete asset output at {failed}")
            if had_data:
                backup.rename(scratch)

    def deploy_plan(self, target):
        if self.profile["override"] == "release64.compose.json":
            raise ManagementError("Embedded-data images are immutable; rebuild and redeploy the ELF64 role images")
        path = self.deployment / f"latest-{target}.json"
        if not path.is_file():
            raise ManagementError(f"No successful {target} build recorded. Run build {target} first.")
        record = json.loads(path.read_text())
        output = Path(record["output"]).resolve(strict=True)
        work = Path(self.settings()["work_root"]).resolve()
        if not output.is_relative_to(work) or output == work:
            raise ManagementError("Build output is outside management work_root")
        if target == "scripts":
            for name in ("base_class", "base_script", "dictionary"):
                if not (output / f"classes/script/{name}.class").is_file():
                    raise ManagementError("Script build is incomplete")
        if target == "assets" and not any(output.rglob("*.iff")):
            raise ManagementError("Asset build contains no IFF files")
        if target == "images" and not re.fullmatch(r"build-[a-z0-9-]+", record.get("tag_suffix", "")):
            raise ManagementError("Invalid recorded image tag")
        selected = select_zones(self.deployment)
        self.preflight(selected)
        steps = [{"action": "preflight_docker"}]
        if target == "images":
            steps += [{"action": "command", "argv": ["docker", "image", "inspect", "--format", "{{.Id}}",
                                                       f"starwarsgalaxies/{role}:{record['tag_suffix']}"]} for role in START]
        steps += [{"action": "command", "argv": self.compose("stop", role)} for role in STOP]
        steps += [{"action": "deploy_build", "target": target, "record": record},
                  {"action": "apply_zones", "zones": selected}, {"action": "start_oracle"}]
        steps += [{"action": "command", "argv": self.compose("up", "-d", "--no-deps", "--no-build", role)} for role in START]
        steps.append({"action": "ready"})
        return {"summary": f"Deploy the latest successful {target} build and restart ALL game services. Oracle stays running.",
                "effects": {"game_services_restarted": True, "oracle_stopped": False, "deploys_changes": True}, "steps": steps}

    def deploy_build(self, step):
        self.require_stopped()
        target, record = step["target"], step["record"]
        output = Path(record["output"])
        if target == "images":
            path = self.deployment / "diagnostic.compose.json"
            shutil.copy2(path, self.log.parent / "diagnostic.compose.before.json")
            compose = json.loads(path.read_text())
            for role in START:
                compose["services"][role]["image"] = f"starwarsgalaxies/{role}:{record['tag_suffix']}"
            atomic_json(path, compose)
            return
        data = self.runtime_data()
        if target == "scripts":
            source = output / "classes/script"
            destination = data / "sku.0/sys.server/compiled/game/script"
            staged = destination.with_name("script.next-" + self.log.parent.name)
            backup = destination.with_name("script.before-" + self.log.parent.name)
            shutil.copytree(source, staged)
            destination.rename(backup)
            staged.rename(destination)
            self.emit("progress", message=f"Previous scripts retained at {backup}")
            return
        # Overlay only files actually produced by this successful asset build.
        # Preserve recovery/client assets outside that set, and back up replacements.
        backup = self.log.parent / "assets-before"
        for source in sorted(output.rglob("*")):
            if not source.is_file() or source.suffix != ".iff":
                continue
            if source.is_symlink() or source.read_bytes()[:4] != b"FORM":
                raise ManagementError(f"Invalid compiled IFF: {source}")
            relative = source.relative_to(output)
            destination = data / relative
            if not destination.resolve().is_relative_to(data):
                raise ManagementError("Asset destination escapes staged data root")
            if destination.exists():
                previous = backup / relative
                previous.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, previous)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        self.command([sys.executable, self.repo / "devtools/docker/build_object_template_crc.py",
                      "--data", data, "--build-root", self.settings()["build_root"]])
