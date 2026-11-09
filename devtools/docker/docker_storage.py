"""Read-only Docker accounting and scoped, revalidated storage maintenance.

No global image/volume/container prune. Database deletion takes exact disposable
names; successful newly created empty fixtures opt out with --retain-database.
"""
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
GIB = 1024 ** 3
PROJECT = re.compile(r"swg-cold-test-[a-f0-9]{8}")
VOLUME = re.compile(r"(swg-cold-test-[a-f0-9]{8})_oracle26_data")
CACHE_FILTER = "description~=whitengold"
DEFAULTS = {"schema_version": 1, "max_test_databases": 3,
            "test_budget_bytes": 16 * GIB, "minimum_free_bytes": 15 * GIB,
            "cache_budget_bytes": 10 * GIB, "cache_age_hours": 24,
            "protected_test_projects": []}


def run(argv):
    result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise ValueError("Docker storage command failed: " + " ".join(map(str, argv[:3])))
    return result.stdout


def validate_policy(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS) or value["schema_version"] != 1:
        raise ValueError("Invalid storage-policy.json schema")
    limits = {"max_test_databases": (1, 20), "test_budget_bytes": (4*GIB, 512*GIB),
              "minimum_free_bytes": (0, 512*GIB), "cache_budget_bytes": (GIB, 512*GIB),
              "cache_age_hours": (24, 8760)}
    if type(value["schema_version"]) is not int or any(
            type(value[key]) is not int or not low <= value[key] <= high
            for key, (low, high) in limits.items()):
        raise ValueError("Storage limits must be bounded integers")
    projects = value["protected_test_projects"]
    if (not isinstance(projects, list) or len(projects) > 20
            or any(not isinstance(p, str) or not PROJECT.fullmatch(p) for p in projects)
            or len(set(projects)) != len(projects)):
        raise ValueError("Invalid protected test project list")
    return value


def policy(repo=REPO):
    path = Path(repo)/"StarWarsGalaxies/storage-policy.json"
    return validate_policy(json.loads(path.read_text()) if path.exists() else dict(DEFAULTS))


def engine_usage():
    # Docker Desktop's daemon filesystem is separate from the WSL checkout.
    # Read the engine API for exact byte counts instead of rounding CLI units.
    host = os.environ.get("DOCKER_HOST") or json.loads(run(
        ["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"] ))
    if not host.startswith("unix://") or not Path(host[7:]).is_absolute():
        raise ValueError("Storage maintenance requires the local WSL/Linux Docker socket")
    connection = http.client.HTTPConnection("localhost", timeout=180)
    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.sock.settimeout(180)
    try:
        connection.sock.connect(host[7:])
        connection.request("GET", "/system/df")
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Docker disk-usage query failed")
        return json.loads(response.read())
    finally:
        connection.close()


def daemon_free_bytes(containers):
    # df inside an existing persistent local volume measures Docker Desktop's
    # actual backing filesystem. No helper container or new volume is created.
    for container in containers:
        labels = container.get("Labels") or {}
        if container.get("State") != "running" or labels.get("com.docker.compose.project") != "starwarsgalaxies":
            continue
        if labels.get("com.docker.compose.service") != "oracle":
            continue
        for mount in container.get("Mounts", []):
            if (mount.get("Type") == "volume" and mount.get("Name") in
                    ("starwarsgalaxies_oracle_data", "starwarsgalaxies_oracle26_data")):
                try:
                    fields = run(["docker", "exec", container["Id"], "df", "-B1", mount["Destination"]]).splitlines()[-1].split()
                    return int(fields[3])
                except (ValueError, IndexError):
                    pass
    return None


