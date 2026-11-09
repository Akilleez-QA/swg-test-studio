"""Validate coordinated local stop evidence before acknowledging generations.

Called by the shared management backend while it holds the mutation lock.
No silence/heartbeat timeout is accepted as evidence that a worker stopped.
"""
from runtime_policy import JOURNALS, INSTANCE_ROOT, ADMISSION_ROOT, FALCON, mounts, journal_definitions


def prove_stopped(compose, containers, attached, initialize=False):
    if compose.get("name") != "starwarsgalaxies":
        raise ValueError("Instance maintenance requires the canonical local project")
    mounts(compose)
    for key, volume, target in JOURNALS.values():
        if compose.get("volumes", {}).get(key) != {"name": volume, "external": True}:
            raise ValueError("Missing existing persistent journal volume: " + volume)
    ids = set()
    for item in containers:
        labels = item.get("Config", {}).get("Labels") or {}
        role = labels.get("com.docker.compose.service")
        if (labels.get("com.docker.compose.project") != "starwarsgalaxies" or
                role not in compose["services"] or labels.get("com.docker.compose.oneoff", "False").lower() != "false"):
            raise ValueError("Unrecognized supervisor/container in instance maintenance proof")
        ids.add(item["Id"])
        if role == "oracle":
            continue
        state = item.get("State", {})
        if (state.get("Status") not in ("created", "exited") or state.get("Running") is not False or
                state.get("Paused") is not False or state.get("Restarting") is not False or state.get("Pid") != 0):
            raise ValueError("All game workers and supervisors must be stopped: " + role)
        if role in JOURNALS:
            key, volume, target = JOURNALS[role]
            actual = [m for m in item.get("Mounts", []) if m.get("Destination") == target]
            if not (initialize and not actual) and (len(actual) != 1 or actual[0].get("Type") != "volume" or actual[0].get("Name") != volume):
                raise ValueError("Stopped " + role + " used a different journal mount")
    if any(item.get("Id") not in ids for item in attached):
        raise ValueError("A container outside the stopped project uses a persistent journal")
    return {"schema_version": 2, "project": "starwarsgalaxies", "journal_volumes": [row[1] for row in JOURNALS.values()],
            "stopped_container_ids": sorted(item["Id"] for item in containers
                if item["Config"]["Labels"].get("com.docker.compose.service") != "oracle"),
            "oracle_stopped": False, "identities_retained": True}


def command(image, initialize=False, state=None):
    """Return only the fixed journal operation; callers prove stop first."""
    volume = JOURNALS["central"][1]
    return ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--volume", volume + ":/capacity-journal", "--entrypoint", "/opt/whitengold/bin/instance-journal",
            image, "--initialize" if initialize else "--acknowledge-stopped", INSTANCE_ROOT] + ([] if initialize else journal_definitions(state) or [FALCON])


def admission_command(image, initialize=False, family_logins=False):
    """Caller proves all executors stopped; utility retains durable receipts."""
    return ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--volume", JOURNALS["central"][1] + ":/capacity-journal", "--entrypoint", "/opt/whitengold/bin/instance-journal",
            image, ("--initialize-family-logins" if initialize else "--acknowledge-family-logins-stopped") if family_logins else
            ("--initialize-admission" if initialize else "--acknowledge-admission-stopped"),
            "/capacity-journal/family-logins" if family_logins else ADMISSION_ROOT]


def login_command(image):
    """Call only after stopped-container AND idle-database proofs, under the lock."""
    return ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--volume", JOURNALS["database"][1] + ":/login-journal", "--entrypoint", "/opt/whitengold/bin/instance-journal",
            image, "--acknowledge-login-stopped", "/login-journal/records"]


def database_idle(container, evidence):
    """Read-only Oracle proof: no game sessions, transactions or rollback work.

    The caller verifies this container's identity/persistent storage. No session
    kill or forced rollback is issued; a non-idle database blocks maintenance.
    """
    import json
    import subprocess
    sql = """set echo off verify off heading off feedback off pagesize 0 linesize 32767
whenever oserror exit failure
whenever sqlerror exit failure
alter session set container=FREEPDB1;
select json_object(
 'game_sessions' value (select count(*) from v$session where username='BUILDCLUSTER'),
 'transactions' value (select count(*) from v$transaction),
 'recovering_transactions' value (select count(*) from v$fast_start_transactions)) from dual;
exit;
"""
    result = subprocess.run(["docker", "exec", "-i", "--user", "oracle", container,
                             "sqlplus", "-s", "/ as sysdba"], input=sql, text=True, capture_output=True, timeout=60)
    evidence.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError("Unable to establish idle Oracle; leave game services stopped")
    state = json.loads(result.stdout.strip())
    if (set(state) != {"game_sessions", "transactions", "recovering_transactions"} or
            any(type(value) is not int or value != 0 for value in state.values())):
        raise ValueError("Oracle still has sessions/transactions; leave game services stopped")
    return state
