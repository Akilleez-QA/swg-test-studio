import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from swg_test_studio.batch import run_selected
from swg_test_studio.collection import FORMAT, Collection
from swg_test_studio.groups import UNGROUPED, move_test
from swg_test_studio.store import Library


class GroupTests(unittest.TestCase):
    def test_collection_groups_round_trip_without_changing_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            collection = Collection(workspace / "collection.json")
            suites = [Library(workspace).get("login_relogin"), Library(workspace).get("driver_guards")]
            collection.write({"format": FORMAT, "schema_version": 1, "title": "Checks", "suites": suites})
            self.assertEqual(collection.groups(), {})
            groups = {"Smoke": ["login_relogin"], "Unit": ["driver_guards"]}
            collection.save_groups(move_test(groups, "login_relogin", "Unit"))
            self.assertEqual(collection.groups(), {"Smoke": [], "Unit": ["driver_guards", "login_relogin"]})
            with self.assertRaisesRegex(ValueError, "only one group"):
                collection.save_groups(groups | {"Second": ["login_relogin"]})
            collection.save_groups(move_test(collection.groups(), "login_relogin", UNGROUPED))
            self.assertEqual(collection.read()["suites"], suites)
            self.assertEqual(collection.groups(), {"Smoke": [], "Unit": ["driver_guards"]})

    def test_selected_run_uses_one_server_and_exact_test_order(self):
        with tempfile.TemporaryDirectory() as directory:
            names = ["login_relogin", "driver_guards"]
            env = {"bindings": {"actor": "tester"}}
            result = {"passed": True}
            with patch("swg_test_studio.setup.automatic_environment", return_value=env), \
                    patch("swg_test_studio.batch.plan"), \
                    patch("swg_test_studio.docker_runtime.active_server",
                          return_value=contextlib.nullcontext()) as active, \
                    patch("swg_test_studio.batch.run_batch", return_value=result) as batch:
                self.assertIs(run_selected(names, Library(directory), directory, emit=lambda _: None), result)
            active.assert_called_once()
            self.assertTrue(active.call_args.kwargs["login_only"])
            self.assertEqual([job["id"] for job in batch.call_args.args[0]], names)
            self.assertEqual(batch.call_args.args[2], 1)