def fixture_proof(name, fixture_parent=Path("/tmp")):
    match = VOLUME.fullmatch(name)
    if not match:
        raise ValueError("Exact disposable Oracle volume required")
    project = match.group(1)
    root = (fixture_parent/project).resolve()
    if root.parent != fixture_parent.resolve() or root.name != project:
        raise ValueError("Fixture root escaped its parent")
    compose_path = root/"compose.json"
    if compose_path.is_symlink():
        raise ValueError("Fixture proof must be a regular local file")
    compose = json.loads(compose_path.read_text())
    if not isinstance(compose, dict):
        raise ValueError("Invalid fixture configuration")
    services = compose.get("services", {})
    if not isinstance(services, dict):
        raise ValueError("Invalid fixture services")
    oracle = services.get("oracle", {})
    if not isinstance(oracle, dict) or not isinstance(oracle.get("labels", {}), dict):
        raise ValueError("Invalid fixture Oracle service")
    if (compose.get("name") != project or oracle.get("image") != "gvenzl/oracle-free:23.26.3-slim-faststart"
            or (oracle.get("labels") or {}).get("whitengold.test.kind") != "cold-start"):
        raise ValueError("Fixture ownership evidence missing")
    configured = compose.get("volumes", {})
    if not isinstance(configured, dict) or any(not isinstance(v, dict) for v in configured.values()):
        raise ValueError("Invalid fixture volume definitions")
    if not isinstance(oracle.get("volumes", []), list):
        raise ValueError("Invalid fixture Oracle mounts")
    exact = False
    for mount in oracle.get("volumes", []):
        if isinstance(mount, str):
            parts = mount.split(":")
            source, destination = parts[:2] if len(parts) in (2, 3) else (None, None)
        elif isinstance(mount, dict) and mount.get("type") == "volume":
            source, destination = mount.get("source"), mount.get("target")
        else:
            continue
        if destination == "/opt/oracle/oradata" and configured.get(source, {}).get("name") == name:
            exact = True
    report = root/"report.json"
    if not exact or report.is_symlink() or not report.is_file():
        raise ValueError("Exact database mount and retained report required")
    contents = json.loads(report.read_text())
    if not isinstance(contents, dict) or contents.get("project") != project:
        raise ValueError("Matching retained report required")
    return root


def volume_reason(volume, containers, settings, fixture_parent):
    name = volume["Name"]
    match = VOLUME.fullmatch(name)
    if not match:
        return "canonical, legacy or unrelated volume"
    project = match.group(1)
    if project in settings["protected_test_projects"]:
        return "protected client/test fixture"
    if (volume.get("Labels") or {}).get("whitengold.test.kind") != "cold-start":
        return "missing disposable ownership label"
    if volume.get("Driver") != "local" or volume.get("Options"):
        return "unexpected storage driver/options"
    if volume.get("UsageData", {}).get("RefCount") != 0:
        return "referenced by a container or reference count unknown"
    if any((c.get("Labels") or {}).get("com.docker.compose.project") == project or
           any(m.get("Name") == name for m in c.get("Mounts", [])) for c in containers):
        return "fixture containers still exist"
    try:
        fixture_proof(name, fixture_parent)
    except (OSError, ValueError, KeyError, TypeError):
        return "missing or invalid retained fixture proof"
    return None


def summarize(raw, settings, free_bytes, fixture_parent=Path("/tmp")):
    containers = raw.get("Containers") or []
    volumes = raw.get("Volumes") or []
    tests = []
    for volume in volumes:
        if not VOLUME.fullmatch(volume["Name"]):
            continue
        tests.append({"name": volume["Name"], "bytes": volume.get("UsageData", {}).get("Size", -1),
                      "references": volume.get("UsageData", {}).get("RefCount", -1),
                      "identity": {"created_at": volume.get("CreatedAt"), "labels": volume.get("Labels")},
                      "protected_reason": volume_reason(volume, containers, settings, fixture_parent)})
    images = raw.get("Images") or []
    used = {c.get("ImageID") for c in containers}
    owned = [i for i in images if (i.get("Labels") or {}).get("whitengold.owner") == "whitengold"]
    # Named and container-referenced images include the active tags and rollback
    # references. Only explicitly labelled, untagged, unreferenced layers qualify.
    image_candidates = [i["Id"] for i in owned if i["Id"] not in used and
                        not i.get("RepoDigests") and not [t for t in i.get("RepoTags") or [] if t != "<none>:<none>"]]
    cache = raw.get("BuildCache") or []
    project_cache = [c for c in cache if "whitengold" in c.get("Description", "").lower()]
    reclaimable = sum(c["Size"] for c in project_cache if not c.get("InUse") and not c.get("Shared"))
    test_bytes = sum(max(0, t["bytes"]) for t in tests)
    warnings = []
    if len(tests) >= settings["max_test_databases"] or test_bytes >= settings["test_budget_bytes"]:
        warnings.append("Retained test databases reached their storage limit; new fixture creation is blocked")
    if reclaimable > settings["cache_budget_bytes"]:
        warnings.append("Reclaimable SWG build cache exceeds its budget; use explicit --build-cache cleanup")
    if free_bytes is None:
        warnings.append("Daemon free space unavailable; start existing canonical Oracle or explicitly disable the free-space floor")
    elif free_bytes < settings["minimum_free_bytes"]:
        warnings.append("Docker filesystem free space is below its floor")
    return {"schema_version": 1, "policy": settings, "free_bytes": free_bytes,
            "image_layer_bytes": raw.get("LayersSize"),
            "volume_bytes": sum(max(0, v.get("UsageData", {}).get("Size", 0)) for v in volumes),
            "build_cache_bytes": sum(c["Size"] for c in cache),
            "swg_build_cache_bytes": sum(c["Size"] for c in project_cache),
            "active_build_cache_records": sum(bool(c.get("InUse")) for c in cache),
            "reclaimable_cache_bytes": reclaimable,
            "test_database_count": len(tests), "test_database_bytes": test_bytes,
            "test_databases": tests, "removable_image_ids": image_candidates,
            "swg_images": [{"id": i["Id"], "tags": i.get("RepoTags"), "bytes": i["Size"],
                            "shared_bytes": i.get("SharedSize")} for i in images
                           if any(t.startswith("starwarsgalaxies/") for t in i.get("RepoTags") or [])],
            "warnings": warnings, "global_volume_prune": False, "global_image_prune": False}


