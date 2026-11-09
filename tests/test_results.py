import contextlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from swg_test_studio import backend
from swg_test_studio.results import ResultSource, failed_action, open_saved_report, result_steps
from swg_test_studio.store import write_json


class ResultsTests(unittest.TestCase):
    def test_driver_failure_keeps_reason_action_log_and_unrun_steps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {"tests": [{"id": name, "kind": "driver_unit"} for name in ("first", "flight", "after")]}
            outputs = iter([(0, "passed\n"), (1, "STUDIO_STEP start 2 land\nSCENARIO_FAILURE Expected hangar\n")])

            def execute(argv, log, timeout, env):
                code, output = next(outputs)
                log.write(output)
                return code, False

            legacy = SimpleNamespace(validate=lambda _: None, source_hashes=dict, command=lambda *args: [],
                                     execute=execute)
            events = []
            with patch.object(backend, "plan", return_value={"manifest": manifest, "bindings": {}}), \
                    patch.object(backend, "driver_modules", return_value=(SimpleNamespace(REPO=root), legacy)), \
                    patch.object(backend, "studio_lock", return_value=contextlib.nullcontext()):
                result = backend.run_suite({"id": "ship_test"}, {"server_checkout": root, "folder": root,
                                                                 "binary": root / "driver"}, root, events.append)
            self.assertFalse(result["passed"])
            report = Path(result["evidence"]) / "result.json"
            steps = result_steps(open_saved_report(report)["ship_test"])
            self.assertEqual([step.status for step in steps], ["Passed", "Failed", "Not run"])
            self.assertEqual(steps[1].action, "Action 2 · Land")
            self.assertEqual(steps[1].reason, "Expected hangar")
            self.assertIn("Expected hangar", steps[1].log.read_text(encoding="utf-8"))
            self.assertIn("Expected hangar", events[-1]["error"])

    def test_saved_batch_can_open_a_setup_failure_without_a_case_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "batch-result.json"
            write_json(path, {"runs": [{"id": "login", "passed": False, "result": "/unused/old/path"}]})
            log = root / "login" / "cli.jsonl"
            log.parent.mkdir()
            log.write_text('{"event":"error","error":"Fixture could not load"}\n', encoding="utf-8")
            step, = result_steps(open_saved_report(path)["login"])
            self.assertEqual(step.status, "Failed")
            self.assertEqual(step.reason, "Fixture could not load")
            self.assertEqual(step.log, log.resolve())

    def test_completed_actions_are_not_blame_for_later_cleanup_errors(self):
        self.assertEqual(failed_action("STUDIO_STEP start 2 land\nSTUDIO_STEP pass 2 land\n"), "")

    def test_case_id_cannot_read_outside_the_report_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.json"
            write_json(path, {"cases": [{"id": "../private"}]})
            with self.assertRaisesRegex(ValueError, "invalid step ID"):
                result_steps(ResultSource(report=path))
