"""Offline schema 270 -> 271 upgrade for the canonical Oracle26 deployment.

The management backend owns the mutation lock and stop sequence. DDL commits
independently: preserve checkpoints/backups and leave services stopped on error.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid


def inputs(repo):
    paths = [repo / "devtools/zones/zone_instance_schema.sql"]
    paths += [repo / "src/game/server/database/schema/objects_view.view"]
    paths += [repo / "src/game/server/database/packages" / (name + "." + suffix)
              for suffix in ("plsqlh", "plsql") for name in ("loader", "persister")]
    paths += [repo / "devtools/zones/zone_instance_finalize.sql"]
    return paths


def sql_script(body, password=None):
    connect = (f'connect buildcluster/"{password}"@//localhost:1521/FREEPDB1\n' if password else
               "connect / as sysdba\nalter session set container=FREEPDB1;\n")
    return ("set echo off verify off define off heading off feedback off pagesize 0 linesize 32767 serveroutput on\n"
            "whenever oserror exit failure rollback\nwhenever sqlerror exit sql.sqlcode rollback\n" + connect + body + "\nexit;\n")


def export_sql(job, dump, log):
    if not all(re.fullmatch(r"[A-Za-z0-9_.]+", value) for value in (job, dump, log)):
        raise ValueError("Invalid generated backup identity")
    return f"""declare
 handle number; state varchar2(30);
begin
 handle:=dbms_datapump.open(operation=>'EXPORT',job_mode=>'SCHEMA',job_name=>'{job}');
 dbms_datapump.add_file(handle,'{dump}','DATA_PUMP_DIR',filetype=>dbms_datapump.ku$_file_type_dump_file);
 dbms_datapump.add_file(handle,'{log}','DATA_PUMP_DIR',filetype=>dbms_datapump.ku$_file_type_log_file);
 dbms_datapump.metadata_filter(handle,'SCHEMA_EXPR','IN (''BUILDCLUSTER'')');
 dbms_datapump.start_job(handle);
 dbms_datapump.wait_for_job(handle,state);
 if state<>'COMPLETED' or state is null then raise_application_error(-20050,'Schema backup did not complete');end if;
