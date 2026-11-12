#!/usr/bin/env python3
"""A stand-in for the held protocol peer (devtools/zones/protocol_driver64.cpp) in offline tests.

It speaks the same control channel: "@<id> <verb> [args]" request lines and the plain "logout"/"quit"
lines on stdin; "DRIVER {json}" events on stdout. Several fake peers share one small "server": a state
file and one inbox per character in a bus directory, so a trade request from one process reaches the
other as the game server would deliver it (ServerSecureTrade, CreatureController, the chat server).
The rules mirror the server code paths cited in docs/fixture-client-actions.md; they are a test double,
not a second implementation of the game.

Faults (--fault NAME=MODE, repeatable): a verb with fail (failure event, exit 1), crash (exit 3 at once),
hang (no reply), refuse (reply accepted=false), silent (reply but no server deliveries), status7
(command_result status 7); login=fail; logout=hang.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

GROUP = {"groupInvite": "invite", "groupJoin": "join", "groupDecline": "decline", "groupUninvite": "uninvite",
         "groupLeave": "leaveGroup", "groupDisband": "disband", "groupMakeLeader": "makeLeader",
         "groupDismiss": "dismissGroupMember"}
TRADE = ("tradeRequest", "tradeAccept", "tradeDeny", "tradeItem", "tradeCredits", "tradeOffer", "tradeUnoffer",
         "tradeVerify", "tradeReject", "tradeCancel")
TARGETED = ("groupInvite", "groupJoin", "groupUninvite", "groupMakeLeader", "groupDismiss", "tradeRequest", "tell")


def emit(name, **fields):
    sys.stdout.write("DRIVER " + json.dumps(dict(schema_version=1, event=name, **fields)) + "\n")
    sys.stdout.flush()


class Bus:
    def __init__(self, folder, me):
        self.folder, self.me, self.offset = Path(folder), me, 0

    def deliver(self, player, name, **fields):
        with (self.folder / (player + ".inbox")).open("a") as inbox:
            inbox.write(json.dumps(dict(event=name, **fields)) + "\n")

    def receive(self):
        path = self.folder / (self.me + ".inbox")
        if not path.exists():
            return []
        with path.open() as inbox:
            inbox.seek(self.offset)
            text = inbox.read()
        complete = text[:text.rfind("\n") + 1]
        self.offset += len(complete.encode())
        return [json.loads(line) for line in complete.splitlines() if line]

    def state(self):
        """Exclusive access to the shared server state; use as a context manager."""
        bus = self

        class Locked:
            def __enter__(self):
                self.lock = (bus.folder / "state.lock").open("a")
                fcntl.flock(self.lock, fcntl.LOCK_EX)
                path = bus.folder / "state.json"
                self.data = json.loads(path.read_text()) if path.exists() else {"requests": {}, "trades": {}}
                return self.data

            def __exit__(self, *exc):
                (bus.folder / "state.json").write_text(json.dumps(self.data))
                fcntl.flock(self.lock, fcntl.LOCK_UN)
                self.lock.close()
        return Locked()


def serve(bus, me, character, verb, args, sequence, companions, mode):
    """Server-side effects of one accepted request, as deliveries to inboxes."""
    if mode == "silent":
        return
    if verb in GROUP:
        bus.deliver(me, "command_result", command=GROUP[verb], status=7 if mode == "status7" else 0, detail=0,
                    sequence=sequence)
        return
    if verb == "tell":
        bus.deliver(me, "tell_result", sequence=sequence, result=0)
        bus.deliver(args[0], "tell_received", **{"from": character.lower(), "text": args[1]})
        return
    with bus.state() as state:
        trades, requests = state["trades"], state["requests"]
        trade = next((t for t in trades.values() if me in t["parties"]), None)
        other = None if trade is None else next(p for p in trade["parties"] if p != me)
        if verb == "tradeRequest":
            if trade is not None or args[0] in requests:
                bus.deliver(me, "secure_trade", trade="busy", initiator=me, recipient=args[0])
            else:
                requests[args[0]] = me
                bus.deliver(args[0], "secure_trade", trade="requested", initiator=me, recipient=args[0])
        elif verb in ("tradeAccept", "tradeDeny"):
            initiator = requests.pop(me, None)
            if initiator is None:
                return
            if verb == "tradeDeny":
                bus.deliver(initiator, "secure_trade", trade="denied", initiator=initiator, recipient=me)
                return
            trades[initiator + ":" + me] = {"parties": [initiator, me], "ok": [], "verified": [], "state": "trading"}
            bus.deliver(initiator, "trade_begun", partner=me)
            bus.deliver(me, "trade_begun", partner=initiator)
        elif trade is None:
            return
        elif verb in ("tradeItem", "tradeCredits"):
            if verb == "tradeItem":
                bus.deliver(other, "trade_item_added", item=args[0])
            else:
                bus.deliver(other, "trade_credits", amount=int(args[0]))
            for party in list(trade["ok"]):   # ServerSecureTrade::unacceptOffer for both traders
                bus.deliver(next(p for p in trade["parties"] if p != party), "trade_offer_withdrawn")
            trade["ok"] = []
        elif verb == "tradeOffer" and trade["state"] == "trading":
            if me not in trade["ok"]:
                trade["ok"].append(me)
            bus.deliver(other, "trade_offer_accepted")
            if len(trade["ok"]) == 2:
                trade.update(state="verifying", verified=[])
                for party in trade["parties"]:
                    bus.deliver(party, "trade_verification")
        elif verb == "tradeUnoffer" and trade["state"] == "trading" and me in trade["ok"]:
            trade["ok"].remove(me)
            bus.deliver(other, "trade_offer_withdrawn")
        elif verb == "tradeVerify" and trade["state"] == "verifying":
            if me not in trade["verified"]:
                trade["verified"].append(me)
            bus.deliver(other, "trade_verified")
            if len(trade["verified"]) == 2:
                for party in trade["parties"]:
                    bus.deliver(party, "trade_complete")
                trades.pop(next(k for k, v in trades.items() if v is trade))
        elif verb == "tradeReject":
            bus.deliver(other, "trade_rejected")
            trade.update(state="trading", ok=[], verified=[])
            for party in trade["parties"]:
                bus.deliver(party, "trade_begun", partner=next(p for p in trade["parties"] if p != party))
        elif verb == "tradeCancel":
            for party in trade["parties"]:
                bus.deliver(party, "trade_aborted")
            trades.pop(next(k for k, v in trades.items() if v is trade))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bus", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--character", required=True)
    parser.add_argument("--companion", action="append", default=[], help="OID:NAME")
    parser.add_argument("--fault", action="append", default=[], help="NAME=MODE")
    parser.add_argument("--lifetime", type=float, default=60)
    parser.add_argument("--pid-file")
    args = parser.parse_args()
    faults = dict(item.split("=", 1) for item in args.fault)
    companions = dict(item.split(":", 1) for item in args.companion)
    if args.pid_file:
        with open(args.pid_file, "a") as pids:
            pids.write(f"{os.getpid()}\n")
    bus = Bus(args.bus, args.player)
    lines = queue.Queue()

    def read():
        for line in sys.stdin:
            lines.put(line.rstrip("\n"))
        lines.put(None)
    threading.Thread(target=read, daemon=True).start()
    emit("started", project="swg-cold-test-0123abcd", account="capbot_0123abc")
    if faults.get("login") == "fail":
        emit("failure", reason="login denied")
        return 1
    emit("authenticated", station_id="12345")
    emit("scene_ready", character=args.player, scene="terrain/tatooine.trn", position=[0, 0, 0])
    deadline, sequence = time.monotonic() + args.lifetime, 0
    while True:
        if time.monotonic() > deadline:
            emit("failure", reason="session deadline")
            return 1
        for event in bus.receive():
            emit(event.pop("event"), **event)
        try:
            line = lines.get(timeout=.01)
        except queue.Empty:
            continue
        if line is None:
            emit("input_closed")
            return 0
        if line == "logout":
            if faults.get("logout") == "hang":
                continue
            emit("logout_accepted")
            return 0
        if line == "quit":
            emit("disconnect_requested")
            return 0
        if not line.startswith("@"):
            emit("failure", reason="unknown or invalid action")
            return 1
        number, _, rest = line[1:].partition(" ")
        verb, _, tail = rest.partition(" ")
        mode = faults.get(verb)
        if mode == "crash":
            return 3
        if mode == "fail":
            emit("failure", reason="injected failure at " + verb)
            return 1
        if mode == "hang":
            continue
        if mode == "refuse":
            emit("reply", request=int(number), verb=verb, accepted=False, reason="injected refusal")
            continue
        words = tail.split(" ", 1) if tail else []
        if verb in TARGETED:
            if not words or words[0] not in companions:
                emit("reply", request=int(number), verb=verb, accepted=False, reason="not a roster companion")
                continue
            if verb == "tell":
                words = [words[0], words[1] if len(words) > 1 else ""]
        if verb not in GROUP and verb not in TRADE and verb != "tell":
            emit("reply", request=int(number), verb=verb, accepted=False, reason="invalid client action")
            continue
        sequence += 1
        emit("reply", request=int(number), verb=verb, accepted=True, sequence=sequence)
        serve(bus, args.player, args.character, verb, words, sequence, companions, mode)


if __name__ == "__main__":
    sys.exit(main())
