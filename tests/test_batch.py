from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from swg_test_studio.batch import prepare_batch, run_one, schedule, write_report
from swg_test_studio.store import Library, read_json, write_json


def job(name, checkout, project):
    return {"id": name, "suite": {"id": "ord_round_trip"},
            "scopes": {("checkout", checkout), ("project", project)}}


class BatchTests(unittest.TestCase):
    def test_independent_jobs_overlap_and_shared_scopes_keep_order(self):
        prepared = [job("first", "checkout-a", "project-a"),
                    job("second", "checkout-a", "project-b"),
                    job("third", "checkout-c", "project-b"),
                    job("independent", "checkout-d", "project-d")]
        barrier = threading.Barrier(2, timeout=3)
        active = set()
        order = []
        results = {}
        lock = threading.Lock()

        def run(entry):
            with lock:
                self.assertTrue(active.isdisjoint(entry["scopes"]))
                active.update(entry["scopes"])
                order.append(entry["id"])
            if entry["id"] in ("first", "independent"):
                barrier.wait()
            with lock:
                active.difference_update(entry["scopes"])
            return {"id": entry["id"], "suite": "ord_round_trip", "passed": entry["id"] != "first"}

        self.assertTrue(schedule(prepared, 2, run, results, lambda event: None))
        self.assertEqual(set(order[:2]), {"first", "independent"})
        self.assertEqual(order[2:], ["second", "third"])
        self.assertEqual(len(results), 4)
        self.assertFalse(results["first"]["passed"])

    def test_batch_report_retains_failed_and_skipped_rows(self):
        prepared = [job("first", "a", "a"), job("second", "b", "b")]
        results = {"first": {"id": "first", "suite": "ord_round_trip", "passed": False}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = write_report(root, prepared, results, False, 2)
            self.assertFalse(result["passed"])
            self.assertTrue(result["interrupted"])
            self.assertTrue(read_json(root / "batch-result.json")["runs"][1]["skipped"])
            xml = ET.parse(root / "batch-junit.xml").getroot()
            self.assertEqual(xml.attrib["failures"], "1")
            self.assertEqual(xml.attrib["skipped"], "1")

    def test_job_needs_matching_evidence_even_on_zero_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = Library(root)
            entry = {"id": "first", "suite": library.get("ord_round_trip"), "env": {}}

            def worker(argv, **_):
                folder = Path(argv[argv.index("--workspace") + 1])
                report = folder / "runs" / "operation" / "result.json"
                write_json(report, {"suite": "ord_round_trip", "passed": True})
                report.with_name("junit.xml").write_text("<testsuite/>", encoding="utf-8")
                self.assertEqual(argv[argv.index("run") + 1], "ord_round_trip")
                return subprocess.CompletedProcess(argv, 0)

            with patch("swg_test_studio.batch.subprocess.run", side_effect=worker):
                self.assertTrue(run_one(root, entry)["passed"])
            entry["id"] = "second"
            with patch("swg_test_studio.batch.subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
                self.assertFalse(run_one(root, entry)["passed"])

    def test_driver_manifests_are_rejected_before_opening_a_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "batch.json"
            write_json(path, {"schema_version": 1, "runs": [
                {"id": "fault", "suite": "old_fault", "environment": "missing.json"},
            ]})
            with patch.object(Library, "get", return_value={"id": "old_fault"}):
                with self.assertRaisesRegex(ValueError, "original server harness"):
                    prepare_batch(path, Library(temporary))