def collect(repo=REPO):
    raw = engine_usage()
    return summarize(raw, policy(repo), daemon_free_bytes(raw.get("Containers") or []))


def check_allocation(report, estimate_bytes=4*GIB):
    settings = report["policy"]
    if report["test_database_count"] + 1 > settings["max_test_databases"]:
        raise ValueError("Test database count limit reached; reuse the retained fixture or clean exact old test volumes")
    if any(t["bytes"] < 0 for t in report["test_databases"]):
        raise ValueError("Test database storage size unknown")
    if report["test_database_bytes"] + estimate_bytes > settings["test_budget_bytes"]:
        raise ValueError("Test database byte budget exceeded")
    floor = settings["minimum_free_bytes"]
    if floor and (report["free_bytes"] is None or report["free_bytes"] - estimate_bytes < floor):
        raise ValueError("Insufficient measured Docker free space for another test database")


def cleanup_plan(report, test_volumes=(), images=False, build_cache=False):
    if not isinstance(test_volumes, (list, tuple)) or any(not isinstance(n, str) for n in test_volumes):
        raise ValueError("Test volumes must be exact names")
    if type(images) is not bool or type(build_cache) is not bool:
        raise ValueError("Cleanup switches must be booleans")
    if len(set(test_volumes)) != len(test_volumes):
        raise ValueError("Duplicate cleanup volume")
    known = {t["name"]: t for t in report["test_databases"]}
    for name in test_volumes:
        if not VOLUME.fullmatch(name) or name not in known or known[name]["protected_reason"]:
            raise ValueError("Volume is not an eligible unused disposable database: " + name)
    if build_cache and report.get("active_build_cache_records", 0):
        raise ValueError("A Docker build is active; defer cache cleanup until it finishes")
    return {"test_volumes": list(test_volumes),
            "volume_identities": {n: known[n]["identity"] for n in test_volumes},
            "image_ids": report["removable_image_ids"] if images else [],
            "build_cache": build_cache, "policy": report["policy"],
            "estimated_database_bytes": sum(known[n]["bytes"] for n in test_volumes),
            "cache_scope": "SWG description-matched private cache older than the configured age",
            "cache_filter": CACHE_FILTER,
            "reports_and_logs_preserved": True}


def execute_cleanup(repo, selection, archive, command=run):
    current = collect(repo)
    rechecked = cleanup_plan(current, selection["test_volumes"], bool(selection["image_ids"]), selection["build_cache"])
    if (current["policy"] != selection["policy"] or rechecked["volume_identities"] != selection["volume_identities"]
            or not set(selection["image_ids"]).issubset(rechecked["image_ids"])):
        raise ValueError("Storage selection changed; preview again")
    # Archive proof for the complete batch before deleting any database.
    archive = Path(archive); archive.mkdir(parents=True, exist_ok=True)
    for name in selection["test_volumes"]:
        root = fixture_proof(name)
        destination = archive/root.name; destination.mkdir()
        for report in root.glob("*report*.json"):
            if report.is_symlink() or not report.is_file():
                raise ValueError("Reports to archive must be regular local files")
            shutil.copy2(report, destination/report.name)
    deleted = {"test_volumes": [], "image_ids": []}
    receipt = archive/"receipt.json"
    def record():
        receipt.write_text(json.dumps(deleted, indent=2)+"\n")
    record()
    for name in selection["test_volumes"]:
        # A container created after the preview blocks deletion. Docker also
        # performs its own reference check; there is no force removal.
        attached = run(["docker", "ps", "-aq", "--filter", "volume="+name]).strip()
        metadata = json.loads(run(["docker", "volume", "inspect", name]))[0]
        identity = {"created_at": metadata.get("CreatedAt"), "labels": metadata.get("Labels")}
        if attached or identity != selection["volume_identities"][name] or (metadata.get("Labels") or {}).get("whitengold.test.kind") != "cold-start":
            raise ValueError("Disposable database became attached or changed ownership")
        command(["docker", "volume", "rm", name]); deleted["test_volumes"].append(name); record()
    for image in selection["image_ids"]:
        # Recheck all stopped/running container references and named tags.
        metadata = json.loads(run(["docker", "image", "inspect", image]))[0]
        refs = run(["docker", "ps", "-aq", "--filter", "ancestor="+image]).strip()
        if refs or metadata.get("RepoTags") or metadata.get("RepoDigests") or (metadata.get("Config", {}).get("Labels") or {}).get("whitengold.owner") != "whitengold":
            raise ValueError("Image became referenced or changed ownership")
        command(["docker", "image", "rm", image]); deleted["image_ids"].append(image); record()
    if selection["build_cache"]:
        # An unrelated build may have started while a database batch was being
        # removed. Check again immediately before the scoped cache mutation.
        cleanup_plan(collect(repo), build_cache=True)
        settings = selection["policy"]
        command(["docker", "buildx", "prune", "--force", "--filter", CACHE_FILTER, "--filter", "shared=false",
                 "--filter", "until="+str(settings["cache_age_hours"])+"h",
                 "--max-used-space", str(settings["cache_budget_bytes"]), "--reserved-space", str(GIB)])
        deleted["build_cache_cleanup_requested"] = True; record()
    return deleted


