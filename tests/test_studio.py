import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from swg_test_studio import backend, model, recording
from swg_test_studio.cli import main
from swg_test_studio.store import EXAMPLES, Library, read_json, write_json


def example(name="login_relogin"):
    return read_json(EXAMPLES / (name + ".json"))


def env():
    return {"schema_version": 1, "name": "Isolated SWG", "server_checkout": "/mnt/f/SWGProjects/whitengold-ai/whitengold",
            "folder": "/tmp/swg-cold-test-0123abcd/client-012345abcdef", "binary": "/tmp/matched-driver",
            "bindings": {"actor": "beta", "leader": "gamma", "member": "delta", "newleader": "epsilon"}}


class ModelTests(unittest.TestCase):
    def test_all_examples_validate(self):
        for path in EXAMPLES.glob("*.json"):
            with self.subTest(path=path.name):
                model.validate(read_json(path), runnable=True)

    def test_strict_fields_types_and_no_executable_commands(self):
        for change in ({"shell": "bad"}, {"schema_version": True}, {"roles": ["actor", "actor"]}, {"id": "../escape"}):
            data = example()
            data.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                model.validate(data)
        for options in ({"role": "actor", "create": 1}, {"role": "actor", "script": "x"},
                        {"role": "actor", "expect_scene": "../../x"}, {"role": "actor", "create": True, "prepare_terminal": True}):
            data = example()
            data["steps"][0]["options"] = options
            with self.subTest(options=options), self.assertRaises(ValueError):
                model.validate(data)

    def test_duplicate_json_nan_and_size_refused(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', ' ' * 262145):
            with self.assertRaises(ValueError):
                model.loads(text)

    def test_recording_cannot_be_promoted_by_approval_alone(self):
        data = example()
        data["steps"] = [{"id": "observed", "action": "recorded_observation", "options": {"summary": "menu"}}]
        model.validate(data)
        with self.assertRaises(ValueError):
            model.validate(data, runnable=True)
        for review in ({"approved": False, "recording": None, "unsupported": []},
                       {"approved": True, "recording": None, "unsupported": ["movement"]}):
            data = example()
            data["review"] = review
            with self.assertRaises(ValueError):
                model.validate(data, runnable=True)

    def test_fault_recipes_not_exposed(self):
        data = example("ship_and_group")
        data["steps"][0]["options"]["suite"] = "stage7_live_fault_recovery"
        with self.assertRaises(ValueError):
            model.validate(data)

    def test_compiler_preserves_semantics_and_declared_roles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root / "ship_group.json", {"roles": ["leader", "member"], "tests": [
                {"id": "round_trip", "kind": "ship_group", "options": {"leader": "leader", "member": "member"}}]})
            data = example("ship_and_group")
            data["roles"] = ["pilot", "friend"]
            data["steps"][0]["options"]["bindings"] = {"leader": "pilot", "member": "friend"}
            manifest = model.compile_suite(data, root)
            self.assertEqual(manifest["tests"][0]["options"], {"leader": "pilot", "member": "friend"})
            self.assertEqual(manifest["roles"], ["pilot", "friend"])
            write_json(root / "ship_group.json", {"roles": ["leader", "member"], "tests": [
                {"id": "fault", "kind": "pending_faults", "options": {}}]}, replace=True)
            with self.assertRaises(ValueError):
                model.compile_suite(data, root)

    def test_recipe_cannot_expand_creation_into_shuttle(self):
        data = example("gamma_shuttle")
        data["steps"][0]["options"]["create"] = True
        with self.assertRaises(ValueError):
            model.validate(data)


class StoreTests(unittest.TestCase):
    def test_save_import_replace_and_examples_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            library = Library(temporary)
            data = example()
            with self.assertRaises(ValueError):
                library.save(data)
            data["id"] = "my_login"
            library.save(data)
            self.assertEqual(library.get("my_login"), data)
            with self.assertRaises(FileExistsError):
                library.save(data)
            data["title"] = "Changed title"
            library.save(data, replace=True)
            self.assertEqual(library.get("my_login")["title"], "Changed title")
            self.assertEqual(len(library.list()), 8)

    def test_path_traversal_never_reads_a_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                Library(temporary).get("../../results")


