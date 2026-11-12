"""Typed client-side group, trade, tell and session steps (docs/fixture-client-actions.md).

Everything here is offline. Held sessions are exercised for real against tests/fake_client_peer.py, a
stand-in peer speaking the same control channel. The grounding tests read the server tree named by
SWG_RESTORATION_TREE and run only when it is present; the gate always provides it. Every test class
also shows its check failing on a seeded fault.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from swg_test_studio import backend, model
from swg_test_studio.backend import ClientStepFailed, HeldPeer, HeldPool, plan
from swg_test_studio.model import (CLIENT_KINDS, CLIENT_VERB, CLIENT_WIRE, TRADE_CREDITS_MAX, client_order,
                                   compile_suite, loads, validate)
from swg_test_studio.server_tools import TOOLS_ROOT
from swg_test_studio.store import EXAMPLES
from devtools.zones import server_profile
from devtools.zones.studio_tool_bundle import verify

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("client_wire_bytes", Path(__file__).with_name("client_wire_bytes.py"))
_WIRE_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_WIRE_MODULE)
WIRE = _WIRE_MODULE.WIRE
FAKE_PEER = Path(__file__).with_name("fake_client_peer.py")
RESTORATION_TREE = Path(os.environ.get("SWG_RESTORATION_TREE") or "/nonexistent/restoration-tree")
HAVE_TREE = (RESTORATION_TREE / "src/engine/server/application/CentralServer/Makefile.am").is_file()
COMMANDS = "dsrc/sku.0/sys.shared/compiled/game/datatables/command/command_table.tab"
MESSAGES = "src/engine/shared/library/sharedNetworkMessages/src/shared/clientGameServer/"
CHAT = "src/engine/shared/library/sharedNetworkMessages/src/shared/chat/"
CLIENT_CPP = "src/engine/server/library/serverGame/src/shared/core/Client.cpp"
CONTROLLER_CPP = "src/engine/server/library/serverGame/src/shared/controller/CreatureController.cpp"
CONNECTION_CPP = "src/engine/server/application/ConnectionServer/src/shared/ClientConnection.cpp"
CONTROLLER_DEF = "src/engine/shared/library/sharedFoundation/src/shared/GameControllerMessage.def"
# sha256 of the default-profile plans of the stock examples, as the code before this branch produced them:
# the ten without client steps, and the three with client steps (whose two corrected counters are reverted
# before hashing; see DefaultPlanTests).
PLAIN_PLANS_BEFORE = "04fda58bbff2aca1e22e6ab83d319718962b0218accaa7a562f03f36ca9011e0"
CLIENT_PLANS_BEFORE = "ed937e6aa59c605c15f9168766045417466714f733230f6d785c379db6cf7d68"
STOCK = ("create_character", "driver_guards", "gamma_shuttle", "group_disband", "group_with_fixture_asserts",
         "login_relogin", "ord_group_sequence", "ord_round_trip", "scenario_concert", "ship_and_group",
         "shuttle_recorded_cases", "terminal_journey", "trade_between_accounts")
STOCK_WITH_CLIENT = ("group_with_fixture_asserts", "scenario_concert", "trade_between_accounts")
NEW_EXAMPLES = ("trade_two_accounts_client", "group_invite_accept_client")


def client(step_id, role, kind, **fields):
    return {"id": step_id, "action": "client", "options": dict(role=role, kind=kind, **fields)}


def fixture(step_id, role, op, args, **fields):
    return {"id": step_id, "action": "agent_fixture", "options": dict(role=role, op=op, args=args, **fields)}


def suite(steps, roles=("leader", "member")):
    return {"format": "swg-test-studio", "schema_version": 1, "id": "group_and_trade",
            "title": "Group, trade and server-side assertions", "category": "functional",
            "roles": list(roles), "steps": steps,
            "review": {"approved": True, "recording": None, "unsupported": []}}


def happy_steps():
    """A invites, B joins, the fixture looks, then a full secure trade with credits and an item, and a tell."""
    return [
        client("hold_leader", "leader", "session_hold"),
        client("hold_member", "member", "session_hold"),
        client("invite", "leader", "group_invite", peer="member"),
        client("join", "member", "group_join", peer="leader"),
        fixture("server_looks", "leader", "inspect", []),
        client("request", "leader", "trade_request", peer="member"),
        client("accept", "member", "trade_accept"),
        client("item", "leader", "trade_add_item", item="123456789"),
        client("credits", "member", "trade_credits", amount=500),
        client("offer_leader", "leader", "trade_offer"),
        client("offer_member", "member", "trade_offer"),
        client("verify_leader", "leader", "trade_verify"),
        client("verify_member", "member", "trade_verify"),
        client("thanks", "member", "tell", peer="leader", text="Thanks for the trade!"),
        client("disband", "leader", "group_disband"),
        client("release_leader", "leader", "session_release"),
        client("release_member", "member", "session_release"),
    ]


def example(name):
    return loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def env(**changes):
    data = {"schema_version": 1, "name": "Isolated SWG", "server_checkout": "/srv/swg",
            "folder": "/tmp/swg-cold-test-0123abcd/client-012345abcdef", "binary": "/tmp/swg-driver64/driver",
            "bindings": {}}
    data.update(changes)
    return data


def bound(suite_data, **changes):
    return env(bindings={r: "bot" + "abcde"[i] for i, r in enumerate(suite_data["roles"])}, **changes)


class ClientStepShapeTests(unittest.TestCase):
    def test_suite_validates_and_compiles_to_interleaved_cases(self):
        cases = compile_suite(suite(happy_steps()), ROOT)["tests"]
        self.assertEqual([c["kind"] for c in cases].count("client_action"), 16)
        self.assertEqual(cases[4]["kind"], "agent_fixture")
        self.assertEqual(cases[2], {"id": "invite", "kind": "client_action",
                                    "options": {"role": "leader", "kind": "group_invite", "peer": "member"}})
        # Every kind is grounded, has a declared field list and (sessions aside) a peer verb.
        self.assertEqual(set(CLIENT_KINDS), set(CLIENT_WIRE))
        self.assertEqual(set(CLIENT_VERB), set(CLIENT_KINDS) - {"session_hold", "session_release"})

    def test_typed_refusals(self):
        bad = [
            {"role": "leader", "kind": "whisper", "peer": "member"},          # not a client action
            {"role": "leader", "kind": "tell", "peer": "member"},             # tell without text
            {"role": "leader", "kind": "group_invite"},                       # missing peer
            {"role": "leader", "kind": "group_leave", "peer": "member"},      # extra field
            {"role": "leader", "kind": "group_invite", "peer": "leader"},     # self
            {"role": "leader", "kind": "group_invite", "peer": "stranger"},   # undeclared peer
            {"role": "ghost", "kind": "session_hold"},                        # undeclared role
            {"role": "leader", "kind": "trade_add_item", "item": "1; drop"},  # injection
            {"role": "leader", "kind": "trade_add_item", "item": "0"},
            {"role": "leader", "kind": "trade_add_item", "item": 12},
            {"role": "leader", "kind": "trade_add_item", "item": "1" * 20},
            {"role": "leader", "kind": "trade_add_item", "item": "5", "item_from": {"step": "make", "row": 0}},
            {"role": "leader", "kind": "trade_add_item", "item_from": {"step": "make"}},
            {"role": "leader", "kind": "trade_add_item", "item_from": {"step": "make", "row": 10}},
            {"role": "leader", "kind": "trade_add_item", "item_from": {"step": "Make!", "row": 0}},
            {"role": "leader", "kind": "trade_credits", "amount": 0},
            {"role": "leader", "kind": "trade_credits", "amount": -5},
            {"role": "leader", "kind": "trade_credits", "amount": TRADE_CREDITS_MAX + 1},
            {"role": "leader", "kind": "trade_credits", "amount": 5.0},
            {"role": "leader", "kind": "trade_credits", "amount": True},
            {"role": "leader", "kind": "trade_credits", "amount": "5"},
            {"role": "leader", "kind": "tell", "peer": "member", "text": ""},
            {"role": "leader", "kind": "tell", "peer": "member", "text": " padded"},
            {"role": "leader", "kind": "tell", "peer": "member", "text": "line\nbreak"},
            {"role": "leader", "kind": "tell", "peer": "member", "text": "x" * 201},
            {"role": "leader", "kind": "tell", "peer": "member", "text": "café"},
            {"role": "leader", "kind": "group_leave", "timeout": 4},
            {"role": "leader", "kind": "group_leave", "timeout": 121},
            {"role": "leader", "kind": "group_leave", "timeout": "30"},
            {"role": "leader", "kind": "group_leave", "expect": {}},
            {"role": "leader", "kind": "group_leave", "expect": {"status": "ok"}},
            {"role": "leader", "kind": "group_leave", "expect": {"result": "0"}},
            {"role": "leader", "kind": "group_leave", "expect": {"secret": "1"}},
            {"role": "leader", "kind": "group_leave", "expect": {"peer_message": "group:left"}},
            {"role": "leader", "kind": "session_hold", "expect": {"actor_message": "a:b"}},
            {"role": "leader", "kind": "session_hold", "command": "runScript"},
            "session_hold",
        ]
        for options in bad:
            with self.subTest(options=options), self.assertRaises(ValueError):
                model.validate_client(options, ["leader", "member"])
        # Seeded fault: the bounds are inclusive and correct values pass.
        good = [
            {"role": "leader", "kind": "trade_credits", "amount": TRADE_CREDITS_MAX},
            {"role": "leader", "kind": "trade_add_item", "item": "9223372036854775807"},
            {"role": "leader", "kind": "trade_add_item", "item_from": {"step": "make", "row": 9}},
            {"role": "leader", "kind": "tell", "peer": "member", "text": "x" * 200},
            {"role": "leader", "kind": "tell", "peer": "member", "text": "Hi, there!", "expect": {"result": "0"}},
            {"role": "leader", "kind": "group_leave", "timeout": 5, "expect": {"status": "0"}},
            {"role": "leader", "kind": "group_invite", "peer": "member", "timeout": 120,
             "expect": {"actor_message": "group:invite_leader", "peer_message": "group:invite_target"}},
        ]
        for options in good:
            with self.subTest(options=options):
                self.assertTrue(model.validate_client(options, ["leader", "member"]))


class ClientOrderTests(unittest.TestCase):
    def refused(self, steps, message):
        with self.assertRaisesRegex(ValueError, message):
            validate(suite(steps))

    def test_happy_path_ends_clean(self):
        result = client_order(happy_steps())
        self.assertEqual(result, {"held": [], "open_trades": [], "grouped": []})

    def test_each_rule_refuses_and_its_seeded_fault_passes(self):
        base = happy_steps()

        def without(*ids):
            return [s for s in copy.deepcopy(base) if s["id"] not in ids]

        rules = [
            (without("hold_member"), "Hold both roles"),
            (without("invite"), "open invitation"),
            (without("accept"), "has not been accepted"),
            (without("offer_member"), "Both traders must offer"),
            (without("request", "accept", "item", "credits", "offer_leader", "offer_member",
                     "verify_leader", "verify_member"), None),
        ]
        for steps, message in rules:
            with self.subTest(message=message):
                if message:
                    self.refused(steps, message)
                else:
                    validate(suite(steps))
        # An answer from the requester, a second simultaneous trade, a non-leader disband.
        swapped = copy.deepcopy(base)
        swapped[6] = client("accept", "leader", "trade_accept")
        self.refused(swapped, "Only the requested peer")
        twice = copy.deepcopy(base)
        twice.insert(7, client("request_again", "member", "trade_request", peer="leader"))
        self.refused(twice, "one peer at a time")
        member_disband = copy.deepcopy(base)
        member_disband[14] = client("disband", "member", "group_disband")
        self.refused(member_disband, "Only the group leader")
        # Releasing with an open trade is refused; cancelling first is fine.
        early = copy.deepcopy(base)[:9] + [client("release_leader", "leader", "session_release")]
        self.refused(early, "open trade")
        cancelled = copy.deepcopy(base)[:9] + [client("cancel", "member", "trade_cancel"),
                                               client("release_leader", "leader", "session_release")]
        validate(suite(cancelled))
        # A change after an offer clears both offers.
        changed = copy.deepcopy(base)
        changed.insert(11, client("more", "leader", "trade_credits", amount=1))
        self.refused(changed, "Both traders must offer")
        # A held role cannot run an ordinary session step meanwhile.
        mixed = copy.deepcopy(base)
        mixed.insert(2, {"id": "plain", "action": "session", "options": {"role": "leader"}})
        self.refused(mixed, "held role cannot also run")
        # A tell needs both sessions held.
        self.refused([client("hold_leader", "leader", "session_hold"),
                      client("say_hi", "leader", "tell", peer="member", text="hi")], "Hold both roles")

    def test_item_from_names_an_earlier_inventory_step_of_the_trader(self):
        head = happy_steps()[:7]
        make = fixture("make", "leader", "createInInventory", ["object/tangible/loot/misc/recording_rod_s01.iff"],
                       scenario="trade1")
        add = client("item", "leader", "trade_add_item", item_from={"step": "make", "row": 0})
        validate(suite(head[:2] + [make] + head[2:] + [add]))
        for steps, why in (
                (head + [add], "earlier createInInventory"),                                     # no such step
                (head + [add, make], "earlier createInInventory"),                               # later step
                (head[:2] + [dict(make, options=dict(make["options"], role="member"))] + head[2:] + [add],
                 "earlier createInInventory"),                                                   # other role's item
                (head[:2] + [fixture("make", "leader", "inspect", [])] + head[2:] + [add],
                 "earlier createInInventory")):                                                  # not an item source
            with self.subTest(why=why):
                self.refused(steps, why)

    def test_group_rules_follow_leadership(self):
        roles = ("leader", "member", "third")
        held = [client("hold_" + r, r, "session_hold") for r in roles]
        form = [client("invite_member", "leader", "group_invite", peer="member"),
                client("join_member", "member", "group_join", peer="leader"),
                client("invite_third", "leader", "group_invite", peer="third"),
                client("join_third", "third", "group_join", peer="leader")]
        promote = [client("promote", "leader", "group_make_leader", peer="member"),
                   client("kick", "member", "group_dismiss", peer="third"),
                   client("leave_old", "leader", "group_leave")]
        self.assertEqual(client_order(held + form + promote)["grouped"], [])
        # Seeded fault: the old leader no longer leads after the promotion.
        bad = held + form + [promote[0], client("kick", "leader", "group_dismiss", peer="third")]
        with self.assertRaisesRegex(ValueError, "Only the group leader"):
            validate(suite(bad, roles))
        declined = held[:2] + [form[0], client("decline_member", "member", "group_decline"),
                               client("join_member", "member", "group_join", peer="leader")]
        with self.assertRaisesRegex(ValueError, "open invitation"):
            validate(suite(declined, roles[:2]))
        uninvited = held[:2] + [form[0], client("take_back", "leader", "group_uninvite", peer="member")]
        self.assertEqual(client_order(uninvited)["grouped"], [])
        with self.assertRaisesRegex(ValueError, "Uninvite needs"):
            validate(suite(held[:2] + [client("take_back", "leader", "group_uninvite", peer="member")], roles[:2]))


class ClientProfileTests(unittest.TestCase):
    def test_restoration_runs_client_actions_and_still_refuses_what_it_must(self):
        restoration = server_profile.get("restoration")
        cases = [{"id": k, "kind": "client_action", "options": {"role": "leader", "kind": k}} for k in CLIENT_KINDS]
        self.assertEqual(server_profile.unsupported(cases, restoration), [])
        self.assertEqual(restoration.client_kinds, frozenset(CLIENT_KINDS))
        # Still refused: station staging, shuttles and the other whitengold-only case kinds.
        for kind in ("studio_journey", "studio_action_sequence", "ship_group", "group_affinity_ord"):
            self.assertTrue(server_profile.unsupported([{"id": "x", "kind": kind, "options": {}}], restoration), kind)
        self.assertTrue(server_profile.unsupported(
            [{"id": "x", "kind": "protocol_session", "options": {"role": "a", "stage_station": True}}], restoration))
        # Seeded fault: a profile without a client kind refuses exactly that step.
        narrowed = server_profile.Profile(**dict(restoration.__dict__, client_kinds=restoration.client_kinds - {"tell"}))
        self.assertEqual(server_profile.unsupported(cases, narrowed), ["tell: client action tell"])
        without = server_profile.Profile(**dict(restoration.__dict__,
                                                case_kinds=restoration.case_kinds - {"client_action"}))
        self.assertEqual(len(server_profile.unsupported(cases, without)), len(CLIENT_KINDS))
        # The default profile accepts every kind, as before.
        self.assertEqual(server_profile.unsupported(cases, server_profile.get()), [])

    def test_new_examples_plan_under_restoration(self):
        for name in NEW_EXAMPLES + STOCK_WITH_CLIENT:
            with self.subTest(suite=name):
                data = example(name)
                selected = plan(data, bound(data, profile="restoration"))
                self.assertEqual(selected["profile"], "restoration")
                self.assertTrue(selected["effects"]["client_held_roles"])
        # Seeded fault: a suite with a whitengold-only step is still refused.
        with self.assertRaisesRegex(ValueError, "restoration server profile cannot run"):
            data = example("ship_and_group")
            plan(data, bound(data, profile="restoration"))

    def test_bundled_tools_still_match_their_manifest(self):
        hashes = verify(TOOLS_ROOT)
        for name in ("zones/protocol_driver.py", "zones/protocol_driver64.cpp", "zones/server_profile.py"):
            self.assertEqual(hashes[name], hashlib.sha256((TOOLS_ROOT / name).read_bytes()).hexdigest())


class DefaultPlanTests(unittest.TestCase):
    """Default-profile plans: unchanged for every stock example; only the two wrong counters are corrected."""

    @staticmethod
    def digest(plans):
        return hashlib.sha256(json.dumps(plans, sort_keys=True).encode()).hexdigest()

    def plans(self, names):
        return {name: plan(example(name), bound(example(name))) for name in names}

    @staticmethod
    def as_before(plans):
        old = copy.deepcopy(plans)
        for row in old.values():
            for key in ("client_held_roles", "client_actions", "client_trade_possible", "client_tells"):
                row["effects"].pop(key)
            # The corrections: a held client step is not a legacy proximity setup, and group steps can leave a group.
            row["effects"]["fixture_proximity_setup"] = True
            row["effects"]["group_cleanup_possible"] = False
        return old

    def test_stock_plans_are_identical_except_the_corrected_counters(self):
        plain = self.plans([n for n in STOCK if n not in STOCK_WITH_CLIENT])
        self.assertEqual(self.digest(plain), PLAIN_PLANS_BEFORE)
        with_client = self.plans(STOCK_WITH_CLIENT)
        self.assertEqual(self.digest(self.as_before(with_client)), CLIENT_PLANS_BEFORE)
        effects = with_client["group_with_fixture_asserts"]["effects"]
        self.assertEqual((effects["fixture_proximity_setup"], effects["group_cleanup_possible"]), (False, True))
        trade = with_client["trade_between_accounts"]["effects"]
        self.assertEqual((trade["fixture_proximity_setup"], trade["group_cleanup_possible"],
                          trade["client_trade_possible"]), (False, False, True))
        # Seeded fault: any change in a plan changes the digest.
        plain["login_relogin"]["effects"]["service_restart"] = True
        self.assertNotEqual(self.digest(plain), PLAIN_PLANS_BEFORE)


# --- Wire bytes: an independent reimplementation of the tree's pack code ------------------------------

def crc(text):
    """sharedFoundation Crc::calculate: CRC-32, polynomial 0x04C11DB7, MSB first, init and xor-out 0xFFFFFFFF."""
    value = 0xFFFFFFFF
    for byte in text.encode("latin-1"):
        value ^= byte << 24
        for _ in range(8):
            value = ((value << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if value & 0x80000000 else (value << 1) & 0xFFFFFFFF
    return value ^ 0xFFFFFFFF


def u16(v): return struct.pack("<H", v)
def u32(v): return struct.pack("<I", v)
def i32(v): return struct.pack("<i", v)
def i64(v): return struct.pack("<q", v)
def f32(v): return struct.pack("<f", v)
def string(text): return u16(len(text)) + text.encode("ascii")                       # Archive put std::string
def unicode(text): return u32(len(text)) + text.encode("utf-16-le")                 # UnicodeArchive put


def message(name, *members):
    """GameNetworkMessage: AutoByteStream count (the type crc is a member), the type crc, then the members."""
    return u16(1 + len(members)) + u32(crc(name)) + b"".join(members)


SEND, RELIABLE, DEST_AUTH_SERVER = 0x1, 0x2, 0x20     # GameControllerMessageFlags


def controller_ids(text=None):
    """CM_secureTrade and CM_commandQueueEnqueue, counted from GameControllerMessage.def when the tree is present."""
    if text is None:
        return {"CM_secureTrade": 277, "CM_commandQueueEnqueue": 278}
    body = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
    body = body[body.index("enum GameControllerMessage"):]
    body = body[body.index("{") + 1:body.index("}")]
    ids, value = {}, -1
    for item in (part.strip() for part in body.split(",")):
        if not item or item.startswith("#"):
            continue
        name, _, explicit = item.partition("=")
        value = int(explicit.strip(), 0) if explicit.strip() else value + 1
        ids[name.strip()] = value
    return {k: ids[k] for k in ("CM_secureTrade", "CM_commandQueueEnqueue")}


def objcontroller(character, controller, payload):
    return message("ObjControllerMessage", u32(SEND | RELIABLE | DEST_AUTH_SERVER), i32(controller), i64(character),
                   f32(0.0)) + payload


def expected_bytes(verb, args, character, sequence, ids):
    """The bytes the peer must send, from the pack code cited in docs/fixture-client-actions.md."""
    tmi = {"tradeRequest": 0, "tradeAccept": 2, "tradeDeny": 3}   # MessageQueueSecureTrade::TradeMessageId order
    if verb in tmi:   # MessageQueueSecureTrade::pack: int id, initiator, recipient
        recipient = int(args[0]) if verb == "tradeRequest" else 0
        return objcontroller(character, ids["CM_secureTrade"], i32(tmi[verb]) + i64(0) + i64(recipient))
    groups = {"groupInvite": "invite", "groupJoin": "join", "groupDecline": "decline", "groupUninvite": "uninvite",
              "groupLeave": "leaveGroup", "groupDisband": "disband", "groupMakeLeader": "makeLeader",
              "groupDismiss": "dismissGroupMember"}
    if verb in groups:   # MessageQueueCommandQueueEnqueue::pack: sequence, command crc, target, params
        target = 0 if verb in ("groupInvite", "groupDecline", "groupLeave", "groupDisband") else int(args[0])
        params = args[1] if verb == "groupInvite" else ""
        return objcontroller(character, ids["CM_commandQueueEnqueue"],
                             u32(sequence) + u32(crc(groups[verb].lower())) + i64(target) + unicode(params))
    if verb == "tradeItem":
        return message("AddItemMessage", i64(int(args[0])))
    if verb == "tradeCredits":
        return message("GiveMoneyMessage", i32(int(args[0])))
    empty = {"tradeOffer": "AcceptTransactionMessage", "tradeUnoffer": "UnAcceptTransactionMessage",
             "tradeVerify": "VerifyTradeMessage", "tradeReject": "DenyTradeMessage", "tradeCancel": "AbortTradeMessage"}
    if verb in empty:
        return message(empty[verb])
    if verb == "tell":   # ChatInstantMessageToCharacter: ChatAvatarId(game, cluster, name), message, oob, sequence
        return message("ChatInstantMessageToCharacter", string("") + string("") + string(args[1]), unicode(args[2]),
                       unicode(""), u32(sequence))
    raise ValueError(verb)


class ClientWireTests(unittest.TestCase):
    """Bytes printed by the peer's --encode mode (linked against the tree) against the reimplementation."""

    def setUp(self):
        self.wire = WIRE
        ids_text = (RESTORATION_TREE / CONTROLLER_DEF).read_text(encoding="latin-1") if HAVE_TREE else None
        self.ids = controller_ids(ids_text)

    def test_recorded_bytes_come_from_this_peer_source(self):
        source = (TOOLS_ROOT / "zones/protocol_driver64.cpp").read_bytes()
        self.assertEqual(self.wire["source_sha256"], hashlib.sha256(source).hexdigest(),
                         "Re-record tests/client_wire_bytes.py with the rebuilt peer's --encode mode")
        self.assertEqual({row["verb"] for row in self.wire["messages"]}, set(CLIENT_VERB.values()))

    def test_every_message_matches_the_pack_code(self):
        character, sequence = int(self.wire["character"]), self.wire["sequence"]
        for row in self.wire["messages"]:
            with self.subTest(verb=row["verb"]):
                self.assertEqual(bytes.fromhex(row["hex"]),
                                 expected_bytes(row["verb"], row["args"], character, sequence, self.ids))
        # Spot checks of known constants: the type crc of a message and a command hash.
        self.assertEqual(crc("ObjControllerMessage"), 0x80CE5E46)
        self.assertEqual(self.ids, {"CM_secureTrade": 277, "CM_commandQueueEnqueue": 278})

    def test_seeded_faults_change_the_bytes(self):
        character, sequence = int(self.wire["character"]), self.wire["sequence"]
        rows = {row["verb"]: row for row in self.wire["messages"]}
        recorded = bytes.fromhex(rows["tradeRequest"]["hex"])
        # Initiator and recipient swapped, as a peer that misread the pack order would send them.
        swapped = objcontroller(character, self.ids["CM_secureTrade"],
                                i32(0) + i64(int(rows["tradeRequest"]["args"][0])) + i64(0))
        self.assertNotEqual(recorded, swapped)
        self.assertNotEqual(bytes.fromhex(rows["tradeCredits"]["hex"]), message("GiveMoneyMessage", i64(500)))
        self.assertNotEqual(bytes.fromhex(rows["tradeItem"]["hex"]), message("AddItemMessage", i32(9123456789012 & 0x7fffffff)))
        invite = bytes.fromhex(rows["groupInvite"]["hex"])
        self.assertNotEqual(invite, expected_bytes("groupInvite", ["8800000000067890", "Capabcdefghijkl"],
                                                   character, sequence + 1, self.ids))
        self.assertNotEqual(crc("Invite"), crc("invite"))   # the command hash is of the normalized (lowercase) name


