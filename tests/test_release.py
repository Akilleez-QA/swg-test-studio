from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from swg_test_studio.backend import plan
from swg_test_studio.server_tools import TOOLS_ROOT
from swg_test_studio.store import Library
from devtools.zones.studio_tool_bundle import MANIFEST, verify
import zipfile


class ReleaseTests(unittest.TestCase):
    def test_archive_is_repeatable_with_platform_independent_metadata(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ("first.zip", "second.zip")]
            for path in paths:
                subprocess.run([sys.executable, str(root / "build_release.py"), "--output", str(path)],
                               check=True, capture_output=True, text=True)
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
            with zipfile.ZipFile(paths[0]) as archive:
                self.assertIn("swg_test_studio/examples/terminal_journey.json", archive.namelist())
                self.assertIn("tests/test_release.py", archive.namelist())
                names = {name for name in archive.namelist() if name.startswith("devtools/")}
                self.assertEqual(names, {"devtools/" + name for name in (MANIFEST, *verify(TOOLS_ROOT))})
                self.assertIn("swg_test_studio/collections/swg-regression-collection.json", archive.namelist())
                for info in archive.infolist():
                    self.assertEqual(info.create_system, 3)
                    self.assertEqual(info.external_attr, 0o600 << 16)
                    self.assertEqual(info.date_time, (2026, 11, 8, 0, 0, 0))
                    self.assertFalse(Path(info.filename).is_absolute())
                    self.assertNotIn("..", Path(info.filename).parts)
                    self.assertEqual(archive.read(info), (root / info.filename).read_bytes())


    def test_saved_recipe_comes_from_studio_even_with_a_conflicting_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            checkout_recipe = source / "devtools/zones/test_sets/driver_unit.json"
            checkout_recipe.parent.mkdir(parents=True)
            checkout_recipe.write_text("incompatible server recipe", encoding="utf-8")
            suite = Library(source / "workspace").get("driver_guards")
            env = {"bindings": {}, "server_checkout": str(source), "name": "Offline test"}
            [case] = plan(suite, env)["manifest"]["tests"]
            self.assertEqual(case["kind"], "driver_unit")

    @unittest.skipUnless(sys.platform == "linux", "Server tool imports require Linux")
    def test_driver_uses_bundled_modules_with_an_independent_server_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            for component in ("src/engine/server/application/CentralServer", "src/game/server/application/SwgGameServer"):
                (source / component).mkdir(parents=True)
                (source / component / "Makefile.am").touch()
            foreign_tool = source / "devtools/zones/protocol_driver.py"
            foreign_tool.parent.mkdir(parents=True)
            foreign_tool.write_text("raise RuntimeError('foreign driver loaded')", encoding="utf-8")
            foreign_tool.with_name("studio_tool_bundle.py").write_text(
                "raise RuntimeError('foreign manifest helper loaded')", encoding="utf-8"
            )
            program = """
from pathlib import Path
import sys

source = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source))
from swg_test_studio.backend import driver_modules
from swg_test_studio.server_tools import TOOLS_ROOT, load_tool
driver, legacy = driver_modules({"server_checkout": str(source)})
assert driver.REPO == legacy.REPO == source
assert Path(driver.__file__) == TOOLS_ROOT / "zones/protocol_driver.py"
peer = load_tool("teststudio_server/retained_peer.py")
assert Path(peer.__file__) == TOOLS_ROOT / "teststudio_server/retained_peer.py"
policy = load_tool("zones/rryatt_runtime_policy.py")
assert Path(policy.__file__) == TOOLS_ROOT / "zones/rryatt_runtime_policy.py"
"""
            subprocess.run([sys.executable, "-B", "-c", program, str(source)], check=True, capture_output=True, text=True)
            self.assertEqual(foreign_tool.read_text(encoding="utf-8"), "raise RuntimeError('foreign driver loaded')")
