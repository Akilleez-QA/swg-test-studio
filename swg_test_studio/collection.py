"""Portable Studio collections and inert copies of server driver manifests."""
import json
from pathlib import Path

from .groups import validate_groups
from .model import ROLE, exact, identifier, validate
from .store import EXAMPLES, read_json, write_json


FORMAT = "swg-test-studio-collection"
MAX_BYTES = 2 * 1024 * 1024
MAX_SUITES = 1024


def is_driver_suite(suite):
    return isinstance(suite, dict) and "format" not in suite


def validate_entry(suite):
    if len(json.dumps(suite, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 262144:
        raise ValueError("A collection suite exceeds 256 KiB")
    if not is_driver_suite(suite):
        return validate(suite)
    exact(suite, ("schema_version", "id", "title", "category", "roles", "tests"), "driver suite")
    identifier(suite["id"])
    if (type(suite["schema_version"]) is not int or suite["schema_version"] != 1 or
            suite["category"] not in ("unit", "functional", "system", "regression") or
            not isinstance(suite["title"], str) or not 1 <= len(suite["title"]) <= 200):
        raise ValueError("Invalid driver suite version, category or title")
    roles = suite["roles"]
    if (not isinstance(roles, list) or len(roles) > 5 or
            any(not isinstance(role, str) or not ROLE.fullmatch(role) for role in roles) or
            len(set(roles)) != len(roles)):
        raise ValueError("At most five distinct driver roles are supported")
    tests = suite["tests"]
    if not isinstance(tests, list) or not 1 <= len(tests) <= 32:
        raise ValueError("Define 1–32 driver cases")
    ids = set()
    for case in tests:
        exact(case, ("id", "kind", "options"), "driver case")
        name = identifier(case["id"])
        identifier(case["kind"])
        if name in ids or not isinstance(case["options"], dict):
            raise ValueError("Driver cases need unique IDs and typed options")
        ids.add(name)
    return suite


def validate_collection(data):
    optional = ("groups",) if isinstance(data, dict) and "groups" in data else ()
    exact(data, ("format", "schema_version", "title", "suites", *optional), "collection")
    if (data["format"] != FORMAT or type(data["schema_version"]) is not int or
            data["schema_version"] != 1 or not isinstance(data["title"], str) or
            not 1 <= len(data["title"]) <= 200):
        raise ValueError("Invalid Studio collection format, version or title")
    suites = data["suites"]
    if not isinstance(suites, list) or len(suites) > MAX_SUITES:
        raise ValueError(f"A collection supports up to {MAX_SUITES} suites")
    ids = set()
    for suite in suites:
        validate_entry(suite)
        if suite["id"] in ids:
            raise ValueError("Duplicate collection suite ID: " + suite["id"])
        ids.add(suite["id"])
    if optional:
        validate_groups(data["groups"], ids)
    return data


class Collection:
    def __init__(self, path):
        self.path = Path(path).absolute()

    def read(self):
        return validate_collection(read_json(self.path, max_bytes=MAX_BYTES))

    def write(self, data, *, replace=False):
        validate_collection(data)
        text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise ValueError("Collection exceeds 2 MiB")
        write_json(self.path, data, replace=replace)
        return self.path

    def list(self):
        return [{"id": suite["id"], "title": suite["title"], "category": suite["category"],
                 "origin": "driver" if is_driver_suite(suite) else "studio", "roles": suite["roles"]}
                for suite in self.read()["suites"]]

    def get(self, name):
        identifier(name)
        for suite in self.read()["suites"]:
            if suite["id"] == name:
                return suite
        raise ValueError("Unknown collection suite: " + name)

    def groups(self):
        return self.read().get("groups", {})

    def save_groups(self, groups):
        validate_groups(groups)
        data = self.read()
        if groups:
            data["groups"] = groups
        else:
            data.pop("groups", None)
        return self.write(data, replace=True)

    def save(self, value, *, replace=False):
        suite = validate_entry(value)
        data = self.read()
        for index, existing in enumerate(data["suites"]):
            if existing["id"] == suite["id"]:
                if not replace:
                    raise ValueError("Collection already contains " + suite["id"])
                if is_driver_suite(existing) != is_driver_suite(suite):
                    raise ValueError("Use a new ID when changing the suite format")
                data["suites"][index] = suite
                break
        else:
            data["suites"].append(suite)
        return self.write(data, replace=True)


def export_regression(server_checkout, output):
    saved = Path(server_checkout) / "devtools/zones/test_sets"
    sources = sorted(saved.glob("*.json"))
    if not sources:
        raise ValueError("Select an SWG checkout with saved driver suites")
    suites = [validate(read_json(path)) for path in sorted(EXAMPLES.glob("*.json"))]
    for path in sources:
        suite = read_json(path)
        if not is_driver_suite(suite) or validate_entry(suite)["id"] != path.stem:
            raise ValueError("Driver suite ID must match its filename: " + path.name)
        suites.append(suite)
    return Collection(output).write({"format": FORMAT, "schema_version": 1,
                                     "title": "SWG regression collection", "suites": suites})