@unittest.skipUnless(HAVE_TREE, "The restoration server tree is not on this machine")
class ClientGroundingTests(unittest.TestCase):
    def read(self, relative):
        return (RESTORATION_TREE / relative).read_text(encoding="latin-1")

    def grounded(self, source, name):
        if source == "command":
            return re.search(r"^" + re.escape(name) + r"\t", self.read(COMMANDS), re.M) is not None
        if source == "trade":
            return (re.search(r"\b" + name + r"\b", self.read(MESSAGES + "MessageQueueSecureTrade.h")) is not None and
                    "case MessageQueueSecureTrade::" + name + ":" in self.read(CONTROLLER_CPP))
        if source == "message":
            headers = self.read(MESSAGES + "SecureTradeMessages.h") + self.read(MESSAGES + "LogoutMessage.h")
            declared = re.search(r"class " + name + r"\b", headers) is not None
            return declared and (name == "LogoutMessage" or 'isType("' + name + '")' in self.read(CLIENT_CPP))
        if source == "chat":
            return ((RESTORATION_TREE / (CHAT + name + ".h")).is_file() and
                    'm.isType("' + name + '")' in self.read(CONNECTION_CPP))
        return source == "peer" and name == "login"

    def test_every_client_kind_exists_in_the_server_tree(self):
        for kind, (source, name) in CLIENT_WIRE.items():
            with self.subTest(kind=kind):
                self.assertTrue(self.grounded(source, name), (source, name))
        # The trade request travels as a controller message the server accepts from a client, and only the
        # three client trade ids pass the server's provenance check.
        self.assertIn("CONTROLLER_MESSAGE_ALLOW_FROM_CLIENT_IMPLEMENTATION(MessageQueueSecureTrade, CM_secureTrade)",
                      self.read(MESSAGES + "MessageQueueSecureTrade.cpp"))
        integrity = self.read("src/engine/server/library/serverGame/src/shared/trading/SecureTradeIntegrity.h")
        allowed = integrity[integrity.index("isClientTradeMessageAllowed"):][:300]
        self.assertEqual(sorted(re.findall(r"TMID_(\w+)", allowed)), ["AcceptTrade", "DeniedTrade", "RequestTrade"])
        # Seeded faults: invented names are not grounded.
        for source, name in (("command", "peace_now"), ("command", "secureTrade"), ("message", "RemoveAllMessage"),
                             ("trade", "TMI_ForceTrade"), ("chat", "ChatPrivateWhisper"), ("command", "tell")):
            self.assertFalse(self.grounded(source, name), name)

    def test_the_peer_builds_and_reads_the_grounded_classes(self):
        peer = (TOOLS_ROOT / "zones/protocol_driver64.cpp").read_text(encoding="utf-8")
        for built in ("new MessageQueueSecureTrade(tmi,NetworkId::cms_invalid,recipient)", "new AddItemMessage(",
                      "new GiveMoneyMessage(", "new AcceptTransactionMessage()", "new UnAcceptTransactionMessage()",
                      "new VerifyTradeMessage()", "new DenyTradeMessage()", "new AbortTradeMessage()",
                      "new ChatInstantMessageToCharacter(", "new MessageQueueCommandQueueEnqueue("):
            self.assertIn(built, peer)
        server = self.read("src/engine/server/library/serverGame/src/shared/trading/ServerSecureTrade.cpp")
        for sent in ("BeginTradeMessage", "AddItemMessage", "AddItemFailedMessage", "GiveMoneyMessage",
                     "AcceptTransactionMessage", "UnAcceptTransactionMessage", "BeginVerificationMessage",
                     "VerifyTradeMessage", "DenyTradeMessage", "TradeCompleteMessage", "AbortTradeMessage"):
            self.assertIn(sent + " const", server)            # the server sends it ...
            self.assertRegex(peer, r'isType\((")?' + sent)    # ... and the peer reports it
        self.assertNotRegex(peer, r'isType\("BeginTradeRequestMessage')   # seeded fault: an invented class

    def test_remove_item_is_left_out_because_the_server_cancels_the_trade(self):
        text = self.read("src/engine/server/library/serverGame/src/shared/trading/ServerSecureTrade.cpp")
        body = text[text.index("void ServerSecureTrade::removeItem"):][:400]
        self.assertIn("cancelTrade (trader);", body)
        self.assertNotIn("trade_remove_item", CLIENT_KINDS)


