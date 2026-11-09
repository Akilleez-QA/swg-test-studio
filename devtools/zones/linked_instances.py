"""Source geometry checks for Rryatt's linked levels, not runtime readiness."""
from decimal import Decimal, InvalidOperation


SCENE = "kashyyyk_rryatt_trail"
PREFIX = "kashyyyk_rryatt_trail_lvl_"
# Reviewed relative bounds from the original areas table. Each candidate set
# must contain these four rectangles under one translation. Never pair by row
# order: native buildout row indices themselves remain part of object identity.
LAYOUT = {
    PREFIX + "1_and_2": (0, 0, 1700, 1500),
    PREFIX + "3": (1700, -500, 3500, 1500),
    PREFIX + "4": (0, -1250, 1700, 0),
    PREFIX + "5": (1700, -1250, 3200, -500),
}


def rryatt_sets(areas):
    """Fail closed on missing, moved, duplicated, or additional level rows."""
    rows = []
    try:
        for area in areas:
            if area["scene"] != SCENE:
                continue
            for placement in area["placements"]:
                bounds = tuple(Decimal(placement["bounds"][key])
                               for key in ("x1", "z1", "x2", "z2"))
                if not all(value.is_finite() for value in bounds):
                    raise ValueError("Non-finite Rryatt bounds")
                rows.append((area["area"], placement["line"], bounds))
    except (InvalidOperation, KeyError) as error:
        raise ValueError("Invalid Rryatt area geometry") from error
    if not rows:
        return {"scene": SCENE, "geometry_verified": False, "sets": [],
                "blockers": ["missing_area_rows"], "runtime_linkage_verified": False}
    sets, used = [], set()
    for name, line, bounds in rows:
        if name != PREFIX + "1_and_2":
            continue
        x, z = bounds[:2]
        members = []
        for level, relative in LAYOUT.items():
            expected = tuple(value + (x if index % 2 == 0 else z)
                             for index, value in enumerate(relative))
            matches = [(other_line, other_bounds) for other_name, other_line, other_bounds in rows
                       if other_name == level and other_bounds == expected]
            if len(matches) != 1 or matches[0][0] in used:
                raise ValueError(f"Ambiguous or incomplete Rryatt set at source line {line}: {level}")
            source_line = matches[0][0]
            used.add(source_line)
            members.append({"area": level, "line": source_line,
                            "buildout_row": source_line - 3})
        sets.append({"anchor_line": line, "anchor_buildout_row": line - 3,
                     "members": members})
    if len(used) != len(rows):
        raise ValueError("Unassigned Rryatt level rows; linked layout needs review")
    return {"scene": SCENE, "geometry_verified": True,
            "basis": "reviewed four-level bounds under a common translation",
            "sets": sorted(sets, key=lambda item: item["anchor_line"]),
            "runtime_linkage_verified": False,
            "blockers": ["controller_and_portal_registration", "clone_and_unstuck_identity",
                         "session_and_reconnect_leases", "independent_activation_and_drain"]}
