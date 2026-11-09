"""Typed Ord travel and two-character group sequences."""

from .model import exact

PAIR = {"form_group", "promote", "dismiss"}
GROUP = PAIR | {"leave", "disband"}
KINDS = GROUP | {"launch", "land"}


def validate(options, declared_roles):
    exact(options, ("roles", "actions"), "action sequence")
    roles, actions = options["roles"], options["actions"]
    if (not isinstance(roles, list) or not 1 <= len(roles) <= 2 or
            any(not isinstance(role, str) or role not in declared_roles for role in roles) or
            len(set(roles)) != len(roles)):
        raise ValueError("Select one or two distinct declared roles")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 16:
        raise ValueError("Define one to sixteen typed actions")
    used = set()
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("kind"), str):
            raise ValueError("Typed action required")
        kind = action["kind"]
        if kind not in KINDS:
            raise ValueError("Unknown recorded action")
        exact(action, ("kind", "actor", "peer") if kind in PAIR else ("kind", "actor"), "recorded action")
        actor = action["actor"]
        if not isinstance(actor, str) or actor not in roles or (kind in GROUP and len(roles) != 2):
            raise ValueError("Action requires a declared actor and an exact two-role group roster")
        used.add(actor)
        if kind in PAIR:
            peer = action["peer"]
            if not isinstance(peer, str) or peer not in roles or peer == actor:
                raise ValueError("Choose a different recorded peer")
            used.add(peer)
    if used != set(roles):
        raise ValueError("Every role must participate in a recorded action")
    return options


def command(options, env, bindings, output, identifier):
    from pathlib import Path
    import sys

    from .store import write_json

    roles = options["roles"]
    validate(options, roles)
    actions = []
    for action in options["actions"]:
        bound = dict(action, actor=bindings[action["actor"]])
        if "peer" in action:
            bound["peer"] = bindings[action["peer"]]
        actions.append(bound)
    path = output / (identifier + "-actions.json")
    write_json(path, {"schema_version": 1, "actions": actions})
    return [
        sys.executable, str(Path(env["server_checkout"]) / "devtools/zones/protocol_scenarios.py"),
        "--folder", env["folder"], "--binary", env["binary"], "--bots",
        *(bindings[role] for role in roles), "--studio-actions", str(path),
    ]
