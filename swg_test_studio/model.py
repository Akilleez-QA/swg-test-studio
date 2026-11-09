"""Strict, non-executable suite data shared by the desktop and CLI."""
import copy
import json
import re

FORMAT = "swg-test-studio"
NAME = re.compile(r"[a-z][a-z0-9_]{2,63}\Z")
ROLE = re.compile(r"[a-z]{3,16}\Z")
RECIPES = {"station_shuttle": ("actor",), "ship_group": ("leader", "member"),
           "stage7_group_disband": ("leader", "member", "newleader"), "driver_unit": ()}
SESSION_OPTIONS = {"create": bool, "disconnect": bool, "prepare_terminal": bool,
                   "stage_station": bool, "expect_scene": str, "expect_family": str,
                   "answer": str}


def identifier(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError("Use a lowercase test ID (3–64 letters, digits or underscores)")
    return value


def exact(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("Unknown or missing " + label + " fields")


def loads(text):
    if len(text.encode("utf-8")) > 262144:
        raise ValueError("Suite exceeds 256 KiB")
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError("Duplicate JSON field: " + key)
            obj[key] = value
        return obj
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Finite JSON required")))


def validate(data, *, runnable=False):
    exact(data, ("format", "schema_version", "id", "title", "category", "roles", "steps", "review"), "suite")
    if data["format"] != FORMAT or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported SWG Test Studio format/version")
    identifier(data["id"])
    if not isinstance(data["title"], str) or not 1 <= len(data["title"]) <= 200:
        raise ValueError("A title of 1–200 characters is required")
    if data["category"] not in ("unit", "functional", "regression", "system"):
        raise ValueError("Unknown test category")
    roles = data["roles"]
    if (not isinstance(roles, list) or len(roles) > 5 or
            any(not isinstance(r, str) or not ROLE.fullmatch(r) for r in roles) or len(set(roles)) != len(roles)):
        raise ValueError("At most five distinct named test roles are supported")
    review = data["review"]
    extra = ("capture_ranges",) if isinstance(review, dict) and "capture_ranges" in review else ()
    exact(review, ("approved", "recording", "unsupported") + extra, "review")
    if extra:
        from .clips import validate_ranges
        validate_ranges(review["capture_ranges"])
        if review["recording"] is None:
            raise ValueError("Recording clips require their source recording ID")
    if (type(review["approved"]) is not bool or
            (review["recording"] is not None and (not isinstance(review["recording"], str) or
                                                not re.fullmatch(r"[a-f0-9]{32}", review["recording"]))) or
            not isinstance(review["unsupported"], list) or len(review["unsupported"]) > 128 or
            any(not isinstance(v, str) or not 1 <= len(v) <= 300 for v in review["unsupported"])):
        raise ValueError("Invalid review metadata")
    if runnable and (not review["approved"] or review["unsupported"]):
        raise ValueError("Review expectations and resolve unsupported recording steps before running")
    steps = data["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
        raise ValueError("Define 1–32 test steps")
    seen = set()
    for step in steps:
        exact(step, ("id", "action", "options"), "step")
        name = identifier(step["id"])
        if name in seen:
            raise ValueError("Step IDs must be unique")
        seen.add(name)
        options = step["options"]
        if not isinstance(options, dict):
            raise ValueError("Typed step options required")
        if step["action"] == "session":
            if options.get("role") not in roles or set(options) - (set(SESSION_OPTIONS) | {"role"}):
                raise ValueError("Unknown session role/option")
            for key, value in options.items():
                if key != "role" and type(value) is not SESSION_OPTIONS[key]:
                    raise ValueError("Incorrect session option type: " + key)
            if options.get("expect_family") not in (None, "npe_space_station", "npe_space_dungeon"):
                raise ValueError("Unsupported public station family")
            if "expect_scene" in options and not re.fullmatch(r"terrain/[a-z0-9_]+\.trn", options["expect_scene"]):
                raise ValueError("Expected scene must be a terrain resource name")
            if options.get("answer", "ok") not in ("ok", "cancel"):
                raise ValueError("Only offered OK/Cancel dialog answers are supported")
            if sum(bool(options.get(k)) for k in ("create", "stage_station", "prepare_terminal")) > 1:
                raise ValueError("Creation, station setup and terminal travel are separate lifecycles")
            if options.get("prepare_terminal") and ("expect_family" not in options or options.get("answer", "ok") != "ok"):
                raise ValueError("Shuttle recipe requires an explicit destination and confirmation")
        elif step["action"] == "journey":
            from .journey import validate as validate_journey
            validate_journey(options, roles)
        elif step["action"] == "action_sequence":
            from .action_sequence import validate as validate_sequence
            validate_sequence(options, roles)
        elif step["action"] == "saved_suite":
            exact(options, ("suite", "bindings"), "saved-suite")
            recipe = options["suite"]
            if not isinstance(recipe, str) or recipe not in RECIPES:
                raise ValueError("Select an approved ordinary-action suite")
            bindings = options["bindings"]
            if (not isinstance(bindings, dict) or set(bindings) != set(RECIPES[recipe]) or
                    any(not isinstance(v, str) or v not in roles for v in bindings.values()) or
                    len(set(bindings.values())) != len(bindings)):
                raise ValueError("Bind each recipe role to a distinct declared role")
        elif step["action"] == "recorded_observation":
            exact(options, ("summary",), "recorded-observation")
            if not isinstance(options["summary"], str) or not 1 <= len(options["summary"]) <= 300:
                raise ValueError("A bounded observation summary is required")
            if runnable:
                raise ValueError("Recorded observations must be replaced with supported actions and expectations")
        else:
            raise ValueError("Unknown action; arbitrary commands and executable expressions are not supported")
    if runnable and len(roles) and not any(s["action"] != "recorded_observation" for s in steps):
        raise ValueError("No replayable actions")
    return copy.deepcopy(data)


def compile_suite(data, legacy_dir):
    """Compile private execution cases; legacy recipes keep their original schema."""
    data = validate(data, runnable=True)
    cases = []
    for step in data["steps"]:
        if step["action"] == "session":
            cases.append({"id": step["id"], "kind": "protocol_session", "options": step["options"]})
        elif step["action"] == "journey":
            cases.append({"id": step["id"], "kind": "studio_journey", "options": step["options"]})
        elif step["action"] == "action_sequence":
            cases.append({"id": step["id"], "kind": "studio_action_sequence", "options": step["options"]})
        else:
            options = step["options"]
            original = loads((legacy_dir / (options["suite"] + ".json")).read_text(encoding="utf-8"))
            if original["roles"] != list(RECIPES[options["suite"]]):
                raise ValueError("Bundled recipe role contract changed")
            for case in original["tests"]:
                # Do not inherit newly added native/fault backends through an approved suite name.
                allowed = {"protocol_session", "ship_group", "driver_unit", "group_affinity_rryatt", "group_affinity_ord"}
                if case["kind"] not in allowed:
                    raise ValueError("Bundled recipe gained an unsupported backend; review its adapter")
                case = copy.deepcopy(case)
                case["id"] = step["id"] + "_" + case["id"]
                identifier(case["id"])
                for key, value in case["options"].items():
                    if isinstance(value, str) and value in options["bindings"]:
                        case["options"][key] = options["bindings"][value]
                cases.append(case)
    if len(cases) > 32:
        raise ValueError("Expanded suite exceeds 32 cases")
    return {"schema_version": 1, "id": data["id"], "title": data["title"],
            "category": data["category"], "roles": data["roles"], "tests": cases}
