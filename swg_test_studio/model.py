"""Strict, non-executable suite data shared by the desktop and CLI."""
import copy
import json
import re

FORMAT = "swg-test-studio"
NAME = re.compile(r"[a-z][a-z0-9_]{2,63}\Z")
ROLE = re.compile(r"[a-z]{3,16}\Z")
RECIPES = {"station_shuttle": ("actor",), "ship_group": ("leader", "member"),
           "stage7_group_disband": ("leader", "member", "newleader"), "driver_unit": ()}
SESSION_OPTIONS = {"create": bool, "disconnect": bool, "prepare_terminal": bool,
                   "stage_station": bool, "expect_scene": str, "expect_family": str,
                   "answer": str}

# Client-side actions of a held protocol peer (docs/fixture-client-actions.md). Each kind names the fields it
# takes besides "role" and "kind". Every kind is grounded in the server tree: group kinds are rows of the
# command table sent as a command-queue request, trade kinds are the secure-trade messages the game server's
# Client and CreatureController handle. CLIENT_WIRE records that grounding; tests check it against the tree.
CLIENT_KINDS = {
    "session_hold": (), "session_release": (),
    "group_invite": ("peer",), "group_join": ("peer",), "group_decline": (), "group_uninvite": ("peer",),
    "group_leave": (), "group_disband": (), "group_make_leader": ("peer",), "group_dismiss": ("peer",),
    "trade_request": ("peer",), "trade_accept": (), "trade_deny": (),
    "trade_add_item": ("item",), "trade_credits": ("amount",),
    "trade_offer": (), "trade_unoffer": (), "trade_verify": (), "trade_reject": (), "trade_cancel": (),
}
CLIENT_WIRE = {
    "session_hold": ("peer", "login"), "session_release": ("message", "LogoutMessage"),
    "group_invite": ("command", "invite"), "group_join": ("command", "join"),
    "group_decline": ("command", "decline"), "group_uninvite": ("command", "uninvite"),
    "group_leave": ("command", "leaveGroup"), "group_disband": ("command", "disband"),
    "group_make_leader": ("command", "makeLeader"), "group_dismiss": ("command", "dismissGroupMember"),
    "trade_request": ("trade", "TMI_RequestTrade"), "trade_accept": ("trade", "TMI_AcceptTrade"),
    "trade_deny": ("trade", "TMI_DeniedTrade"),
    "trade_add_item": ("message", "AddItemMessage"), "trade_credits": ("message", "GiveMoneyMessage"),
    "trade_offer": ("message", "AcceptTransactionMessage"), "trade_unoffer": ("message", "UnAcceptTransactionMessage"),
    "trade_verify": ("message", "VerifyTradeMessage"), "trade_reject": ("message", "DenyTradeMessage"),
    "trade_cancel": ("message", "AbortTradeMessage"),
}
CLIENT_ITEM = re.compile(r"[1-9][0-9]{0,18}\Z")
TRADE_CREDITS_MAX = 1000000  # GiveMoneyMessage carries an int; the server ignores a negative amount
MAX_HELD_SESSIONS = 5        # one held peer per declared role; a suite declares at most five roles


def validate_client(options, roles):
    """One typed client action; the order rules across steps are checked by client_order."""
    kind = options.get("kind") if isinstance(options, dict) else None
    if not isinstance(kind, str) or kind not in CLIENT_KINDS:
        raise ValueError("Unknown client action; only the typed group, trade and session actions are supported")
    exact(options, ("role", "kind") + CLIENT_KINDS[kind], "client action")
    if options["role"] not in roles:
        raise ValueError("Client actions need a declared role")
    if "peer" in options and (not isinstance(options["peer"], str) or options["peer"] not in roles or
                              options["peer"] == options["role"]):
        raise ValueError("A client action's peer must be a different declared role")
    if "item" in options and (not isinstance(options["item"], str) or not CLIENT_ITEM.fullmatch(options["item"])):
        raise ValueError("A traded item is one object ID")
    if "amount" in options and (type(options["amount"]) is not int or
                                not 0 < options["amount"] <= TRADE_CREDITS_MAX):
        raise ValueError(f"Trade credits must be a whole number from 1 to {TRADE_CREDITS_MAX}")
    return options