# --- Held sessions against the fake peer ------------------------------------------------------------

class FakeFixture:
    """Starts fake peers that share one bus; records every pid so tests can prove nothing leaked."""

    def __init__(self, test, roles, faults=None, lifetime=60):
        self.folder = Path(tempfile.mkdtemp(prefix="held-"))
        test.addCleanup(self.reap)
        self.pids = self.folder / "pids"
        self.faults = faults or {}
        self.lifetime = lifetime
        self.ids = {role: str(8800000000000001 + i) for i, role in enumerate(roles)}
        self.names = {role: "Cap" + "abcdefghijkl"[i:] + "a" * i for i, role in enumerate(roles)}
        self.launched = []

    def launch(self, role):
        companions = [f"--companion={self.ids[r]}:{self.names[r]}" for r in self.ids if r != role]
        faults = [f"--fault={f}" for f in self.faults.get(role, ())]
        argv = [sys.executable, "-I", str(FAKE_PEER), "--bus", str(self.folder), "--player", self.ids[role],
                "--character", self.names[role], "--pid-file", str(self.pids), "--lifetime", str(self.lifetime),
                *companions, *faults]
        peer = HeldPeer(role, argv, self.folder / f"{role}-{len(self.launched)}.log")
        self.launched.append(peer)
        try:
            peer.wait(lambda e: e["event"] == "scene_ready", after=0, timeout=10, describe="scene_ready")
        except BaseException:
            peer.close(graceful=False)
            raise
        return peer, {"player": self.ids[role], "character": self.names[role]}

    def alive(self):
        if not self.pids.exists():
            return []
        live = []
        for pid in map(int, self.pids.read_text().split()):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            # A reaped zombie is not running; read its state.
            stat = Path(f"/proc/{pid}/stat")
            if stat.exists() and stat.read_text().split(")")[-1].split()[0] != "Z":
                live.append(pid)
        return live

    def reap(self):
        for peer in self.launched:
            if peer.process.poll() is None:
                peer.process.kill()
                peer.process.wait()


