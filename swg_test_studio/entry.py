"""File entrypoint also usable by Windows-to-WSL dispatch after installation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swg_test_studio.cli import main

raise SystemExit(main())
