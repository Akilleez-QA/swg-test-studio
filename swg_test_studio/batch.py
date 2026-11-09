"""Schedule ordinary Studio runs while preserving the driver's original locks."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
import secrets
import subprocess
import sys
import xml.etree.ElementTree as ET

from .backend import environment, plan, studio_lock, validate_environment
from .collection import FORMAT, Collection, is_driver_suite
from .model import exact, identifier, validate
from .store import read_json, write_json


MAX_JOBS = 8
MAX_RUNS = 64


def batch_template():
    return {"schema_version": 1, "runs": [
        {"id": "ord", "suite": "ord_round_trip", "environment": "fixture-a.environment.json"},
        {"id": "shuttle", "suite": "gamma_shuttle", "environment": "fixture-b.environment.json"},
    ]}


def prepare_batch(path, library):
    path = Path(path).absolute()
    data = read_json(path)
    exact(data, ("schema_version", "runs"), "batch")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported batch version")
    runs = data["runs"]
    if not isinstance(runs, list) or not 1 <= len(runs) <= MAX_RUNS:
        raise ValueError(f"A batch needs 1–{MAX_RUNS} explicitly selected runs")
    prepared = []
    seen = set()
    for entry in runs:
        exact(entry, ("id", "suite", "environment"), "batch run")
        name = identifier(entry["id"])
        if name in seen:
            raise ValueError("Duplicate batch run ID: " + name)
        seen.add(name)
        suite = library.get(identifier(entry["suite"]))
        if is_driver_suite(suite):
            raise ValueError("Batch runs require Studio suites. Driver manifests use the original server harness.")
        profile = entry["environment"]
        if not isinstance(profile, str) or not profile.strip() or any(ord(c) < 32 for c in profile):
            raise ValueError("A batch run needs an environment JSON path")
        env = environment(path.parent / profile)
        for key in ("server_checkout", "folder"):
            location = Path(env[key]).resolve(strict=True)
            if not location.is_dir():
                raise ValueError(key + " must be a directory")
            env[key] = str(location)
        validate_environment(env)
        plan(suite, env)
        prepared.append({"id": name, "suite": suite, "env": env,
                         "scopes": {("checkout", env["server_checkout"]),
                                    ("project", Path(env["folder"]).parent.name)}})
    return prepared


def run_one(root, job):
    folder = root / job["id"]
    row = {"id": job["id"], "suite": job["suite"]["id"], "passed": False, "folder": str(folder)}
    try:
        folder.mkdir(mode=0o700)
        write_json(folder / "environment.json", job["env"])
        collection = Collection(folder / "suite-collection.json")
        collection.write({"format": FORMAT, "schema_version": 1, "title": "Batch suite snapshot",
                          "suites": [job["suite"]]})
        argv = [sys.executable, str(Path(__file__).with_name("entry.py")),
                "--workspace", str(folder), "--collection", str(collection.path),
                "run", row["suite"], "--environment", str(folder / "environment.json")]
        log = folder / "cli.jsonl"
        with log.open("xb") as output:
            process = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
        row.update(exit_code=process.returncode, log=str(log))
        reports = list((folder / "runs").glob("*/result.json"))
        if len(reports) == 1:
            report = reports[0]
            junit = report.with_name("junit.xml")
            if junit.is_file():
                row.update(result=str(report), junit=str(junit))
                result = read_json(report, max_bytes=2 * 1024 * 1024)
                row["passed"] = (process.returncode == 0 and result.get("passed") is True and
                                 result.get("suite") == row["suite"])
        if process.returncode == 0 and not row["passed"]:
            row["error"] = "Suite did not produce a matching passing JSON and JUnit report"
    except Exception as exc:
        row["error"] = type(exc).__name__ + ": " + str(exc)
    return row


def schedule(prepared, workers, run, results, emit):
    pending = list(prepared)
    active = {}

    def finish(future):
        job = active.pop(future)
        result = future.result()
        results[job["id"]] = result
        emit({"event": "batch_job_finished", **result})

    with ThreadPoolExecutor(max_workers=workers) as pool:
        try:
            while pending or active:
                reserved = set().union(*(job["scopes"] for job in active.values()))
                waiting = []
                for job in pending:
                    if len(active) < workers and reserved.isdisjoint(job["scopes"]):
                        emit({"event": "batch_job_started", "id": job["id"], "suite": job["suite"]["id"]})
                        active[pool.submit(run, job)] = job
                    else:
                        waiting.append(job)
                    # Preserve file order for any later run sharing a queued scope.
                    reserved.update(job["scopes"])
                pending = waiting
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    finish(future)
        except KeyboardInterrupt:
            for future in list(active):
                finish(future)
            return False
    return True


def write_report(root, prepared, results, completed, workers):
    rows = [results.get(job["id"], {"id": job["id"], "suite": job["suite"]["id"],
                                    "passed": False, "skipped": True}) for job in prepared]
    passed = completed and all(row["passed"] for row in rows)
    report = {"schema_version": 1, "passed": passed, "interrupted": not completed,
              "max_workers": workers, "runs": rows}
    write_json(root / "batch-result.json", report)
    junit = ET.Element("testsuite", name="swg_test_studio_batch", tests=str(len(rows)),
                       failures=str(sum(not row["passed"] and not row.get("skipped") for row in rows)),
                       skipped=str(sum(bool(row.get("skipped")) for row in rows)))
    for row in rows:
        case = ET.SubElement(junit, "testcase", name=row["id"], classname=row["suite"])
        if row.get("skipped"):
            ET.SubElement(case, "skipped", message="Batch interrupted before the suite started")
        elif not row["passed"]:
            ET.SubElement(case, "failure", message=row.get("error", "See the suite's retained logs"))
    ET.ElementTree(junit).write(root / "batch-junit.xml", encoding="utf-8", xml_declaration=True)
    return {"event": "batch_finished", "passed": passed, "interrupted": not completed, "evidence": str(root)}


def run_batch(prepared, workspace, workers, emit):
    if type(workers) is not int or not 1 <= workers <= MAX_JOBS:
        raise ValueError(f"Choose between 1 and {MAX_JOBS} workers")
    if sys.platform != "linux":
        raise ValueError("Batch replay requires Linux/WSL")
    workspace = Path(workspace).absolute()
    operation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4)
    root = workspace / "batches" / operation
    results = {}
    with studio_lock(workspace):
        root.mkdir(mode=0o700, parents=True)
        emit({"event": "batch_started", "runs": len(prepared), "max_workers": workers, "evidence": str(root)})
        completed = schedule(prepared, workers, lambda job: run_one(root, job), results, emit)
        return write_report(root, prepared, results, completed, workers)


def run_selected(names, library, workspace, *, project=None, profile=None, keep_running=False, emit,
                 source=None, run_workspace=None):
    """Run checked suites in order under one managed test server lifecycle."""
    from .docker_runtime import active_server, plain_login
    from .setup import automatic_environment, creation_roles

    if not 1 <= len(names) <= MAX_RUNS or len(set(names)) != len(names):
        raise ValueError(f"Select 1–{MAX_RUNS} distinct Studio tests.")
    suites = [library.get(name) for name in names]
    for suite in suites:
        if is_driver_suite(suite):
            raise ValueError(f"{suite['title']} uses the SWG server test tools.")
        validate(suite, runnable=True)
    prepared, reserved = [], set()
    for suite in suites:
        creates = creation_roles(suite)
        env = profile if profile is not None else automatic_environment(
            workspace, suite["roles"], project=project, creation_roles=creates, source=source)
        plan(suite, env)
        targets = {env["bindings"][role] for role in creates}
        if reserved & targets:
            raise ValueError("The selected character-creation tests would reuse a single free slot. Run them separately.")
        reserved.update(targets)
        prepared.append({"id": suite["id"], "suite": suite, "env": env, "scopes": set()})

    run_workspace = workspace if run_workspace is None else run_workspace
    live = [job for job in prepared if job["suite"]["roles"]]
    if profile is not None or not live:
        return run_batch(prepared, run_workspace, 1, emit)
    login_only = all(plain_login(job["suite"]) for job in live)
    server = live[0]["env"]
    if login_only:
        # Readiness must cover all of the exact saved hosts in this selection.
        bindings = {key: key for job in live for key in job["env"]["bindings"].values()}
        server = dict(server, bindings=bindings)
    with active_server(server, keep_running=keep_running, emit=emit, login_only=login_only):
        return run_batch(prepared, run_workspace, 1, emit)