class EnvironmentTests(unittest.TestCase):
    def test_only_explicit_swg_fixture_and_distinct_bindings(self):
        backend.validate_environment(env())
        for change in ({"folder": "/tmp/other/client-012345abcdef"}, {"server_checkout": "/x/../y"},
                       {"binary": "driver;anything"}, {"bindings": {"leader": "beta", "member": "beta"}},
                       {"password": "never"}):
            data = env()
            data.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                backend.validate_environment(data)

    def test_preview_is_read_only_and_exposes_proximity_setup(self):
        result = backend.plan(example("gamma_shuttle"), env())
        self.assertTrue(result["effects"]["fixture_proximity_setup"])
        self.assertFalse(result["effects"]["service_restart"])
        self.assertEqual(result["bindings"], {"actor": "beta"})
        with self.assertRaises(ValueError):
            backend.plan(example(), dict(env(), bindings={}))


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.root = self.workspace / "fixture"
        self.root.mkdir()
        self.token = "a" * 32
        (self.root / self.token).mkdir()
        self.control = "SWGTS1 " + self.token + " 9999999999 42 Capabcdefghijkl\n"
        self.metadata = {"schema_version": 1, "id": self.token, "state": "recording", "expires": 9999999999,
                         "environment": env(), "actors": {"123": {"role": "actor"}}, "controls": {"123": self.control}}
        write_json(self.workspace / "recordings" / (self.token + ".json"), self.metadata)
        (self.root / "123.control").write_text(self.control)
        self.patch = patch.object(recording, "root_for", return_value=self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def event(self, **changes):
        row = {"schema_version": 1, "sequence": 1, "session": self.token, "actor": "123", "time": 1,
               "event": "menu_selected", "data": {"scene": "dungeon1"}}
        row.update(changes)
        return row

    def write_events(self, rows):
        (self.root / self.token / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_capture_timeline_stop_and_review_draft(self):
        self.write_events([self.event()])
        self.assertFalse(recording.status(self.workspace, self.token)["replayable"])
        with patch.object(recording, "studio_lock", side_effect=lambda _: contextlib.nullcontext()), patch.object(recording, "finish_writers"):
            recording.stop(self.workspace, self.token)
        self.assertFalse((self.root / "123.control").exists())
        draft = recording.draft(self.workspace, self.token, "my_recording", "Review me")
        model.validate(draft)
        with self.assertRaises(ValueError):
            model.validate(draft, runnable=True)

    def test_gap_foreign_actor_or_session_never_export(self):
        for row in (self.event(sequence=2), self.event(actor="999"), self.event(session="b" * 32)):
            self.write_events([row])
            with self.assertRaises(ValueError):
                recording.status(self.workspace, self.token)

    def test_overflow_partial_and_server_error_visible(self):
        self.write_events([self.event(event="overflow")])
        self.assertTrue(recording.status(self.workspace, self.token)["errors"])
        (self.root / self.token / "events.jsonl").write_text('{"partial":')
        self.assertTrue(recording.status(self.workspace, self.token)["errors"])
        self.write_events([self.event()])
        (self.root / self.token / "capture.error").touch()
        self.assertTrue(recording.status(self.workspace, self.token)["errors"])

    def test_stop_refuses_replaced_control(self):
        (self.root / "123.control").write_text("different recording")
        with patch.object(recording, "studio_lock", side_effect=lambda _: contextlib.nullcontext()), self.assertRaises(ValueError):
            recording.stop(self.workspace, self.token)
        self.assertTrue((self.root / "123.control").exists())


class CliTests(unittest.TestCase):
    def test_list_and_validation_use_shared_engine(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--workspace", temporary, "list"]), 0)
            value = json.loads(output.getvalue())
            self.assertEqual(len(value["suites"]), 7)
            output.seek(0)
            output.truncate()
            self.assertEqual(main(["--workspace", temporary, "validate", "login_relogin"]), 0)
            self.assertTrue(json.loads(output.getvalue())["valid"])


if __name__ == "__main__":
    unittest.main()
