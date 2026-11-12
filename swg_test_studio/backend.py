"""Run the pinned SWG driver against the selected server source and fixture."""
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET

from . import model
from .model import compile_suite, exact, ROLE
from .agent_fixture import OPS as AGENT_OPS, REGISTRY as AGENT_REGISTRY, scenario_ids
from .server_tools import load_tool, profile_of, source_folder, tool_environment, verified_tool_root
from .store import read_json, write_json


def environment_template():
    return {
        "schema_version": 1,
        "name": "My isolated SWG fixture",
        "server_checkout": "/mnt/f/SWGProjects/swg-server",
        "folder": "/tmp/swg-cold-test-0123abcd/client-012345abcdef",
        "binary": "/tmp/swg-driver64/driver",
        "bindings": {"actor": "tester"},
    }


def environment(path):
    return validate_environment(read_json(path))


def validate_environment(data):
    # "profile" is optional; without it the environment is the original whitengold one.
    optional = ("profile",) if isinstance(data, dict) and "profile" in data else ()
    exact(data, ("schema_version", "name", "server_checkout", "folder", "binary", "bindings") + optional, "environment")
    if optional:
        if not isinstance(data["profile"], str):
            raise ValueError("Unknown server profile")
        profile_of(data)
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported environment version")
    if not isinstance(data["name"], str) or not 1 <= len(data["name"]) <= 100:
        raise ValueError("Environment name required")
    for key in ("server_checkout", "folder", "binary"):
        value = data[key]
        if (not isinstance(value, str) or not value.startswith("/") or "\x00" in value or
                any(ord(c) < 32 for c in value) or ".." in PurePosixPath(value).parts):
            raise ValueError(key + " must be an absolute Linux/WSL path")
    if not re.fullmatch(r"/tmp/swg-cold-test-[a-f0-9]{8}/client-[a-f0-9]{12}", data["folder"]):
        raise ValueError("Only a prepared isolated SWG fixture is supported")
    bindings = data["bindings"]
    if (not isinstance(bindings, dict) or len(bindings) > 5 or
            any(not isinstance(k, str) or not ROLE.fullmatch(k) or not isinstance(v, str) or
                not ROLE.fullmatch(v) for k, v in bindings.items()) or len(set(bindings.values())) != len(bindings)):
        raise ValueError("Bind at most five distinct roles to retained registries")
    return data


def local_path(value):
    if os.name == "nt" and re.match(r"/mnt/[a-z]/", value):
        return Path(value[5].upper() + ":/" + value[7:])
    return Path(value)


