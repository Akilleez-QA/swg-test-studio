"""Explicit dependency on the SWG checkout; never a second driver implementation."""
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
from .store import read_json, write_json


def environment(path):
    return validate_environment(read_json(path))


def validate_environment(data):
    exact(data, ("schema_version", "name", "server_checkout", "folder", "binary", "bindings"), "environment")
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
    if set(bindings) != set(suite["roles"]):
        raise ValueError("Bind every declared role in the environment")
    manifest = compile_suite(suite, local_path(env["server_checkout"]) / "devtools/zones/test_sets")
    return {"schema_version": 1, "suite": suite["id"], "environment": env["name"],
            "bindings": bindings, "manifest": manifest,
            "effects": {"gameplay_actions": bool(bindings), "creates_dedicated_character": any(
                c["kind"] == "protocol_session" and c["options"].get("create", False) for c in manifest["tests"]),
                "explicit_station_setup": any(c["options"].get("stage_station", False) for c in manifest["tests"]),
                "fixture_proximity_setup": any(c["options"].get("prepare_terminal", False) or c["kind"] != "protocol_session"
                                               for c in manifest["tests"] if c["kind"] != "driver_unit"),
                "service_restart": False, "client_changed": False}}


def driver_modules(env):
    if sys.platform != "linux":
        raise ValueError("Live operations require Linux/WSL; use the Windows launcher to relay them")
    tools = Path(env["server_checkout"]).resolve(strict=True) / "devtools/zones"
    sys.path.insert(0, str(tools))
    import protocol_driver
    import protocol_test_sets
    if Path(protocol_driver.__file__).resolve().parent != tools:
        raise ValueError("An incompatible driver module is already loaded")
    return protocol_driver, protocol_test_sets


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
    selected = plan(suite, env)
    driver, legacy = driver_modules(env)
    manifest = legacy.validate(selected["manifest"])
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
            report["source_hashes"] = legacy.source_hashes()
            for case in manifest["tests"]:
                started = time.monotonic()
                row = {"id": case["id"], "kind": case["kind"], "passed": False}
                report["cases"].append(row)
                emit({"event": "case_started", "id": case["id"], "operation": operation})
                try:
                    argv = legacy.command(case, selected["bindings"], Path(env["folder"]), Path(env["binary"]))
                    with (output / (case["id"] + ".log")).open("x") as log:
                        code, timed_out = legacy.execute(argv, log, timeout=2400)
                    row.update(exit_code=code, timed_out=timed_out, passed=code == 0 and not timed_out)
                    if row["passed"] and case["kind"] != "driver_unit":
                        row["artifact"] = legacy.runtime_artifact(output / (case["id"] + ".log"), Path(env["folder"]))
                except (Exception, KeyboardInterrupt) as exc:
                    row.update(passed=False, error=type(exc).__name__ + ": " + str(exc))
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
