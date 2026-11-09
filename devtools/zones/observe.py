"""Bounded read-only resource observations for the dynamic scene capacity catalog."""
from datetime import datetime, timedelta, timezone
import json
import re
import subprocess
import time

ROLES = {"planet": "PlanetServer", "game": "SwgGameServer"}
# Only numeric PIDs discovered inside the role container become arguments.
COUNTERS = ('for pid do if test -r "/proc/$pid/stat"; then '
            'cat "/proc/$pid/stat"; fi; done')


def query(args, timeout):
    result = subprocess.run(["docker", *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        # Docker output/command lines may contain private configuration.
        raise RuntimeError("Docker observation query failed")
    return result.stdout


def parse_processes(text, binary):
    result = {}
    for line in text.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        argv = fields[1].split()
        if not argv or argv[0] != "/opt/whitengold/bin/" + binary:
            continue
        scenes = [x[8:] for x in argv[1:] if x.startswith("sceneID=")]
        if len(scenes) != 1 or not re.fullmatch(r"[a-z][a-z0-9_]*", scenes[0]):
            raise ValueError("Role process has missing or ambiguous scene identity")
        result[int(fields[0])] = scenes[0]
    return result


def parse_counters(text):
    result = {}
    for line in text.splitlines():
        end = line.rfind(")")
        if end < 0:
            raise ValueError("Invalid process counters")
        pid = int(line.split(" ", 1)[0])
        fields = line[end + 2:].split()
        if len(fields) < 22:
            raise ValueError("Truncated process counters")
        result[pid] = {"cpu_ticks": int(fields[11]) + int(fields[12]),
                       "start_ticks": int(fields[19]), "rss_pages": max(0, int(fields[21]))}
    return result


def snapshot(role, run):
    name = "starwarsgalaxies-" + role + "-1"
    # Never request full inspect output: it includes environment/configuration.
    identity = json.loads(run(["inspect", "-f",
        '{"id":{{json .Id}},"started_at":{{json .State.StartedAt}},"running":{{json .State.Running}}}', name]))
    if not isinstance(identity, dict) or type(identity.get("running")) is not bool:
        raise ValueError("Invalid container identity")
    if not identity.get("id") or not identity.get("started_at"):
        raise ValueError("Missing container identity")
    if not identity["running"]:
        return {"identity": identity, "processes": {}, "counters": {}, "hz": None, "page_size": None}
    names = parse_processes(run(["exec", name, "ps", "-eo", "pid,args"]), ROLES[role])
    hz = int(run(["exec", name, "getconf", "CLK_TCK"]).strip())
    page = int(run(["exec", name, "getconf", "PAGESIZE"]).strip())
    if hz <= 0 or page <= 0:
        raise ValueError("Invalid container counter units")
    values = parse_counters(run(["exec", name, "sh", "-c", COUNTERS, "sh", *map(str, sorted(names))])) if names else {}
    final_identity = json.loads(run(["inspect", "-f",
        '{"id":{{json .Id}},"started_at":{{json .State.StartedAt}},"running":{{json .State.Running}}}', name]))
    if final_identity != identity:
        raise RuntimeError("Container changed while reading process counters")
    return {"identity": identity, "processes": names, "counters": values, "hz": hz, "page_size": page}


def compare(before, after, elapsed):
    """Restarted/new/exited processes cannot produce a CPU delta."""
    if before["identity"] != after["identity"] or before["hz"] != after["hz"] or before["page_size"] != after["page_size"]:
        return {"state": "changed_during_sample", "processes": [], "complete": False}
    if not after["identity"]["running"]:
        return {"state": "stopped", "processes": [], "complete": True}
    rows = []
    complete = before["processes"] == after["processes"]
    for pid, scene in sorted(after["processes"].items()):
        now = after["counters"].get(pid)
        old = before["counters"].get(pid)
        stable = (now is not None and old is not None and before["processes"].get(pid) == scene
                  and now["start_ticks"] == old["start_ticks"] and now["cpu_ticks"] >= old["cpu_ticks"])
        complete = complete and stable
        rows.append({"scene": scene, "pid": pid,
            "process_start_ticks": now["start_ticks"] if now else None,
            "rss_bytes": now["rss_pages"] * after["page_size"] if now else None,
            "cpu_percent_of_one_core": round((now["cpu_ticks"] - old["cpu_ticks"]) * 100 / after["hz"] / elapsed, 2) if stable and elapsed > 0 else None})
    return {"state": "observed", "processes": rows, "complete": complete}


def collect(seconds=2, timeout=45, run=query, monotonic=time.monotonic, sleep=time.sleep):
    if not 1 <= seconds <= 15 or not seconds < timeout <= 60:
        raise ValueError("Sample must be 1-15 seconds within a 60-second query deadline")
    deadline = monotonic() + timeout
    def bounded(args):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Observation deadline expired")
        return run(args, min(10, remaining))
    before, times, roles = {}, {}, {}
    errors = (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired)
    for role in ROLES:
        try:
            before[role] = snapshot(role, bounded)
            times[role] = monotonic()
        except errors:
            roles[role] = {"state": "unavailable", "processes": [], "complete": False}
    if before:
        sleep(min(seconds, max(0, deadline - monotonic())))
    for role, first in before.items():
        try:
            after = snapshot(role, bounded)
            elapsed = monotonic() - times[role]
            roles[role] = {**compare(first, after, elapsed), "sample_seconds": round(elapsed, 3),
                           "container": after["identity"]}
        except errors:
            roles[role] = {"state": "unavailable", "processes": [], "complete": False}
    checked = datetime.now(timezone.utc)
    return {"checked_at": checked.isoformat(), "valid_until": (checked + timedelta(seconds=30)).isoformat(),
            "roles": roles, "complete": all(r["complete"] for r in roles.values())}


def report(observation, proposal):
    """Keep observed resources separate from unknown content/admission capacity."""
    scenes = set(proposal["selected_scenes"])
    scenes.update(s for g in proposal["groups"] for s in g["scenes"])
    scenes.update(p["scene"] for r in observation["roles"].values() for p in r["processes"])
    rows = {}
    for scene in sorted(scenes):
        roles = {}
        for role, sample in observation["roles"].items():
            processes = [p for p in sample["processes"] if p["scene"] == scene]
            known = sample["state"] in ("observed", "stopped")
            roles[role] = {"process_count": len(processes) if known else None,
                "pids": [p["pid"] for p in processes],
                "rss_bytes": sum(p["rss_bytes"] for p in processes) if known and all(p["rss_bytes"] is not None for p in processes) else None,
                "cpu_percent_of_one_core": round(sum(p["cpu_percent_of_one_core"] for p in processes), 2) if known and sample["complete"] and all(p["cpu_percent_of_one_core"] is not None for p in processes) else None}
        rows[scene] = {"selected": scene in proposal["selected_scenes"], "roles": roles,
                       "content_ready": None, "occupied": None, "reserved": None, "capacity": None}
    groups = []
    for group in proposal["groups"]:
        members = [rows[s] for s in group["scenes"]]
        rss = [r["rss_bytes"] for m in members for r in m["roles"].values()]
        cpu = [r["cpu_percent_of_one_core"] for m in members for r in m["roles"].values()]
        groups.append({"id": group["id"], "kind": group["kind"], "scenes": group["scenes"],
            "proposed_warm": group["proposed_warm"], "proposed_on_demand": group["proposed_on_demand"],
            "capacity_unit": group["capacity_unit"], "rss_bytes": sum(rss) if all(v is not None for v in rss) else None,
            "cpu_percent_of_one_core": round(sum(cpu), 2) if all(v is not None for v in cpu) else None,
            "decision": "observe_only", "blockers": group["blockers"]})
    return {"schema_version": 1, "mode": "observe", "runtime_control_available": False,
        "live_state_checked": True, "observation": observation, "scene_observations": rows, "groups": groups,
        "effects": proposal["effects"], "actions": [],
        "limitations": ["CPU uses one core = 100%; RSS sums include shared pages and are not reclaimable-memory estimates.",
                        "Process presence does not prove preload, content readiness or free session capacity.",
                        "No automatic growth/retirement decisions; authoritative occupancy/reservations and lifecycle integration are pending."]}
