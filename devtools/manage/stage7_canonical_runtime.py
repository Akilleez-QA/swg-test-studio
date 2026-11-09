"""Canonical Stage 7 shutdown wiring for the reviewed SWG role topology.

The accepted game binaries use the durable capacity journal. Each local
TaskManager also needs its own persistent launch-fence directory before
Central may enable automatic retirement.
"""
import re

BEGIN = "# stage7-distributed begin"
END = "# stage7-distributed end"
FENCE_TARGET = "/world-launch-fences"
FENCE_ROOT = "/capacity-journal/launch-fences"
NODES = ("taskmanager", "central", "connection", "database", "planet",
         "game", "chat", "log", "metrics", "commodities")
OWNED = {"capacityDistributedShutdownEnabled", "capacityShutdownNode",
         "capacityWorkerFreezeEnabled", "capacityLaunchFenceEnabled",
         "capacityLaunchFenceRoot", "restartCentral"}


def _nodes(nodes):
    nodes = tuple(nodes)
    if nodes != NODES:
        raise ValueError("Exact canonical shutdown-node topology required")
    return nodes


def config(text, role, enabled, nodes):
    """Replace only our owned block; a malformed or foreign key fails closed."""
    nodes = _nodes(nodes)
    if type(enabled) is not bool or role not in nodes and role != "login":
        raise ValueError("Invalid canonical retirement role or setting")
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError("Malformed Stage 7 config block")
    clean = re.sub(r"(?ms)^" + re.escape(BEGIN) + r"\n.*?^" + re.escape(END) + r"\n?", "", text)
    if any(line.partition("=")[0].strip() in OWNED for line in clean.splitlines()):
        raise ValueError("Unowned distributed-shutdown setting in canonical config")
    if not enabled:
        return clean
    lines = [BEGIN]
    if role == "central":
        lines += ["[CentralServer]", "capacityDistributedShutdownEnabled=true"]
        lines += ["capacityShutdownNode=node%d" % index for index in range(len(nodes))]
    if role == "game":
        lines += ["[GameServer]", "capacityWorkerFreezeEnabled=true"]
    if role in nodes:
        root = FENCE_ROOT if role == "central" else FENCE_TARGET + "/launch-fences"
        lines += ["[TaskManager]", "restartCentral=false",
                  "capacityDistributedShutdownEnabled=true", "capacityLaunchFenceEnabled=true",
                  "capacityLaunchFenceRoot=%s/node%d" % (root, nodes.index(role))]
    lines.append(END)
    return clean.rstrip("\n") + "\n" + "\n".join(lines) + "\n"


def mounts(compose, enabled, nodes, install=False):
    """Use the existing private capacity volume for each node's fence root."""
    nodes = _nodes(nodes)
    if type(enabled) is not bool or compose.get("name") != "starwarsgalaxies":
        raise ValueError("Exact canonical retirement Compose project required")
    if compose.get("volumes", {}).get("capacity_journal") != {
            "name": "starwarsgalaxies_capacity_journal", "external": True}:
        raise ValueError("Persistent canonical capacity journal required")
    for role in nodes:
        service = compose["services"][role]
        values = service.get("volumes", [])
        if role == "central":
            expected = {"type": "volume", "source": "capacity_journal", "target": "/capacity-journal"}
            if [v for v in values if v.get("target") == "/capacity-journal"] != [expected]:
                raise ValueError("Central capacity-journal mount changed")
            continue
        expected = {"type": "volume", "source": "capacity_journal", "target": FENCE_TARGET}
        found = [v for v in values if v.get("target") == FENCE_TARGET or
                 v.get("source") == "capacity_journal"]
        if found and found != [expected]:
            raise ValueError("Unexpected launch-fence mount for " + role)
        if enabled and install and not found:
            values.append(expected)
    return compose


def initialize_command(image, nodes):
    """Create missing private directories only; never remove a fence."""
    nodes = _nodes(nodes)
    script = ("set -eu; root=/capacity-journal/launch-fences; "
              "[ ! -L \"$root\" ]; "
              "if [ ! -e \"$root\" ]; then mkdir -m 700 \"$root\"; fi; "
              "[ -d \"$root\" ] && [ \"$(stat -c %a \"$root\")\" = 700 ]; "
              "for node do path=\"$root/$node\"; [ ! -L \"$path\" ]; "
              "if [ ! -e \"$path\" ]; then mkdir -m 700 \"$path\"; fi; "
              "[ -d \"$path\" ] && [ \"$(stat -c %a \"$path\")\" = 700 ]; done")
    return ["docker", "run", "--rm", "--pull", "never", "--network", "none",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--volume", "starwarsgalaxies_capacity_journal:/capacity-journal",
            "--entrypoint", "/bin/sh", image, "-ceu", script, "--"] + [
                "node%d" % index for index in range(len(nodes))]
