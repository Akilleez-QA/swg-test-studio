import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from swg_test_studio.cli import main
from swg_test_studio.collection import Collection, export_regression
from swg_test_studio.store import EXAMPLES, read_json, write_json


class CollectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.collection = Collection(self.root / "regression.json")
        self.driver = {"schema_version": 1, "id": "old_fault", "title": "Historical recovery test",
                       "category": "system", "roles": [], "tests": [
                           {"id": "old_gate", "kind": "native_gate", "options": {"gate": "old_fixture"}}
                       ]}
        checkout = self.root / "server"
        write_json(checkout / "devtools/zones/test_sets/old_fault.json", self.driver)
        export_regression(checkout, self.collection.path)

    def test_export_and_edit_preserve_original_entries(self):
        before = self.collection.read()["suites"]
        self.assertEqual(len(before), len(list(EXAMPLES.glob("*.json"))) + 1)
        self.assertEqual(self.collection.get("old_fault"), self.driver)
        new = read_json(EXAMPLES / "login_relogin.json")
        new["id"] = "custom_login"
        self.collection.save(new)
        with self.assertRaisesRegex(ValueError, "already contains"):
            self.collection.save(new)
        new["title"] = "Edited title"
        self.collection.save(new, replace=True)
        self.assertEqual(self.collection.read()["suites"], before + [new])
        self.assertEqual(self.collection.get("custom_login"), new)

    def test_driver_manifest_is_visible_but_never_dispatched(self):
        for command in (["validate", "old_fault"], ["run", "old_fault", "--environment", "unused.json"]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                # Exercise the native CLI dispatch without a Windows-to-WSL relay.
                with patch("swg_test_studio.cli.os", SimpleNamespace(name="posix")):
                    status = main(["--collection", str(self.collection.path), *command])
            payload = json.loads(output.getvalue())
            if command[0] == "validate":
                self.assertEqual(status, 0)
                self.assertFalse(payload["studio_replay"])
            else:
                self.assertEqual(status, 1)
                self.assertIn("original server test harness", payload["error"])

    def test_duplicate_ids_do_not_overwrite_collection(self):
        data = self.collection.read()
        data["suites"].append(self.driver)
        before = self.collection.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Duplicate collection"):
            self.collection.write(data, replace=True)
        self.assertEqual(self.collection.path.read_bytes(), before)
