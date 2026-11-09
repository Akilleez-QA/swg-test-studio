"""Exact retained-fixture service identity for distributed retirement faults.

This module only observes. Signal adapters must recheck the returned PID/start
pair immediately before a separately authorized, allowlisted fault action.
"""
import json
import re
from protocol_driver import run

SERVICES = {
    'central': '/opt/whitengold/bin/CentralServer',
    'database': '/opt/whitengold/bin/SwgDatabaseServer',
    'taskmanager': '/opt/whitengold/bin/TaskManager',
    'game': '/opt/whitengold/bin/TaskManager',
    'planet': '/opt/whitengold/bin/TaskManager',
}


def validate_container(meta, project, schema, role, expected):
    labels = meta.get('Config', {}).get('Labels') or {}
    if (role not in SERVICES or not re.fullmatch('swg-cold-test-[a-f0-9]{8}', project) or
            not re.fullmatch('WGC_[A-F0-9]{12}', schema) or
            labels.get('com.docker.compose.project') != project or
            labels.get('com.docker.compose.service') != role or
            labels.get('whitengold.test.client') != schema or
            not meta.get('State', {}).get('Running') or
            not re.fullmatch('[a-f0-9]{64}', meta.get('Id', '')) or
            meta.get('Id') != expected.get('Id') or meta.get('Image') != expected.get('Image')):
        raise RuntimeError('Exact running retained SWG service identity required')


def service_target(project, schema, services, manifest, role, query=run):
    """Observe only the requested, positively identified SWG service container."""
    if role not in SERVICES or role not in services:
        raise ValueError('Explicit Central, database or reviewed supervisor required')
    expected = services[role]
    # Validate the supplied fixture receipt before issuing any Docker operation.
    validate_container(expected, project, schema, role, expected)
    container = project+'-'+role+'-1'
    records = json.loads(query(['docker', 'inspect', container]))
    if not isinstance(records, list) or len(records) != 1:
        raise RuntimeError('Exactly one service container required')
    current = records[0]
    validate_container(current, project, schema, role, expected)
    executable = SERVICES[role]
    digest = manifest['files']['bin/'+executable.rsplit('/', 1)[1]]['sha256']
    if not re.fullmatch('[a-f0-9]{64}', digest):
        raise RuntimeError('Verified ELF64 manifest digest required')
    found = []
    for line in query(['docker', 'exec', container, 'ps', '-eo', 'pid,args']).splitlines():
        fields = line.split()
        if len(fields) > 1 and fields[1] == executable:
            if not re.fullmatch('[1-9][0-9]{0,9}', fields[0]) or int(fields[0]) > 2147483647:
                raise RuntimeError('Invalid service PID')
            found.append(fields[0])
    if len(found) != 1:
        raise RuntimeError('Exactly one matching service executable required')
    pid = found[0]
    stat = query(['docker', 'exec', container, 'cat', '/proc/'+pid+'/stat'])
    if not stat.startswith(pid+' (') or ') ' not in stat:
        raise RuntimeError('Service process identity changed')
    fields = stat.rsplit(') ', 1)[1].split()
    if len(fields) < 20 or not re.fullmatch('[1-9][0-9]{0,19}', fields[19]):
        raise RuntimeError('Exact process start time required')
    actual = query(['docker', 'exec', container, 'sha256sum', '/proc/'+pid+'/exe']).split()
    if len(actual) != 2 or actual[0] != digest or actual[1] != '/proc/'+pid+'/exe':
        raise RuntimeError('Service executable differs from the accepted package')
    return dict(role=role, container=container, container_id=current['Id'], image_id=current['Image'],
                executable=executable, sha256=digest, pid=pid, start_ticks=fields[19])