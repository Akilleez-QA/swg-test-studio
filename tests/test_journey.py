import copy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from swg_test_studio import capture_compile, model, recording
from swg_test_studio.journey import Journey
from swg_test_studio.store import EXAMPLES, read_json, write_json


def options():
    return read_json(EXAMPLES / "terminal_journey.json")["steps"][0]["options"]


def capture():
    action = options()["actions"][0]
    records = [
        ("menu_selected", dict(action["source"], selector="gamma_shuttle", menu_type=21, target="12345")),
        ("sui_presented", dict(action["source"], page=41, page_name="Script.messageBox", prompt=action["prompt"])),
        ("sui_callback", dict(action["source"], page=41, page_name="Script.messageBox", prompt=action["prompt"], answer="ok")),
        ("scene_published", dict(action["expected"], instance=294)),
    ]
    return [dict(schema_version=1, sequence=i + 1, actor="123", session="a" * 32, time=i,
                 event=event, data=dict(data, capture_contract=2)) for i, (event, data) in enumerate(records)]


class CompilerTests(unittest.TestCase):
    def test_complete_capture_generates_stable_action_without_runtime_ids(self):
        actions, problems = capture_compile.convert(capture())
        self.assertFalse(problems)
        self.assertEqual(actions, options()["actions"][:1])
        text = json.dumps(actions)
        self.assertNotIn("12345", text)
        self.assertNotIn('"page"', text)
        self.assertNotIn('"instance"', text)

    def test_changed_page_and_object_ids_generate_identical_tests(self):
        records = capture()
        records[0]["data"]["target"] = "99999"
        records[1]["data"]["page"] = records[2]["data"]["page"] = 777
        records[3]["data"]["instance"] = 400
        self.assertEqual(capture_compile.convert(records), capture_compile.convert(capture()))

    def test_missing_offer_callback_arrival_and_wrong_room_stay_blocked(self):
        for index in (1, 2, 3):
            records = capture()
            del records[index]
            with self.subTest(index=index):
                self.assertTrue(capture_compile.convert(records)[1])
        for field, value in (("page", 42), ("prompt", "@other:prompt"), ("page", True), ("family", "npe_space_dungeon")):
            records = capture()
            records[2]["data"][field] = value
            self.assertTrue(capture_compile.convert(records)[1])
        records = capture()
        records[3]["data"]["room"] = "hangarbay2"
        self.assertTrue(capture_compile.convert(records)[1])

    def test_movement_unknown_commands_overlapping_requests_and_legacy_hooks_block(self):
        for kind, data in (("movement_requested", {}), ("command_requested", {"command": "unsupported"}),
                           ("unknown_event", {}), ("menu_selected", capture()[0]["data"])):
            records = capture()
            records.insert(1, dict(records[0], event=kind, data=dict(data, capture_contract=2)))
            self.assertTrue(capture_compile.convert(records)[1])
        records = capture()
        records[0]["data"].pop("capture_contract")
        self.assertTrue(capture_compile.convert(records)[1])

    def test_cancel_is_explicit_and_has_no_inferred_arrival(self):
        records = capture()[:3]
        records[2]["data"]["answer"] = "cancel"
        actions, problems = capture_compile.convert(records)
        self.assertFalse(problems)
        self.assertEqual(actions[0]["source"], actions[0]["expected"])
        self.assertEqual(actions[0]["answer"], "cancel")

    def test_draft_requires_review_and_compiles_into_typed_journey(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            meta = {"actors": {"123": {"role": "actor"}}}
            with patch.object(recording, "load", return_value=(None, meta, root)), patch.object(recording, "status", return_value={
                    "state": "stopped", "errors": [], "events": capture()}):
                draft = recording.draft(root, "a" * 32, "my_recording", "Recorded test")
            self.assertEqual(draft["steps"][0]["action"], "journey")
            self.assertEqual(draft["review"]["unsupported"], [])
            with self.assertRaises(ValueError):
                model.validate(draft, runnable=True)
            draft["review"]["approved"] = True
            model.validate(draft, runnable=True)
            compiled = model.compile_suite(draft, root)
            self.assertEqual(compiled["tests"][0]["kind"], "studio_journey")

    def test_typed_contract_rejects_arbitrary_selectors_and_inconsistent_actions(self):
        for key, value in (("selector", "arbitrary"), ("menu_type", True), ("timeout_seconds", 0), ("answer", "yes")):
            data = read_json(EXAMPLES / "terminal_journey.json")
            data["steps"][0]["options"]["actions"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                model.validate(data, runnable=True)
        data = read_json(EXAMPLES / "terminal_journey.json")
        data["steps"][0]["options"]["actions"][1]["source"]["room"] = "wrongroom"
        with self.assertRaises(ValueError):
            model.validate(data)


class Clock:
    def __init__(self): self.now = 0
    def __call__(self): self.now += .1; return self.now
    def sleep(self, seconds): self.now += seconds


class Session:
    def __init__(self, fixture):
        self.fixture, self.commands, self.waits, self.answered = fixture, [], [], False
    def send(self, command):
        self.commands.append(command)
        if command.startswith("answer "): self.answered = True
    def wait(self, kind, timeout, after=None):
        self.waits.append((kind, after))
        if kind == "menu": return {"target": "99999", "items": [{"type": 21}]}
        if kind == "sui": return {"page": 777, "name": "Script.messageBox", "properties": [{
            "widget": "Prompt.lblPrompt", "property": "Text", "value": self.fixture.action["prompt"]}]}
        if kind == "scene_ready": return {"scene": "terrain/dungeon1.trn"}
        return {}


class Fixture:
    def __init__(self):
        self.action = options()["actions"][0]
        self.before = dict(self.action["source"], connected="true", pending="false", outstanding="false", protected="false",
                           instance="12", cell="71", x="1", y="2", z="3", group="null", combat="0", gamma_dialog_pending="false")
        self.after = dict(self.before, **self.action["expected"], cell="88", gamma_dialog_pending="false")
        self.report = {"setup": [], "checks": []}
        self.session = Session(self)
        self.terminal = dict(protocol_bot="terminal", target="99999", selector="gamma_shuttle", terminal_metadata="2", scene="dungeon1",
                             family="npe_space_station", cell="71", same_cell="true", distance="2")
    def row(self): return copy.deepcopy(self.before)
    def query(self, command):
        if command == "botTerminals": return copy.deepcopy(self.terminal)
        if command == "botInspect":
            return copy.deepcopy(self.after if self.session.answered else dict(self.before, gamma_dialog_pending="true"))
        raise AssertionError("Unexpected setup/query: " + command)


class ReplayTests(unittest.TestCase):
    def make(self):
        fixture, clock = Fixture(), Clock()
        return fixture, Journey(fixture, fixture.query, clock, clock.sleep)

    def test_replay_resolves_fresh_ids_and_uses_all_fresh_event_fences(self):
        fixture, engine = self.make()
        result = engine.action(fixture.action)
        self.assertEqual(result["family"], "npe_space_dungeon")
        self.assertEqual(fixture.session.commands, ["menu 99999", "select 99999 21", "answer 777 ok"])
        self.assertTrue(all(stamp is not None for _, stamp in fixture.session.waits))
        self.assertIn("scene_ready", [kind for kind, _ in fixture.session.waits])

    def test_terminal_ambiguity_wrong_copy_cell_or_distance_sends_nothing(self):
        for change in ({"protocol_bot": "ambiguous-terminal"}, {"family": "other"}, {"cell": "999"},
                       {"same_cell": "false"}, {"distance": "nan"}, {"distance": "20"}):
            fixture, engine = self.make()
            fixture.terminal.update(change)
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                engine.action(fixture.action)
            self.assertEqual(fixture.session.commands, [])

    def test_wrong_offered_menu_never_selects(self):
        fixture, engine = self.make()
        original = fixture.session.wait
        fixture.session.wait = lambda kind, *a, **k: {"target": "99999", "items": [{"type": 22}]} if kind == "menu" else original(kind, *a, **k)
        with self.assertRaises(RuntimeError): engine.action(fixture.action)
        self.assertEqual(fixture.session.commands, ["menu 99999"])

    def test_wrong_destination_and_unsettled_arrival_never_pass(self):
        for change in ({"room": "hangarbay2"}, {"protected": "true"}, {"pending": "true"}, {"outstanding": "true"},
                       {"x": "nan"}, {"cell": "null"}, {"instance": "missing"}):
            fixture, engine = self.make()
            fixture.after.update(change)
            fixture.action["timeout_seconds"] = 10
            with self.subTest(change=change), self.assertRaises(TimeoutError): engine.action(fixture.action)
            self.assertEqual(fixture.report["checks"], [])

    def test_cancel_waits_for_consumption_and_preserves_point_and_copy(self):
        fixture, engine = self.make()
        fixture.action["answer"] = "cancel"
        fixture.action["expected"] = copy.deepcopy(fixture.action["source"])
        fixture.after = copy.deepcopy(fixture.before)
        engine.action(fixture.action)
        self.assertEqual(fixture.session.commands[-1], "answer 777 cancel")
        self.assertNotIn("scene_ready", [kind for kind, _ in fixture.session.waits])
        for change in ({"x": "2"}, {"x": "nan"}, {"cell": "999"}, {"instance": "14"}):
            fixture, engine = self.make()
            fixture.action.update(answer="cancel", expected=copy.deepcopy(fixture.action["source"]))
            fixture.after = dict(fixture.before, **change)
            with self.subTest(change=change), self.assertRaises(RuntimeError): engine.action(fixture.action)

    def test_preview_failure_prevents_position_mutation(self):
        fixture, engine = self.make()
        calls = []
        engine.query = lambda command: calls.append(command) or {"protocol_bot": "ambiguous-terminal"}
        with self.assertRaises(RuntimeError): engine.position()
        self.assertEqual(calls, ["botTerminals"])


if __name__ == "__main__": unittest.main()
