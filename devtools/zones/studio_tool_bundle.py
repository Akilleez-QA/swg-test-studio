"""Validate a curated Studio copy of the existing WhiteNGold server tools."""
import hashlib
import json
from pathlib import Path
import re
import stat


MANIFEST = "studio-tools.json"
PATH = re.compile(r"(?:docker|manage|teststudio_server|zones)/(?:[a-zA-Z0-9_]+/)*[a-zA-Z0-9_]+[.][a-zA-Z0-9_]+")
SHA256 = re.compile(r"[a-f0-9]{64}")


def check_path(root, name):
    path = root
    for part in name.split("/"):
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Unexpected link in Studio tools: " + str(path))
    return path


def verify(root):
    manifest = check_path(root, MANIFEST)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int or
            data["schema_version"] != 1 or not isinstance(data.get("files"), dict) or not data["files"]):
        raise ValueError("Invalid Studio tools manifest")
    for name, expected in data["files"].items():
        if not PATH.fullmatch(name) or not isinstance(expected, str) or not SHA256.fullmatch(expected):
            raise ValueError("Invalid path or hash in Studio tools manifest")
        if hashlib.sha256(check_path(root, name).read_bytes()).hexdigest() != expected:
            raise ValueError("Studio tool differs from its manifest: " + name)
    return data["files"]
