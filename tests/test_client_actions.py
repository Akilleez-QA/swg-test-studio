"""Typed client-side group, trade and session steps (docs/fixture-client-actions.md).

Everything here is offline. The grounding tests read the server tree named by SWG_RESTORATION_TREE and run
only when it is present; the gate always provides it.
"""
import copy
import os
from pathlib import Path
import re
import unittest

from swg_test_studio import model
from swg_test_studio.model import CLIENT_KINDS, CLIENT_WIRE, TRADE_CREDITS_MAX, client_order, compile_suite, validate
from swg_test_studio.server_tools import TOOLS_ROOT
from devtools.zones import server_profile
from devtools.zones.studio_tool_bundle import verify

ROOT = Path(__file__).resolve().parents[1]
RESTORATION_TREE = Path(os.environ.get("SWG_RESTORATION_TREE") or "/nonexistent/restoration-tree")
HAVE_TREE = (RESTORATION_TREE / "src/engine/server/application/CentralServer/Makefile.am").is_file()
COMMANDS = "dsrc/sku.0/sys.shared/compiled/game/datatables/command/command_table.tab"
MESSAGES = "src/engine/shared/library/sharedNetworkMessages/src/shared/clientGameServer/"
CLIENT_CPP = "src/engine/server/library/serverGame/src/shared/core/Client.cpp"
CONTROLLER_CPP = "src/engine/server/library/serverGame/src/shared/controller/CreatureController.cpp"


def client(step_id, role, kind, **fields):
    return {"id": step_id, "action": "client", "options": dict(role=role, kind=kind, **fields)}


def suite(steps, roles=("leader", "member")):
    return {"format": "swg-test-studio", "schema_version": 1, "id": "group_and_trade",
            "title": "Group, trade and server-side assertions", "category": "functional",
            "roles": list(roles), "steps": steps,
            "review": {"approved": True, "recording": None, "unsupported": []}}


def happy_steps():
    """A invites, B joins, the fixture looks, then a full secure trade with credits and an item."""
    return [
        client("hold_leader", "leader", "session_hold"),
        client("hold_member", "member", "session_hold"),
        client("invite", "leader", "group_invite", peer="member"),
        client("join", "member", "group_join", peer="leader"),
        {"id": "server_looks", "action": "agent_fixture", "options": {"role": "leader", "op": "inspect", "args": []}},
        client("request", "leader", "trade_request", peer="member"),
        client("accept", "member", "trade_accept"),
        client("item", "leader", "trade_add_item", item="123456789"),
        client("credits", "member", "trade_credits", amount=500),
        client("offer_leader", "leader", "trade_offer"),
        client("offer_member", "member", "trade_offer"),
        client("verify_leader", "leader", "trade_verify"),
        client("verify_member", "member", "trade_verify"),
        client("disband", "leader", "group_disband"),
        client("release_leader", "leader", "session_release"),
        client("release_member", "member", "session_release"),
    ]