def options(role, kind, **fields):
    return dict(role=role, kind=kind, **fields)


@unittest.skipUnless(sys.platform != "win32", "The fake peer uses fcntl")
class HeldSessionTests(unittest.TestCase):
    def pool(self, roles, **kw):
        fake = FakeFixture(self, roles, **kw)
        pool = HeldPool(fake.launch)
        self.addCleanup(pool.close)
        return fake, pool

    def test_two_roles_group_trade_and_tell_interleaved_with_fixture_steps(self):
        fake, pool = self.pool(("leader", "member"))
        steps = [s for s in happy_steps()]
        artifacts = {}
        for step in steps:
            if step["action"] == "agent_fixture":
                # A server-side step between client steps: the sessions stay held meanwhile.
                self.assertEqual(sorted(pool.peers), ["leader", "member"])
                self.assertTrue(all(p.process.poll() is None for p in pool.peers.values()))
                pool.record_fixture(step["id"], {"reply": {"status": "ok", "fields": {}, "rows": []}})
                continue
            artifacts[step["id"]] = pool.perform(step["options"])
        self.assertEqual(pool.peers, {})
        self.assertEqual(fake.alive(), [])
        observed = {k: [(o["role"], o["event"]) for o in v.get("observed", [])] for k, v in artifacts.items()}
        self.assertEqual(observed["request"], [("member", "secure_trade")])
        self.assertEqual(observed["accept"], [("member", "trade_begun"), ("leader", "trade_begun")])
        self.assertEqual(observed["offer_member"], [("leader", "trade_offer_accepted"), ("member", "trade_verification"),
                                                    ("leader", "trade_verification")])
        self.assertEqual(observed["verify_member"], [("leader", "trade_verified"), ("member", "trade_complete"),
                                                     ("leader", "trade_complete")])
        self.assertEqual(observed["thanks"], [("member", "tell_result"), ("leader", "tell_received")])
        self.assertEqual(artifacts["invite"]["observed"][0]["command"], "invite")
        self.assertEqual(artifacts["release_leader"]["closed"]["mode"], "logout")
        self.assertEqual(artifacts["credits"]["observed"][0]["amount"], 500)

    def test_item_from_resolves_the_fixture_reply_row(self):
        fake, pool = self.pool(("leader", "member"))
        for kind, role, extra in (("session_hold", "leader", {}), ("session_hold", "member", {}),
                                  ("trade_request", "leader", {"peer": "member"}), ("trade_accept", "member", {})):
            pool.perform(options(role, kind, **extra))
        pool.record_fixture("make", {"reply": {"status": "ok", "fields": {}, "rows": ["", "4242424242,carried"]}})
        result = pool.perform(options("leader", "trade_add_item", item_from={"step": "make", "row": 1}))
        self.assertEqual(result["observed"][0]["item"], "4242424242")
        # Seeded faults: an absent row and a row that is not an object ID fail before anything is sent.
        with self.assertRaisesRegex(ClientStepFailed, "no reply row 5"):
            pool.perform(options("leader", "trade_add_item", item_from={"step": "make", "row": 5}))
        with self.assertRaisesRegex(ClientStepFailed, "does not start with an object ID"):
            pool.perform(options("leader", "trade_add_item", item_from={"step": "make", "row": 0}))
        pool.perform(options("member", "trade_cancel"))
        self.assertEqual(pool.trades, {})

    def test_five_concurrent_sessions_and_the_limit(self):
        roles = ("alpha", "bravo", "charlie", "delta", "echo")
        fake, pool = self.pool(roles)
        for role in roles:
            pool.perform(options(role, "session_hold"))
        self.assertEqual(len(fake.alive()), 5)
        for sender, receiver in zip(roles, roles[1:] + roles[:1]):
            result = pool.perform(options(sender, "tell", peer=receiver, text="ring from " + sender))
            self.assertEqual(result["observed"][1]["text"], "ring from " + sender)
        with self.assertRaisesRegex(ValueError, "At most 5"):
            HeldPool(fake.launch, limit=6)
        small = HeldPool(fake.launch, limit=1)
        self.addCleanup(small.close)
        self.assertRaisesRegex(ClientStepFailed, "already held", pool.perform, options("alpha", "session_hold"))
        self.assertEqual(len(pool.close()), 5)
        self.assertEqual(fake.alive(), [])
        # Seeded fault: a pool of one refuses a second role.
        small.perform(options("alpha", "session_hold"))
        with self.assertRaisesRegex(ClientStepFailed, "At most 1"):
            small.perform(options("bravo", "session_hold"))

    def test_a_failing_role_tears_every_role_down(self):
        for fault, error in (("tradeRequest=fail", "injected failure"), ("tradeRequest=crash", "peer exited"),
                             ("tradeRequest=refuse", "refused tradeRequest")):
            with self.subTest(fault=fault):
                fake, pool = self.pool(("leader", "member", "third"), faults={"leader": (fault,)})
                for role in ("leader", "member", "third"):
                    pool.perform(options(role, "session_hold"))
                pool.perform(options("leader", "group_invite", peer="member"))
                pool.perform(options("member", "group_join", peer="leader"))
                with self.assertRaisesRegex(ClientStepFailed, error):
                    pool.perform(options("leader", "trade_request", peer="member"))
                records = pool.close()
                self.assertEqual(sorted(r["role"] for r in records), ["leader", "member", "third"])
                self.assertEqual(fake.alive(), [])
                healthy = [r for r in records if r["role"] != "leader"]
                self.assertTrue(all(r["mode"] == "logout" and r["exit_code"] == 0 for r in healthy), healthy)
                self.assertTrue(pool.closed)
                with self.assertRaisesRegex(ClientStepFailed, "closed"):
                    pool.perform(options("member", "group_leave"))

    def test_timeouts_are_bounded_and_typed(self):
        with patch.object(backend, "HELD_REPLY_TIMEOUT", 1), patch.object(backend, "HELD_CLOSE_TIMEOUT", 1):
            fake, pool = self.pool(("leader", "member"), faults={"leader": ("tradeRequest=hang", "logout=hang"),
                                                                   "member": ("groupDecline=silent",)})
            pool.perform(options("leader", "session_hold"))
            pool.perform(options("member", "session_hold"))
            started = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, "no reply to tradeRequest within 1"):
                pool.perform(options("leader", "trade_request", peer="member"))
            with self.assertRaisesRegex(TimeoutError, "member saw no command result 0 within 5"):
                pool.perform(options("member", "group_decline", timeout=5))
            self.assertLess(time.monotonic() - started, 12)
            records = {r["role"]: r for r in pool.close()}
            # The leader ignores its logout: it is still stopped, and the record says how.
            self.assertIn("TimeoutError", records["leader"]["error"])
            self.assertIsNotNone(records["leader"]["exit_code"])
            self.assertEqual(records["member"]["exit_code"], 0)
            self.assertEqual(fake.alive(), [])

    def test_server_answers_that_contradict_the_step_fail_it(self):
        fake, pool = self.pool(("leader", "member"), faults={"leader": ("groupInvite=status7",)})
        pool.perform(options("leader", "session_hold"))
        pool.perform(options("member", "session_hold"))
        with self.assertRaisesRegex(ClientStepFailed, "command finished otherwise"):
            pool.perform(options("leader", "group_invite", peer="member"))
        # Seeded fault: the same answer passes when the step expects it.
        result = pool.perform(options("leader", "group_invite", peer="member", expect={"status": "7"}))
        self.assertEqual(result["observed"][0]["status"], 7)
        # A recipient that already has a pending request answers busy: a refusal, not a timeout
        # (CreatureController::tradeRequested returns false, the requester gets TMI_DeniedPlayerBusy).
        pool.perform(options("leader", "trade_request", peer="member"))
        with self.assertRaisesRegex(ClientStepFailed, "refused the request"):
            pool.perform(options("leader", "trade_request", peer="member"))
        pool.close()
        self.assertEqual(fake.alive(), [])

    def test_login_failure_leaves_nothing_running(self):
        fake, pool = self.pool(("leader", "member"), faults={"member": ("login=fail",)})
        pool.perform(options("leader", "session_hold"))
        with self.assertRaisesRegex(ClientStepFailed, "login denied"):
            pool.perform(options("member", "session_hold"))
        self.assertEqual(sorted(pool.peers), ["leader"])
        pool.close()
        self.assertEqual(fake.alive(), [])
        # Seeded fault: a peer that never logs out is still stopped by close().
        fake2, pool2 = self.pool(("solo",), faults={"solo": ("logout=hang",)})
        with patch.object(backend, "HELD_CLOSE_TIMEOUT", 1):
            pool2.perform(options("solo", "session_hold"))
            self.assertEqual(len(fake2.alive()), 1)
            pool2.close()
        self.assertEqual(fake2.alive(), [])


