#!/usr/bin/env python3
"""Copy a consistent canonical schema into a fresh user in an existing test DB.

Preserves both source data and the fixture's original schema. Creates no images,
database volumes or client ports. Private dumps/config credentials stay in /tmp.
Oracle API: https://docs.oracle.com/en/database/oracle/oracle-database/26/arpls/DBMS_DATAPUMP.html
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

from studio_tool_bundle import TOOLS_ROOT, server_source

REPO = server_source()
sys.path.insert(0, str(TOOLS_ROOT / 'docker'))
from disposable_database import validate
from instance_schema_upgrade import export_sql, sql_script


def run(argv, **kwargs):
    result = subprocess.run(argv, text=True, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(argv[:3]))
    return result.stdout.strip()


def target_root(value):
    root = Path(value).resolve(strict=True)
    if root.parent != Path('/tmp') or not re.fullmatch(r'swg-cold-test-[a-f0-9]{8}', root.name):
        raise ValueError('Requires an existing labelled Linux-native test root')
    compose = json.loads((root / 'compose.json').read_text())
    volume = root.name + '_oracle26_data'
    if compose.get('name') != root.name or compose.get('volumes') != {
            'oracle_data': {'name': volume, 'external': True}}:
        raise ValueError('Unexpected fixture project/storage')
    oracle = compose['services']['oracle']
    if (oracle.get('ports') or oracle.get('privileged') or
            oracle.get('labels', {}).get('whitengold.test.kind') != 'cold-start'):
        raise ValueError('Unexpected fixture Oracle exposure/identity')
    return root, compose, volume


def import_sql(schema, token, password):
    if not re.fullmatch(r'WGC_[A-F0-9]{12}', schema) or not re.fullmatch(r'[a-f0-9]{12}', token):
        raise ValueError('Invalid generated fixture schema identity')
    if not re.fullmatch(r'[a-f0-9]{24}', password):
        raise ValueError('Invalid private fixture credential')
    return f"""declare n number;
begin
 select count(*) into n from dba_users where username='{schema}';
 if n<>0 then raise_application_error(-20051,'Fixture schema already exists');end if;
 execute immediate 'create user {schema} identified by "{password}" default tablespace DATA temporary tablespace TEMP';
 execute immediate 'grant create type, unlimited tablespace, SWG_GENERAL to {schema}';
end;
/
declare h number; s varchar2(30);
begin
 h:=dbms_datapump.open(operation=>'IMPORT',job_mode=>'SCHEMA',job_name=>'WGC_IMP_{token.upper()}');
 dbms_datapump.add_file(h,'wgc_{token}.dmp','DATA_PUMP_DIR',filetype=>dbms_datapump.ku$_file_type_dump_file);
 dbms_datapump.add_file(h,'wgc_import_{token}.log','DATA_PUMP_DIR',filetype=>dbms_datapump.ku$_file_type_log_file);
 dbms_datapump.metadata_remap(h,'REMAP_SCHEMA','BUILDCLUSTER','{schema}');
 dbms_datapump.metadata_filter(h,'EXCLUDE_PATH_EXPR','IN (''USER'')');
 dbms_datapump.start_job(h);
 dbms_datapump.wait_for_job(h,s);
 if s<>'COMPLETED' or s is null then raise_application_error(-20052,'Import incomplete');end if;
