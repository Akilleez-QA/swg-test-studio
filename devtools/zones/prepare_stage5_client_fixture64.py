#!/usr/bin/env python3
"""Prepare the existing copied-character fixture for Stage 5 client acceptance.

Uses a verified native/script overlay and existing images/database. All fixture
workers must be stopped. Canonical containers, selection and journals are excluded.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from prepare_client_fixture_schema import REPO, run, target_root
from disposable_database import validate
from configure import ROLES,NODES
from fixture_overlay import BOOT, GAME_BOOT, refresh, refresh_game
import runtime_policy
import hosted_public_fixture
import hosted_public_instances_fixture
import hosted_private_instances_fixture
import hoth_heroic_fixture
import private_crew_fixture
import private_group_fixture
sys.path.insert(0,str(REPO/'devtools/manage'))
from service import operation_lock, update_zone_config


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def encounter_bootstrap_config(text,enabled,initialize=False,automatic=False):
    if any(type(value) is not bool for value in (enabled,initialize,automatic)):
        raise ValueError('Typed encounter startup options required')
    if automatic and (not enabled or initialize) or initialize and not enabled:
        raise ValueError('Automatic encounter startup requires existing history and explicit bootstrap')
    text=re.sub(r'(?m)^capacityEncounter(?:BootstrapEnabled|AutomaticBootstrapEnabled|LeaseJournal|InitializeJournal)=.*\n?', '', text)
    if enabled:
        text+='\n[CentralServer]\ncapacityEncounterBootstrapEnabled=true\ncapacityEncounterLeaseJournal=/capacity-journal/encounters\n'
        text+='capacityEncounterInitializeJournal='+str(initialize).lower()+'\n'
        text+='capacityEncounterAutomaticBootstrapEnabled='+str(automatic).lower()+'\n'
    return text


def verify_source_inputs(manifest):
    script_root=REPO/'dsrc/sku.0/sys.server/compiled/game'
    expected=[(REPO,row['path'],row['sha256']) for row in manifest['native_sources']]
    expected += [(REPO,name,digest) for name,digest in manifest.get('maintenance_sources',{}).items()]
    inputs=manifest['script_inputs']
    expected += [(script_root,name,digest) for name,digest in inputs['sources'].items()]
    expected += [(script_root,row['source'],row['sha256']) for row in inputs['reconstructed'].values()]
    from source_input_verification import verify
    verify(expected)
    from capacity_wire_contract import verify as verify_capacity_wire
    verify_capacity_wire(manifest)


def inspect_project(project):
    ids=run(['docker','ps','-aq','--filter','label=com.docker.compose.project='+project]).split()
    return json.loads(run(['docker','inspect']+ids)) if ids else []


def central_debugger(compose,requested,distributed):
    """Explicit copied-fixture capability, preserved across fault maintenance."""
    if (not re.fullmatch('swg-cold-test-[a-f0-9]{8}',compose.get('name','')) or
            requested is not None and type(requested) is not bool or type(distributed) is not bool):
        raise ValueError('Typed copied-fixture debugger option required')
    service=compose['services']['central']
    caps={c.removeprefix('CAP_') for c in service.get('cap_add',[])}
    enabled=bool(caps) if requested is None else requested
    if service.get('privileged') or caps not in (set(),{'SYS_PTRACE'}) or enabled and not distributed:
        raise ValueError('Only the distributed copied Central may opt into SYS_PTRACE')
    if enabled:service['cap_add']=['SYS_PTRACE']
    else:service.pop('cap_add',None)
    return enabled



def encounter_lifecycle_config(text, enabled):
    """Enable both lifecycle peers' committed-save barrier only by explicit opt-in."""
    if type(enabled) is not bool:
        raise ValueError('Typed encounter lifecycle option required')
    text=re.sub(r'(?m)^capacityEncounter(?:LifecycleEnabled|SaveEnabled)=.*\n?', '', text)
    if enabled:
        for section in ('CentralServer','GameServer'):
            text+='\n['+section+']\ncapacityEncounterLifecycleEnabled=true\ncapacityEncounterSaveEnabled=true\n'
    return text


