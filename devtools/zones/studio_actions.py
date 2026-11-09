"""Bounded Studio action plans executed by the existing isolated protocol scenario."""

import json
import time

SOLO = ("null", "0")
SHIP_ACTIONS = {"launch", "land"}
PAIR_ACTIONS = {"form_group", "promote", "dismiss"}
GROUP_ACTIONS = PAIR_ACTIONS | {"leave", "disband"}


def load(path, registries):
    if path.stat().st_size > 16384:
        raise ValueError("Studio action plan exceeds 16 KiB")
    plan = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(plan, dict) or set(plan) != {"schema_version", "actions"} or
            type(plan["schema_version"]) is not int or plan["schema_version"] != 1):
        raise ValueError("Unsupported Studio action plan")
    actions = plan["actions"]
    if (not isinstance(actions, list) or not 1 <= len(actions) <= 16 or
            not 1 <= len(registries) <= 2 or len(set(registries)) != len(registries)):
        raise ValueError("Studio plans require 1–16 actions and one or two distinct registries")
    used = set()
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("kind"), str):
            raise ValueError("Typed Studio action required")
        kind = action["kind"]
        fields = {"kind", "actor"} | ({"peer"} if kind in PAIR_ACTIONS else set())
        if kind not in SHIP_ACTIONS | GROUP_ACTIONS or set(action) != fields:
            raise ValueError("Unknown Studio action or fields")
        actor = action["actor"]
        if not isinstance(actor, str) or actor not in registries:
            raise ValueError("Studio actor must be in the dedicated roster")
        used.add(actor)
        if kind in GROUP_ACTIONS and len(registries) != 2:
            raise ValueError("Group replay requires two dedicated registries")
        if kind in PAIR_ACTIONS:
            peer = action["peer"]
            if not isinstance(peer, str) or peer == actor or peer not in registries:
                raise ValueError("A different dedicated peer is required")
            used.add(peer)
    if used != set(registries):
        raise ValueError("Every Studio registry must be used by an action")
    return actions


def station(row):
    return row.get("scene") == "dungeon1" and row.get("family") == "npe_space_station"


def solo(row):
    return row.get("group") in SOLO


def wait_solo(case):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if all(solo(case.row(key)) for key in case.bots):
            return
        time.sleep(.25)
    raise TimeoutError("Both recorded group members must leave the group")


def group_action(case, action, rows):
    from protocol_scenarios import matching_group

    actor = action["actor"]
    peer = next(key for key in case.bots if key != actor)
    kind = action["kind"]
    if kind == "form_group":
        if not all(solo(row) for row in rows.values()):
            raise RuntimeError("Both replay actors must be solo before inviting")
        case.group(actor, peer)
        return

    leader = rows[actor]["leader"]
    if not matching_group(rows[actor], rows[peer], leader):
        raise RuntimeError("Current group is not the exact two-actor replay group")
    if kind != "leave" and leader != case.bots[actor]["player"]:
        raise RuntimeError("The recorded actor must lead the replay group")
    if kind == "promote":
        case.promote(actor, peer)
        return

    command = {"leave": "leaveGroup", "disband": "disband", "dismiss": "dismissGroupMember"}[kind]
    if kind == "dismiss":
        command += " " + case.bots[peer]["player"]
    stamp = time.monotonic()
    case.sessions[actor].send(command)
    case.sessions[actor].wait("group_command", 10, after=stamp)
    wait_solo(case)


def execute(case, actions):
    """Each checked action is distinct from explicit test positioning and cleanup."""
    from protocol_scenarios import matching_group, owned_ship

    initial = {key: case.row(key) for key in case.bots}
    if any(not solo(row) for row in initial.values()):
        raise RuntimeError("Studio replay actors must start ungrouped")
    for key, row in initial.items():
        if not station(row) and not owned_ship(row, case.bots[key], case.ships.get(key)):
            raise RuntimeError("Studio replay requires Tansaari or the actor's tracked Ord ship")
    case.report["studio_started_solo"] = True
    for index, action in enumerate(actions, 1):
        key, kind = action["actor"], action["kind"]
        print(f"STUDIO_STEP start {index} {kind}", flush=True)
        rows = {name: case.row(name) for name in case.bots}
        if any(row.get("combat") != "0" for row in rows.values()):
            raise RuntimeError("Studio replay requires quiet actors before the action")
        if kind == "launch":
            if not station(rows[key]):
                raise RuntimeError("Launch requires the actor at Tansaari")
            case.launch(key, case.setup_pilot(key, expected_ship=case.ships.get(key)))
        elif kind == "land":
            if not owned_ship(rows[key], case.bots[key], case.ships.get(key)):
                raise RuntimeError("Landing requires the actor piloting the tracked original ship")
            arrival = case.land(key)
            if not station(arrival) or arrival.get("room") != "hangarbay1":
                raise RuntimeError("Landing must settle in the authored Tansaari hangar")
        else:
            group_action(case, action, rows)
        after = case.record(f"studio_{index}_{kind}")
        if kind in SHIP_ACTIONS and len(rows) == 2 and not solo(rows[key]):
            peer = next(name for name in rows if name != key)
            if (not matching_group(after[key], after[peer], rows[key]["leader"]) or
                    after[key]["group"] != rows[key]["group"]):
                raise RuntimeError("Travel did not preserve the recorded two-actor group")
            if (after[key]["scene"] == after[peer]["scene"] == "space_ord_mantell" and
                    after[key]["instance"] != after[peer]["instance"]):
                raise RuntimeError("The two actors reached different Ord instances")
        print(f"STUDIO_STEP pass {index} {kind}", flush=True)
    cleanup_group(case)
    # The legacy lifecycle performs ordinary ground logout with exact save checks.
    for key in case.bots:
        row = case.row(key)
        if row.get("scene") == "space_ord_mantell":
            case.report["setup"].append({"bot": key, "kind": "studio_cleanup_landing"})
            case.land(key)
    case.record("studio_final_ground_save")


def cleanup_group(case):
    rows = {key: case.row(key) for key in case.bots}
    if all(solo(row) for row in rows.values()):
        return
    leader = next((key for key, row in rows.items() if row["leader"] == case.bots[key]["player"]), None)
    if leader is None or len(rows) != 2:
        raise RuntimeError("Could not prove the exact Studio group for cleanup")
    case.report["setup"].append({"bot": leader, "kind": "studio_cleanup_disband"})
    group_action(case, {"kind": "disband", "actor": leader}, rows)
