import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
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
                for info in archive.infolist():
                    self.assertEqual(info.create_system, 3)
                    self.assertEqual(info.external_attr, 0o600 << 16)
                    self.assertEqual(info.date_time, (2026, 11, 8, 0, 0, 0))
                    self.assertFalse(Path(info.filename).is_absolute())
                    self.assertNotIn("..", Path(info.filename).parts)
                    self.assertEqual(archive.read(info), (root / info.filename).read_bytes())
