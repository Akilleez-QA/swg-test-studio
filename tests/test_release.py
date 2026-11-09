from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from swg_test_studio.server_tools import BUNDLED_TOOLS, install_server_tools
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
                self.assertEqual(names, {"devtools/" + name for name in (MANIFEST, *verify(BUNDLED_TOOLS))})
                self.assertIn("swg_test_studio/collections/swg-regression-collection.json", archive.namelist())
                for info in archive.infolist():
                    self.assertEqual(info.create_system, 3)
                    self.assertEqual(info.external_attr, 0o600 << 16)
                    self.assertEqual(info.date_time, (2026, 11, 8, 0, 0, 0))
                    self.assertFalse(Path(info.filename).is_absolute())
                    self.assertNotIn("..", Path(info.filename).parts)
                    self.assertEqual(archive.read(info), (root / info.filename).read_bytes())

    def test_install_from_a_checkout_without_devtools(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            for folder in ("src/engine/server/application/CentralServer", "src/game/server/application/SwgGameServer"):
                (source / folder).mkdir(parents=True)
                (source / folder / "Makefile.am").touch()
            destination = install_server_tools(source / "src")
            self.assertEqual(destination, install_server_tools(source))
            self.assertEqual(verify(destination), verify(BUNDLED_TOOLS))

    def test_install_refuses_a_conflicting_file_before_copying(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            for folder in ("src/engine/server/application/CentralServer", "src/game/server/application/SwgGameServer"):
                (source / folder).mkdir(parents=True)
                (source / folder / "Makefile.am").touch()
            existing = source / "devtools/zones/protocol_driver.py"
            existing.parent.mkdir(parents=True)
            existing.write_text("local changes", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Existing server tool differs"):
                install_server_tools(source)
            self.assertEqual(list(existing.parent.iterdir()), [existing])
            self.assertEqual(existing.read_text(encoding="utf-8"), "local changes")