class ClientStepShapeTests(unittest.TestCase):
    def test_suite_validates_and_compiles_to_interleaved_cases(self):
        cases = compile_suite(suite(happy_steps()), ROOT)["tests"]
        self.assertEqual([c["kind"] for c in cases].count("client_action"), 15)
        self.assertEqual(cases[4]["kind"], "agent_fixture")
        self.assertEqual(cases[2], {"id": "invite", "kind": "client_action",
                                    "options": {"role": "leader", "kind": "group_invite", "peer": "member"}})
        # Every kind is grounded and has a declared field list.
        self.assertEqual(set(CLIENT_KINDS), set(CLIENT_WIRE))

    def test_typed_refusals(self):
        bad = [
            {"role": "leader", "kind": "tell", "peer": "member"},             # not a client action
            {"role": "leader", "kind": "group_invite"},                       # missing peer
            {"role": "leader", "kind": "group_leave", "peer": "member"},      # extra field
            {"role": "leader", "kind": "group_invite", "peer": "leader"},     # self
            {"role": "leader", "kind": "group_invite", "peer": "stranger"},   # undeclared peer
            {"role": "ghost", "kind": "session_hold"},                        # undeclared role
            {"role": "leader", "kind": "trade_add_item", "item": "1; drop"},  # injection
            {"role": "leader", "kind": "trade_add_item", "item": "0"},
            {"role": "leader", "kind": "trade_add_item", "item": 12},
            {"role": "leader", "kind": "trade_add_item", "item": "1" * 20},
            {"role": "leader", "kind": "trade_credits", "amount": 0},
            {"role": "leader", "kind": "trade_credits", "amount": -5},
            {"role": "leader", "kind": "trade_credits", "amount": TRADE_CREDITS_MAX + 1},
            {"role": "leader", "kind": "trade_credits", "amount": 5.0},
            {"role": "leader", "kind": "trade_credits", "amount": True},
            {"role": "leader", "kind": "trade_credits", "amount": "5"},
            {"role": "leader", "kind": "session_hold", "command": "runScript"},
            "session_hold",
        ]
        for options in bad:
            with self.subTest(options=options), self.assertRaises(ValueError):
                model.validate_client(options, ["leader", "member"])
        # Seeded fault: the bounds are inclusive and a correct value passes.
        self.assertTrue(model.validate_client({"role": "leader", "kind": "trade_credits", "amount": TRADE_CREDITS_MAX},
                                              ["leader", "member"]))
        self.assertTrue(model.validate_client({"role": "leader", "kind": "trade_add_item",
                                               "item": "9223372036854775807"}, ["leader", "member"]))


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
        member_disband[13] = client("disband", "member", "group_disband")
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
    def test_client_actions_are_refused_until_the_held_runner_exists(self):
        case = [{"id": "invite", "kind": "client_action", "options": {"role": "leader", "kind": "group_invite",
                                                                       "peer": "member"}}]
        restoration = server_profile.get("restoration")
        self.assertEqual(server_profile.unsupported(case, restoration), ["invite: client_action steps"])
        # Seeded fault: a profile listing the kind would accept it.
        widened = server_profile.Profile(**dict(restoration.__dict__,
                                                case_kinds=restoration.case_kinds | {"client_action"}))
        self.assertEqual(server_profile.unsupported(case, widened), [])
        # The whitengold run path refuses the unknown backend in its own validator.
        text = (TOOLS_ROOT / "zones/protocol_test_sets.py").read_text(encoding="utf-8")
        self.assertIn("raise ValueError('Unknown test backend')", text)

    def test_bundled_tools_still_match_their_manifest(self):
        # The driver, peer and profile are hash-pinned in devtools/studio-tools.json; this atom left them as pinned.
        hashes = verify(TOOLS_ROOT)
        for name in ("zones/protocol_driver.py", "zones/protocol_driver64.cpp", "zones/server_profile.py"):
            self.assertIn(name, hashes)


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
        return source == "peer" and name == "login"

    def test_every_client_kind_exists_in_the_server_tree(self):
        for kind, (source, name) in CLIENT_WIRE.items():
            with self.subTest(kind=kind):
                self.assertTrue(self.grounded(source, name), (source, name))
        # The trade request travels as a controller message the server accepts from a client.
        self.assertIn("CONTROLLER_MESSAGE_ALLOW_FROM_CLIENT_IMPLEMENTATION(MessageQueueSecureTrade, CM_secureTrade)",
                      self.read(MESSAGES + "MessageQueueSecureTrade.cpp"))
        # Seeded faults: invented names are not grounded.
        for source, name in (("command", "peace_now"), ("command", "secureTrade"), ("message", "RemoveAllMessage"),
                             ("trade", "TMI_ForceTrade")):
            self.assertFalse(self.grounded(source, name), name)

    def test_remove_item_is_left_out_because_the_server_cancels_the_trade(self):
        text = self.read("src/engine/server/library/serverGame/src/shared/trading/ServerSecureTrade.cpp")
        body = text[text.index("void ServerSecureTrade::removeItem"):][:400]
        self.assertIn("cancelTrade (trader);", body)
        self.assertNotIn("trade_remove_item", CLIENT_KINDS)


if __name__ == "__main__":
    unittest.main()