class RunSuiteTests(unittest.TestCase):
    """run_suite sends client cases to one pool, keeps it across agent_fixture steps and always closes it."""

    def run_suite(self, data, faults=None):
        fake = FakeFixture(self, data["roles"], faults=faults)

        class Driver:
            REPO = ROOT

        class Legacy:
            @staticmethod
            def source_hashes():
                return {}

            @staticmethod
            def validate(manifest):
                raise AssertionError("client and fixture cases never reach the legacy validator")

        def run_live(options, env, registry, bindings=None):
            rows = ["777000111,carried"] if options["op"] == "createInInventory" else []
            return {"fixture": "agent_scenario", "op": options["op"], "reply": {"status": "ok", "fields": {}, "rows": rows}}

        workspace = tempfile.mkdtemp(prefix="studio-")
        events = []
        with patch.object(backend, "driver_modules", return_value=(Driver, Legacy)), \
                patch("swg_test_studio.agent_fixture.run_live", side_effect=run_live):
            result = backend.run_suite(data, bound(data), workspace, emit=events.append,
                                       launcher=lambda env, bindings, output, driver: (fake.launch, lambda: None))
        report = json.loads((Path(result["evidence"]) / "result.json").read_text())
        return fake, result, report

    def test_new_example_runs_end_to_end_against_fake_peers(self):
        fake, result, report = self.run_suite(example("trade_two_accounts_client"))
        self.assertTrue(result["passed"], report.get("error") or [c for c in report["cases"] if not c["passed"]])
        self.assertEqual(fake.alive(), [])
        self.assertEqual(report["held_sessions"], [])   # both roles were released by the suite itself
        added = next(c for c in report["cases"] if c["id"] == "offer_rod")
        self.assertEqual(added["artifact"]["observed"][0]["item"], "777000111")

    def test_a_failure_stops_the_run_and_closes_every_session(self):
        data = example("group_invite_accept_client")
        fake, result, report = self.run_suite(data, faults={"member": ("groupJoin=crash",)})
        self.assertFalse(result["passed"])
        failed = [c for c in report["cases"] if not c["passed"]]
        self.assertEqual([c["id"] for c in failed], ["join"])
        self.assertEqual(sorted(r["role"] for r in report["held_sessions"]), ["leader", "member"])
        self.assertEqual(fake.alive(), [])
        # Seeded fault: without the fault the same suite passes.
        fake, result, report = self.run_suite(data)
        self.assertTrue(result["passed"], report)


if __name__ == "__main__":
    unittest.main()
