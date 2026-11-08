"""Compile only fully correlated supported observations; unknown actions stay blocked."""
import copy

from .journey import FAMILIES, PROMPT, ROOMS, state, validate as validate_journey


def station_state(data):
    return dict(state({key: data.get(key) for key in ("scene", "family", "room")}))


def convert(events):
    actions, problems = [], []
    pending = None
    previous = None
    def problem(message):
        if message not in problems:
            problems.append(message)
    for event in events:
        kind, data = event["event"], event["data"]
        if type(data.get("capture_contract")) is not int or data["capture_contract"] != 2:
            problem("Capture needs the matched version-2 semantic server hooks")
            continue
        if kind == "menu_selected":
            if pending:
                problem("Overlapping terminal requests cannot be correlated")
            try:
                source = station_state(data)
            except ValueError:
                problem("Terminal source is outside the supported public station families")
                pending = None
                continue
            if data.get("selector") != "gamma_shuttle" or type(data.get("menu_type")) is not int or data["menu_type"] != 21:
                problem("A recorded radial action has no supported stable selector")
                pending = None
                continue
            if previous is not None and source != previous:
                problem("Movement or a transition between recorded actions is not replayable")
            pending = dict(source=source, page=None, answer=None)
        elif kind == "sui_presented":
            if not pending or pending["page"] is not None or pending["answer"] is not None:
                problem("Dialog offer has no unique preceding terminal request")
            elif (data.get("prompt") != PROMPT or data.get("page_name") != "Script.messageBox" or
                  type(data.get("page")) is not int or data["page"] <= 0 or
                  any(data.get(key) != value for key, value in pending["source"].items())):
                problem("A recorded dialog offer is unsupported")
            else:
                pending["page"] = data["page"]
        elif kind == "sui_callback":
            if (not pending or pending["answer"] is not None or pending["page"] is None or
                    type(data.get("page")) is not int or data["page"] != pending["page"] or
                    data.get("prompt") != PROMPT or data.get("page_name") != "Script.messageBox" or
                    any(data.get(key) != value for key, value in pending["source"].items()) or
                    data.get("answer") not in ("ok", "cancel")):
                problem("Callback does not match the recorded offered confirmation")
            else:
                pending["answer"] = data["answer"]
                if pending["answer"] == "cancel":
                    expected = copy.deepcopy(pending["source"])
                    actions.append(make_action(pending, expected))
                    previous, pending = expected, None
        elif kind == "scene_published":
            try:
                destination = station_state(data)
            except ValueError:
                problem("A recorded scene is outside the supported station scope")
                continue
            if pending and pending["answer"] == "ok":
                if destination["family"] == pending["source"]["family"] or destination["room"] != ROOMS[destination["family"]]:
                    problem("Confirmed shuttle did not reach its authored opposite-family entrance")
                else:
                    actions.append(make_action(pending, destination))
                    previous, pending = destination, None
            elif pending:
                problem("Scene changed before the terminal confirmation was consumed")
            elif previous is not None and destination != previous:
                problem("Unexplained scene change has no supported recorded action")
            else:
                previous = destination
        elif kind == "command_requested":
            if data.get("command") not in ("sitServer", "logoutServer"):
                problem("A queued command is not supported by recorded shuttle replay")
        elif kind == "control_cleared":
            pass  # Handoff/logout observation, not an inferred travel success.
        elif kind == "movement_requested":
            problem("Movement replay is pending; start recording beside the terminal and stay still")
        else:
            problem("Unsupported recorded event: " + kind[:48])
    if pending:
        problem("The recorded terminal interaction or arrival did not finish")
    if not actions:
        problem("No complete supported terminal interaction was recorded")
    if len(actions) > 16:
        problem("Recording exceeds sixteen replayable terminal interactions")
    return actions[:16], problems[:128]


def make_action(pending, expected):
    return dict(kind="radial_dialog", selector="gamma_shuttle", menu_type=21, prompt=PROMPT,
                answer=pending["answer"], source=pending["source"], expected=expected, timeout_seconds=120)
