#!/usr/bin/env python3
"""Generate the crowded-world preload table and reversible ELF64 config overlay.

The original heavy table is the authority for established regions and server
IDs. Extra city rectangles reuse those IDs, so the scenario adds no invented
server identities or host paths. Nothing here modifies the running cluster.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[2]
DEPLOYMENT = REPO / "StarWarsGalaxies"
NAME = "crowded20000"
TABLE_NAME = "preload_list_crowded20000"
TABLE_PATH = f"datatables/planet_server/{TABLE_NAME}.iff"
SOURCE = REPO / "dsrc/sku.0/sys.server/compiled/game/datatables/planet_server/preload_list_heavy.tab"
OUTPUT = DEPLOYMENT / "scenarios" / NAME
# Coordinates come from the heavy preload rectangles. City centers are checked
# against the original travel/Jedi city tables. All edges are 100 m node aligned.
# City-only rows preload the busy quadrants. Outside them, PlanetServer's
# getClosestGameServer() assigns nodes on demand to the nearest city worker.
CITY_SPLITS = {
    "naboo": ("Theed", (-5600, 3500, -4200, 5000), (-4900, 4200), (1, 2, 3, 6)),
    "tatooine": ("Mos Eisley", (2900, -5400, 4100, -4200), (3500, -4800), (9, 5, 6, 10)),
    "rori": ("Restuss", (4400, 4600, 6400, 6600), (5400, 5600), (3, 1, 2, 3)),
}
HOT = ("naboo", "tatooine", "rori", "corellia")
HOT_WORKERS = {"naboo": 4, "tatooine": 4, "rori": 3, "corellia": 5}
HEAVY_SOURCE_WORKERS = {"naboo": 6, "tatooine": 11, "rori": 3, "corellia": 5}


def source_rows():
    lines = SOURCE.read_text(encoding="utf-8-sig").splitlines()
    if lines[:2] != [
        "Scene\tTop Left Chunk X\tTop Left Chunk Z\tBottom Right Chunk X\tBottom Right Chunk Z\tCity Server Id\tWilderness Server Id",
        "s\ti\ti\ti\ti\ti\ti",
    ]:
        raise ValueError("Unexpected heavy preload table schema")
    rows = defaultdict(list)
    for line in lines[2:]:
        fields = line.split("\t")
        if len(fields) != 7 or any(not re.fullmatch(r"-?\d+", value) for value in fields[1:]):
            raise ValueError("Malformed heavy preload row")
        rows[fields[0]].append(fields)
    if len(rows) != 46 or not all(scene in rows for scene in HOT):
        raise ValueError("Heavy preload table does not cover the 46 known scenes")
    for scene, expected in HEAVY_SOURCE_WORKERS.items():
        ids = {int(value) for row in rows[scene] for value in row[5:] if int(value) > 0}
        if len(ids) != expected:
            raise ValueError(f"Unexpected {scene} server IDs in heavy table")
    return lines[:2], rows


def city_rows(scene, original):
    _, (left, top, right, bottom), (split_x, split_z), ids = CITY_SPLITS[scene]
    areas = ((left, top, split_x, split_z),
             (split_x, top, right, split_z),
             (left, split_z, split_x, bottom),
             (split_x, split_z, right, bottom))
    available = {int(value) for row in original for value in row[5:] if int(value) > 0}
    if not set(ids) <= available or any(value % 100 for area in areas for value in area):
        raise ValueError(f"Invalid node-aligned {scene} city split")
    return [[scene, *map(str, area), str(server_id), "0"]
            for area, server_id in zip(areas, ids)]


def generate_table():
    header, source = source_rows()
    rows = []
    for scene, original in source.items():
        if scene in CITY_SPLITS:
            # Preload the three crowded cities. Other chunks load on demand
            # through PlanetServer's nearest-operational-city fallback.
            rows.extend(city_rows(scene, original))
        elif scene == "corellia":
            rows.extend(original)
        else:
            # Matches PlanetServer's existing one-server fake beacon exactly.
            rows.append([scene, "0", "0", "100", "100", "1", "1"])
    text = "\n".join(header + ["\t".join(row) for row in rows]) + "\n"
    workers = {scene: len({int(value) for row in rows if row[0] == scene
                           for value in row[5:] if int(value) > 0}) for scene in source}
    if any(workers[scene] != expected for scene, expected in HOT_WORKERS.items()):
        raise ValueError("Hotspot worker count drifted")
    if any(count != 1 for scene, count in workers.items() if scene not in HOT):
        raise ValueError("Non-hot worlds must retain one GameServer")
    return text, workers


def expected_workers(selected):
    _, workers = generate_table()
    missing = set(selected) - set(workers)
    if missing:
        raise ValueError(f"Preload table does not cover selected scenes: {sorted(missing)}")
    return {scene: workers[scene] for scene in selected}


def set_keys(config, section, replacements):
    """Set exact keys in a generated role cfg, preserving unrelated settings."""
    lines = config.splitlines()
    start = next((i for i, line in enumerate(lines) if line == f"[{section}]"), None)
    if start is None:
        raise ValueError(f"Missing [{section}] section")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    current = lines[start + 1:end]
    for key, value in replacements.items():
        matches = [i for i, line in enumerate(current) if line.startswith(key + "=")]
        if len(matches) > 1:
            raise ValueError(f"Duplicate {key} in [{section}]")
        if matches:
            current[matches[0]] = f"{key}={value}"
        else:
            current.append(f"{key}={value}")
    lines[start + 1:end] = current
    return "\n".join(lines) + "\n"


def high_configs(planet, game, login, connection, selected):
    count = sum(expected_workers(selected).values())
    planet = set_keys(planet, "PlanetServer", {
        "preloadDataTableName": TABLE_PATH,
        "loadWholePlanet": 0,
        # The scenario image's launch wrapper enables multiserver only for
        # the four crowded scenes. All other worlds retain low-mode startup.
        "loadWholePlanetMultiserver": 0,
    })
    game = set_keys(game, "GameServer", {"enablePreload": 1,
                                         "reservedObjectIds": 50000,
                                         "minObjectIds": 25000})
    # Locator rejects a spawn at load >= maximumLoad; leave one slot of headroom.
    game = set_keys(game, "TaskManager", {"maximumLoad": count + 1})
    game += f"[ClusterScenario]\nname={NAME}\n"
    login = set_keys(login, "LoginServer", {
        "maxClients": 25000,
        "maxPlayersPerCluster": 20000,
        "maxCharactersPerCluster": 50000,
    })
    connection = set_keys(connection, "ConnectionServer", {
        "maxClients": 25000,
        "clientMaxConnections": 25000,
        "clientHashTableSize": 32768,
    })
    return planet, game, login, connection


def prepare(tool, base_image):
    if not re.fullmatch(r"starwarsgalaxies/planet:[a-zA-Z0-9_.-]+", base_image):
        raise ValueError("A local starwarsgalaxies/planet ELF64 image is required")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    table, workers = generate_table()
    tab = OUTPUT / f"{TABLE_NAME}.tab"
    iff = OUTPUT / f"{TABLE_NAME}.iff"
    tab.write_text(table, encoding="utf-8", newline="\n")
    launcher = OUTPUT / "launch-planet-scenario.sh"
    shutil.copy2(Path(__file__).with_name("launch-planet-scenario.sh"), launcher)
    iff.unlink(missing_ok=True)
    # The ELF32 compiler's stat() fails on Windows-backed WSL mounts. Compile
    # on Linux-native temporary storage, then copy the verified artifact out.
    with tempfile.TemporaryDirectory(prefix="swg-crowded-table-") as scratch:
        native_tab = Path(scratch) / tab.name
        native_iff = Path(scratch) / iff.name
        shutil.copy2(tab, native_tab)
        # -t asks the native reader to reopen the emitted table. It requires
        # relative paths because its legacy path normalizer strips leading /.
        result = subprocess.run([str(tool), "-i", native_tab.name, "-o", native_iff.name, "-t"],
                                cwd=scratch, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        if native_iff.is_file():
            shutil.copy2(native_iff, iff)
    (OUTPUT / "compiler.log").write_text(result.stdout, encoding="utf-8")
    if not iff.is_file() or iff.read_bytes()[:4] != b"FORM":
        raise RuntimeError(f"DataTableTool did not produce a valid IFF; exit {result.returncode}")
    if result.returncode not in (0, -11, 139) or "FATAL" in result.stdout:
        raise RuntimeError(f"DataTableTool failed with exit {result.returncode}; see compiler.log")
    tag = base_image + "-crowded20000"
    subprocess.run(["docker", "build", "--pull=false", "--build-arg", f"BASE_IMAGE={base_image}",
                    "-f", str(Path(__file__).with_name("ScenarioPlanet.Dockerfile")),
                    "-t", tag, str(OUTPUT)], check=True)
    manifest = {"scenario": NAME, "target_connections": 20000,
                "source": str(SOURCE.relative_to(REPO)), "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                "table_sha256": hashlib.sha256(iff.read_bytes()).hexdigest(),
                "launcher_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
                "planet_base_image": base_image, "planet_image": tag,
                "table": TABLE_PATH, "workers_per_scene": workers,
                "city_splits": {scene: label for scene, (label, *_rest) in CITY_SPLITS.items()},
                "compiler_exit": result.returncode}
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", type=Path, required=True, help="existing Linux DataTableTool wrapper")
    parser.add_argument("--base-image", required=True, help="current local ELF64 planet role image")
    args = parser.parse_args()
    print(json.dumps(prepare(args.tool, args.base_image), indent=2))


if __name__ == "__main__":
    main()