end;
/
select 'BACKUP_COMPLETED' from dual;
"""


def upgrade(manager, fixture_container=None):
    manager.require_stopped()
    oracle = manager.oracle()
    if oracle["Config"]["Image"] != "gvenzl/oracle-free:23.26.3-slim-faststart" or not oracle["State"]["Running"]:
        raise ValueError("Offline instance migration requires the existing running Oracle26 database")
    root = manager.deployment
    container = "starwarsgalaxies-oracle-1"
    if fixture_container is not None:
        from disposable_database import validate
        validate(oracle, root, root.name + "_oracle26_data")
        if fixture_container != root.name + "-oracle-1":
            raise ValueError("Wrong disposable migration container")
        container = fixture_container
    password = (root / "schema-password.txt").read_text().strip()
    if not re.fullmatch(r"[a-f0-9]{24}", password):
        raise ValueError("Unexpected private schema credential format")
    folder = manager.log.parent / "schema-271"
    folder.mkdir(mode=0o700)
    sources = inputs(manager.repo)
    runtime = root / "runtime.cfg"
    before = runtime.read_text()
    after, number = re.subn(r"(?m)^expectedDBVersion=270[ \t]*$", "expectedDBVersion=271", before)
    if number != 1:
        raise ValueError("Expected exactly one legacy database version in runtime.cfg")
    manifest = {str(path.relative_to(manager.repo)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    state = {"schema_version": 1, "target": 271, "source_hashes": manifest, "completed": [], "passed": False}

    def save():
        (folder / "report.json").write_text(json.dumps(state, indent=2) + "\n")

    def sql(body, label, admin=False, timeout=120):
        result = subprocess.run(["docker", "exec", "-i", "--user", "oracle", container, "sqlplus", "-s", "/nolog"],
            input=sql_script(body, None if admin else password), text=True, capture_output=True, timeout=timeout)
        output = (result.stdout + result.stderr).replace(password, "[REDACTED]")
        (folder / (label + ".log")).write_text(output)
        if result.returncode or re.search(r"(^|\n)(ORA-|SP2-)", output):
            raise RuntimeError("Schema migration failed; inspect " + str(folder / (label + ".log")))
        return output.strip()

    def no_sessions():
        if sql("select count(*) from v$session where username='BUILDCLUSTER';", "offline-sessions", admin=True) != "0":
            raise ValueError("BUILDCLUSTER still has database sessions; do not migrate while game workers are connected")

    save()
    try:
        no_sessions()
        version = sql("select version_number||':'||min_version_number from version_number;", "version-before")
        if version != "270:270":
            raise ValueError("Upgrade requires schema 270:270; inspect prior migration evidence before retrying")
        if sql("select count(*) from user_tab_columns where table_name='OBJECTS' and column_name='ZONE_INSTANCE_ID';", "column-before") != "0":
            raise ValueError("Instance column already exists before cutover; reconcile the earlier migration checkpoint")
        state["source_version"] = version
        # Copy exact source inputs before the first DDL. Later changes to the
        # checkout cannot alter the remainder of this operation.
        staged = []
        for n, path in enumerate(sources):
            target = folder / (str(n) + "-" + path.name)
            shutil.copy2(path, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != manifest[str(path.relative_to(manager.repo))]:
                raise RuntimeError("Migration source changed while staging")
            staged.append(target)
        token = uuid.uuid4().hex[:16]
        job = "WG_INST_" + token.upper()
        dump, log = "wg_instances_" + token + ".dmp", "wg_instances_" + token + ".log"
        directory = sql("select directory_path from dba_directories where directory_name='DATA_PUMP_DIR';", "backup-directory", admin=True)
        if not re.fullmatch(r"/opt/oracle/admin/FREE/dpdump/[A-Fa-f0-9]{32}", directory):
            raise ValueError("Unexpected Oracle backup directory")
        # The PDB dictionary retains this GUID path when the Oracle container
        # is recreated, but that directory lives outside its data volume.
        # Recreate only this exact backup directory as Oracle's runtime user.
        manager.command(["docker", "exec", "--user", "oracle", container, "/bin/sh", "-ec",
            'test "$(readlink -f /opt/oracle/admin/FREE/dpdump)" = /opt/oracle/admin/FREE/dpdump; '
            'test ! -L "$1"; if test ! -e "$1"; then mkdir -m 700 -- "$1"; fi; test -d "$1"; test -w "$1"',
            "sh", directory])
        state["backup"] = {"job": job, "oracle_dump": directory.rstrip("/") + "/" + dump}
        save()
        if sql(export_sql(job, dump, log), "export", admin=True, timeout=1800) != "BACKUP_COMPLETED":
            raise RuntimeError("Backup completion was not confirmed")
        for name in (dump, log):
            source = directory.rstrip("/") + "/" + name
            manager.command(["docker", "cp", container + ":" + source, str(folder / name)])
        export_log = (folder / log).read_text(errors="replace")
        if "successfully completed" not in export_log.lower() or re.search(r"(^|\n)(ORA-|UDE-|LRM-)", export_log):
            raise RuntimeError("Data Pump reported an incomplete backup")
        digest = hashlib.sha256((folder / dump).read_bytes()).hexdigest()
        remote = manager.command(["docker", "exec", "--user", "oracle", container,
                                  "sha256sum", state["backup"]["oracle_dump"]], capture=True).stdout.split()[0]
        if digest != remote or (folder / dump).stat().st_size == 0:
            raise RuntimeError("Copied schema backup failed hash verification")
        state["backup"].update(local_dump=str(folder / dump), sha256=digest, verified=True)
        save()
        counts = "select (select count(*) from objects)||':'||(select count(*) from players) from dual;"
        state["rows_before"] = sql(counts, "rows-before")
        no_sessions()
        for path in staged[:-1]:
            state["pending"] = path.name
            save()
            sql(path.read_text(encoding="latin-1"), path.stem)
            state["completed"].append(path.name)
            state.pop("pending")
            save()
        sql("begin dbms_utility.compile_schema(schema=>'BUILDCLUSTER',compile_all=>false); end;\n/", "compile-schema")
        invalid = sql("select object_type||':'||object_name from user_objects where status='INVALID' order by object_type,object_name;", "invalid-objects")
        if invalid:
            raise RuntimeError("Invalid database objects remain after migration")
        if sql(counts, "rows-after") != state["rows_before"] or sql("select count(*) from objects where zone_instance_id<>0;", "legacy-identities") != "0":
            raise RuntimeError("Existing records changed unexpectedly during offline migration")
        state["pending"] = staged[-1].name
        save()
        sql(staged[-1].read_text(), "finalize")
        if sql("select version_number||':'||min_version_number from version_number;", "version-after") != "271:271":
            raise RuntimeError("Schema compatibility marker did not advance")
        state["completed"].append(staged[-1].name)
        state.pop("pending")
        if runtime.read_text() != before:
            raise RuntimeError("Runtime configuration changed during offline migration")
        shutil.copy2(runtime, folder / "runtime-before.cfg")
        runtime.write_text(after)
        state["passed"] = True
    except BaseException as error:
        state["failure"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        save()
    return state