def create_test_database(repo, volume):
    if not VOLUME.fullmatch(volume):
        raise ValueError("Exact fresh test volume required")
    sys.path.insert(0, str(Path(repo)/"devtools/manage"))
    from service import operation_lock
    with operation_lock(Path(repo)/"StarWarsGalaxies"):
        report = collect(repo)
        if any(t["name"] == volume for t in report["test_databases"]):
            raise ValueError("Fresh fixture must not reuse an existing database")
        check_allocation(report)
        return run(["docker", "volume", "create", "--label", "whitengold.test.kind=cold-start",
                    "--label", "whitengold.test.project="+VOLUME.fullmatch(volume).group(1), volume])


def build_space_report(repo=REPO):
    """Measure build headroom through only the exact owned Oracle container.

    Image packaging needs a filesystem free-space measurement, not a Docker
    engine resource inventory. Verify ownership/storage before executing df.
    """
    rows = json.loads(run(["docker", "inspect", "starwarsgalaxies-oracle-1"]))
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("Exact canonical SWG Oracle metadata required")
    row = rows[0]
    config = row.get("Config") or {}
    labels = config.get("Labels") or {}
    storage = {
        "gvenzl/oracle-xe:11.2.0.2-slim-faststart":
            ("starwarsgalaxies_oracle_data", "/u01/app/oracle/oradata"),
        "gvenzl/oracle-free:23.26.3-slim-faststart":
            ("starwarsgalaxies_oracle26_data", "/opt/oracle/oradata"),
    }.get(config.get("Image"))
    if (labels.get("com.docker.compose.project") != "starwarsgalaxies" or
            labels.get("com.docker.compose.service") != "oracle" or
            not re.fullmatch(r"[a-f0-9]{64}", row.get("Id", "")) or storage is None or
            not any(m.get("Type") == "volume" and
                    (m.get("Name"), m.get("Destination")) == storage
                    for m in row.get("Mounts", []))):
        raise ValueError("Canonical SWG Oracle ownership and persistent mount required")
    container = dict(Id=row["Id"], Labels=labels, Mounts=row["Mounts"],
                     State="running" if row.get("State", {}).get("Running") is True else "exited")
    return dict(policy=policy(repo), free_bytes=daemon_free_bytes([container]),
                scope="Canonical SWG Oracle filesystem only; no engine inventory")


def check_build_space(repo=REPO, estimate_bytes=4*GIB):
    if type(estimate_bytes) is not int or estimate_bytes < 0:
        raise ValueError("Nonnegative integer build-space estimate required")
    report = build_space_report(repo)
    floor = report['policy']['minimum_free_bytes']
    if floor and (report['free_bytes'] is None or report['free_bytes']-estimate_bytes < floor):
        raise ValueError('Docker image build would exceed the measured free-space floor')
    return report


def cleanup_passed_database(repo, volume):
    root = fixture_proof(volume)
    if json.loads((root/"report.json").read_text()).get("passed") is not True:
        raise ValueError("Only a passing empty fixture can automatically discard its database")
    sys.path.insert(0, str(Path(repo)/"devtools/manage"))
    from service import operation_lock
    with operation_lock(Path(repo)/"StarWarsGalaxies"):
        selection = cleanup_plan(collect(repo), [volume])
        archive = Path(repo)/"StarWarsGalaxies/logs/storage"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return execute_cleanup(repo, selection, archive)