def stop(stage,project):
    compose=json.loads((stage/'compose.json').read_text())
    if compose.get('name')!=project or set(compose['services'])-(set(ROLES)|{'oracle','local_chat'}):
        raise ValueError('Exact SWG fixture deployment required before stopping')
    for row in inspect_project(project):
        labels=row['Config']['Labels']
        if labels.get('com.docker.compose.project')!=project or labels.get('com.docker.compose.service') not in compose['services']:
            raise ValueError('Unverified SWG fixture container ownership')
    command=['docker','compose','--project-name',project,'-f',str(stage/'compose.json')]
    # Central must stop before the supervisors, or it will recover the workers.
    run(command+['stop','--timeout','90','central'])
    compose=json.loads((stage/'compose.json').read_text())
    run(command+['stop','--timeout','90']+[name for name in compose['services'] if name not in ('central','oracle')])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--overlay',type=Path,required=True)
    parser.add_argument('--ord-capacity',type=int,default=2,help='small fixture budget for two-client demand growth')
    parser.add_argument('--rryatt-set-limit',type=int,default=80,help='trusted whole-set budget for the explicit Rryatt pilot')
    parser.add_argument('--occupied-retirement',action='store_true',help='explicit bounded linked-set/owned-ship evacuation pilot; requires distributed shutdown')
    parser.add_argument('--distributed-shutdown',action='store_true',help='explicit empty reviewed-world distributed shutdown pilot; automatic retirement requires a separate opt-in')
    parser.add_argument('--central-freeze-debugger',action=argparse.BooleanOptionalAction,default=None,
                        help='fixture-only SYS_PTRACE for exact Central freeze/commit fault gates; preserve when omitted, explicitly disable before measurements')
    parser.add_argument('--automatic-retirement',action='store_true',help='fixture-only Ord/Rryatt idle retirement pilot; requires a verified automatic-retirement overlay')
    parser.add_argument('--automatic-retirement-idle-ms',type=int,default=1500)
    parser.add_argument('--automatic-retirement-uptime-ms',type=int,default=1500)
    parser.add_argument('--automatic-retirement-cooldown-ms',type=int,default=0)
    parser.add_argument('--encounter-observations',action='store_true',help='fixture-only native object origin observations; no cleanup or retirement authority')
    parser.add_argument('--encounter-bootstrap',action='store_true',help='fixture-only native writer/journal bootstrap; no room grants')
    parser.add_argument('--automatic-encounter-bootstrap',action='store_true',help='bind existing encounter history automatically after current warm workers are ready; requires --encounter-bootstrap')
    parser.add_argument('--encounter-root-claims',action='store_true',help='opt-in native private-room starts, committed cleanup and restart recovery; requires bootstrap, observations and private MTP fixture')
    parser.add_argument('--initialize-encounter-journal',action='store_true',help='explicitly create a new empty private encounter journal directory; requires --encounter-bootstrap')
    parser.add_argument('--world-save-probes',action='store_true',help='enable operation-bound committed-prefix diagnostics; no quiescence or retirement permission')
    parser.add_argument('--rryatt-instances',action='store_true',help='schema-4 demand-created complete linked sets; requires --rryatt-groups and --kashyyyk')
    parser.add_argument('--rryatt-maximum-instances',type=int,default=2,help='explicit bounded complete-set count for the demand fixture')
    parser.add_argument('--rryatt-groups',action='store_true',help='enable reviewed runtime-zero public linked-set group/combat pilot; requires --kashyyyk')
    parser.add_argument('--start',action='store_true')
    parser.add_argument('--stop',action='store_true',help='stop only this fixture, Central first; keep Oracle')
    parser.add_argument('--kashyyyk',action='store_true',help='Stage 6 entry pilot: also preload main and linked Rryatt; no Kashyyyk autoscaling')
    parser.add_argument('--private-mtp',action='store_true',help='ordinary solo MTP owner/close fixture; also preload its original single Corellia exit')
    parser.add_argument('--existing-journals-only',action='store_true',help='reuse all provisioned native journals through direct mounts, without added container capabilities')
    parser.add_argument('--world-family',action='append',default=[],help='explicit eligible whole-world definition for isolated functional acceptance; repeat as needed')
    parser.add_argument('--world-capacity',type=int,default=2)
    parser.add_argument('--world-maximum-instances',type=int,default=2)
    parser.add_argument('--hosted-public',action='append',default=[],choices=('myyydril_caverns','nova_orion_station'),
                        help='explicit original-host public portal acceptance; does not enable extra host worlds')
    parser.add_argument('--hosted-public-limit',type=int,default=0,help='explicit finite per-room public fixture limit')
    parser.add_argument('--hosted-public-instances',action='store_true',help='explicit isolated public login/admission in complete positive Dungeon1/PoB hosts; not private-session admission or release approval')
    parser.add_argument('--hosted-public-instance-limit',type=int,default=0,help='finite per-room public limit for the positive-host fixture')
    parser.add_argument('--hosted-private-instances',action='store_true',help='explicit private-entry pilot on the existing complete positive public hosts; not canonical release approval')
    parser.add_argument('--private-crew-ships',action='store_true',help='explicit temporary owned-POB setup/cleanup for dedicated copied-fixture actors; does not enable group entry')
    parser.add_argument('--private-group-choices',action='store_true',help='explicit retained-fixture private group/independent crew admission with existing durable source history; not release activation')
    parser.add_argument('--heroic-group-tests',action='store_true',help='explicit retained-schema heroic entry prerequisites for saved live ejection tests; requires private group choices')
    parser.add_argument('--heroic-hoth-tests',action='store_true',help='explicit private-only Hoth host and original Dathomir return; actor setup retains recorded pilot-novice training when needed and restores temporary matching masters; requires the retained heroic/group fixture')
    parser.add_argument('--test-studio-recording',action='store_true',help='explicit fixture-only semantic recorder with a verified native contract and dedicated writable capture mount; leaves client/tools unchanged')
    parser.add_argument('--initialize-private-departures',action='store_true',help='explicit first creation of a new durable source journal; requires --private-group-choices and all fixture workers stopped')
    args=parser.parse_args()
    if args.start and args.stop:parser.error('Choose start or stop')
    if args.initialize_private_departures and not args.private_group_choices:
        parser.error('Private source journal creation requires the explicit private-group fixture')
    if args.heroic_group_tests and not args.private_group_choices:
        parser.error('Heroic group testing requires the explicit private-group fixture')
    if args.stop and args.private_group_choices:
        parser.error('Private-group preparation is separate from stopping the fixture')
    folder=args.folder.resolve(strict=True);root,_,volume=target_root(folder.parent)
    if not re.fullmatch('client-[a-f0-9]{12}',folder.name):parser.error('Verified copied-character folder required')
    stage=folder/'runtime';compose_path=stage/'compose.json'
    proof=json.loads((folder/'schema-report.json').read_text())
    compose=json.loads(compose_path.read_text());schema=proof.get('schema','')
    if not proof.get('passed') or not re.fullmatch('WGC_[A-F0-9]{12}',schema) or compose.get('name')!=root.name:
        parser.error('Wrong fixture project or copied-schema evidence')
    if any(value.get('name','').startswith('starwarsgalaxies_') for value in compose.get('volumes',{}).values()):
        parser.error('Canonical volumes prohibited')
    if args.stop:
        with operation_lock(REPO/'StarWarsGalaxies'):stop(stage,root.name)
        print(json.dumps({'fixture':root.name,'game_services_stopped':True,'oracle_preserved':True}));return
    if args.encounter_root_claims and not (args.encounter_bootstrap and args.encounter_observations and args.private_mtp):
        parser.error('Root claims require explicit bootstrap, native observations and the private MTP fixture')
    if args.automatic_encounter_bootstrap and (not args.encounter_bootstrap or args.initialize_encounter_journal):
        parser.error('Automatic startup requires explicit bootstrap and existing encounter history')
    overlay=args.overlay.resolve(strict=True)
    manifest=json.loads((overlay/'manifest.json').read_text())
    if str(overlay).startswith('/mnt/') or manifest.get('stage')!=(6 if args.kashyyyk else 5) or manifest.get('mode')!='cold_start_staged' or not manifest.get('native_sources') or not manifest.get('script_inputs'):
        parser.error('Complete verified Linux-native overlay matching the selected stage required')
    for name,row in manifest['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or sha(overlay/name)!=row['sha256']:parser.error('Overlay changed: '+name)
    try:verify_source_inputs(manifest)
    except ValueError as error:parser.error(str(error))
    if args.test_studio_recording:
        sys.path.insert(0,str(REPO/'devtools/teststudio_server'))
        from recording_fixture import supports as supports_recording
        if not supports_recording(manifest):parser.error('Matched Test Studio native/adapter contract required')
    if not 2<=args.ord_capacity<=16384:parser.error('Invalid fixture Ord budget')
    if args.occupied_retirement and (not args.distributed_shutdown or not manifest.get('stage7_occupied_retirement')):parser.error('Verified occupied-retirement overlay and distributed shutdown required')
    if args.distributed_shutdown and (not args.rryatt_instances or not manifest.get('stage7_distributed_shutdown')):parser.error('Verified distributed shutdown overlay and complete Rryatt demand pilot required')
    if args.automatic_retirement and (not args.distributed_shutdown or not manifest.get('stage7_automatic_retirement')):
        parser.error('Verified automatic-retirement overlay and distributed shutdown required')
    if args.automatic_retirement and (not 1000<=args.automatic_retirement_idle_ms<=86400000 or
                                      not 1000<=args.automatic_retirement_uptime_ms<=86400000 or
                                      not 0<=args.automatic_retirement_cooldown_ms<=86400000):
        parser.error('Invalid automatic-retirement fixture timing')
    if args.rryatt_instances and not args.rryatt_groups:parser.error('--rryatt-instances requires --rryatt-groups')
    if not 1<=args.rryatt_maximum_instances<=64:parser.error('Invalid bounded Rryatt instance count')
    if args.rryatt_groups and not args.kashyyyk:parser.error('--rryatt-groups requires --kashyyyk')
    if type(args.rryatt_set_limit) is not int or not 2<=args.rryatt_set_limit<=16384:parser.error('Invalid Rryatt set budget')
    if not args.rryatt_groups and args.rryatt_set_limit!=80:parser.error('Rryatt budget requires the explicit group pilot')
    selected=['tatooine','tutorial','dungeon1','space_npe_falcon','space_ord_mantell']
    if args.kashyyyk: selected += ['kashyyyk_main','kashyyyk_rryatt_trail']
    if args.private_mtp: selected.append('corellia')
    state={'schema_version':3,'mode':'npe_instances','maximum_instances':2,'ord_maximum_instances':2,
           'ord_capacity':args.ord_capacity,'public_world_capacity':1024,'growth_percent':50,'epoch':folder.name[7:]+'0'*20}
    if args.rryatt_instances:state.update(schema_version=4,rryatt_capacity=args.rryatt_set_limit,rryatt_maximum_instances=args.rryatt_maximum_instances,rryatt_growth_percent=75)
    if args.world_family:
        from world_family_fixture import extend,supports_worlds
        if not args.existing_journals_only or not supports_worlds(manifest):
            parser.error('World acceptance requires matching shared-world provenance and existing no-capability journal maintenance')
        try:state,selected=extend(state,selected,args.world_family,args.world_capacity,args.world_maximum_instances)
        except ValueError as error:parser.error(str(error))
    elif args.world_capacity!=2 or args.world_maximum_instances!=2:
        parser.error('World budgets require an explicit --world-family')
    public_policy=None
    if args.hosted_public:
        complete=manifest.get('hosted_complete',{})
        if (not args.world_family or not args.existing_journals_only or complete.get('schema_version')!=1 or
            complete.get('public_portal_families')!=2):
            parser.error('Public portals require matching complete-host provenance and explicit shared-world fixture policy')
        try:public_policy=hosted_public_fixture.policy(args.hosted_public,args.hosted_public_limit)
        except ValueError as error:parser.error(str(error))
        for public in public_policy['families']:
            if public['definition'] not in selected:selected.append(public['definition'])
        sources={'myyydril_caverns':'kashyyyk_dead_forest','nova_orion_station':'space_nova_orion'}
        if any(sources[f] not in args.world_family for f in args.hosted_public):
            parser.error('Public portal acceptance requires its explicitly selected original source world')
    elif args.hosted_public_limit:
        parser.error('Public room budget requires an explicit --hosted-public')
    public_instances_policy=None
    if args.hosted_public_instances:
        if args.hosted_public or not args.world_family or not args.existing_journals_only or not args.automatic_encounter_bootstrap:
            parser.error('Positive public hosts require separate explicit shared-world, existing-journal and automatic encounter policies')
        try:
            public_instances_policy=hosted_public_instances_fixture.policy(args.hosted_public_instance_limit)
            state=hosted_public_instances_fixture.configuration_state(state,public_instances_policy,args.world_family)
        except ValueError as error:parser.error(str(error))
        for definition in hosted_public_instances_fixture.additions({'hosted_public_instances_fixture':public_instances_policy}):
            if definition not in selected:selected.append(definition)
    elif args.hosted_public_instance_limit:
        parser.error('Positive public room limit requires --hosted-public-instances')
    private_instances_policy=None
    if args.hosted_private_instances:
        if (schema!='WGC_AE80ACB41011' or not args.hosted_public_instances or not args.private_mtp or not args.encounter_root_claims or
                not args.automatic_encounter_bootstrap or not args.existing_journals_only or args.central_freeze_debugger is not False):
            parser.error('Private pilot requires explicit positive public hosts, MTP, committed root lifecycle, automatic bootstrap, existing journals and --no-central-freeze-debugger')
        if not hosted_private_instances_fixture.supports(manifest):
            parser.error('Current compiled private arrival, recovery and unload-fence provenance required')
        try:private_instances_policy=hosted_private_instances_fixture.policy(public_instances_policy)
        except ValueError as error:parser.error(str(error))
    if args.private_crew_ships and (schema!=private_crew_fixture.SCHEMA or not private_instances_policy):
        parser.error('POB setup requires the explicit retained-schema private-entry fixture')
    if args.private_group_choices and (not private_instances_policy or schema!=private_crew_fixture.SCHEMA or
                                      not private_group_fixture.supports(manifest)):
        parser.error('Private-group fixture requires coordinated private entry and current durable/crew/publication native provenance')
    hoth_policy=None
    if args.heroic_hoth_tests:
        if not args.heroic_group_tests or not args.private_group_choices or not private_instances_policy or not hoth_heroic_fixture.supports(manifest):
            parser.error('Hoth requires current mixed-area native provenance and explicit heroic/private/group fixture')
        hoth_policy=hoth_heroic_fixture.policy()
        for definition in hoth_heroic_fixture.additions({'hoth_heroic_fixture':hoth_policy}):
            if definition not in selected:selected.append(definition)
    runtime_policy.validate_state(state)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    os.umask(0o077)
    with operation_lock(REPO/'StarWarsGalaxies'):
        containers=inspect_project(root.name)
        oracle=next((r for r in containers if r['Config']['Labels'].get('com.docker.compose.service')=='oracle'),None)
        if not oracle:parser.error('Existing fixture Oracle required; no replacement provisioning')
        validate(oracle,root,volume)
        for row in containers:
            role=row['Config']['Labels'].get('com.docker.compose.service');status=row['State']
            if role not in compose['services']:parser.error('Unknown fixture supervisor')
            if role!='oracle' and (status.get('Running') is not False or status.get('Paused') or status.get('Restarting') or status.get('Pid')!=0 or status.get('Status') not in ('created','exited')):
                parser.error('Every fixture worker must be stopped: '+role)
        for role in ROLES:
            if compose['services'][role]['image']!=manifest['roles'][role]['image'] or run(['docker','image','inspect',compose['services'][role]['image'],'--format','{{.Id}}'])!=manifest['roles'][role]['base_id']:
                parser.error('Pinned role image changed: '+role)
        sql="""set echo off verify off heading off feedback off pagesize 0 linesize 32767
whenever oserror exit failure
whenever sqlerror exit failure
alter session set container=FREEPDB1;
select json_object('sessions' value (select count(*) from v$session where username='%s'),
 'transactions' value (select count(*) from v$transaction),
 'recovering' value (select count(*) from v$fast_start_transactions)) from dual;
exit;
"""%schema
        result=subprocess.run(['docker','exec','-i','--user','oracle',oracle['Name'].lstrip('/'),'sqlplus','-s','/ as sysdba'],input=sql,text=True,capture_output=True,check=True,timeout=60)
        idle=json.loads(result.stdout.strip())
        if any(type(v) is not int or v for v in idle.values()):parser.error('Fixture Oracle still has game sessions or transactions')
        if args.existing_journals_only:
            import fixture_journal_maintenance
            for path in fixture_journal_maintenance.ROOTS:
                fixture_journal_maintenance.verify_root(stage,path)
        archive=stage/'stage5-runs'/stamp;archive.mkdir(parents=True,mode=0o700)
        shutil.copy2(compose_path,archive/'compose.before.json');shutil.copytree(stage/'config',archive/'config.before')
        debugger_enabled=central_debugger(compose,args.central_freeze_debugger,args.distributed_shutdown)
        for name in ('zones.txt','report.json','stage5-report.json'):
            if (stage/name).is_file():shutil.copy2(stage/name,archive/(name+'.before'))
        configs={}
        for role in ROLES:
            config=stage/'config'/(role+'.cfg')
            # Replace the complete fixture selection so a prior acceptance batch
            # cannot leave extra hot worlds behind. Preserve all other sections.
            text=update_zone_config(hosted_private_instances_fixture.disabled(hosted_public_instances_fixture.clear(hosted_public_fixture.clear(hoth_heroic_fixture.clear(config.read_text())))),selected,role=='game')
            configs[config]=runtime_policy.config(text,role,state,selected)
            if public_policy and role in ('central','game'):
                configs[config]=hosted_public_fixture.configure(configs[config],role,public_policy)
            if public_instances_policy and role in ('central','game','database'):
                configs[config]=hosted_public_instances_fixture.configure(configs[config],role,public_instances_policy)
            configs[config]=re.sub(r'(?m)^capacityWorldSaveProbeEnabled=.*\n?', '', configs[config])
            configs[config]=re.sub(r'(?m)^(?:capacityOccupiedRetirementEnabled|capacityDistributedShutdownEnabled|capacityAutomaticRetirement(?:Enabled|IdleMs|UptimeMs|CooldownMs|Utilization|Headroom)|capacityWorkerFreezeEnabled|capacityLaunchFenceEnabled|capacityLaunchFenceRoot|capacityShutdownNode)=.*\n?', '', configs[config])
            if args.distributed_shutdown:
                nodes=re.findall(r'(?m)^node([0-9]+)=([^\s]+)$',text)
                if [int(n) for n,_ in nodes]!=list(range(len(NODES))):parser.error('Complete exact fixture supervisor topology required')
                configs[config]+='\n[CentralServer]\ncapacityDistributedShutdownEnabled=true\n'+''.join('capacityShutdownNode=node'+n+'\n' for n,_ in nodes)
                configs[config]+='[GameServer]\ncapacityWorkerFreezeEnabled=true\n'
                if role in NODES:
                    node='node'+str(NODES.index(role));fences=stage/'capacity-journal'/'launch-fences'/node
                    if not fences.parent.exists():fences.parent.mkdir(mode=0o700)
                    if not fences.exists():fences.mkdir(mode=0o700)
                    if fences.is_symlink() or not fences.is_dir():parser.error('Private supervisor fence directory required')
                    configs[config]=re.sub(r'(?m)^restartCentral=.*\n?', '', configs[config])
                    configs[config]+='[TaskManager]\nrestartCentral=false\ncapacityDistributedShutdownEnabled=true\ncapacityLaunchFenceEnabled=true\ncapacityLaunchFenceRoot=/world-launch-fences\n'
            if args.occupied_retirement:
                configs[config]+='\n[CentralServer]\ncapacityOccupiedRetirementEnabled=true\n'
            if args.automatic_retirement:
                configs[config]+=('\n[CentralServer]\ncapacityAutomaticRetirementEnabled=true\n'
                                  f'capacityAutomaticRetirementIdleMs={args.automatic_retirement_idle_ms}\n'
                                  f'capacityAutomaticRetirementUptimeMs={args.automatic_retirement_uptime_ms}\n'
                                  f'capacityAutomaticRetirementCooldownMs={args.automatic_retirement_cooldown_ms}\n')
            if args.world_save_probes:
                configs[config]+='\n[CentralServer]\ncapacityWorldSaveProbeEnabled=true\n[GameServer]\ncapacityWorldSaveProbeEnabled=true\n'
            configs[config]=re.sub(r'(?m)^capacityEncounterObservationEnabled=.*\n?', '', configs[config])
            if args.encounter_observations:
                configs[config]+='\n[GameServer]\ncapacityEncounterObservationEnabled=true\n'
            configs[config]=encounter_bootstrap_config(configs[config],args.encounter_bootstrap and role=='central',
                args.initialize_encounter_journal and role=='central',args.automatic_encounter_bootstrap and role=='central')
            configs[config]=re.sub(r'(?m)^capacityPrivateMtpFixture=.*\n?', '', configs[config])
            configs[config]=encounter_lifecycle_config(configs[config],args.encounter_root_claims)
            if args.private_mtp: configs[config]+='\n[GameServer]\ncapacityPrivateMtpFixture=1\n'

            if not args.rryatt_instances:
                configs[config]=re.sub(r'(?m)^capacityRryatt(?:GroupEnabled|InstancesEnabled|SetLimit)=.*\n?', '', configs[config])
                configs[config]=re.sub(r'(?m)^capacityGroupWorldLimit="?kashyyyk_rryatt_trail .*\n?', '', configs[config])
            if args.rryatt_groups and not args.rryatt_instances:
                configs[config]+=f'\n[CentralServer]\ncapacityRryattGroupEnabled=true\ncapacityGroupWorldLimit="kashyyyk_rryatt_trail 1024"\n[GameServer]\ncapacityRryattGroupEnabled=true\ncapacityRryattSetLimit={args.rryatt_set_limit}\n'

            if private_instances_policy and role in ('central','game'):
                configs[config]=hosted_private_instances_fixture.configure(configs[config],role,private_instances_policy,public_instances_policy)
            configs[config]=private_crew_fixture.configure(configs[config],role,args.private_crew_ships,schema,private_instances_policy)
            configs[config]=private_group_fixture.configure(configs[config],role,args.private_group_choices,schema,private_instances_policy)
            if args.heroic_group_tests and role=='game':
                configs[config]+='\n[GameServer]\ncapacityHeroicGroupFixture=1\n'
            if hoth_policy:
                configs[config]=hoth_heroic_fixture.configure(configs[config],role,hoth_policy)
            if role=='game':
                sys.path.insert(0,str(REPO/'devtools/teststudio_server'))
                import recording_fixture
                configs[config]=recording_fixture.configure(configs[config],args.test_studio_recording)
                recording_fixture.mount(compose['services'][role],folder,args.test_studio_recording)

            service=compose['services'][role]
            service['volumes']=[v for v in service.get('volumes',[]) if not (isinstance(v,str) and (v.endswith(':/overlay:ro') or v.endswith(':/world-launch-fences')))]+[str(overlay)+':/overlay:ro']
            if args.distributed_shutdown and role in NODES:service['volumes'].append(str(stage/'capacity-journal'/'launch-fences'/('node'+str(NODES.index(role))))+':/world-launch-fences')
            if service.get('entrypoint'):
                entry=service['entrypoint']
                if role=='game':refresh_game(entry)
                else:refresh(entry)
            else:
                metadata=json.loads(run(['docker','image','inspect',service['image']]))[0]['Config']
                entry=metadata.get('Entrypoint')
                if not entry:parser.error('Missing native role entrypoint')
                service['entrypoint']=['/bin/sh','-ec',GAME_BOOT if role=='game' else BOOT,'stage5-overlay']+entry
        if args.initialize_encounter_journal and not args.encounter_bootstrap:
            raise ValueError('Encounter journal creation requires the explicit bootstrap profile')
        if args.encounter_bootstrap:
            parent=stage/'capacity-journal';directory=parent/'encounters'
            if not parent.is_dir() or parent.is_symlink() or directory.is_symlink():
                raise ValueError('Existing owned capacity journal parent required')
            if args.initialize_encounter_journal:
                if directory.exists():raise ValueError('Encounter journal directory already exists; use existing-only bootstrap')
                run(['docker','run','--rm','--pull','never','--network','none','--read-only',
                     '--volume',str(parent)+':/capacity-journal','--entrypoint','/usr/bin/install',
                     manifest['roles']['central']['image'],'-d','-m','700','/capacity-journal/encounters'])
            elif not directory.is_dir():
                raise ValueError('Existing encounter journal directory required; never infer empty history')
        if args.private_group_choices:
            # The operation lock, exact container/image checks, stopped workers
            # and idle Oracle were proved above. Never infer empty history from
            # a missing/corrupt journal or acknowledge an existing settlement.
            argv=private_group_fixture.journal_command(stage,overlay,manifest['roles']['central']['image'],args.initialize_private_departures)
            result=subprocess.run(argv,text=True,capture_output=True)
            name='private-departures-initialize.txt' if args.initialize_private_departures else 'private-departures-check.txt'
            (archive/name).write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError('Private source journal verification failed; game services remain stopped; see '+str(archive/name))
        for config,text in configs.items():config.write_text(text)
        (stage/'zones.txt').write_text('\n'.join(selected)+'\n')
        compose_path.write_text(json.dumps(compose,indent=2)+'\n')
        def journal(option,path,*definitions):
            if args.existing_journals_only:
                argv=fixture_journal_maintenance.command(stage,path,option,definitions,overlay,manifest['roles']['central']['image'])
                result=subprocess.run(argv,text=True,capture_output=True)
                (archive/(option[2:]+'.txt')).write_text(result.stdout+result.stderr)
                if result.returncode:raise RuntimeError('Existing journal acknowledgement failed; game services remain stopped; see '+str(archive/(option[2:]+'.txt')))
                return
            mount='capacity-journal' if path.startswith('/capacity-journal/') else 'login-journal'
            if not (stage/mount).is_dir():raise ValueError('Existing fixture journal missing')
            script='export LD_LIBRARY_PATH=/overlay/lib:/opt/whitengold/lib:$LD_LIBRARY_PATH; exec /overlay/bin/instance-journal "$@"'
            # Fixture parent directories belong to the WSL user; their private
            # native children belong to the server UID. Permit traversal without
            # changing either owner/mode or broadening the canonical utility.
            argv=['docker','run','--rm','--pull','never','--network','none','--read-only','--cap-drop','ALL','--cap-add','DAC_OVERRIDE','--security-opt','no-new-privileges:true',
                  '--volume',str(overlay)+':/overlay:ro','--volume',str(stage/mount)+':/'+mount,'--entrypoint','/bin/sh',manifest['roles']['central']['image'],
                  '-ec',script,'stage5-journal',option,path]+list(definitions)
            output=run(argv);(archive/(option[2:]+'.txt')).write_text(output+'\n')
        journal('--acknowledge-stopped','/capacity-journal/instances',*state_definitions(state))
        journal('--acknowledge-login-stopped','/login-journal/records')
        # First Stage 5 activation explicitly provisions two new private logs.
        # Later proven stops acknowledge them and retain complete descriptors.
        for name,initial,ack in (('admission','--initialize-admission','--acknowledge-admission-stopped'),
                                ('family-logins','--initialize-family-logins','--acknowledge-family-logins-stopped')):
            exists=args.existing_journals_only or subprocess.run(['docker','run','--rm','--pull','never','--network','none','--read-only','--volume',str(stage/'capacity-journal')+':/capacity-journal:ro',
                '--entrypoint','/usr/bin/test',manifest['roles']['central']['image'],'-e','/capacity-journal/'+name],capture_output=True).returncode==0
            journal(ack if exists else initial,'/capacity-journal/'+name)
        report={'schema_version':1,'stage':5,'prepared_utc':stamp,'project':root.name,'schema':schema,'overlay':str(overlay),
                'central_freeze_debugger':debugger_enabled,
                'existing_journals_only':args.existing_journals_only,
                'automatic_encounter_bootstrap':args.automatic_encounter_bootstrap,
                'whole_world_families':sorted(args.world_family),
                'hosted_public_fixture':public_policy,
                'hosted_public_instances_fixture':public_instances_policy,
                'hosted_private_instances_fixture':private_instances_policy,
                'private_crew_ship_fixture':private_crew_fixture.policy() if args.private_crew_ships else None,
                'private_group_fixture':private_group_fixture.policy() if args.private_group_choices else None,
                'heroic_group_fixture':args.heroic_group_tests,
                'test_studio_recording':args.test_studio_recording,
                'test_studio_action_capture':1 if args.test_studio_recording else 0,
                'hoth_heroic_fixture':hoth_policy,
                'overlay_manifest_sha256':sha(overlay/'manifest.json'),'policy':state,'selected':selected,'archive':str(archive),
                'stop_proof':[r['Id'] for r in containers if r is not oracle],'oracle_idle':idle,'images_created':0,'canonical_changed':False,'client_acceptance':'pending',
                'private_mtp_pilot':args.private_mtp,'encounter_observations':args.encounter_observations,'encounter_root_claims':args.encounter_root_claims,
                'rryatt_set_limit':args.rryatt_set_limit if args.rryatt_groups else 0,'rryatt_public_group_pilot':args.rryatt_groups,'kashyyyk_entry_pilot':args.kashyyyk,'kashyyyk_automatic_growth':args.rryatt_instances,'rryatt_demand_instances':args.rryatt_instances,'world_save_probes':args.world_save_probes,'distributed_shutdown':args.distributed_shutdown,'occupied_retirement':args.occupied_retirement,'automatic_retirement':args.automatic_retirement,'automatic_retirement_idle_ms':args.automatic_retirement_idle_ms if args.automatic_retirement else 0,'automatic_retirement_uptime_ms':args.automatic_retirement_uptime_ms if args.automatic_retirement else 0,'automatic_retirement_cooldown_ms':args.automatic_retirement_cooldown_ms if args.automatic_retirement else 0,'shutdown_nodes':['node'+str(i) for i in range(len(NODES))] if args.distributed_shutdown else []}
        (stage/'stage5-report.json').write_text(json.dumps(report,indent=2)+'\n')
        if args.start:
            command=['docker','compose','--project-name',root.name,'-f',str(compose_path)]
            try:run(command+['up','-d','--no-build','--force-recreate']+[name for name in compose['services'] if name!='oracle'])
            except Exception:
                stop(stage,root.name)
                raise
        print(json.dumps({'prepared':True,'project':root.name,'started':args.start,'report':str(stage/'stage5-report.json'),
                          'overlay_manifest_sha256':report['overlay_manifest_sha256'],'canonical_changed':False,'images_created':0}))


def state_definitions(state):
    # A later batch can deselect a previously tested world. Keep the exact
    # canonical decoding catalog, while only state policies can launch worlds.
    runtime_policy.validate_state(state)
    from instance_scope import load as family_scope
    original=[runtime_policy.FALCON,runtime_policy.ORD,"kashyyyk_rryatt_trail"]
    known={row['definition'] for row in family_scope()['definitions']}
    return original+sorted(known-set(original))


if __name__=='__main__':main()