end;
/
begin dbms_utility.compile_schema(schema=>'{schema}',compile_all=>false);end;
/
select 'IMPORT_COMPLETED' from dual;
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-root', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='export a consistent snapshot and import into a fresh test schema')
    parser.add_argument('--resume-export', action='store_true', help='resume the recorded completed export before any import began')
    args = parser.parse_args()
    root, compose, volume = target_root(args.fixture_root)
    metadata = json.loads(run(['docker', 'volume', 'inspect', volume]))[0]
    if metadata.get('Labels', {}).get('whitengold.test.kind') != 'cold-start':
        raise ValueError('Existing test volume lacks its original label')
    attached = set(run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + root.name]).split())
    attached.update(run(['docker', 'ps', '-aq', '--filter', 'volume=' + volume]).split())
    if attached:
        rows = json.loads(run(['docker', 'inspect'] + sorted(attached)))
        if not args.resume_export or len(rows) != 1 or rows[0]['Name'] != '/' + root.name + '-oracle-1':
            raise ValueError('Fixture containers must be removed before preparing client copies')
        validate(rows[0], root, volume)
    source = 'starwarsgalaxies-oracle-1'
    live = json.loads(run(['docker', 'inspect', source]))[0]
    if (not live['State']['Running'] or live['Config']['Image'] != 'gvenzl/oracle-free:23.26.3-slim-faststart' or
            not any(m.get('Type') == 'volume' and m.get('Name') == 'starwarsgalaxies_oracle26_data' and
                    m.get('Destination') == '/opt/oracle/oradata' for m in live['Mounts'])):
        raise ValueError('Expected the existing canonical Oracle26 source')
    latest = root / 'client-fixture-latest.json'
    if latest.exists() != args.resume_export:
        raise ValueError('Client fixture preparation already recorded; inspect it before another copy')
    print(json.dumps({'source': source, 'target_volume': volume, 'new_schema': True,
                      'new_database_volumes': 0, 'new_images': 0, 'apply': args.apply}), flush=True)
    if not args.apply:
        return
    os.umask(0o077)
    with (root / '.client-fixture.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.resume_export:
            previous = json.loads(latest.read_text())
            folder = Path(previous['folder']).resolve(strict=True)
            if folder.parent != root or not re.fullmatch('client-[a-f0-9]{12}', folder.name):
                raise ValueError('Invalid recorded client folder')
            token = folder.name[7:]
            schema = 'WGC_' + token.upper()
            report = json.loads((folder / 'schema-report.json').read_text())
            if (report.get('schema') != schema or report.get('volume') != volume or
                    report.get('passed') or report.get('pending') != 'export'):
                raise ValueError('Only a completed export before import may resume')
            password = (folder / 'schema-password.txt').read_text().strip()
        else:
            if latest.exists():
                raise ValueError('Another client preparation was recorded')
            token = secrets.token_hex(6)
            schema = 'WGC_' + token.upper()
            folder = root / ('client-' + token)
            folder.mkdir(mode=0o700)
            password = secrets.token_hex(12)
            (folder / 'schema-password.txt').write_text(password + '\n')
            report = {'schema_version': 1, 'root': str(root), 'folder': str(folder),
                      'schema': schema, 'volume': volume, 'passed': False, 'source_game_data_changed': False,
                      'target_original_schema_preserved': True, 'created_images': 0, 'created_database_volumes': 0}

        def save():
            (folder / 'schema-report.json').write_text(json.dumps(report, indent=2) + '\n')
            latest.write_text(json.dumps({'folder': str(folder), 'schema': schema, 'passed': report['passed']}) + '\n')

        def sql(container, body, label, timeout=120):
            result = subprocess.run(['docker', 'exec', '-i', '--user', 'oracle', container,
                                     'sqlplus', '-s', '/nolog'], input=sql_script(body),
                                    text=True, capture_output=True, timeout=timeout)
            output = (result.stdout + result.stderr).replace(password, '[REDACTED]')
            (folder / (label + '.log')).write_text(output)
            if result.returncode or re.search(r'(^|\n)(ORA-|SP2-)', output):
                raise RuntimeError('Oracle step failed; see ' + str(folder / (label + '.log')))
            return output.strip()

        def directory(container, label):
            path = sql(container, "select directory_path from dba_directories where directory_name='DATA_PUMP_DIR';", label)
            if not re.fullmatch(r'/opt/oracle/admin/FREE/dpdump/[A-Fa-f0-9]{32}', path):
                raise ValueError('Unexpected Data Pump directory')
            run(['docker', 'exec', '--user', 'oracle', container, '/bin/sh', '-ec',
                 'test "$(readlink -f /opt/oracle/admin/FREE/dpdump)" = /opt/oracle/admin/FREE/dpdump; '
                 'test ! -L "$1"; if test ! -e "$1"; then mkdir -m 700 -- "$1"; fi; test -d "$1"; test -w "$1"', 'sh', path])
            return path

        save()
        target = root.name + '-oracle-1'
        run(['docker', 'compose', '-f', str(root / 'compose.json'), 'up', '-d', '--no-build', 'oracle'])
        validate(json.loads(run(['docker', 'inspect', target]))[0], root, volume)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            if 'DATABASE IS READY TO USE!' in run(['docker', 'logs', target]):
                break
            time.sleep(2)
        else:
            raise RuntimeError('Test Oracle readiness deadline')
        original_counts = sql(target, "select (select count(*) from buildcluster.objects)||':'||"
                              "(select count(*) from buildcluster.players) from dual;", 'original-test-counts')
        if sql(source, "select (select count(*) from dba_db_links where owner='BUILDCLUSTER')+"
               "(select count(*) from dba_scheduler_jobs where owner='BUILDCLUSTER')+"
               "(select count(*) from dba_jobs where schema_user='BUILDCLUSTER') from dual;", 'source-external-jobs') != '0':
            raise ValueError('Review external links/jobs before copying this schema')
        scn = report['snapshot_scn'] if args.resume_export else sql(source, 'select dbms_flashback.get_system_change_number from dual;', 'snapshot-scn')
        if not scn.isdigit():
            raise ValueError('Invalid snapshot SCN')
        report['snapshot_scn'] = scn
        tables = ((folder / 'source-tables.log').read_text().strip().splitlines() if args.resume_export else
                  sql(source, "select table_name from dba_tables where owner='BUILDCLUSTER' and nested='NO' order by table_name;", 'source-tables').splitlines())
        if not tables or any(not re.fullmatch('[A-Z][A-Z0-9_]*', table) for table in tables):
            raise ValueError('Unexpected source table inventory')
        def counts(owner, at=''):
            return '\n'.join(f"select '{table}:'||count(*) from {owner}.{table}{at};" for table in tables)
        if not args.resume_export:
            report['table_counts'] = sql(source, counts('BUILDCLUSTER', ' as of scn ' + scn), 'source-counts').splitlines()
        elif report['table_counts'] != (folder / 'source-counts.log').read_text().strip().splitlines():
            raise ValueError('Retained snapshot counts differ')
        source_dir = directory(source, 'source-directory')
        dump = 'wgc_' + token + '.dmp'
        export = export_sql('WGC_EXP_' + token.upper(), dump, 'wgc_export_' + token + '.log')
        export = export.replace(' dbms_datapump.start_job(handle);',
                                " dbms_datapump.set_parameter(handle,'FLASHBACK_SCN'," + scn + ');\n dbms_datapump.start_job(handle);')
        report['pending'] = 'export'
        save()
        if not args.resume_export:
            if sql(source, export, 'export', 1800) != 'BACKUP_COMPLETED':
                raise RuntimeError('Export completion not confirmed')
            for name in (dump, 'wgc_export_' + token + '.log'):
                run(['docker', 'cp', source + ':' + source_dir + '/' + name, str(folder / name)])
        elif (folder / 'export.log').read_text().strip() != 'BACKUP_COMPLETED':
            raise ValueError('Retained export did not complete')
        export_detail = (folder / ('wgc_export_' + token + '.log')).read_text(errors='replace')
        if re.search(r'\b(ORA-|UDE-|LRM-)', export_detail) or 'successfully completed' not in export_detail.lower():
            raise RuntimeError('Data Pump reported export errors')
        digest = hashlib.sha256((folder / dump).read_bytes()).hexdigest()
        if run(['docker', 'exec', source, 'sha256sum', source_dir + '/' + dump]).split()[0] != digest:
            raise RuntimeError('Snapshot copy hash mismatch')
        report['dump_sha256'] = digest
        target_dir = directory(target, 'target-directory')
        run(['docker', 'cp', str(folder / dump), target + ':' + target_dir + '/' + dump])
        run(['docker', 'exec', '--user', '0', target, 'chown', 'oracle:oinstall', target_dir + '/' + dump])
        if run(['docker', 'exec', target, 'sha256sum', target_dir + '/' + dump]).split()[0] != digest:
            raise RuntimeError('Imported dump hash mismatch')
        report['pending'] = 'import'
        save()
        if sql(target, import_sql(schema, token, password), 'import', 1800) != 'IMPORT_COMPLETED':
            raise RuntimeError('Import completion not confirmed')
        run(['docker', 'cp', target + ':' + target_dir + '/wgc_import_' + token + '.log', str(folder / 'import-details.log')])
        detail = (folder / 'import-details.log').read_text(errors='replace')
        if re.search(r'\b(ORA-|UDE-|LRM-)', detail) or 'successfully completed' not in detail.lower():
            raise RuntimeError('Data Pump reported import errors; preserve the new schema for diagnosis')
        if sql(target, counts(schema), 'target-counts').splitlines() != report['table_counts']:
            raise RuntimeError('Imported table counts differ from the snapshot')
        if sql(target, f"select version_number||':'||min_version_number from {schema}.version_number;", 'target-version') != '271:271':
            raise RuntimeError('Imported schema version is not 271')
        if sql(target, f"select count(*) from dba_objects where owner='{schema}' and status='INVALID';", 'target-invalid') != '0':
            raise RuntimeError('Invalid imported objects remain')
        if sql(target, f"select (select count(*) from dba_dependencies where owner='{schema}' and referenced_owner='BUILDCLUSTER')+"
               f"(select count(*) from dba_synonyms where owner='{schema}' and table_owner='BUILDCLUSTER') from dual;", 'target-cross-schema') != '0':
            raise RuntimeError('Imported objects still reference the original test schema')
        if sql(target, "select (select count(*) from buildcluster.objects)||':'||"
               "(select count(*) from buildcluster.players) from dual;", 'original-test-counts-after') != original_counts:
            raise RuntimeError('Original fixture row counts changed')
        report['original_test_counts'] = original_counts
        report.pop('pending', None)
        report['passed'] = True
        save()
        print(json.dumps({'passed': True, 'folder': str(folder), 'schema': schema,
                          'tables_verified': len(tables), 'dump_sha256': digest}), flush=True)


if __name__ == '__main__':
    main()
