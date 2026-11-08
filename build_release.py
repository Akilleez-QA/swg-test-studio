"""Create a deterministic source application ZIP; no downloaded build dependencies."""
import argparse
import hashlib
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    sources = [root / name for name in ("README.md", "pyproject.toml", "swg-tests.py", "swg-tests.ps1", "build_release.py")]
    sources += sorted((root / "swg_test_studio").glob("*.py"))
    sources += sorted((root / "swg_test_studio/examples").glob("*.json"))
    sources += sorted((root / "tests").glob("*.py"))
    output = args.output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream, zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sources:
            info = zipfile.ZipInfo(source.relative_to(root).as_posix(), date_time=(2026, 11, 8, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, source.read_bytes())
    print("Built", output, "files", len(sources), "sha256", hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
