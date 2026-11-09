"""Explicit private-group/crew test activation with a separate durable journal.

Configuration alone cannot initialize missing history or authorize a transfer.
The caller must independently prove all fixture workers stopped before journal
maintenance and validate the full native/script package before activation.
"""
from pathlib import Path
import hashlib,re,stat
from private_crew_fixture import SCHEMA
from studio_tool_bundle import server_source

REPO=server_source()

MARKER='private-group-choices-fixture'
JOURNAL='/capacity-journal/private-departures'
NATIVE=(
    'src/engine/server/application/CentralServer/src/shared/PrivateDepartureJournal.h',
    'src/engine/server/application/CentralServer/src/shared/PrivateShipCrewJourney.h',
    'src/engine/server/application/CentralServer/src/shared/CentralServer_PrivateArrival.cpp',
    'src/engine/server/application/CentralServer/src/shared/CentralServer_PrivateResume.cpp',
    'src/engine/server/library/serverGame/src/shared/network/CentralConnection.cpp',
    'src/engine/server/library/serverGame/src/shared/network/CapacityPlayerWorld.h',
    'src/engine/server/library/serverGame/src/shared/object/GroupIdObserver.cpp',
    'src/engine/server/library/serverGame/src/shared/object/ServerObject.cpp',
    'src/engine/server/library/serverScript/src/shared/ScriptMethodsObjectMove.cpp')


def policy():
    return dict(schema_version=1,private_group_choices=True,independent_ticketed_crew=True,
                heroic_single_group=True,source_settlement_journal=JOURNAL,
                initialize_missing_history=False,canonical_release=False)


def supports(manifest):
    pins=manifest.get('native_sources') if type(manifest) is dict else None
    if type(pins) is not list:return False
    for name in NATIVE:
        found=[row for row in pins if type(row) is dict and row.get('path')==name]
        if len(found)!=1 or found[0].get('sha256')!=hashlib.sha256((REPO/name).read_bytes()).hexdigest():return False
    return True


def clear(text):
    pattern=r'(?ms)^# '+MARKER+r' begin\n.*?^# '+MARKER+r' end\n?'
    starts=len(re.findall(r'(?m)^# '+MARKER+r' begin$',text))
    ends=len(re.findall(r'(?m)^# '+MARKER+r' end$',text))
    if starts!=ends or starts>1 or len(re.findall(pattern,text))!=starts:
        raise ValueError('Malformed owned private-group fixture block')
    plain=re.sub(pattern,'',text)
    section=''
    for line in plain.splitlines():
        if line.strip().startswith('['):section=line.strip()
        key,sep,value=line.strip().partition('=')
        if sep and section in ('[CentralServer]','[GameServer]'):
            if key=='capacityPrivateDepartureJournal' or key=='capacityPrivateGroupChoiceEnabled' and value not in ('false','0'):
                raise ValueError('Private-group settings belong to an unknown configuration source')
    return plain


def configure(text,role,enabled,schema,private):
    if type(enabled) is not bool:raise ValueError('Typed private-group fixture opt-in required')
    plain=clear(text)
    if not enabled:return plain
    if schema!=SCHEMA or type(private) is not dict or private.get('private_player_admission') is not True or private.get('canonical_release') is not False:
        raise ValueError('Explicit retained-schema private-entry fixture required')
    if role not in ('central','game'):return plain
    target='[CentralServer]' if role=='central' else '[GameServer]'
    section='';settings={}
    for line in plain.splitlines():
        if line.strip().startswith('['):section=line.strip()
        key,sep,value=line.strip().partition('=')
        if sep:settings.setdefault((section,key),[]).append(value)
    for key in ('capacityPrivatePlayerAdmissionEnabled','capacityGroupTransferEnabled',
                'capacityEncounterLifecycleEnabled','capacityEncounterSaveEnabled'):
        if settings.get((target,key))!=['true']:raise ValueError('Coordinated private/lifecycle gate required: '+key)
    # A known default-off value is replaced only inside its native section.
    lines=[];section=''
    for line in plain.splitlines(keepends=True):
        if line.strip().startswith('['):section=line.strip()
        if section==target and re.match(r'^\s*capacityPrivateGroupChoiceEnabled\s*=',line):continue
        lines.append(line)
    extra='capacityPrivateDepartureJournal='+JOURNAL+'\n' if role=='central' else ''
    return ''.join(lines).rstrip()+'\n# '+MARKER+' begin\n'+target+'\ncapacityPrivateGroupChoiceEnabled=true\n'+extra+'# '+MARKER+' end\n'


def journal_source(stage,initialize):
    if type(initialize) is not bool:raise ValueError('Typed journal creation request required')
    stage=Path(stage)
    if (not stage.is_absolute() or str(stage).startswith('/mnt/') or stage.name!='runtime' or
            stage.parent.name!='client-ae80acb41011' or stage.parent.parent.name!='swg-cold-test-d9d6e6af' or
            stage.resolve(strict=True)!=stage):
        raise ValueError('Exact Linux-native retained SWG runtime required')
    parent=stage/'capacity-journal';source=parent/'private-departures'
    if parent.is_symlink() or source.is_symlink() or not parent.is_dir() or stat.S_IMODE(parent.stat().st_mode)!=0o700:
        raise ValueError('Existing private fixture journal parent required')
    if initialize:
        if source.exists():raise ValueError('Never replace or initialize existing private-source history')
    else:
        if not source.is_dir():raise ValueError('Existing durable private source journal required; never infer empty history')
        from fixture_journal_maintenance import verify_metadata
        verify_metadata(source.stat())
    return source


def journal_command(stage,overlay,image,initialize=False):
    """Fixed initialization/check only; caller holds the stopped-worker fence."""
    if not re.fullmatch(r'starwarsgalaxies/central:[A-Za-z0-9_.-]+',image):
        raise ValueError('Pinned SWG Central role image required')
    source=journal_source(stage,initialize)
    from fixture_journal_maintenance import runtime_mounts
    mounts=runtime_mounts(Path(overlay).resolve(strict=True))
    command=['docker','run','--rm','--pull','never','--network','none','--read-only','--user','0:0',
             '--security-opt','no-new-privileges:true']
    # First initialization uses the role image's ordinary default permissions,
    # like the existing encounter-journal setup; no capability is added. Later
    # checks bind only the existing server-owned leaf and drop all capabilities.
    if initialize:
        mounts+=['--volume',str(source.parent)+':/capacity-journal']
        option='--initialize-private-departures';target=JOURNAL
    else:
        command+=['--cap-drop','ALL'];mounts+=['--volume',str(source)+':/journal']
        option='--check-private-departures';target='/journal'
    script='export LD_LIBRARY_PATH=/maintenance/lib:/opt/whitengold/lib:$LD_LIBRARY_PATH; exec /maintenance/bin/instance-journal "$@"'
    return command+mounts+['--entrypoint','/bin/sh',image,'-ec',script,'private-swg-source-journal',option,target]
