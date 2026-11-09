"""Validate and render cold-start probe or Falcon growth policy. No cluster actions."""
import argparse
import json
from pathlib import Path
import re
import uuid

from capacity import read_json, load_catalog

# Later families remain pinned until their reference and content gates pass.
REVIEWED = ("space_npe_falcon_2", "space_npe_falcon_3")


def validate(policy, selected, catalog=None):
    catalog = catalog or load_catalog()
    growth = isinstance(policy, dict) and policy.get("mode") == "falcon_growth"
    fields = {"schema_version", "revision", "mode", "cold_scenes"} | ({"growth_percent"} if growth else set())
    if not isinstance(policy, dict) or set(policy) != fields:
        raise ValueError("Expected schema_version, revision, mode and cold_scenes")
    if type(policy["schema_version"]) is not int or policy["schema_version"] != 1:
        raise ValueError("Unsupported cold-start schema")
    if policy["mode"] not in ("cold_start_probe", "falcon_growth") or not isinstance(policy["revision"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", policy["revision"]):
        raise ValueError("Only explicitly versioned cold_start_probe and falcon_growth are supported")
    if growth and (type(policy["growth_percent"]) is not int or not 1 <= policy["growth_percent"] <= 99):
        raise ValueError("growth_percent must be an integer from 1 to 99")
    scenes = policy["cold_scenes"]
    if not isinstance(scenes, list) or not scenes or any(not isinstance(s, str) for s in scenes):
        raise ValueError("cold_scenes must be a nonempty exact scene list")
    if len(set(scenes)) != len(scenes) or set(scenes) - set(REVIEWED):
        raise ValueError("Duplicate or unreviewed cold scene; other families remain pinned")
    falcon = next(g for g in catalog["groups"] if g["id"] == "falcon")
    if set(scenes) - set(falcon["scenes"]) or set(scenes) - set(selected):
        raise ValueError("Cold scenes must remain selected in the catalog and zones.txt")
    if "space_npe_falcon" not in selected:
        raise ValueError("The base Falcon scene must remain warm")
    if growth and set(selected).intersection(REVIEWED) != set(scenes):
        raise ValueError("Every selected extra Falcon scene must be cold; the base is the only warm copy")
    if growth and "tutorial" not in selected:
        raise ValueError("Falcon growth requires the tutorial scene for owned offline recovery")
    return {"schema_version": 1, "mode": policy["mode"], "revision": policy["revision"],
            "selected_scenes": list(selected), "warm_scenes": [s for s in selected if s not in scenes],
            "cold_scenes": list(scenes), "start_deadline_seconds": 300,
            "maximum_concurrent_starts": 2, "minimum_npe_space_controllers": 124,
            "automatic_growth": growth, "growth_percent": policy.get("growth_percent"),
            "retirement": False, "live_applied": False}


def render(report, journal, epoch):
    if not isinstance(journal, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", journal) or ".." in journal:
        raise ValueError("Journal must be an absolute Linux path without traversal")
    if not re.fullmatch(r"[a-f0-9]{32}", epoch):
        raise ValueError("Epoch must be 32 hexadecimal characters")
    return "[CentralServer]\ncapacityColdStartEnabled=true\n" + \
        f"capacityColdStartEpoch={epoch}\ncapacityColdStartJournal={journal}\n" + \
        "".join(f"capacityColdStartScene={scene}\n" for scene in report["cold_scenes"]) + \
        (f"capacityFalconGrowthEnabled=true\ncapacityFalconGrowthPercent={report['growth_percent']}\n" if report["automatic_growth"] else "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--selected", action="append", required=True, help="exact selected scenes; repeatable")
    parser.add_argument("--output", type=Path, help="fresh staging cfg; does not deploy or modify zones.txt")
    parser.add_argument("--journal", default="/capacity-journal")
    args = parser.parse_args()
    report = validate(read_json(args.policy), args.selected)
    if args.output:
        with args.output.open("x") as stream:
            stream.write(render(report, args.journal, uuid.uuid4().hex))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
