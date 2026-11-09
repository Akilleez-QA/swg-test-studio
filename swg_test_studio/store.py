"""Bounded local storage; suites and credentials never share a file."""
import json
import os
from pathlib import Path
import secrets

from .model import identifier, loads, validate

APP = Path(__file__).resolve().parents[1]
EXAMPLES = Path(__file__).with_name("examples")
DEFAULT_WORKSPACE = Path(os.environ.get("LOCALAPPDATA", os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))) / "SWGTestStudio"


def read_json(path, *, max_bytes=262144):
    path = Path(path)
    with path.open("rb") as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"JSON exceeds {max_bytes // 1024} KiB")
    return loads(data.decode("utf-8"), max_bytes=max_bytes)


def write_json(path, data, *, replace=False):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Refusing a symbolic-link destination")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if not replace:
        with path.open("x", encoding="utf-8") as output:
            os.chmod(path, 0o600)
            output.write(text)
    else:
        temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
        try:
            with temporary.open("x", encoding="utf-8") as output:
                os.chmod(temporary, 0o600)
                output.write(text)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


class Library:
    def __init__(self, workspace=DEFAULT_WORKSPACE):
        self.workspace = Path(workspace).absolute()

    def list(self, *, on_invalid_saved_test=None):
        result = []
        for origin, folder in (("example", EXAMPLES), ("user", self.workspace / "suites")):
            for path in sorted(folder.glob("*.json")):
                try:
                    suite = validate(read_json(path))
                except (OSError, ValueError) as exc:
                    if origin == "example" or on_invalid_saved_test is None:
                        raise
                    on_invalid_saved_test(path, exc)
                    continue
                result.append({"id": suite["id"], "title": suite["title"], "origin": origin,
                               "category": suite["category"], "roles": suite["roles"],
                               "approved": suite["review"]["approved"], "path": str(path)})
        return result

    def get(self, name):
        identifier(name)
        for folder in (self.workspace / "suites", EXAMPLES):
            path = folder / (name + ".json")
            if path.exists():
                return validate(read_json(path))
        raise ValueError("Unknown test: " + name)

    def save(self, data, *, replace=False):
        suite = validate(data)
        if (EXAMPLES / (suite["id"] + ".json")).exists():
            raise ValueError("Give your copy a new ID; bundled examples are read-only")
        path = self.workspace / "suites" / (suite["id"] + ".json")
        write_json(path, suite, replace=replace)
        return path
