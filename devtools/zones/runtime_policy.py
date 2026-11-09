"""Persistent, allowlisted NPE policies for the canonical ELF64 deployment."""
import re
from cold_start import REVIEWED, validate, render
from capacity import read_json
from instance_scope import validate_instance_policies

JOURNALS = {
    "central": ("capacity_journal", "starwarsgalaxies_capacity_journal", "/capacity-journal"),
    "database": ("login_journal", "starwarsgalaxies_login_journal", "/login-journal"),
}
KEYS = {"capacityColdStartEnabled", "capacityColdStartEpoch", "capacityColdStartJournal",
        "capacityColdStartScene", "capacityFalconGrowthEnabled", "capacityFalconGrowthPercent",
        "zoneInstanceJournal", "zoneInstancePolicy", "zoneInstanceMaximum", "zoneInstanceConcurrentStarts",
        "zoneInstanceCooldownMilliseconds", "zoneInstanceStartupMilliseconds", "zoneInstancePlayerAdmission",
        "capacityRryattGroupEnabled", "capacityRryattInstancesEnabled", "capacityRryattSetLimit",
        "capacityGroupTransferEnabled", "capacityGroupTransferJournal", "capacityFamilyLoginJournal", "capacityGroupWorldLimit",
        "capacityAllFamiliesEnabled", "capacityWorldFamily"}
FALCON = "space_npe_falcon"
FALCON_SCENES = (FALCON, "space_npe_falcon_2", "space_npe_falcon_3")
INSTANCE_ROOT = "/capacity-journal/instances"
ADMISSION_ROOT = "/capacity-journal/admission"
ORD = "space_ord_mantell"
ORD_SCENES = (ORD, "space_ord_mantell_2", "space_ord_mantell_3", "space_ord_mantell_4", "space_ord_mantell_5", "space_ord_mantell_6")


def npe_instances(state):
    return bool(state and ((state.get("schema_version") in (3,4) and state.get("mode") == "npe_instances") or
                          (state.get("schema_version")==5 and state.get("mode")=="world_instances")))


def instances(state):
    return bool(state and state.get("schema_version") == 2 and state.get("mode") == "falcon_instances") or npe_instances(state)


def base_profile(state):
    """Read the retained profile without discarding an expanded policy.

    This is not an activation gate. Canonical load still requires release
    acceptance, and callers must keep the full state when rendering/saving.
    """
    if state is None:
        return None
    validate_state(state)
    return state['base'] if state['schema_version'] == 5 else state


def automatic_retirement(state):
    profile = base_profile(state)
    return bool(profile and profile.get('automatic_retirement', False))


def managed_definitions(state):
    """Exact canonical journal definitions, independent of warm selection."""
    profile = base_profile(state)
    if not instances(profile):
        return []
    result = [FALCON]
    if npe_instances(profile):
        result.append(ORD)
    if profile['schema_version'] == 4:
        result.append('kashyyyk_rryatt_trail')
    if state['schema_version'] == 5:
        result.extend(sorted(row['definition'] for row in state['world_families']))
    return result


def journal_definitions(state):
    """Keep stopped catalog records readable after a selection change.

    These names are a decoding scope, never launch policies. Canonical retired
    history remains readable after a scope change; aliases remain excluded.
    Maintenance still requires proof
    that every executor is stopped before acknowledging a generation.
    """
    result=managed_definitions(state)
    if state and state['schema_version']==5:
        from instance_scope import load as family_scope
        known={row['definition'] for row in family_scope()['definitions']}
        return result[:3]+sorted(known-set(result[:3]))
    return result


