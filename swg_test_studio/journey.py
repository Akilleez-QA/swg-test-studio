"""Typed single-character radial/dialog journeys using the existing protocol peer."""
import math
import re
import time

FAMILIES = ("npe_space_station", "npe_space_dungeon")
PROMPT = "@npe:gamma_shuttle_prompt"
ROOMS = {"npe_space_station": "hangarbay1", "npe_space_dungeon": "cave_entrance"}


def state(value):
    from .model import exact
    exact(value, ("scene", "family", "room"), "journey-state")
    if (value["scene"] != "dungeon1" or value["family"] not in FAMILIES or
            not isinstance(value["room"], str) or not re.fullmatch(r"[a-z0-9_]{1,48}", value["room"])):
        raise ValueError("Journey requires an authored public station family and room")
    return value


def validate(options, roles):
    from .model import exact
    extra = ("prepare_between_actions",) if "prepare_between_actions" in options else ()
    exact(options, ("role", "prepare_start", "actions") + extra, "journey")
    if extra and type(options["prepare_between_actions"]) is not bool:
        raise ValueError("Explicit between-action setup Boolean required")
    if options["role"] not in roles or type(options["prepare_start"]) is not bool:
        raise ValueError("Journey requires a declared role and explicit setup choice")
    actions = options["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= 16:
        raise ValueError("Define 1–16 sequential journey actions")
    previous = None
    for action in actions:
        exact(action, ("kind", "selector", "menu_type", "prompt", "answer", "source", "expected", "timeout_seconds"), "journey-action")
        if (action["kind"] != "radial_dialog" or action["selector"] != "gamma_shuttle" or
                type(action["menu_type"]) is not int or action["menu_type"] != 21 or action["prompt"] != PROMPT or
                action["answer"] not in ("ok", "cancel") or type(action["timeout_seconds"]) is not int or
                not 10 <= action["timeout_seconds"] <= 120):
            raise ValueError("Only the original Gamma radial/confirmation contract is supported")
        source, expected = state(action["source"]), state(action["expected"])
        if previous is not None and source != previous:
            raise ValueError("Journey actions have inconsistent source/destination states")
        if action["answer"] == "cancel":
            if expected != source:
                raise ValueError("Cancel must preserve the source state")
        elif expected["family"] == source["family"] or expected["room"] != ROOMS[expected["family"]]:
            raise ValueError("Confirm must use the original opposite-family shuttle entrance")
        previous = expected
    return options


def matches(row, expected):
    return all(row.get(key) == value for key, value in expected.items())


def safe_row(row):
    try:
        positioned = (all(math.isfinite(float(row.get(key, "nan"))) for key in ("x", "y", "z")) and
                      re.fullmatch(r"-?[1-9][0-9]{0,18}", row.get("cell", "")) is not None and
                      re.fullmatch(r"[0-9]{1,20}", row.get("instance", "")) is not None)
    except (ValueError, TypeError):
        positioned = False
    return (row.get("connected") == "true" and row.get("pending") == "false" and
            row.get("outstanding") == "false" and row.get("protected") == "false" and positioned)


class Journey:
    """Protocol decisions are testable with a peer adapter; commands remain typed."""
    def __init__(self, peer, query, clock=time.monotonic, sleep=time.sleep, complete_arrival=None):
        self.peer, self.query, self.clock, self.sleep = peer, query, clock, sleep
        self.complete_arrival = complete_arrival

    def run(self, options, *, trace=None):
        validate(options, [options["role"]])
        if options["prepare_start"]:
            self.prepare(options["actions"][0]["source"])
        for index, action in enumerate(options["actions"]):
            label = "cancel_shuttle" if action["answer"] == "cancel" else "confirm_shuttle"
            if trace:
                trace("start", index + 1, label)
            if index and options.get("prepare_between_actions", False):
                row = self.row()
                if (not matches(row, action["source"]) or row.get("group") not in ("null", "0") or
                        row.get("combat") != "0"):
                    raise RuntimeError("Between-action setup requires the expected solo, quiet source")
                self.position()
            self.action(action)
            if trace:
                trace("pass", index + 1, label)

    def row(self):
        row = self.peer.row()
        if not safe_row(row):
            raise RuntimeError("Journey actor has not settled")
        return row

    def wait_state(self, expected, timeout):
        end = self.clock() + timeout
        while self.clock() < end:
            row = self.query("botInspect")
            if row and matches(row, expected) and safe_row(row):
                return row
            self.sleep(.25)
        raise TimeoutError("Expected authored shuttle arrival did not settle")

    def prepare(self, initial):
        row = self.row()
        if row.get("group") not in ("null", "0") or row.get("combat") != "0" or row.get("family") not in FAMILIES:
            raise RuntimeError("Shuttle setup requires an ungrouped, quiet public-station actor")
        if row["family"] != initial["family"]:
            self.position()
            current = self.row()
            source = {key: current[key] for key in ("scene", "family", "room")}
            action = dict(kind="radial_dialog", selector="gamma_shuttle", menu_type=21, prompt=PROMPT, answer="ok",
                          source=source, expected=dict(scene="dungeon1", family=initial["family"], room=ROOMS[initial["family"]]), timeout_seconds=120)
            self.peer.report["setup"].append({"kind": "normal_shuttle_return_to_recorded_source"})
            self.action(action, setup=True)
        self.position()
        if not matches(self.row(), initial):
            raise RuntimeError("Prepared entrance differs from the recorded source room")

    def position(self):
        preview = self.query("botTerminals")
        if (not preview or preview.get("protocol_bot") != "terminal" or preview.get("selector") != "gamma_shuttle" or
                preview.get("terminal_metadata") != "2"):
            raise RuntimeError("Unique terminal preview unavailable; no setup performed")
        result = self.query("botPrepare")
        self.peer.report["setup"].append({"kind": "explicit_terminal_proximity", "preview": preview, "result": result})
        if not preview or not result or result.get("accepted") != "true" or result.get("target") != preview.get("target"):
            raise RuntimeError("Explicit terminal-proximity setup refused")
        stamp = self.clock()
        self.peer.session.send("awaitReady")
        self.peer.session.wait("action_ready", 30, after=stamp)
        self.row()

    def action(self, action, *, setup=False):
        before = self.row()
        if (not matches(before, action["source"]) or before.get("group") not in ("null", "0") or
                before.get("combat") != "0"):
            raise RuntimeError("Journey source or solo/quiet precondition differs")
        target = self.query("botTerminals")
        if (not target or target.get("protocol_bot") != "terminal" or target.get("selector") != action["selector"] or
                target.get("terminal_metadata") != "2" or
                target.get("scene") != before["scene"] or target.get("family") != before["family"] or
                target.get("cell") != before.get("cell") or target.get("same_cell") != "true" or
                not re.fullmatch(r"-?[1-9][0-9]{0,18}", target.get("target", ""))):
            raise RuntimeError("Unique current-copy terminal selector could not be proven")
        distance = float(target.get("distance", "nan"))
        if not math.isfinite(distance) or not 0 <= distance <= 8:
            raise RuntimeError("Actor is outside the recorded terminal interaction range")
        session = self.peer.session
        stamp = self.clock()
        session.send("menu " + target["target"])
        menu = session.wait("menu", 15, after=stamp)
        if menu.get("target") != target["target"] or action["menu_type"] not in [r["type"] for r in menu.get("items", [])]:
            raise RuntimeError("Required terminal action was not offered")
        stamp = self.clock()
        session.send("select " + target["target"] + " " + str(action["menu_type"]))
        deadline = self.clock() + 15
        while True:
            page = session.wait("sui", max(.01, deadline - self.clock()), after=stamp)
            if page.get("name") == "Script.messageBox" and any(
                    p.get("widget") == "Prompt.lblPrompt" and p.get("property") == "Text" and
                    p.get("value") == action["prompt"] for p in page.get("properties", [])):
                break
            if self.clock() >= deadline:
                raise TimeoutError("The expected current confirmation was not offered")
        page_id = page.get("page")
        if type(page_id) is not int or page_id <= 0:
            raise RuntimeError("Invalid live dialog page identity")
        pending = self.query("botInspect")
        if not pending or pending.get("gamma_dialog_pending") != "true" or not matches(pending, action["source"]):
            raise RuntimeError("Current original shuttle dialog is not pending on this actor")
        stamp = self.clock()
        session.send("answer " + str(page_id) + " " + action["answer"])
        session.wait("sui_answered", 10, after=stamp)
        if action["answer"] == "cancel":
            end = self.clock() + action["timeout_seconds"]
            while self.clock() < end:
                after = self.query("botInspect")
                if after and after.get("gamma_dialog_pending") == "false":
                    break
                self.sleep(.25)
            else:
                raise TimeoutError("Server did not consume the cancelled dialog")
            if (not safe_row(after) or not matches(after, action["expected"]) or after.get("instance") != before.get("instance") or
                    after.get("cell") != before.get("cell") or any(
                    not math.isfinite(float(after.get(k, "nan"))) or not math.isfinite(float(before.get(k, "nan"))) or
                    abs(float(after[k]) - float(before[k])) > .01 for k in ("x", "y", "z"))):
                raise RuntimeError("Cancel changed the actor's location")
        else:
            if self.complete_arrival is None:
                raise RuntimeError("Matching driver ground-loading adapter required")
            loading = self.complete_arrival(session, self.query, action["expected"], action["timeout_seconds"])
            if loading["readiness"].get("scene") != "terrain/dungeon1.trn":
                raise RuntimeError("Client readiness reports an unexpected destination scene")
            after = self.wait_state(action["expected"], action["timeout_seconds"])
            self.peer.report.setdefault("loading", []).append(loading)
        self.peer.report["checks"].append({"kind": "radial_dialog", "setup": setup, "selector": action["selector"],
                                            "answer": action["answer"], "before": before, "after": after})
        return after


def run_live(options, env, registry):
    validate(options, [options["role"]])
    from .backend import driver_modules
    from .server_tools import load_tool

    driver, _ = driver_modules(env)
    retained_peer = load_tool("teststudio_server/retained_peer.py")
    if getattr(retained_peer, "PROTOCOL_PEER_VERSION", None) != 1:
        raise ValueError("Unexpected retained-peer adapter")
    with retained_peer.open_peer(env["folder"], env["binary"], registry) as peer:
        engine = Journey(peer, lambda command: driver.bot_query(peer.project, peer.bot, command),
                         complete_arrival=driver.complete_ground_arrival)
        engine.run(options, trace=lambda state, index, label: print(f"STUDIO_STEP {state} {index} {label}", flush=True))
    import hashlib
    result = peer.evidence / "result.json"
    return {"path": str(result), "sha256": hashlib.sha256(result.read_bytes()).hexdigest()}
