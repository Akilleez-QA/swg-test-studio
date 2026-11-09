"""Validate a curated Studio copy of the existing WhiteNGold server tools."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat


TOOLS_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT_ENV = "SWG_STUDIO_SERVER_SOURCE"
MANIFEST = "studio-tools.json"
PATH = re.compile(r"(?:docker|manage|teststudio_server|zones)/(?:[a-zA-Z0-9_]+/)*[a-zA-Z0-9_]+[.][a-zA-Z0-9_]+")
SHA256 = re.compile(r"[a-f0-9]{64}")


_source_root = None


def bind_server_source(path):
    global _source_root
    source = Path(path).resolve(strict=True)
    if _source_root is not None and _source_root != source:
        raise ValueError("Use a separate Studio process for a different WhiteNGold server source.")
    _source_root = source
    return source


def server_source():
    if _source_root is not None:
        return _source_root
    value = os.environ.get(SOURCE_ROOT_ENV)
    if not value:
        raise ValueError("A selected WhiteNGold server source is required for these Studio tools.")
    return bind_server_source(value)


def contract_input_sha256(source, relative):
    # Existing fixture receipts pin the upstream producer. Studio's changes
    # for these files resolve paths only. Record their actual bytes separately.
    relative = Path(relative)
    if relative.parts[:1] != ("devtools",):
        return hashlib.sha256((source / relative).read_bytes()).hexdigest()
    name = relative.relative_to("devtools").as_posix()
    digest = hashlib.sha256(check_path(TOOLS_ROOT, name).read_bytes()).hexdigest()
    manifest = bundle_manifest(TOOLS_ROOT)
    if digest != manifest["files"].get(name):
        raise ValueError("Studio contract tool differs from its manifest: " + name)
    return manifest["upstream_contract_sha256"].get(name, digest)


def zone_tool_hashes():
    return {Path(os.path.relpath(TOOLS_ROOT / name, TOOLS_ROOT / "zones")).as_posix(): digest
            for name, digest in verify(TOOLS_ROOT).items()}


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


def bundle_manifest(root):
    manifest = check_path(root, MANIFEST)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int or
            data["schema_version"] != 1 or not isinstance(data.get("files"), dict) or not data["files"]):
        raise ValueError("Invalid Studio tools manifest")
    upstream = data.get("upstream_contract_sha256")
    if (not isinstance(upstream, dict) or any(name not in data["files"] or
            not isinstance(digest, str) or not SHA256.fullmatch(digest) for name, digest in upstream.items())):
        raise ValueError("Invalid Studio upstream contract hashes")
    return data


def verify(root):
    data = bundle_manifest(root)
    for name, expected in data["files"].items():
        if not PATH.fullmatch(name) or not isinstance(expected, str) or not SHA256.fullmatch(expected):
            raise ValueError("Invalid path or hash in Studio tools manifest")
        if hashlib.sha256(check_path(root, name).read_bytes()).hexdigest() != expected:
            raise ValueError("Studio tool differs from its manifest: " + name)
    return data["files"]