def validate_state(state):
    version = state.get("schema_version") if isinstance(state, dict) else None
    if version == 5:
        import world_runtime_policy
        return world_runtime_policy.validate_state(state)
    if version == 4:
        import rryatt_runtime_policy
        return rryatt_runtime_policy.validate_state(state)
    fields = {"schema_version", "mode", "growth_percent", "epoch"}
    if version in (2, 3):
        fields.add("maximum_instances")
    if version == 3:
        fields.update(("ord_maximum_instances", "ord_capacity", "public_world_capacity"))
    if (not isinstance(state, dict) or set(state) != fields or type(version) is not int or version not in (1, 2, 3)
            or state["mode"] not in {1: ("eager", "falcon_growth"), 2: ("falcon_instances",), 3: ("npe_instances",)}[version]
            or type(state["growth_percent"]) is not int or not 1 <= state["growth_percent"] <= 99
            or not isinstance(state["epoch"], str) or not re.fullmatch(r"[a-f0-9]{32}", state["epoch"])
            or (version in (2, 3) and (type(state["maximum_instances"]) is not int or not 1 <= state["maximum_instances"] <= 16))
            or (version == 3 and (type(state["ord_maximum_instances"]) is not int or not 1 <= state["ord_maximum_instances"] <= 16
                or type(state["ord_capacity"]) is not int or not 2 <= state["ord_capacity"] <= 16384
                or type(state["public_world_capacity"]) is not int or not 50 <= state["public_world_capacity"] <= 16384))):
        raise ValueError("Invalid capacity-runtime.json; expected a typed NPE policy")
    return state


def load(deployment, selected):
    path = deployment / "capacity-runtime.json"
    if not path.exists():
        return None
    state = validate_state(read_json(path))
    if state.get('schema_version')==5:
        raise ValueError('Full-family policy is staged; coordinated native, script and saved-suite release acceptance is required before canonical activation')
    report(state, selected)
    return state


def report(state, selected):
    if state and state.get("schema_version") == 5:
        import world_runtime_policy
        return world_runtime_policy.report(state, selected)
    if state and state.get("schema_version") == 4:
        import rryatt_runtime_policy
        return rryatt_runtime_policy.report(state, selected)
    if state:
        validate_state(state)
    if instances(state):
        if "tutorial" not in selected or not set(selected).intersection(FALCON_SCENES):
            raise ValueError("Canonical Falcon instances require tutorial and a selected Falcon definition or explicit alias")
        if npe_instances(state) and ("dungeon1" not in selected or not set(selected).intersection(ORD_SCENES)):
            raise ValueError("NPE instances require selected dungeon1 and an Ord definition or explicit alias")
        effective = list(dict.fromkeys(FALCON if name in FALCON_SCENES else ORD if npe_instances(state) and name in ORD_SCENES else name for name in selected))
        definitions = [FALCON, ORD] if npe_instances(state) else [FALCON]
        warm = [name for name in effective if name not in definitions]
        result = {"schema_version": state["schema_version"], "mode": state["mode"], "selected_scenes": list(selected),
                "effective_scenes": effective, "warm_scenes": warm, "cold_scenes": [],
                "managed_definitions": definitions, "warm_instances": 1, "maximum_instances": state["maximum_instances"],
                "maximum_game_workers": len(warm) + state["maximum_instances"] + (state["ord_maximum_instances"] if npe_instances(state) else 0),
                "growth_percent": state["growth_percent"], "automatic_growth": True,
                "retirement": False, "player_admission": True, "group_transfer": npe_instances(state)}
        if npe_instances(state):
            result.update(ord_maximum_instances=state["ord_maximum_instances"], ord_capacity=state["ord_capacity"], public_world_capacity=state["public_world_capacity"])
        return result
    if not state or state["mode"] == "eager":
        return {"mode": "eager", "warm_scenes": list(selected), "cold_scenes": [], "retirement": False}
    return validate({"schema_version": 1, "mode": "falcon_growth", "revision": "runtime-1",
                     "growth_percent": state["growth_percent"],
                     "cold_scenes": [scene for scene in REVIEWED if scene in selected]}, selected)