def client_order(steps):
    """Static order rules for the client steps of one suite (sessions, groups, one trade per pair)."""
    held, invites, leader_of, trades = set(), {}, {}, {}

    def require(condition, why):
        if not condition:
            raise ValueError(why)

    def group(role):
        return {r for r, lead in leader_of.items() if lead == leader_of.get(role)} if role in leader_of else set()

    def drop(role):
        lead = leader_of.pop(role)
        rest = {r for r, l in leader_of.items() if l == lead}
        if len(rest) < 2:
            for r in rest:
                del leader_of[r]
        elif role == lead:
            new = sorted(rest)[0]
            for r in rest:
                leader_of[r] = new

    for step in steps:
        if step["action"] == "session" and step["options"].get("role") in held:
            raise ValueError("A held role cannot also run a separate session step until it is released")
        if step["action"] != "client":
            continue
        o = step["options"]
        kind, actor, peer = o["kind"], o["role"], o.get("peer")
        if kind == "session_hold":
            require(actor not in held, "This role is already held")
            held.add(actor)
            continue
        require(actor in held and (peer is None or peer in held), "Hold both roles' sessions before a client action")
        trade = next((t for t in trades if actor in t), None)
        if kind == "session_release":
            require(trade is None, "Cancel or complete the open trade before releasing a session")
            if actor in leader_of:
                drop(actor)
            invites = {k: v for k, v in invites.items() if actor not in (k, v)}
            held.discard(actor)
        elif kind == "group_invite":
            require(peer not in group(actor) and peer not in leader_of and
                    (actor not in leader_of or leader_of[actor] == actor), "Only a leader or a solo role invites a solo role")
            invites[peer] = actor
        elif kind == "group_join":
            require(invites.get(actor) == peer, "Join needs an open invitation from that peer")
            del invites[actor]
            leader_of.setdefault(peer, peer)
            leader_of[actor] = leader_of[peer]
        elif kind == "group_decline":
            require(actor in invites, "Decline needs an open invitation")
            del invites[actor]
        elif kind == "group_uninvite":
            require(invites.get(peer) == actor, "Uninvite needs this role's open invitation to that peer")
            del invites[peer]
        elif kind == "group_leave":
            require(actor in leader_of, "Leave needs a group")
            drop(actor)
        elif kind in ("group_disband", "group_make_leader", "group_dismiss"):
            require(leader_of.get(actor) == actor, "Only the group leader can do this")
            members = group(actor)
            if kind == "group_disband":
                for r in members:
                    del leader_of[r]
            else:
                require(peer in members, "The peer must be in the leader's group")
                if kind == "group_make_leader":
                    for r in members:
                        leader_of[r] = peer
                else:
                    drop(peer)
        elif kind == "trade_request":
            require(trade is None and not any(peer in t for t in trades), "Each role trades with one peer at a time")
            trades[(actor, peer)] = {"state": "requested", "offered": set(), "verified": set()}
        else:
            require(trade is not None, "This client action needs an open trade")
            row = trades[trade]
            if kind in ("trade_accept", "trade_deny"):
                require(row["state"] == "requested" and actor == trade[1], "Only the requested peer answers a trade request")
                if kind == "trade_deny":
                    del trades[trade]
                else:
                    row["state"] = "trading"
            elif kind == "trade_cancel":
                del trades[trade]
            else:
                require(row["state"] == "trading", "The trade has not been accepted yet")
                if kind in ("trade_add_item", "trade_credits", "trade_unoffer", "trade_reject"):
                    row["offered"].clear()
                    row["verified"].clear()
                elif kind == "trade_offer":
                    row["offered"].add(actor)
                else:  # trade_verify
                    require(row["offered"] == set(trade), "Both traders must offer before either verifies")
                    row["verified"].add(actor)
                    if row["verified"] == set(trade):
                        del trades[trade]
    return {"held": sorted(held), "open_trades": sorted(trades), "grouped": sorted(leader_of)}