def plan(suite, env):
    bindings = {r: env["bindings"][r] for r in suite["roles"] if r in env["bindings"]}
    missing = [role for role in suite["roles"] if role not in bindings]
    if missing:
        raise ValueError("The test setup has no characters assigned for these parts: " + ", ".join(missing))
    manifest = compile_suite(suite, verified_tool_root() / "zones/test_sets")
    cases = manifest["tests"]
    profile = profile_of(env)
    load_tool("zones/server_profile.py").require_supported(cases, profile)
    action_kinds = {
        action["kind"]
        for case in cases if case["kind"] == "studio_action_sequence"
        for action in case["options"]["actions"]
    }
    ground_or_legacy_setup = any(
        any(case["options"].get(key, False) for key in
            ("prepare_terminal", "prepare_start", "prepare_between_actions")) or
        case["kind"] not in ("protocol_session", "studio_journey", "studio_action_sequence", "agent_fixture",
                             "client_action")
        for case in cases if case["kind"] != "driver_unit"
    )
    client_steps = [case for case in cases if case["kind"] == "client_action"]
    client_kinds = {case["options"]["kind"] for case in client_steps}
    fixture_steps = [case for case in cases if case["kind"] == "agent_fixture"]
    scenarios = scenario_ids(fixture_steps)
    partners = sorted({case["options"]["args"][i] for case in fixture_steps
                       for i in AGENT_REGISTRY.role_args.get(case["options"]["op"], ())
                       if i < len(case["options"]["args"])})
    return {"schema_version": 1, "suite": suite["id"], "environment": env["name"],
            **({} if profile.case_kinds is None else {"profile": profile.name}),
            "bindings": bindings, "manifest": manifest,
            "effects": {"gameplay_actions": bool(bindings), "creates_dedicated_character": any(
                case["kind"] == "protocol_session" and case["options"].get("create", False) for case in cases),
                "explicit_station_setup": any(case["options"].get("stage_station", False) for case in cases),
                "fixture_proximity_setup": ground_or_legacy_setup or bool(action_kinds & {"launch", "land"}),
                "ship_pilot_reward_and_proximity_setup": "launch" in action_kinds,
                "group_cleanup_possible": "form_group" in action_kinds or bool(client_kinds & {"group_invite", "group_join"}),
                "agent_fixture_changes": sorted({case["options"]["op"] for case in cases
                                                 if case["kind"] == "agent_fixture" and AGENT_OPS[case["options"]["op"]][1]}),
                "service_restart": False, "client_changed": False,
                # Only for suites with fixture steps, so every other plan stays as it was.
                **({} if not fixture_steps else {
                    "agent_fixture_classes": sorted({AGENT_REGISTRY.fixture_of[case["options"]["op"]]
                                                     for case in fixture_steps}),
                    "agent_fixture_partner_roles": partners,
                    "agent_fixture_scenarios": scenarios,
                    # True when every scenario begun or used is also ended in the suite; otherwise
                    # its objects outlive the run until `scenario-end` removes them.
                    "agent_fixture_scenarios_all_ended": all(row["ended"] for row in scenarios)}),
                # Only for suites with client steps, so every other plan stays as it was.
                **({} if not client_steps else {
                    "client_held_roles": sorted({case["options"]["role"] for case in client_steps
                                                 if case["options"]["kind"] == "session_hold"}),
                    "client_actions": sorted(client_kinds),
                    "client_trade_possible": any(kind.startswith("trade_") for kind in client_kinds),
                    "client_tells": "tell" in client_kinds})}}


def require_profile_support(suite, profile):
    """Refuse a suite the named server profile cannot run, before anything is started."""
    tools = load_tool("zones/server_profile.py")
    manifest = compile_suite(suite, verified_tool_root() / "zones/test_sets")
    tools.require_supported(manifest["tests"], tools.get(profile))


# --- Held sessions for client steps (docs/fixture-client-actions.md) ---------------------------------
#
# One peer process per role stays logged in across steps. Control channel: one request line
# "@<id> <verb> [args]" on the peer's stdin; exactly one reply event `DRIVER {"event":"reply","request":<id>,...}`
# on stdout; server observations arrive as further DRIVER events at any time. Plain lines ("logout",
# "quit") keep the peer's original meaning and are used only to close it.

HELD_LIFETIME = 900       # the peer's own deadline (timeoutSeconds, its maximum): a held session cannot outlive it
HELD_LOGIN_TIMEOUT = 120  # login, character select and scene start
HELD_REPLY_TIMEOUT = 10   # a request's reply (the peer replies after queueing the message)
HELD_CLOSE_TIMEOUT = 40   # an accepted logout
CLIENT_DEFAULT_TIMEOUT = 30


class ClientStepFailed(RuntimeError):
    """A client step's request was refused, a peer failed, or a server observation contradicted the step."""