def config(text, role, state, selected):
    validate_instance_policies(text)
    if state and state.get("schema_version") == 5:
        import world_runtime_policy
        return world_runtime_policy.config(text,role,state,selected)
    if state and state.get("schema_version") == 4:
        import rryatt_runtime_policy
        return rryatt_runtime_policy.config(text, role, state, selected)
    capacity = report(state, selected)
    if not state:
        return text
    # Replace only owned keys in their exact sections; preserve private endpoints.
    section = ""
    lines = []
    owned = False
    written = set()
    for line in text.splitlines():
        if line == "# capacity-runtime begin":
            owned = True
            continue
        if line == "# capacity-runtime end":
            owned = False
            continue
        if owned:
            continue
        if line.startswith("["):
            section = line.strip()
        key = line.split("=", 1)[0]
        if section == "[CentralServer]" and key in KEYS:
            continue
        if section == "[dbProcess]" and key == "loginLoadJournalDirectory":
            continue
        if section == "[GameServer]" and key in ("capacityGroupTransferEnabled", "capacityRryattGroupEnabled", "capacityRryattInstancesEnabled", "capacityRryattSetLimit", "capacityAllFamiliesEnabled", "capacityWorldFamily"):
            continue
        if instances(state):
            name = line.split("=", 1)[1] if key == "startPlanet" else ""
            definition = FALCON if name in FALCON_SCENES else ORD if npe_instances(state) and name in ORD_SCENES else ""
            if section == "[CentralServer]" and definition:
                if definition in written:
                    continue
                line = "startPlanet=" + definition
                written.add(definition)
            if role == "game" and section == "[TaskManager]" and key == "maximumLoad":
                line = "maximumLoad=" + str(capacity["maximum_game_workers"] + 1)
        lines.append(line)
    result = "\n".join(lines) + "\n"
    if state and role == "central" and state["mode"] == "falcon_growth":
        result += "# capacity-runtime begin\n" + render(report(state, selected), "/capacity-journal/records", state["epoch"]) + "# capacity-runtime end\n"
    if instances(state) and role == "central":
        result += ("# capacity-runtime begin\n[CentralServer]\n"
                   f"zoneInstanceJournal={INSTANCE_ROOT}\n"
                   f'zoneInstancePolicy="{FALCON} npe_space content 124 1 {state["maximum_instances"]} {state["growth_percent"]}"\n' +
                   (f'zoneInstancePolicy="{ORD} ord_mantell players {state["ord_capacity"]} 1 {state["ord_maximum_instances"]} {state["growth_percent"]}"\n' if npe_instances(state) else "") +
                   f'zoneInstanceMaximum={state["maximum_instances"] + (state["ord_maximum_instances"] if npe_instances(state) else 0)}\n'
                   "zoneInstanceConcurrentStarts=2\nzoneInstanceCooldownMilliseconds=30000\n"
                   "zoneInstanceStartupMilliseconds=300000\nzoneInstancePlayerAdmission=true\n# capacity-runtime end\n")
        if npe_instances(state):
            result += ("# capacity-runtime begin\n[CentralServer]\ncapacityGroupTransferEnabled=true\n"
                       f"capacityGroupTransferJournal={ADMISSION_ROOT}\ncapacityFamilyLoginJournal=/capacity-journal/family-logins\n"
                       f'capacityGroupWorldLimit="{ORD} {state["ord_capacity"]}"\n'
                       f'capacityGroupWorldLimit="dungeon1 {state["public_world_capacity"]}"\n# capacity-runtime end\n')
    if npe_instances(state) and role == "game":
        result += "# capacity-runtime begin\n[GameServer]\ncapacityGroupTransferEnabled=true\n# capacity-runtime end\n"
    if state and role == "database":
        result += "# capacity-runtime begin\n[dbProcess]\nloginLoadJournalDirectory=/login-journal/records\n# capacity-runtime end\n"
    return result


def mounts(compose, install=False):
    """Validate exact private mounts, optionally add the two intentional journals."""
    for role, (key, name, target) in JOURNALS.items():
        expected = {"type": "volume", "source": key, "target": target}
        existing = [v for v in compose["services"][role].get("volumes", [])
                    if v.get("source") == key or v.get("target") == target]
        definition = compose["volumes"].get(key)
        if existing or definition:
            if existing != [expected] or definition != {"name": name, "external": True}:
                raise ValueError("Invalid persistent journal mount for " + role)
        elif install:
            compose["services"][role]["volumes"].append(expected)
            compose["volumes"][key] = {"name": name, "external": True}
    return compose
