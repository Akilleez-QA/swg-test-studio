"""Authoritative positive-host preconditions for ordinary saved driver logins."""
import json
from inspect_client_fixture import rows, native_snapshots
from hosted_public_instances_fixture import validate

FAMILIES = {'npe_space_station':'dungeon1', 'npe_space_dungeon':'dungeon1',
            'nova_orion_station':'dungeon1', 'myyydril_caverns':'kashyyyk_pob_dungeons'}


def ready_worlds(report, snapshot):
    policy = validate(report.get('hosted_public_instances_fixture'))
    hosts = {r['definition'] for r in policy['hosts']}
    if not snapshot.startswith('schema=1 configured=1 journal_healthy=1 player_admission=1 '):
        raise ValueError('Healthy native positive-host journal/admission evidence required')
    return _worlds(hosts, rows(snapshot))


def _worlds(hosts, instances):
    result = {(r['definition'], r['instance']) for r in instances
              if r.get('definition') in hosts and r.get('state') == 'running' and
              r.get('recovered') == '0' and r.get('ready') == '1' and
              r.get('instance', '').isdigit() and 0 < int(r['instance']) < 2**63}
    if {definition for definition, _ in result} != hosts:
        raise ValueError('Every complete public host must have a current ready positive world')
    return result


def assert_login(row, worlds):
    family = row.get('family')
    if (family not in FAMILIES or row.get('scene') != FAMILIES[family] or
        (row.get('scene'),row.get('instance')) not in worlds or
        row.get('connected') != 'true' or row.get('pending') != 'false' or row.get('outstanding') != 'false' or
        row.get('cell') in (None, '0', 'null') or row.get('building') in (None, '0', 'null', row.get('player'))):
        raise ValueError('Public login did not settle in its independently proved positive hosted world')


def precondition(folder, project, query):
    report = json.loads((folder/'runtime/stage5-report.json').read_text())
    if report.get('project') != project:
        raise ValueError('Exact labelled public-host fixture required')
    policy = validate(report.get('hosted_public_instances_fixture'))
    # Original room readiness depends on the short-lived native content sample.
    # Revalidate source contracts first, then obtain one coherent fresh sample;
    # a lengthy filesystem validation must not age that sample before use.
    _, instances, _, _ = native_snapshots(query)
    return _worlds({r['definition'] for r in policy['hosts']}, instances)