class HeldPeer:
    """One role's peer process and every event it reported."""

    def __init__(self, role, argv, log_path, *, env=None, popen=subprocess.Popen):
        self.role = role
        self.events = []
        self.error = None
        self.stream_closed = False
        self.after_close = None   # callable run once after the peer exits (live: wait until the bot is unloaded)
        self.next_request = 0
        self.cond = threading.Condition()
        self.log = Path(log_path).open("x")
        self.process = popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, env=env, start_new_session=True)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            total = 0
            for line in self.process.stdout:
                total += len(line)
                if len(line) > 65536 or total > 8 * 1024 * 1024:
                    raise RuntimeError("Peer output bound exceeded")
                self.log.write(line)
                self.log.flush()
                if line.startswith("DRIVER "):
                    event = json.loads(line[7:])
                    if not isinstance(event, dict) or event.get("schema_version") != 1 or \
                            not isinstance(event.get("event"), str):
                        raise RuntimeError("Unknown peer event schema")
                    event["received_monotonic"] = time.monotonic()
                    with self.cond:
                        self.events.append(event)
                        self.cond.notify_all()
        except Exception as exc:  # recorded; every later wait reports it
            self.error = exc
        finally:
            with self.cond:
                self.stream_closed = True
                self.cond.notify_all()

    def find(self, match, after):
        """The first event at or after `after` that matches; a failure event or a closed peer raises."""
        with self.cond:
            for event in self.events:
                if event["event"] == "failure":
                    raise ClientStepFailed(f"{self.role} peer failed: {event.get('reason')}")
                if event["received_monotonic"] >= after and match(event):
                    return event
            if self.stream_closed:
                raise ClientStepFailed(f"{self.role} peer exited" + (f": {self.error}" if self.error else ""))
        return None

    def wait(self, match, *, after, timeout, describe):
        deadline = time.monotonic() + timeout
        while True:
            event = self.find(match, after)
            if event is not None:
                return event
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{self.role}: no {describe} within {timeout} s")
            with self.cond:
                self.cond.wait(min(remaining, .25))

    def request(self, verb, args=(), timeout=None):
        """Send one typed request; returns (reply event, send time). A refused request raises."""
        line = " ".join((verb,) + tuple(args))
        if not re.fullmatch(r"[\x20-\x7e]{1,400}", line):
            raise ValueError("A client request is one printable ASCII line")
        self.next_request += 1
        number = self.next_request
        sent = time.monotonic()
        try:
            self.process.stdin.write(f"@{number} {line}\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ClientStepFailed(f"{self.role} peer is not accepting requests") from exc
        reply = self.wait(lambda e: e["event"] == "reply" and e.get("request") == number, after=sent,
                          timeout=HELD_REPLY_TIMEOUT if timeout is None else timeout, describe="reply to " + verb)
        if reply.get("accepted") is not True:
            raise ClientStepFailed(f"{self.role} peer refused {verb}: {reply.get('reason')}")
        return reply, sent

    def close(self, graceful=True):
        """Log out (or quit) and make sure the process is gone; returns a short record. Never raises."""
        record = {"role": self.role, "mode": None, "exit_code": None}
        try:
            if self.process.poll() is None:
                try:
                    ready = self.find(lambda e: e["event"] == "scene_ready", 0) is not None
                except ClientStepFailed:
                    ready = False
                record["mode"] = "logout" if graceful and ready else "quit"
                started = time.monotonic()
                self.process.stdin.write(record["mode"] + "\n")
                self.process.stdin.flush()
                if record["mode"] == "logout":
                    self.wait(lambda e: e["event"] == "logout_accepted", after=started, timeout=_close_timeout(),
                              describe="accepted logout")
                self.process.wait(timeout=10)
        except (BrokenPipeError, OSError, ValueError, subprocess.TimeoutExpired, RuntimeError, TimeoutError) as exc:
            record["error"] = type(exc).__name__ + ": " + str(exc)
        finally:
            for stop in (lambda: self.process.stdin.close(), lambda: self.process.wait(timeout=6),
                         self.process.terminate, lambda: self.process.wait(timeout=5),
                         self.process.kill, lambda: self.process.wait(timeout=5)):
                if self.process.poll() is not None:
                    break
                try:
                    stop()
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
            record["exit_code"] = self.process.poll()
            self.thread.join(timeout=2)
            for stream in (self.process.stdin, self.process.stdout):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
            if not self.log.closed:
                self.log.close()
        if self.after_close is not None:
            try:
                self.after_close()
            except Exception as exc:
                record["after_close_error"] = type(exc).__name__ + ": " + str(exc)
        return record


def _close_timeout():
    return HELD_CLOSE_TIMEOUT


def _public(event):
    return {k: v for k, v in event.items() if k != "received_monotonic"}


class HeldPool:
    """The held sessions of one run: at most MAX_HELD_SESSIONS, all closed by close()."""

    def __init__(self, launch, *, limit=model.MAX_HELD_SESSIONS):
        if not 1 <= limit <= model.MAX_HELD_SESSIONS:
            raise ValueError(f"At most {model.MAX_HELD_SESSIONS} held sessions")
        self.launch = launch      # launch(role) -> (HeldPeer, {"player": oid, "character": name})
        self.limit = limit
        self.peers, self.identity = {}, {}
        self.trades = {}          # role -> {"partner", "offered", "verified"}
        self.leader_of = {}       # role -> leader role (runtime mirror of model.client_order)
        self.invited = {}         # invitee role -> inviter role
        self.fixture_replies = {}  # agent_fixture step id -> reply (for item_from)
        self.closed = False

    # -- bookkeeping shared with run_suite
    def record_fixture(self, step_id, artifact):
        self.fixture_replies[step_id] = artifact.get("reply", {}) if isinstance(artifact, dict) else {}

    def _peer(self, role):
        if role not in self.peers:
            raise ClientStepFailed(f"Role {role} has no held session")
        return self.peers[role]

    def _item(self, options):
        if "item" in options:
            return options["item"]
        source = options["item_from"]
        reply = self.fixture_replies.get(source["step"])
        rows = reply.get("rows", []) if reply else []
        if reply is None or source["row"] >= len(rows):
            raise ClientStepFailed(f"Step {source['step']} has no reply row {source['row']}")
        item = rows[source["row"]].split(",", 1)[0]
        if not model.CLIENT_ITEM.fullmatch(item):
            raise ClientStepFailed(f"Row {source['row']} of step {source['step']} does not start with an object ID")
        return item

    def perform(self, options):
        if self.closed:
            raise ClientStepFailed("The held sessions of this run are closed")
        kind, role = options["kind"], options["role"]
        timeout = options.get("timeout", CLIENT_DEFAULT_TIMEOUT)
        if kind == "session_hold":
            if role in self.peers:
                raise ClientStepFailed(f"Role {role} is already held")
            if len(self.peers) >= self.limit:
                raise ClientStepFailed(f"At most {self.limit} held sessions at once")
            peer, identity = self.launch(role)
            self.peers[role], self.identity[role] = peer, identity
            return {"kind": kind, "role": role, "character": identity["player"]}
        if kind == "session_release":
            if role in self.trades:
                raise ClientStepFailed("Cancel or complete the open trade before releasing a session")
            record = self.peers.pop(self._peer(role).role).close(graceful=True)
            self.identity.pop(role, None)
            self._drop_group(role)
            self.invited = {k: v for k, v in self.invited.items() if role not in (k, v)}
            if record.get("error") or record.get("after_close_error") or record["exit_code"] != 0:
                raise ClientStepFailed(f"{role} did not close cleanly: {record}")
            return {"kind": kind, "role": role, "closed": record}
        actor = self._peer(role)
        peer_role = options.get("peer")
        if peer_role is not None:
            self._peer(peer_role)
        partner = peer_role or (self.trades.get(role) or {}).get("partner")
        if kind.startswith("trade_") and kind != "trade_request" and partner is None:
            raise ClientStepFailed(kind + " needs an open trade")
        args = []
        if peer_role is not None:
            args.append(self.identity[peer_role]["player"])
        if kind == "trade_add_item":
            args.append(self._item(options))
        elif kind == "trade_credits":
            args.append(str(options["amount"]))
        elif kind == "tell":
            args.append(options["text"])
        reply, sent = actor.request(model.CLIENT_VERB[kind], args)
        deadline = sent + timeout
        observed = []

        def expect(who, match, describe, failures=()):
            """Wait for one observation on `who`; any of `failures` (peer, match, why) seen first fails the step."""
            target = self.peers[who]
            while True:
                for peer, bad, why in failures:
                    event = peer.find(bad, sent)
                    if event is not None:
                        raise ClientStepFailed(f"{kind}: {why}: {_public(event)}")
                event = target.find(match, sent)
                if event is not None:
                    observed.append(dict(_public(event), role=who))
                    return event
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{kind}: {who} saw no {describe} within {timeout} s")
                with target.cond:
                    target.cond.wait(.05)

        me = self.identity[role]
        wanted = options.get("expect", {})
        if kind.startswith("group_"):
            status = wanted.get("status", "0")
            same = lambda e: e["event"] == "command_result" and e.get("sequence") == reply.get("sequence")
            expect(role, lambda e: same(e) and str(e.get("status")) == status, "command result " + status,
                   [(actor, lambda e: same(e) and str(e.get("status")) != status, "command finished otherwise")])
        elif kind == "trade_request":
            expect(peer_role, lambda e: e["event"] == "secure_trade" and e.get("trade") == "requested" and
                   e.get("initiator") == me["player"], "trade request",
                   [(actor, lambda e: e["event"] == "secure_trade" and e.get("trade") in ("busy", "unreachable", "denied"),
                     "the server refused the request")])
        elif kind == "trade_accept":
            for who in (role, partner):
                other = self.identity[partner if who == role else role]["player"]
                expect(who, lambda e, o=other: e["event"] == "trade_begun" and e.get("partner") == o, "trade start")
        elif kind == "trade_deny":
            expect(partner, lambda e: e["event"] == "secure_trade" and e.get("trade") == "denied", "trade denial")
        elif kind == "trade_add_item":
            item = args[0]
            expect(partner, lambda e: e["event"] == "trade_item_added" and e.get("item") == item, "added item " + item,
                   [(actor, lambda e: e["event"] == "trade_item_failed" and e.get("item") == item,
                     "the server refused the item")])
        elif kind == "trade_credits":
            expect(partner, lambda e: e["event"] == "trade_credits" and e.get("amount") == options["amount"],
                   "offered credits")
        elif kind == "trade_offer":
            expect(partner, lambda e: e["event"] == "trade_offer_accepted", "offer acceptance")
            if self.trades[partner]["offered"]:
                for who in (role, partner):
                    expect(who, lambda e: e["event"] == "trade_verification", "verification start")
        elif kind == "trade_unoffer":
            if self.trades[role]["offered"]:
                expect(partner, lambda e: e["event"] == "trade_offer_withdrawn", "withdrawn offer")
        elif kind == "trade_verify":
            expect(partner, lambda e: e["event"] == "trade_verified", "verification")
            if self.trades[partner]["verified"]:
                for who in (role, partner):
                    expect(who, lambda e: e["event"] == "trade_complete", "completed trade")
        elif kind == "trade_reject":
            expect(partner, lambda e: e["event"] == "trade_rejected", "rejected offer")
            for who in (role, partner):
                expect(who, lambda e: e["event"] == "trade_begun", "restarted trade")
        elif kind == "trade_cancel":
            for who in (role, partner):
                expect(who, lambda e: e["event"] == "trade_aborted", "aborted trade")
        elif kind == "tell":
            result = wanted.get("result", "0")
            same = lambda e: e["event"] == "tell_result" and e.get("sequence") == reply.get("sequence")
            expect(role, lambda e: same(e) and str(e.get("result")) == result, "tell result " + result,
                   [(actor, lambda e: same(e) and str(e.get("result")) != result, "the chat server answered otherwise")])
            if result == "0":
                expect(peer_role, lambda e: e["event"] == "tell_received" and e.get("text") == options["text"] and
                       str(e.get("from", "")).lower() == me["character"].lower(), "tell from " + role)
        for key, who in (("actor_message", role), ("peer_message", partner)):
            if key in wanted:
                expect(who, lambda e, v=wanted[key]: e["event"] == "system_message" and e.get("string_id") == v,
                       "system message " + wanted[key])
        self._apply(kind, role, peer_role, partner)
        return {"kind": kind, "role": role, "reply": _public(reply), "observed": observed}

    def _drop_group(self, role):
        if role not in self.leader_of:
            return
        lead = self.leader_of.pop(role)
        rest = [r for r, l in self.leader_of.items() if l == lead]
        if len(rest) < 2:
            for r in rest:
                del self.leader_of[r]
        elif role == lead:
            for r in rest:
                self.leader_of[r] = sorted(rest)[0]

    def _apply(self, kind, role, peer, partner):
        """Mirror the state change the step's observations proved (used for the next step and for teardown)."""
        if kind == "group_invite":
            self.invited[peer] = role
        elif kind == "group_join":
            self.invited.pop(role, None)
            self.leader_of.setdefault(peer, peer)
            self.leader_of[role] = self.leader_of[peer]
        elif kind == "group_decline":
            self.invited.pop(role, None)
        elif kind == "group_uninvite":
            self.invited.pop(peer, None)
        elif kind in ("group_leave", "group_dismiss"):
            self._drop_group(role if kind == "group_leave" else peer)
        elif kind == "group_disband":
            lead = self.leader_of.get(role)
            for r in [r for r, l in self.leader_of.items() if l == lead]:
                del self.leader_of[r]
        elif kind == "group_make_leader":
            lead = self.leader_of.get(role)
            for r in [r for r, l in self.leader_of.items() if l == lead]:
                self.leader_of[r] = peer
        elif kind == "trade_request":
            self.trades[role] = {"partner": peer, "offered": False, "verified": False, "pending": True}
            self.trades[peer] = {"partner": role, "offered": False, "verified": False, "pending": True}
        elif kind == "trade_accept":
            for r in (role, partner):
                self.trades[r]["pending"] = False
        elif kind in ("trade_deny", "trade_cancel"):
            self.trades.pop(role, None)
            self.trades.pop(partner, None)
        elif kind in ("trade_add_item", "trade_credits", "trade_unoffer", "trade_reject"):
            for r in (role, partner):
                self.trades[r].update(offered=False, verified=False)
        elif kind == "trade_offer":
            self.trades[role]["offered"] = True
        elif kind == "trade_verify":
            self.trades[role]["verified"] = True
            if self.trades[partner]["verified"]:
                self.trades.pop(role)
                self.trades.pop(partner)

    def close(self):
        """Cancel open trades, leave groups and log every held role out; returns one record per role."""
        if self.closed:
            return []
        self.closed = True
        records = []
        for role in list(self.trades):
            if role in self.peers and not self.trades[role].get("pending"):
                try:
                    self.peers[role].request("tradeCancel")
                except (ClientStepFailed, TimeoutError, ValueError):
                    pass
                break  # one cancel aborts the trade for both traders
        for role in sorted(self.leader_of, key=lambda r: self.leader_of[r] != r):
            if role in self.peers and role in self.leader_of:
                try:
                    self.peers[role].request("groupDisband" if self.leader_of[role] == role else "groupLeave")
                except (ClientStepFailed, TimeoutError, ValueError):
                    pass
        for role in reversed(list(self.peers)):
            records.append(self.peers.pop(role).close(graceful=True))
        return records


def held_launcher(env, bindings, output, driver):
    """Live launcher: a peer per role inside the fixture's game container, with every other role as companion.

    Returns (launch, cleanup). The bots must be retained identities that logged in once (their object IDs
    are the companions' IDs); a held login first waits until the bot is fully unloaded.
    """
    folder = Path(env["folder"]).resolve(strict=True)
    project, _schema, _services = driver.fixture(folder)
    binary, _build = driver.validate_binary(Path(env["binary"]))
    base = folder / "protocol-driver"
    bots = {}
    for role, key in sorted(bindings.items()):
        bot = driver.identity(json.loads((base / (key + ".json")).read_text()))
        if not bot.get("player") or not bot.get("station"):
            raise ValueError(f"Role {role}: log its bot in once with a session step before holding it")
        bots[role] = bot
    profile = load_tool("zones/server_profile.py").active()
    destination = "/tmp/protocol-driver-held-" + output.name
    container = project + "-game-1"
    driver.run(["docker", "exec", container, "mkdir", "-m", "700", destination])
    driver.run(["docker", "cp", str(binary), container + ":" + destination + "/driver"])
    driver.run(["docker", "exec", container, "chmod", "700", destination + "/driver"])

    def launch(role):
        bot = bots[role]
        driver.unloaded(project, bot)
        companions = "".join(f"companion={b['player']}\ncompanionName={b['character']}\n"
                             for r, b in sorted(bots.items()) if r != role)
        config = output / ("held-" + role + ".cfg")
        config.write_text(f"[ProtocolDriver64]\nproject={project}\naccount={bot['account']}\n"
                          f"character={bot['character']}\n{companions}ship=\ncreate=false\n"
                          f"timeoutSeconds={HELD_LIFETIME}\n")
        driver.run(["docker", "cp", str(config), container + ":" + destination + "/" + role + ".cfg"])
        peer = HeldPeer(role, ["docker", "exec", "-i", "-e", "LD_LIBRARY_PATH=" + profile.library_path, container,
                               destination + "/driver", destination + "/" + role + ".cfg"], output / ("held-" + role + ".log"))
        try:
            scene = peer.wait(lambda e: e["event"] == "scene_ready", after=0, timeout=HELD_LOGIN_TIMEOUT,
                              describe="scene_ready")
            if scene.get("character") != bot["player"]:
                raise ClientStepFailed("Retained character identity changed")
            driver.settled(project, bot)
        except BaseException:
            peer.close(graceful=False)
            raise
        peer.after_close = lambda: driver.unloaded(project, bot)
        return peer, {"player": bot["player"], "character": bot["character"]}

    def cleanup():
        driver.run(["docker", "exec", container, "rm", "-rf", destination])

    return launch, cleanup


def driver_modules(env):
    if sys.platform != "linux":
        raise ValueError("Live operations require Linux/WSL; use the Windows launcher to relay them")
    source = source_folder(env["server_checkout"])
    load_tool("zones/server_profile.py").bind(env.get("profile"))
    load_tool("zones/studio_tool_bundle.py").bind_server_source(source)
    return load_tool("zones/protocol_driver.py"), load_tool("zones/protocol_test_sets.py")


@contextlib.contextmanager
def studio_lock(workspace):
    import fcntl
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = workspace / "operation.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def run_suite(suite, env, workspace, emit=print, launcher=None):
    from .results import failed_action, failure_reason, log_tail

    selected = plan(suite, env)
    driver, legacy = driver_modules(env)
    manifest = selected["manifest"]
    ordinary = dict(manifest, tests=[c for c in manifest["tests"] if c["kind"] not in (
        "studio_journey", "studio_action_sequence", "agent_fixture", "client_action")])
    if ordinary["tests"]:
        legacy.validate(ordinary)
    operation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4)
    output = Path(workspace) / "runs" / operation
    with studio_lock(workspace):
        # Existing backends retain their own management lock and full isolation checks.
        if any(Path(env["folder"]).joinpath("fixture/teststudio").glob("*.control")):
            raise ValueError("Stop the active recording before replaying test characters")
        output.mkdir(parents=True, mode=0o700)
        write_json(output / "suite.json", suite)
        write_json(output / "manifest.json", manifest)
        report = {"schema_version": 1, "operation": operation, "suite": suite["id"],
                  "passed": False, "cases": [], "windows_visual": False,
                  "manifest_sha256": hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest(),
                  "application_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in Path(__file__).parent.glob("*.py")}}
        report["application_sha256"].update({"fixture_ops/" + p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                             for p in sorted(Path(__file__).parent.glob("fixture_ops/*.py"))})
        pool, held_cleanup, fixture_replies = None, None, {}
        try:
            emit({"event": "run_preparing", "operation": operation, "cases": len(manifest["tests"])})
            report["source_hashes"] = legacy.source_hashes()
            inputs = {"devtools/teststudio_server/retained_peer.py": verified_tool_root() / "teststudio_server/retained_peer.py"}
            for header in ("TestStudioRecorder.h", "TestStudioCapture.h"):
                relative = "src/engine/server/library/serverGame/src/shared/core/" + header
                if (driver.REPO / relative).is_file():
                    inputs[relative] = driver.REPO / relative
            report["studio_adapter_sha256"] = {
                name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()
            }
            for case in manifest["tests"]:
                started = time.monotonic()
                row = {"id": case["id"], "kind": case["kind"], "passed": False}
                case_log = output / (case["id"] + ".log")
                report["cases"].append(row)
                emit({"event": "case_started", "id": case["id"], "operation": operation})
                try:
                    if case["kind"] == "agent_fixture":
                        from .agent_fixture import run_live as run_fixture
                        with case_log.open("x") as log, contextlib.redirect_stdout(log):
                            row["artifact"] = run_fixture(case["options"], env, selected["bindings"][case["options"]["role"]],
                                                          selected["bindings"])
                        fixture_replies[case["id"]] = row["artifact"].get("reply", {})
                        row.update(exit_code=0, timed_out=False, passed=True)
                    elif case["kind"] == "client_action":
                        if pool is None:
                            launch, held_cleanup = (launcher or held_launcher)(env, selected["bindings"], output, driver)
                            pool = HeldPool(launch)
                            pool.fixture_replies = fixture_replies
                        with case_log.open("x") as log, contextlib.redirect_stdout(log):
                            row["artifact"] = pool.perform(case["options"])
                            print("CLIENT_ACTION", json.dumps(row["artifact"], sort_keys=True), flush=True)
                        row.update(exit_code=0, timed_out=False, passed=True)
                    elif case["kind"] == "studio_journey":
                        from .journey import run_live
                        with case_log.open("x") as log, contextlib.redirect_stdout(log):
                            row["artifact"] = run_live(case["options"], env, selected["bindings"][case["options"]["role"]])
                        row.update(exit_code=0, timed_out=False, passed=True)
                    else:
                        if case["kind"] == "studio_action_sequence":
                            from .action_sequence import command
                            argv = command(case["options"], env, selected["bindings"], output, case["id"])
                        else:
                            argv = legacy.command(case, selected["bindings"], Path(env["folder"]), Path(env["binary"]))
                        with case_log.open("x") as log:
                            code, timed_out = legacy.execute(argv, log, timeout=2400, env=tool_environment(driver.REPO))
                        row.update(exit_code=code, timed_out=timed_out, passed=code == 0 and not timed_out)
                        if row["passed"] and case["kind"] != "driver_unit":
                            row["artifact"] = legacy.runtime_artifact(case_log, Path(env["folder"]))
                except (Exception, KeyboardInterrupt) as exc:
                    row.update(passed=False, error=type(exc).__name__ + ": " + str(exc))
                if not row["passed"]:
                    log = log_tail(case_log)
                    row["error"] = failure_reason(row, log)
                    action = failed_action(log)
                    if action:
                        row["action"] = action
                row["seconds"] = time.monotonic() - started
                emit({"event": "case_finished", **row})
                if not row["passed"]:
                    break
            report["passed"] = len(report["cases"]) == len(manifest["tests"]) and all(r["passed"] for r in report["cases"])
        except (Exception, KeyboardInterrupt) as exc:
            report["error"] = type(exc).__name__ + ": " + str(exc)
        finally:
            # Held sessions end with the run, passed or not: one failing role tears all of them down.
            if pool is not None:
                report["held_sessions"] = pool.close()
                if any(r.get("error") or r.get("after_close_error") or r.get("exit_code") != 0
                       for r in report["held_sessions"]):
                    report["passed"] = False
                    report.setdefault("error", "A held session did not close cleanly")
            if held_cleanup is not None:
                try:
                    held_cleanup()
                except Exception as exc:
                    report["held_cleanup_error"] = type(exc).__name__ + ": " + str(exc)
            write_json(output / "result.json", report)
            xml = ET.Element("testsuite", name=suite["id"], tests=str(len(manifest["tests"])),
                             failures=str(sum(not r["passed"] for r in report["cases"])))
            for case in manifest["tests"]:
                row = next((r for r in report["cases"] if r["id"] == case["id"]), None)
                node = ET.SubElement(xml, "testcase", name=case["id"], time=str(row.get("seconds", 0) if row else 0))
                if row is None:
                    ET.SubElement(node, "skipped", message="Previous case failed or run interrupted")
                elif not row["passed"]:
                    ET.SubElement(node, "failure", message="See retained case log")
            ET.ElementTree(xml).write(output / "junit.xml", encoding="utf-8", xml_declaration=True)
        return {"event": "run_finished", "passed": report["passed"], "operation": operation, "evidence": str(output)}