def identifier(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError("Use a lowercase test ID (3–64 letters, digits or underscores)")
    return value


def exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Unknown or missing " + label + " fields")


def loads(text, *, max_bytes=262144):
    if len(text.encode("utf-8")) > max_bytes:
        raise ValueError(f"JSON exceeds {max_bytes // 1024} KiB")
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError("Duplicate JSON field: " + key)
            obj[key] = value
        return obj
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Finite JSON required")))


def validate(data, *, runnable=False):
    exact(data, ("format", "schema_version", "id", "title", "category", "roles", "steps", "review"), "suite")
    if data["format"] != FORMAT or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported SWG Test Studio format/version")
    identifier(data["id"])
    if not isinstance(data["title"], str) or not 1 <= len(data["title"]) <= 200:
        raise ValueError("A title of 1–200 characters is required")
    if data["category"] not in ("unit", "functional", "regression", "system"):
        raise ValueError("Unknown test category")
    roles = data["roles"]
    if (not isinstance(roles, list) or len(roles) > 5 or
            any(not isinstance(r, str) or not ROLE.fullmatch(r) for r in roles) or len(set(roles)) != len(roles)):
        raise ValueError("At most five distinct named test roles are supported")
    review = data["review"]
    extra = ("capture_ranges",) if isinstance(review, dict) and "capture_ranges" in review else ()
    exact(review, ("approved", "recording", "unsupported") + extra, "review")
    if extra:
        from .clips import validate_ranges
        validate_ranges(review["capture_ranges"])
        if review["recording"] is None:
            raise ValueError("Recording clips require their source recording ID")
    if (type(review["approved"]) is not bool or
            (review["recording"] is not None and (not isinstance(review["recording"], str) or
                                                not re.fullmatch(r"[a-f0-9]{32}", review["recording"]))) or
            not isinstance(review["unsupported"], list) or len(review["unsupported"]) > 128 or
            any(not isinstance(v, str) or not 1 <= len(v) <= 300 for v in review["unsupported"])):
        raise ValueError("Invalid review metadata")
    if runnable and (not review["approved"] or review["unsupported"]):
        raise ValueError("Review expectations and resolve unsupported recording steps before running")
    steps = data["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
        raise ValueError("Define 1–32 test steps")
    seen = set()
    for step in steps:
        exact(step, ("id", "action", "options"), "step")
        name = identifier(step["id"])
        if name in seen:
            raise ValueError("Step IDs must be unique")
        seen.add(name)
        options = step["options"]
        if not isinstance(options, dict):
            raise ValueError("Typed step options required")
        if step["action"] == "session":
            if options.get("role") not in roles or set(options) - (set(SESSION_OPTIONS) | {"role"}):
                raise ValueError("Unknown session role/option")
            for key, value in options.items():
                if key != "role" and type(value) is not SESSION_OPTIONS[key]:
                    raise ValueError("Incorrect session option type: " + key)
            if options.get("expect_family") not in (None, "npe_space_station", "npe_space_dungeon"):
                raise ValueError("Unsupported public station family")
            if "expect_scene" in options and not re.fullmatch(r"terrain/[a-z0-9_]+\.trn", options["expect_scene"]):
                raise ValueError("Expected scene must be a terrain resource name")
            if options.get("answer", "ok") not in ("ok", "cancel"):
                raise ValueError("Only offered OK/Cancel dialog answers are supported")
            if sum(bool(options.get(k)) for k in ("create", "stage_station", "prepare_terminal")) > 1:
                raise ValueError("Creation, station setup and terminal travel are separate lifecycles")
            if options.get("prepare_terminal") and ("expect_family" not in options or options.get("answer", "ok") != "ok"):
                raise ValueError("Shuttle recipe requires an explicit destination and confirmation")
        elif step["action"] == "journey":
            from .journey import validate as validate_journey
            validate_journey(options, roles)
        elif step["action"] == "action_sequence":
            from .action_sequence import validate as validate_sequence
            validate_sequence(options, roles)
        elif step["action"] == "saved_suite":
            exact(options, ("suite", "bindings"), "saved-suite")
            recipe = options["suite"]
            if not isinstance(recipe, str) or recipe not in RECIPES:
                raise ValueError("Select an approved ordinary-action suite")
            bindings = options["bindings"]
            if (not isinstance(bindings, dict) or set(bindings) != set(RECIPES[recipe]) or
                    any(not isinstance(v, str) or v not in roles for v in bindings.values()) or
                    len(set(bindings.values())) != len(bindings)):
                raise ValueError("Bind each recipe role to a distinct declared role")
        elif step["action"] == "agent_fixture":
            from .agent_fixture import validate as validate_fixture
            validate_fixture(options, roles)
        elif step["action"] == "client":
            validate_client(options, roles)
        elif step["action"] == "recorded_observation":
            exact(options, ("summary",), "recorded-observation")
            if not isinstance(options["summary"], str) or not 1 <= len(options["summary"]) <= 300:
                raise ValueError("A bounded observation summary is required")
            if runnable:
                raise ValueError("Recorded observations must be replaced with supported actions and expectations")
        else:
            raise ValueError("Unknown action; arbitrary commands and executable expressions are not supported")
    if runnable and len(roles) and not any(s["action"] != "recorded_observation" for s in steps):
        raise ValueError("No replayable actions")
    if any(s["action"] == "client" for s in steps):
        client_order(steps)
    return copy.deepcopy(data)


def compile_suite(data, legacy_dir):
    """Compile private execution cases; legacy recipes keep their original schema."""
    data = validate(data, runnable=True)
    cases = []
    for step in data["steps"]:
        if step["action"] == "session":
            cases.append({"id": step["id"], "kind": "protocol_session", "options": step["options"]})
        elif step["action"] == "journey":
            cases.append({"id": step["id"], "kind": "studio_journey", "options": step["options"]})
        elif step["action"] == "action_sequence":
            cases.append({"id": step["id"], "kind": "studio_action_sequence", "options": step["options"]})
        elif step["action"] == "agent_fixture":
            cases.append({"id": step["id"], "kind": "agent_fixture", "options": step["options"]})
        elif step["action"] == "client":
            cases.append({"id": step["id"], "kind": "client_action", "options": step["options"]})
        else:
            options = step["options"]
            original = loads((legacy_dir / (options["suite"] + ".json")).read_text(encoding="utf-8"))
            if original["roles"] != list(RECIPES[options["suite"]]):
                raise ValueError("Bundled recipe role contract changed")
            # Role-free runs can overlap live runs, so they must only execute the offline unit backend.
            allowed = {"driver_unit"} if options["suite"] == "driver_unit" else {
                "protocol_session", "ship_group", "driver_unit", "group_affinity_rryatt", "group_affinity_ord"}
            for case in original["tests"]:
                # Do not inherit newly added native/fault backends through an approved suite name.
                if case["kind"] not in allowed:
                    raise ValueError("Bundled recipe gained an unsupported backend; review its adapter")
                case = copy.deepcopy(case)
                case["id"] = step["id"] + "_" + case["id"]
                identifier(case["id"])
                for key, value in case["options"].items():
                    if isinstance(value, str) and value in options["bindings"]:
                        case["options"][key] = options["bindings"][value]
                cases.append(case)
    if len(cases) > 32:
        raise ValueError("Expanded suite exceeds 32 cases")
    return {"schema_version": 1, "id": data["id"], "title": data["title"],
            "category": data["category"], "roles": data["roles"], "tests": cases}
