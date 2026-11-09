"""Verify complete, current Stage 5 saved-suite evidence before packaging."""
import hashlib
import json
from pathlib import Path
from protocol_test_sets import SETS, source_hashes, validate
FIXTURE = Path('/tmp/swg-cold-test-d9d6e6af/client-ae80acb41011')
REQUIRED = {
    'driver_guards':'driver_unit', 'native_capacity':'native_gate', 'native_combat':'native_gate',
    'native_recovery':'native_gate', 'native_routing':'native_gate', 'station_login_logout':'protocol_session',
    'friend_finder_and_public_consolidation':'split_friend', 'separate_space_consolidation':'space_split',
    'ship_launch_group_land_relaunch':'ship_group', 'combat_quiet_protection_and_cancellation':'combat_windows',
    'pending_arrival_partition_crash_reconnect':'pending_faults', 'gamma_entry':'protocol_session',
    'gamma_return':'protocol_session', 'station_relogin':'protocol_session',
    'maintenance_restart_before_growth':'fixture_restart', 'concurrent_capacity_and_expiry':'capacity_race'}


def verify(path, overlay_sha256):
    path = Path(path).resolve(strict=True)
    fixture = FIXTURE
    if not path.is_relative_to(fixture/'test-sets') or path.name != 'result.json':
        raise ValueError('Stage 5 release evidence must belong to the reviewed retained fixture')
    report = json.loads(path.read_text())
    manifest_path = SETS/'stage5_release.json'
    manifest = validate(json.loads(manifest_path.read_text()))
    actual = {case['id']:case['kind'] for case in manifest['tests']}
    if any(actual.get(key) != kind for key, kind in REQUIRED.items()):
        raise ValueError('Stage 5 manifest removed or replaced a mandatory release gate')
    for case in manifest['tests']:
        if case['id'].startswith('native_') and case['options'] != {'gate':case['id'][7:]}:
            raise ValueError('Stage 5 native gate identity changed')
        if case['id'] in ('gamma_entry', 'gamma_return'):
            family = 'npe_space_dungeon' if case['id'] == 'gamma_entry' else 'npe_space_station'
            if case['options'] != {'role': 'leader', 'prepare_terminal': True,
                                   'expect_scene': 'terrain/dungeon1.trn', 'expect_family': family}:
                raise ValueError('Stage 5 shuttle destination assertions changed')
        if case['id'] in ('station_login_logout', 'station_relogin') and case['options'] != {
                'role': 'leader', 'expect_family': 'npe_space_station'}:
            raise ValueError('Stage 5 station login assertions changed')
    if (report.get('schema_version') != 1 or report.get('suite') != 'stage5_release' or
            report.get('passed') is not True or report.get('source_hashes') != source_hashes() or
            report.get('manifest_sha256') != hashlib.sha256(manifest_path.read_bytes()).hexdigest() or
            report.get('runner_sha256') != hashlib.sha256(SETS.parent.joinpath('protocol_test_sets.py').read_bytes()).hexdigest() or
            len(report.get('cases', [])) != len(manifest['tests'])):
        raise ValueError('Complete passing Stage 5 suite with current source/manifest hashes required')
    stage = json.loads((fixture/'runtime/stage5-report.json').read_text())
    if stage['overlay_manifest_sha256'] != overlay_sha256:
        raise ValueError('Stage 5 fixture tested a different native/script overlay')
    artifacts = []
    for case, expected in zip(report['cases'], manifest['tests']):
        if (case.get('id') != expected['id'] or case.get('kind') != expected['kind'] or
                case.get('passed') is not True or case.get('exit_code') != 0 or case.get('timed_out') is not False):
            raise ValueError('Stage 5 case failed, timed out, or changed identity')
        log = path.parent/(case['id']+'.log')
        if hashlib.sha256(log.read_bytes()).hexdigest() != case['log_sha256']:
            raise ValueError('Stage 5 case log changed')
        if case['kind'] in ('driver_unit', 'native_gate'):
            continue
        artifact = case['artifact']
        result = Path(artifact['path']).resolve(strict=True)
        if not result.is_relative_to(fixture/'protocol-driver') or hashlib.sha256(result.read_bytes()).hexdigest() != artifact['sha256']:
            raise ValueError('Stage 5 runtime artifact changed or escaped the fixture')
        data = json.loads(result.read_text())
        if (data.get('passed') is not True or data.get('fully_unloaded') is not True or
                data.get('project') != 'swg-cold-test-d9d6e6af' or data.get('schema') != 'WGC_AE80ACB41011' or
                data.get('created_images') != 0 or data.get('created_databases') != 0):
            raise ValueError('Stage 5 runtime identity, lifecycle or resource proof failed')
        if case['kind'] != 'protocol_session' and data.get('original_characters_unchanged') is not True:
            raise ValueError('Stage 5 scenario lacks original-character preservation proof')
        if case['kind'] == 'pending_faults' and [s['mode'] for s in data.get('signals', [])] != ['--stop', '--continue', '--kill']:
            raise ValueError('Stage 5 fault suite did not execute the required single faults')
        if case['kind'] == 'fixture_restart' and (data.get('login_maintenance_tested') is not True or
                data.get('ready', {}).get('ready') is not True or data.get('oracle_before') != data.get('oracle_after')):
            raise ValueError('Stage 5 maintenance/restart evidence failed')
        artifacts.append(artifact)
    return {'schema_version': 1, 'stage': 5, 'passed': True, 'path': str(path),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'cases': len(report['cases']),
            'overlay_manifest_sha256': overlay_sha256, 'runtime_artifacts': artifacts,
            'login_maintenance_tested': True}
