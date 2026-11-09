"""Select and retain starting zones without editing historical game configs."""
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]


def cfg_zones(path):
    section = None
    zones = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("["):
            section = line
        elif section == "[CentralServer]" and line.startswith("startPlanet="):
            zones.append(line.split("=", 1)[1].strip())
    return zones


def starting_zones(zone_set):
    if zone_set == "tatooine":
        return ["tatooine"]
    if zone_set == "live":
        return validate_zones(cfg_zones(REPO / "exe/linux/commonLiveOptions.cfg"))
    raise ValueError("zone-set must be tatooine or live")


def available_zones():
    catalog = REPO / "dsrc/sku.0/sys.server/compiled/game/universe/planets.mif"
    names = re.findall(r'^\s*Planet\("([a-z][a-z0-9_]*)"\)', catalog.read_text(), re.MULTILINE)
    return sorted(set(names + cfg_zones(REPO / "exe/linux/commonLiveOptions.cfg")))


def validate_zones(zones):
    zones = list(zones)
    if not zones:
        raise ValueError("Select at least one zone; an empty startPlanet list would fall back to Tatooine")
    known = set(available_zones())
    for zone in zones:
        if zone not in known:
            raise ValueError(f"Unknown zone {zone!r}; use --list-zones for supported names")
    if len(set(zones)) != len(zones):
        raise ValueError("Duplicate zones in the selected list")
    return zones


def zone_file_entries(path):
    entries = {}
    known = set(available_zones())
    for number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, separator, setting = line.partition("=")
        name, setting = name.strip(), setting.strip().lower()
        if name not in known:
            raise ValueError(f"Unknown zone {name!r} on line {number}; use --list-zones")
        if name in entries:
            raise ValueError(f"Duplicate zone {name!r} on line {number}")
        if separator and setting not in ("on", "off"):
            raise ValueError(f"Zone {name!r} must be set to on or off")
        # Older one-name-per-line lists remain valid imports.
        entries[name] = not separator or setting == "on"
    return entries


def read_zone_file(path):
    return validate_zones(name for name, enabled in zone_file_entries(path).items() if enabled)


def select_zones(output, *, zone_set=None, zones=None, zones_file=None,
                 add_zones=(), remove_zones=()):
    if sum(item is not None for item in (zone_set, zones, zones_file)) > 1:
        raise ValueError("Use only one of --zone-set, --zone, or --zones-file")
    output = Path(output)
    if zone_set is not None:
        selected = starting_zones(zone_set)
    elif zones is not None:
        selected = validate_zones(zones)
    elif zones_file is not None:
        selected = read_zone_file(zones_file)
    elif (output / "zones.txt").exists():
        selected = read_zone_file(output / "zones.txt")
    elif (output / "config/central.cfg").exists():
        # Migrate existing deployments without silently reverting a live list.
        selected = validate_zones(cfg_zones(output / "config/central.cfg"))
    else:
        selected = ["tatooine"]
    if set(add_zones) & set(remove_zones):
        raise ValueError("A zone cannot be added and removed in the same command")
    for zone in add_zones:
        validate_zones([zone])
        if zone not in selected:
            selected.append(zone)
    for zone in dict.fromkeys(remove_zones):
        validate_zones([zone])
        if zone not in selected:
            raise ValueError(f"Cannot remove {zone!r}: it is not currently selected")
        selected.remove(zone)
    return validate_zones(selected)


def save_zones(output, zones):
    zones = validate_zones(zones)
    path = Path(output) / "zones.txt"
    if path.exists():
        try:
            lines = [line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8-sig").splitlines()]
            toggles = all("=" in line for line in lines if line)
            if toggles and read_zone_file(path) == zones and set(zone_file_entries(path)) == set(available_zones()):
                return  # Preserve comments and disabled lines in hand-edited lists.
        except ValueError:
            pass  # An explicit, validated replacement can repair an invalid list.
    live = starting_zones("live")
    ordered = zones + [name for name in live if name not in zones]
    ordered += [name for name in available_zones() if name not in ordered]
    lines = ["# Zone catalog: change =off to =on to enable, or =on to =off to disable.",
             "# Regenerate configs and restart game roles to apply. This does not delete world data.",
             "# Keep at least one zone on. 'Additional scene' means it is absent from the original live startup list."]
    for name in ordered:
        note = "" if name in live else "  # Additional scene"
        lines.append(f"{name}={'on' if name in zones else 'off'}{note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
