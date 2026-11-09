import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from swg_test_studio import model, recording
from swg_test_studio.action_sequence import command
from swg_test_studio.sequence_capture import convert


ACTORS = {"101": {"role": "pilot"}, "202": {"role": "member"}}
STATION = dict(scene="dungeon1", family="npe_space_station", room="hangarbay1")
ORD = dict(scene="space_ord_mantell", family="", room="")


def event(name, actor="101", **data):
    return {"event": name, "actor": actor, "data": dict(STATION, capture_contract=2) | data}


def group_capture():
    return [
        event("command_requested", command="invite"),
        event("group_invite_sent", peer="202"),
        event("command_requested", actor="202", command="join"),
        event("group_join_sent", actor="202", peer="101"),
        event("group_state", group="808", leader="101"),
        event("group_state", actor="202", group="808", leader="101"),
    ]


def ship_capture():
    return [
        event("menu_selected", selector="ord_launch_terminal", menu_type=21, target="500"),
        event("teleport_applied", **ORD),
        event("scene_published", **ORD),
        event("loading_completed", **ORD),
        event("command_requested", command="npcConversationStart", target="601", **ORD),
        event("command_requested", command="npcConversationSelect", **ORD),
        event("conversation_selected", response="ord_land", **ORD),
        event("teleport_applied"),
        event("scene_published"),
    ]


class SequenceCaptureTests(unittest.TestCase):
    def test_launch_and_landing_resolve_as_typed_actions_without_runtime_ids(self):
        options, problems = convert(ship_capture(), {"101": ACTORS["101"]})
        self.assertEqual(problems, [])
        self.assertEqual(options, {"roles": ["pilot"], "actions": [
            {"kind": "launch", "actor": "pilot"},
            {"kind": "land", "actor": "pilot"},
        ]})

    def test_group_state_must_match_both_members_and_new_leader(self):
        events = group_capture() + [
            event("command_requested", command="makeLeader", target="202"),
            event("group_state", actor="202", group="808", leader="202"),
            event("command_requested", actor="202", command="dismissGroupMember", target="101"),
            event("group_state", group="0", leader="0"),
            event("group_state", actor="202", group="0", leader="0"),
        ]
        options, problems = convert(events, ACTORS)
        self.assertEqual(problems, [])
        self.assertEqual(options["actions"], [
            {"kind": "form_group", "actor": "pilot", "peer": "member"},
            {"kind": "promote", "actor": "pilot", "peer": "member"},
            {"kind": "dismiss", "actor": "member", "peer": "pilot"},
        ])
        for index in (3, 5, 7, 10):
            with self.subTest(missing=index):
                self.assertTrue(convert(events[:index] + events[index + 1:], ACTORS)[1])

    def test_unrelated_teleport_or_unfinished_travel_blocks_a_runnable_draft(self):
        good = ship_capture()
        wrong_room = good[:-1] + [event("scene_published", room="hangarbay2")]
        for events in (good[:-1], wrong_room, good + [event("teleport_applied")],
                       good[:6] + [event("conversation_selected", response="unsupported", **ORD)] + good[7:]):
            with self.subTest(events=events):
                self.assertTrue(convert(events, {"101": ACTORS["101"]})[1])

    def test_exported_group_step_binds_fresh_registry_keys(self):
        events = [dict(row, sequence=index) for index, row in enumerate(group_capture() + ship_capture(), 1)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (patch.object(recording, "load", return_value=(None, {"actors": ACTORS}, root)),
                  patch.object(recording, "status", return_value={"state": "stopped", "errors": [], "events": events})):
                suite = recording.draft(root, "a" * 32, "recorded_crew", "Reviewed crew")
            self.assertFalse(suite["review"]["approved"])
            suite["review"]["approved"] = True
            compiled = model.compile_suite(suite, root)
            case = compiled["tests"][0]
            self.assertEqual(case["kind"], "studio_action_sequence")
            env = {"server_checkout": "/fixture/server", "folder": "/fixture/world", "binary": "/fixture/driver"}
            argv = command(case["options"], env, {"pilot": "gamma", "member": "delta"}, root, case["id"])
            data = json.loads(Path(argv[-1]).read_text(encoding="utf-8"))
            self.assertEqual(data["actions"][0], {"kind": "form_group", "actor": "gamma", "peer": "delta"})
            self.assertEqual(argv[-5:-1], ["--bots", "gamma", "delta", "--studio-actions"])
