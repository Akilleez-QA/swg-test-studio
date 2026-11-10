"""Run the pinned SWG driver against the selected server source and fixture."""
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import sys
import time
import xml.etree.ElementTree as ET

from .model import compile_suite, exact, ROLE
from .agent_fixture import OPS as AGENT_OPS
from .server_tools import load_tool, profile_of, source_folder, tool_environment, verified_tool_root
from .store import read_json, write_json


def environment_template():
    return {
        "schema_version": 1,
        "name": "My isolated SWG fixture",
        "server_checkout": "/mnt/f/SWGProjects/swg-server",
        "folder": "/tmp/swg-cold-test-0123abcd/client-012345abcdef",
        "binary": "/tmp/swg-driver64/driver",
        "bindings": {"actor": "tester"},
    }


def environment(path):
    return validate_environment(read_json(path))


def validate_environment(data):
    # "profile" is optional; without it the environment is the original whitengold one.
    optional = ("profile",) if isinstance(data, dict) and "profile" in data else ()
    exact(data, ("schema_version", "name", "server_checkout", "folder", "binary", "bindings") + optional, "environment")
    if optional:
        if not isinstance(data["profile"], str):
            raise ValueError("Unknown server profile")
        profile_of(data)
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported environment version")
    if not isinstance(data["name"], str) or not 1 <= len(data["name"]) <= 100:
        raise ValueError("Environment name required")
    for key in ("server_checkout", "folder", "binary"):
        value = data[key]
        if (not isinstance(value, str) or not value.startswith("/") or "\x00" in value or
                any(ord(c) < 32 for c in value) or ".." in PurePosixPath(value).parts):
            raise ValueError(key + " must be an absolute Linux/WSL path")
    if not re.fullmatch(r"/tmp/swg-cold-test-[a-f0-9]{8}/client-[a-f0-9]{12}", data["folder"]):
        raise ValueError("Only a prepared isolated SWG fixture is supported")
    bindings = data["bindings"]
    if (not isinstance(bindings, dict) or len(bindings) > 5 or
            any(not isinstance(k, str) or not ROLE.fullmatch(k) or not isinstance(v, str) or
                not ROLE.fullmatch(v) for k, v in bindings.items()) or len(set(bindings.values())) != len(bindings)):
        raise ValueError("Bind at most five distinct roles to retained registries")
    return data


def local_path(value):
    if os.name == "nt" and re.match(r"/mnt/[a-z]/", value):
        return Path(value[5].upper() + ":/" + value[7:])
    return Path(value)


def plan(suite, env):
    bindings = {r: env["bindings"][r] for r in suite["roles"] if r in env["bindings"]}
    missing = [role for role in suite["roles"] if role not in bindings]
    if missing:
        raise ValueError("The test setup has no characters assigned for these parts: " + ", ".join(missing))
    manifest = compile_suite(suite, verified_tool_root() / "zones/test_sets")
    cases = manifest["tests"]
    profile = profile_of(env)
    load_tool("zones/server_profile.py").require_supported(cases, profile)
    action_kinds = {
        action["kind"]
        for case in cases if case["kind"] == "studio_action_sequence"
        for action in case["options"]["actions"]
    }
    ground_or_legacy_setup = any(
        any(case["options"].get(key, False) for key in
            ("prepare_terminal", "prepare_start", "prepare_between_actions")) or
        case["kind"] not in ("protocol_session", "studio_journey", "studio_action_sequence", "agent_fixture")
        for case in cases if case["kind"] != "driver_unit"
    )
    return {"schema_version": 1, "suite": suite["id"], "environment": env["name"],
            **({} if profile.case_kinds is None else {"profile": profile.name}),
            "bindings": bindings, "manifest": manifest,
            "effects": {"gameplay_actions": bool(bindings), "creates_dedicated_character": any(
                case["kind"] == "protocol_session" and case["options"].get("create", False) for case in cases),
                "explicit_station_setup": any(case["options"].get("stage_station", False) for case in cases),
                "fixture_proximity_setup": ground_or_legacy_setup or bool(action_kinds & {"launch", "land"}),
                "ship_pilot_reward_and_proximity_setup": "launch" in action_kinds,
                "group_cleanup_possible": "form_group" in action_kinds,
                "agent_fixture_changes": sorted({case["options"]["op"] for case in cases
                                                 if case["kind"] == "agent_fixture" and AGENT_OPS[case["options"]["op"]][1]}),
                "service_restart": False, "client_changed": False}}


def require_profile_support(suite, profile):
    """Refuse a suite the named server profile cannot run, before anything is started."""
    tools = load_tool("zones/server_profile.py")
    manifest = compile_suite(suite, verified_tool_root() / "zones/test_sets")
    tools.require_supported(manifest["tests"], tools.get(profile))


def driver_modules(env):
    if sys.platform != "linux":
        raise ValueError("Live operations require Linux/WSL; use the Windows launcher to relay them")
    source = source_folder(env["server_checkout"])
    load_tool("zones/server_profile.py").bind(env.get("profile"))
    load_tool("zones/studio_tool_bundle.py").bind_server_source(source)
    return load_tool("zones/protocol_driver.py"), load_tool("zones/protocol_test_sets.py")


