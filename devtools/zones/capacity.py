"""Read-only scene capacity inventory and migration preview. No runtime control."""
import csv
import hashlib
import json
from pathlib import Path
import re

from linked_instances import rryatt_sets

from studio_tool_bundle import server_source

REPO = server_source()
CATALOG = Path(__file__).with_name("catalog.json")
SERVER_TABLES = Path("dsrc/sku.0/sys.server/compiled/game/datatables")
SHARED_TABLES = Path("dsrc/sku.0/sys.shared/compiled/game/datatables")


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)


def scene_names(repo=REPO):
    text = (Path(repo) / "dsrc/sku.0/sys.server/compiled/game/universe/planets.mif").read_text()
    return set(re.findall(r'^\s*Planet\("([a-z][a-z0-9_]*)"\)', text, re.MULTILINE))


def load_catalog(path=CATALOG, known=None):
    catalog = read_json(path)
    if not isinstance(catalog, dict) or set(catalog) != {"schema_version", "revision", "groups"}:
        raise ValueError("Invalid capacity catalog fields")
    if type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1:
        raise ValueError("Unsupported capacity catalog schema")
    if not isinstance(catalog["revision"], str) or not catalog["revision"]:
        raise ValueError("Catalog revision is required")
    if not isinstance(catalog["groups"], list) or not catalog["groups"]:
        raise ValueError("Catalog groups must be a nonempty list")
    seen, ids = set(), set()
    known = scene_names() if known is None else set(known)
    for group in catalog["groups"]:
        if not isinstance(group, dict) or set(group) != {
                "id", "kind", "scenes", "warm_minimum", "capacity_unit", "review"}:
            raise ValueError("Invalid capacity group fields")
        name = group["id"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in ids:
            raise ValueError("Duplicate or invalid capacity group ID")
        ids.add(name)
        if group["kind"] not in ("duplicate_scene", "duplicate_candidate", "distinct_scene", "instance_host"):
            raise ValueError(f"Invalid group kind: {name}")
        members = group["scenes"]
        if not isinstance(members, list) or not members or any(not isinstance(s, str) for s in members):
            raise ValueError(f"Invalid scenes: {name}")
        if len(set(members)) != len(members) or set(members) & seen or set(members) - known:
            raise ValueError(f"Duplicate or unknown scenes: {name}")
        seen.update(members)
        if group["kind"] in ("distinct_scene", "instance_host") and len(members) != 1:
            raise ValueError(f"Distinct scenes must not be interchangeable: {name}")
        minimum = group["warm_minimum"]
        if type(minimum) is not int or not 1 <= minimum <= len(members):
            raise ValueError(f"Invalid warm minimum: {name}")
        if group["review"] != "required":
            raise ValueError("This implementation has no runtime-approved families")
        if group["capacity_unit"] not in ("player", "player_and_station", "dungeon_session", "buildout_instance"):
            raise ValueError(f"Invalid capacity unit: {name}")
    return catalog


def read_table(path):
    """Read original typed tab tables without modifying tabs, rows, or defaults."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    if len(rows) < 2 or not rows[0]:
        raise ValueError(f"Missing table header/types: {path}")
    return [(number, dict(zip(rows[0], row))) for number, row in enumerate(rows[2:], 3)
            if any(row)]


def content_inventory(repo, catalog):
    """Expose original instance identity and exit dependencies, never merge areas."""
    repo = Path(repo)
    # Selection proposals cover catalog groups; the source audit covers every
    # authored scene, including private dungeons on shared and adventure hosts.
    members = scene_names(repo)
    universe = Path('dsrc/sku.0/sys.server/compiled/game/universe/planets.mif')
    inputs = {universe.as_posix(): hashlib.sha256((repo/universe).read_bytes()).hexdigest()}
    areas, routes = [], []

    def table(relative):
        path = repo / relative
        inputs[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return read_table(path)

    for scene in sorted(members):
        relative = SHARED_TABLES / f"buildout/areas_{scene}.tab"
        if not (repo / relative).exists():
            continue
        grouped = {}
        for line, row in table(relative):
            area = row["area"]
            # Rows/coordinates are stable identities; a repeated name is not
            # proof that copies can be independently unloaded at runtime.
            grouped.setdefault(area, []).append({"line": line, "buildout_row": line - 3,
                "bounds": {key: row.get(key, "") for key in ("x1", "z1", "x2", "z2")},
                "composite": row.get("compositeName", ""), "event": row.get("eventRequired", "")})
        for area, placements in sorted(grouped.items()):
            areas.append({"scene": scene, "area": area, "placements": placements,
                          "count": len(placements), "source": relative.as_posix(),
                          "independent_unload_verified": False})

    relative = SERVER_TABLES / "dungeon/space_dungeon.tab"
    for line, row in table(relative):
        if row["planet"] in members:
            routes.append({"source": relative.as_posix(), "line": line,
                "kind": "dungeon", "name": row["dungeon"], "scene": row["planet"],
                "area": row.get("dungeon_area", ""), "exit_scene": row["exit_planet"],
                "entry_cell": row.get("start_cell_name", ""),
                "exit_position": {axis: row["exit_loc_" + axis] for axis in ("x", "y", "z")},
                "exit_radius": row["exit_loc_radius"],
                "login_recovery_verified": False,
                "max_players": row["max_players"], "time_limit": row["time_limit"]})

    relative = SERVER_TABLES / "travel/zone_transition.tab"
    for line, row in table(relative):
        parts = row.get("destination", "").split(":")
        instance = parts[0] == "instance"
        scene = parts[2] if instance and len(parts) >= 3 else parts[0]
        # Relative Rryatt routes have no physical scene field. Preserve them
        # explicitly; matching only the destination scene silently loses them.
        relative_rryatt = (parts[0] == "offset" and row["zoneLine"].startswith("rryatt")
                          and "kashyyyk_rryatt_trail" in members)
        if relative_rryatt:
            scene = "kashyyyk_rryatt_trail"
        if scene in members:
            routes.append({"source": relative.as_posix(), "line": line,
                "kind": "relative_transition" if relative_rryatt else
                        "instance_transition" if instance else "scene_transition",
                "name": row["zoneLine"], "scene": scene,
                "instance": parts[1] if instance else None,
                "destination": row["destination"],
                "initial_required_flag": row.get("initialRequiredFlag", ""),
                "final_required_flag": row.get("finalRequiredFlag", ""),
                "script": row.get("script", "")})
    # Expose controller declarations without treating local object IDs as live
    # network IDs. Repeated placements instantiate the same source declaration.
    controllers, missing = [], []
    for area in areas:
        relative = SERVER_TABLES / "buildout" / area["scene"] / (area["area"] + ".tab")
        if not (repo / relative).exists():
            missing.append(relative.as_posix())
            continue
        for line, row in table(relative):
            values = row.get("objvars", "")
            declarations = dict(re.findall(r"(?:^|\|)(instance_name|isControllerObject|space_dungeon\.name|instance\.data_table)\|[04]\|([^|]+)", values))
            if not declarations:
                continue
            controllers.append({"scene": area["scene"], "area": area["area"],
                "source": relative.as_posix(), "line": line,
                "source_object_id": row.get("objid", ""),
                "source_container_id": row.get("container", ""),
                "template": row.get("server_template_crc", ""),
                "scripts": row.get("scripts", "").split(":"),
                "declarations": declarations,
                "placement_rows": [p["buildout_row"] for p in area["placements"]]})
    return {"scenes": sorted(members), "areas": areas, "routes": routes, "input_sha256": inputs,
            "controller_declarations": controllers, "missing_buildout_tables": missing,
            "linked_instances": [rryatt_sets(areas)] if "kashyyyk_rryatt_trail" in members else [],
            "runtime_registration_verified": False}


def load_policy(path, catalog):
    """Only observation is supported until native lifecycle acceptance passes."""
    policy = read_json(path) if Path(path).exists() else {
        "schema_version": 1, "mode": "observe", "groups": {}}
    if not isinstance(policy, dict) or set(policy) != {"schema_version", "mode", "groups"}:
        raise ValueError("Capacity policy supports only schema_version, mode, groups")
    if type(policy["schema_version"]) is not int or policy["schema_version"] != 1:
        raise ValueError("Unsupported capacity policy schema")
    if policy["mode"] != "observe":
        raise ValueError("Only observe mode is implemented; native wake/drain is not available")
    if not isinstance(policy["groups"], dict):
        raise ValueError("Policy groups must be an object")
    groups = {g["id"]: g for g in catalog["groups"]}
    for name, entry in policy["groups"].items():
        if name not in groups or not isinstance(entry, dict) or set(entry) != {"warm_minimum"}:
            raise ValueError(f"Unsupported group policy: {name}")
        count = entry["warm_minimum"]
        if type(count) is not int or not 0 <= count <= len(groups[name]["scenes"]):
            raise ValueError(f"Invalid warm_minimum: {name}")
        if count == 0 and groups[name]["kind"] in ("duplicate_scene", "duplicate_candidate"):
            raise ValueError(f"Duplicate family needs at least one warm member: {name}")
    return policy


def preview(selected, catalog, policy):
    selected = list(selected)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Selection must be nonempty and unique")
    groups = []
    for group in catalog["groups"]:
        enabled = [s for s in group["scenes"] if s in selected]
        minimum = policy["groups"].get(group["id"], {}).get(
            "warm_minimum", min(group["warm_minimum"], len(enabled)))
        if enabled and minimum > len(enabled):
            raise ValueError(f"Warm minimum exceeds selected members: {group['id']}")
        groups.append({**group, "selected": enabled, "proposed_warm": enabled[:minimum],
            "proposed_on_demand": enabled[minimum:], "proposed_warm_minimum": minimum,
            "blockers": ["reference_and_content_review", "native_admission_and_readiness",
                         "persistence_and_drain", "offline_login_recovery",
                         "client_validation"] if enabled else []})
    sleeping = {scene for group in groups for scene in group["proposed_on_demand"]}
    return {"schema_version": 1, "mode": "observe", "catalog_revision": catalog["revision"],
            "runtime_control_available": False, "live_state_checked": False,
            "selected_scenes": selected, "effective_eager_scenes": selected,
            "proposed_eager_scenes": [s for s in selected if s not in sleeping],
            "proposed_on_demand_scenes": sorted(sleeping), "groups": groups,
            "effects": {"writes_configuration": False, "game_services_restarted": False,
                        "oracle_stopped": False},
            "warning": "Proposals require the listed gates. Current startup remains eager; no live capacity is inferred."}
