"""Turn correlated native Ord travel and group observations into typed actions."""

from .action_sequence import PAIR, validate

STATION = ("dungeon1", "npe_space_station")
ORD = "space_ord_mantell"
GROUP_COMMANDS = {
    "makeleader": "promote", "dismissgroupmember": "dismiss",
    "leavegroup": "leave", "disband": "disband",
}


def applies(events):
    return any(
        event["event"] in ("conversation_selected", "group_invite_sent", "group_join_sent", "group_state")
        or event["data"].get("selector") == "ord_launch_terminal"
        or str(event["data"].get("command", "")).lower() in {*GROUP_COMMANDS, "invite", "join"}
        for event in events
    )


def convert(events, actors):
    actions, problems = [], []
    state, conversations = {}, {}
    group, leader = None, None
    pending = None

    def problem(message):
        if message not in problems:
            problems.append(message)

    def finish():
        action = {"kind": pending["kind"], "actor": actors[pending["actor"]]["role"]}
        if action["kind"] in PAIR:
            action["peer"] = actors[pending["peer"]]["role"]
        actions.append(action)

    for event in events:
        kind, data, actor = event["event"], event["data"], event["actor"]
        if actor not in actors or type(data.get("capture_contract")) is not int or data["capture_contract"] != 2:
            problem("The event is outside the matching semantic recording and actor roster")
            continue
        scene = data.get("scene"), data.get("family"), data.get("room")

        if kind == "command_requested":
            name = str(data.get("command", "")).lower()
            if name in ("sitserver", "logoutserver", "npcconversationstop"):
                continue
            if name in ("npcconversationstart", "npcconversationselect"):
                seen = conversations.setdefault(actor, set())
                if name in seen:
                    problem("Overlapping conversations require separate clips")
                seen.add(name)
                continue
            if name == "join" and pending and pending.get("peer") == actor and pending.get("phase") == "invited":
                pending["phase"] = "joining"
                continue
            if pending:
                problem("Overlapping actions cannot be replayed as a sequence")
                continue
            if name == "invite" and not group and len(actors) == 2:
                pending = {"kind": "form_group", "actor": actor, "phase": "invite", "members": {}}
                continue
            action = GROUP_COMMANDS.get(name)
            if action and group and (action == "leave" or actor == leader):
                peer = data.get("target")
                if action in PAIR and (peer not in actors or peer == actor):
                    problem("Group command target is outside the recorded roster")
                    continue
                pending = {"kind": action, "actor": actor, "peer": peer, "members": {}}
            else:
                problem("No supported replay action for command " + (name[:64] or "(unknown)"))
            continue

        if kind == "group_invite_sent":
            peer = data.get("peer")
            if (pending and pending.get("phase") == "invite" and pending["actor"] == actor and
                    isinstance(peer, str) and peer in actors and peer != actor):
                pending.update(peer=peer, phase="invited")
            else:
                problem("Invitation did not resolve to the recorded companion")
            continue

        if kind == "group_join_sent":
            if (pending and pending.get("phase") == "joining" and pending.get("peer") == actor and
                    data.get("peer") == pending["actor"]):
                pending["phase"] = "joined"
            else:
                problem("Join did not consume the recorded invitation")
            continue

        if kind == "group_state":
            observed_group, observed_leader = data.get("group"), data.get("leader")
            if pending and pending.get("phase") == "joined" and observed_leader == pending["actor"] and observed_group not in (None, "0", ""):
                pending["members"][actor] = observed_group
                if len(pending["members"]) == 2 and len(set(pending["members"].values())) == 1:
                    group, leader = observed_group, observed_leader
                    finish()
                    pending = None
            elif (pending and pending["kind"] == "promote" and observed_group == group and
                    observed_leader == actor == pending["peer"]):
                leader = actor
                finish()
                pending = None
            elif pending and pending["kind"] in ("dismiss", "leave", "disband") and observed_group == "0" and observed_leader == "0":
                pending["members"][actor] = "0"
                if len(pending["members"]) == 2:
                    finish()
                    pending = group = leader = None
            else:
                problem("Group state changed without a matching recorded group action")
            continue

        if kind == "menu_selected" or kind == "conversation_selected":
            launch = (kind == "menu_selected" and data.get("selector") == "ord_launch_terminal" and
                      type(data.get("menu_type")) is int and data["menu_type"] == 21 and scene[:2] == STATION)
            land = kind == "conversation_selected" and data.get("response") == "ord_land" and scene[0] == ORD
            if land:
                conversations.pop(actor, None)
            if not pending and (launch or land):
                pending = {"kind": "launch" if launch else "land", "actor": actor}
                state[actor] = scene
            else:
                problem("Unsupported or overlapping travel request")
            continue

        if kind in ("scene_published", "loading_completed"):
            if pending and pending["actor"] == actor and pending["kind"] in ("launch", "land"):
                launch = pending["kind"] == "launch"
                arrived = scene[0] == ORD if launch else scene == (*STATION, "hangarbay1")
                if arrived:
                    finish()
                    pending = None
                elif state.get(actor) != scene:
                    problem("Travel reached a different scene or room")
            elif actor in state and scene != state[actor]:
                problem("Scene changed outside a matching recorded travel action")
            state[actor] = scene
        elif kind == "teleport_applied":
            if not pending or pending["actor"] != actor or pending["kind"] not in ("launch", "land"):
                problem("Teleport was observed without a supported initiating travel action")
        elif kind != "control_cleared":
            problem("No supported replay for event " + kind[:64])

    if pending or conversations:
        problem("An action lacks its recorded response or authoritative outcome")
    if not actions:
        problem("No complete Ord travel or group action was recorded")
    if len(actions) > 16:
        problem("Recording exceeds sixteen actions; select a shorter clip")
        actions = actions[:16]
    used = {action[key] for action in actions for key in ("actor", "peer") if key in action}
    roles = [value["role"] for value in actors.values() if value["role"] in used]
    options = {"roles": roles, "actions": actions}
    if actions:
        try:
            validate(options, roles)
        except ValueError as error:
            problem(str(error))
    return options, problems