@contextlib.contextmanager
def studio_lock(workspace):
    import fcntl
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = workspace / "operation.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def run_suite(suite, env, workspace, emit=print):
    from .results import failed_action, failure_reason, log_tail

    selected = plan(suite, env)
    driver, legacy = driver_modules(env)
    manifest = selected["manifest"]
    ordinary = dict(manifest, tests=[c for c in manifest["tests"] if c["kind"] not in ("studio_journey", "studio_action_sequence", "agent_fixture")])
    if ordinary["tests"]:
        legacy.validate(ordinary)
    operation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4)
    output = Path(workspace) / "runs" / operation
    with studio_lock(workspace):
        # Existing backends retain their own management lock and full isolation checks.
        if any(Path(env["folder"]).joinpath("fixture/teststudio").glob("*.control")):
            raise ValueError("Stop the active recording before replaying test characters")
        output.mkdir(parents=True, mode=0o700)
        write_json(output / "suite.json", suite)
        write_json(output / "manifest.json", manifest)
        report = {"schema_version": 1, "operation": operation, "suite": suite["id"],
                  "passed": False, "cases": [], "windows_visual": False,
                  "manifest_sha256": hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest(),
                  "application_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in Path(__file__).parent.glob("*.py")}}
        try:
            emit({"event": "run_preparing", "operation": operation, "cases": len(manifest["tests"])})
            report["source_hashes"] = legacy.source_hashes()
            inputs = {"devtools/teststudio_server/retained_peer.py": verified_tool_root() / "teststudio_server/retained_peer.py"}
            for header in ("TestStudioRecorder.h", "TestStudioCapture.h"):
                relative = "src/engine/server/library/serverGame/src/shared/core/" + header
                if (driver.REPO / relative).is_file():
                    inputs[relative] = driver.REPO / relative
            report["studio_adapter_sha256"] = {
                name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()
            }
            for case in manifest["tests"]:
                started = time.monotonic()
                row = {"id": case["id"], "kind": case["kind"], "passed": False}
                case_log = output / (case["id"] + ".log")
                report["cases"].append(row)
                emit({"event": "case_started", "id": case["id"], "operation": operation})
                try:
                    if case["kind"] == "agent_fixture":
                        from .agent_fixture import run_live as run_fixture
                        with case_log.open("x") as log, contextlib.redirect_stdout(log):
                            row["artifact"] = run_fixture(case["options"], env, selected["bindings"][case["options"]["role"]])
                        row.update(exit_code=0, timed_out=False, passed=True)
                    elif case["kind"] == "studio_journey":
                        from .journey import run_live
                        with case_log.open("x") as log, contextlib.redirect_stdout(log):
                            row["artifact"] = run_live(case["options"], env, selected["bindings"][case["options"]["role"]])
                        row.update(exit_code=0, timed_out=False, passed=True)
                    else:
                        if case["kind"] == "studio_action_sequence":
                            from .action_sequence import command
                            argv = command(case["options"], env, selected["bindings"], output, case["id"])
                        else:
                            argv = legacy.command(case, selected["bindings"], Path(env["folder"]), Path(env["binary"]))
                        with case_log.open("x") as log:
                            code, timed_out = legacy.execute(argv, log, timeout=2400, env=tool_environment(driver.REPO))
                        row.update(exit_code=code, timed_out=timed_out, passed=code == 0 and not timed_out)
                        if row["passed"] and case["kind"] != "driver_unit":
                            row["artifact"] = legacy.runtime_artifact(case_log, Path(env["folder"]))
                except (Exception, KeyboardInterrupt) as exc:
                    row.update(passed=False, error=type(exc).__name__ + ": " + str(exc))
                if not row["passed"]:
                    log = log_tail(case_log)
                    row["error"] = failure_reason(row, log)
                    action = failed_action(log)
                    if action:
                        row["action"] = action
                row["seconds"] = time.monotonic() - started
                emit({"event": "case_finished", **row})
                if not row["passed"]:
                    break
            report["passed"] = len(report["cases"]) == len(manifest["tests"]) and all(r["passed"] for r in report["cases"])
        except (Exception, KeyboardInterrupt) as exc:
            report["error"] = type(exc).__name__ + ": " + str(exc)
        finally:
            write_json(output / "result.json", report)
            xml = ET.Element("testsuite", name=suite["id"], tests=str(len(manifest["tests"])),
                             failures=str(sum(not r["passed"] for r in report["cases"])))
            for case in manifest["tests"]:
                row = next((r for r in report["cases"] if r["id"] == case["id"]), None)
                node = ET.SubElement(xml, "testcase", name=case["id"], time=str(row.get("seconds", 0) if row else 0))
                if row is None:
                    ET.SubElement(node, "skipped", message="Previous case failed or run interrupted")
                elif not row["passed"]:
                    ET.SubElement(node, "failure", message="See retained case log")
            ET.ElementTree(xml).write(output / "junit.xml", encoding="utf-8", xml_declaration=True)
        return {"event": "run_finished", "passed": report["passed"], "operation": operation, "evidence": str(output)}
