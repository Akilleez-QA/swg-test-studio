#!/usr/bin/env python3
"""Lose copied-fixture Central at a held distributed shutdown boundary."""
import argparse,contextlib,hashlib,json,math,re,secrets,shutil,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
from protocol_driver import fixture,identity,run,unloaded,operation_lock,REPO
from protocol_preservation import snapshot
from protocol_test_sets import runtime_artifact
from retirement_fault_recovery import invoke,needs_baseline_restart
from retirement_live_fault import FAMILIES,fresh_sample,target as worker_target
from retirement_fault_targets import service_target
from retirement_fault_boundary import boundary,number
from configure import NODES
from inspect_client_fixture import native_snapshots,rows
from central_loss_recovery import CentralLossReceipt,dead_central
import protocol_fixture_restart


HOLDS={'fencing':'taskmanager','authorizing':'database','freezing':'database','committing':'database','stopping_games':'database','stopping_planet':'database'}
SECONDARY_HOLDS={'freezing':'game','committing':'game','stopping_games':'game','stopping_planet':'planet'}
WORKER_HOLDS=('freezing','committing')
PHASE_ORDER=('fencing','authorizing','freezing','committing','stopping_games','stopping_planet')


def freeze_breakpoint_script(target,expected,remote,line):
    """Stop at the real freeze dispatch, after native authorization/freshness."""
    if (target.get('role')!='central' or not re.fullmatch('swg-cold-test-[a-f0-9]{8}-central-1',target.get('container','')) or
            not re.fullmatch('[1-9][0-9]{0,9}',target.get('pid','')) or
            not re.fullmatch('[1-9][0-9]{0,19}',target.get('start_ticks','')) or
            not re.fullmatch('/tmp/central-loss-[a-zA-Z0-9-]+',remote) or type(line) is not int or not 1<=line<=2000):
        raise ValueError('Exact fixture debugger scope required')
    for key in ('instance','generation','operation'):number(expected[key],9223372036854775807)
    if expected.get('definition') not in FAMILIES.values():raise ValueError('Reviewed world required')
    # Recheck /proc on both sides of attach. Never continue a different process.
    check=("assert os.readlink('/proc/%s/exe') == '/opt/whitengold/bin/CentralServer'; "
           "assert open('/proc/%s/stat').read().rsplit(') ',1)[1].split()[19] == '%s'")%(target['pid'],target['pid'],target['start_ticks'])
    return ('set pagination off\nset confirm off\nset auto-load off\nset print thread-events off\n'
            'python\nimport os,gdb\n'+check+'\ngdb.execute("attach '+target['pid']+'")\ntry:\n '+check+
            '\nexcept BaseException:\n gdb.execute("detach")\n raise\nend\n'
            'tbreak CentralServer_WorldShutdown.cpp:'+str(line)+'\necho FIXTURE_FREEZE_ARMED\\n\npython gdb.flush(gdb.STDOUT)\ncontinue\n'
            'printf "FIXTURE_FREEZE_HIT world=%llu generation=%llu operation=%llu phase=%d\\n", '
            'op.request.key.world, op.request.key.generation, op.request.key.operation, op.phase\npython gdb.flush(gdb.STDOUT)\n'
            "shell timeout 10 sh -c 'while test ! -f "+remote+"/release-debugger; do sleep 0.05; done'\ndetach\nquit\n")


def debugger_container(meta,target,project):
    labels=meta['Config']['Labels']
    if (meta['Id']!=target['container_id'] or meta['Image']!=target['image_id'] or
            labels.get('com.docker.compose.project')!=project or labels.get('com.docker.compose.service')!='central' or
            not re.fullmatch('WGC_[A-F0-9]{12}',labels.get('whitengold.test.client','')) or
            meta['HostConfig'].get('Privileged') or {c.removeprefix('CAP_') for c in (meta['HostConfig'].get('CapAdd') or [])}!={'SYS_PTRACE'}):
        raise ValueError('Exact copied Central with explicit debugger capability required')


class FreezeBreakpoint:
    """Fixture-only debugger; native workers keep answering until freeze dispatch."""
    def __init__(self,project,target,expected,remote,output,manifest):
        if not re.fullmatch('swg-cold-test-[a-f0-9]{8}',project):raise ValueError('Copied fixture debugger required')
        freeze_breakpoint_script(target,expected,remote,1)
        self.target=target;self.remote=remote;self.output=output;self.process=None
        self.container=target['container'];self.log=output/'freeze-debugger.log';self.stream=None
        if project+'-central-1'!=self.container:raise ValueError('Debugger project mismatch')
        meta=json.loads(run(['docker','inspect',self.container]))[0]
        debugger_container(meta,target,project)
        source=REPO/'src/engine/server/application/CentralServer/src/shared/CentralServer_WorldShutdown.cpp'
        if not any(r['path']==str(source.relative_to(REPO)) and r['sha256']==hashlib.sha256(source.read_bytes()).hexdigest() for r in manifest['native_sources']):
            raise ValueError('Debugger source differs from accepted native build')
        lines=source.read_text().splitlines()
        marks=[i+2 for i,l in enumerate(lines) if 'op.phase=WorldShutdownOperation::Freezing;' in l]
        if len(marks)!=1 or 'for(unsigned int n=' not in lines[marks[0]-1]:raise ValueError('Exact freeze dispatch source line required')
        script=freeze_breakpoint_script(target,expected,remote,marks[0]);(output/'freezing.gdb').write_text(script)
        cache=output/'debugger';cache.mkdir();(cache/'lib').mkdir();(cache/'python/lib').mkdir(parents=True)
        gdb=Path('/usr/bin/gdb')
        if gdb.read_bytes()[:6]!=b'\x7fELF\x02\x01':raise ValueError('ELF64 debugger required')
        shutil.copy2(gdb,cache/'gdb')
        libs=re.findall(r'(?:=> )?(/[a-zA-Z0-9_./+-]+)',subprocess.check_output(['ldd',str(gdb)],text=True))
        if not libs:raise ValueError('Debugger dependencies unavailable')
        for name in sorted(set(libs)):shutil.copy2(Path(name).resolve(strict=True),cache/'lib'/Path(name).name)
        shutil.copytree('/usr/lib/python3.12',cache/'python/lib/python3.12',ignore=shutil.ignore_patterns('__pycache__','test','tests','site-packages'))
        shutil.copytree('/usr/share/gdb',cache/'share')
        self.evidence=dict(source_line=marks[0],script_sha256=hashlib.sha256(script.encode()).hexdigest(),
            files={str(p.relative_to(cache)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(cache.rglob('*')) if p.is_file()})
        run(['docker','cp',str(cache),self.container+':'+remote+'/debugger'])
        run(['docker','cp',str(output/'freezing.gdb'),self.container+':'+remote+'/freezing.gdb'])
    def start(self):
        self.stream=self.log.open('x')
        self.process=subprocess.Popen(['docker','exec','-e','LD_LIBRARY_PATH='+self.remote+'/debugger/lib',
            '-e','PYTHONHOME='+self.remote+'/debugger/python','-e','PYTHONNOUSERSITE=1',self.container,self.remote+'/debugger/gdb',
            '--data-directory='+self.remote+'/debugger/share','-nx','-nh','-batch','-x',self.remote+'/freezing.gdb'],
            stdout=self.stream,stderr=subprocess.STDOUT)
        self.wait('FIXTURE_FREEZE_ARMED',15)
    def wait(self,token,timeout):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            text=self.log.read_text(errors='replace')
            if token in text:return
            if self.process.poll() is not None:raise RuntimeError('Fixture debugger exited before '+token)
            time.sleep(.05)
        raise TimeoutError('Fixture debugger did not reach '+token)
    def hit(self,expected):
        self.wait('FIXTURE_FREEZE_HIT',25)
        token='FIXTURE_FREEZE_HIT world={instance} generation={generation} operation={operation} phase=3'.format(**expected)
        if token not in self.log.read_text():raise RuntimeError('Debugger reached a different native operation')
    def release(self):
        run(['docker','exec',self.container,'touch',self.remote+'/release-debugger'])
        if self.process is not None:
            self.process.wait(timeout=15)
            if self.process.returncode:raise RuntimeError('Fixture debugger failed; inspect retained log')
        if self.stream:self.stream.close();self.stream=None


def signal(project,target,binary,mode):
    role=target['role']
    if (not re.fullmatch('swg-cold-test-[a-f0-9]{8}',project) or role not in ('central','taskmanager','database','game','planet') or
            target['container']!=project+'-'+role+'-1' or target.get('kind') not in (None,'worker') or
            mode not in (('--kill','--check') if role=='central' else ('--stop','--continue','--check','--kill'))):
        raise ValueError('Exact retained fixture signal scope required')
    argv=['docker','exec',target['container'],binary,target['pid'],target['start_ticks']]
    if target.get('kind')=='worker':
        if role!='game' or mode=='--kill' or target.get('scene') not in FAMILIES.values():raise ValueError('Exact reviewed worker pause required')
        for key in ('world','generation'):number(target[key],9223372036854775807)
        return run(argv+[target['scene'],target['world'],'game',mode])
    if role!='central':argv+=[{'taskmanager':'coordinator','database':'database','game':'game-supervisor','planet':'planet-supervisor'}[role]]
    argv+=[mode]
    return run(argv)


def observe_worker(project,schema,services,manifest,expected):
    digest=manifest['files']['bin/SwgGameServer']['sha256']
    found=worker_target(project,expected['definition'],expected['instance'],expected['generation'],'game',digest)
    meta=services['game'];labels=meta.get('Config',{}).get('Labels') or {}
    if (found['container_id']!=meta['Id'] or found['image_id']!=meta['Image'] or
            labels.get('whitengold.test.client')!=schema or labels.get('com.docker.compose.project')!=project or
            labels.get('com.docker.compose.service')!='game'):
        raise RuntimeError('Exact captured fixture worker container required')
    return dict(found,container=project+'-game-1',kind='worker')


def held_service(target,query=run):
    if (target.get('role') not in set(HOLDS.values())|set(SECONDARY_HOLDS.values()) or
            not re.fullmatch('swg-cold-test-[a-f0-9]{8}-'+target['role']+'-1',target.get('container','')) or
            not re.fullmatch('[1-9][0-9]{0,9}',target.get('pid','')) or
            not re.fullmatch('[1-9][0-9]{0,19}',target.get('start_ticks',''))):
        raise ValueError('Exact fixture hold identity required')
    stat=query(['docker','exec',target['container'],'cat','/proc/'+target['pid']+'/stat'])
    fields=stat.rsplit(') ',1)[-1].split()
    if (not stat.startswith(target['pid']+' (') or len(fields)<20 or
            fields[0]!='T' or fields[19]!=target['start_ticks']):
        raise RuntimeError('Held service is not stopped at the captured identity')


def await_boundary(query,expected,phase,nodes,observations,clock=time.monotonic,pause=time.sleep,on_match=None):
    if phase not in HOLDS:raise ValueError('Only implemented Central-loss boundaries are allowed')
    started=last=clock()
    while True:
        now=clock()
        if not math.isfinite(now) or now<last or now-started>25:raise TimeoutError('Exact held retirement boundary was not observed')
        last=now
        values=rows(query('capacityRetireStatus'))
        if len(values)!=1:raise RuntimeError('Exact single active shutdown required')
        row=values[0]
        if not observations or observations[-1]!=row:observations.append(row)
        if row.get('state') in PHASE_ORDER and PHASE_ORDER.index(row['state'])<PHASE_ORDER.index(phase):
            boundary(row,expected,row['state'],nodes)
            pause(.1)
            continue
        observed=boundary(row,expected,phase,nodes)
        if phase=='fencing' and observed['fenced_nodes']!='0':
            raise RuntimeError('Paused coordinator did not hold before fence receipts')
        if on_match:on_match(observed)
        return observed


def launch_markers(project,roles,expected,query=run):
    if (not re.fullmatch('swg-cold-test-[a-f0-9]{8}',project) or set(roles)!=set(NODES) or
            expected.get('definition') not in FAMILIES.values()):
        raise ValueError('Exact fixture supervisor roster and reviewed world required')
    for key in ('instance','generation','operation'):number(expected[key],9223372036854775807)
    filename=expected['definition']+'-'+expected['instance']+'-'+expected['generation']+'.fence'
    proof={}
    for role in NODES:
        token=query(['docker','exec',project+'-'+role+'-1','cat','/world-launch-fences/'+filename])
        if token!=expected['operation']:raise RuntimeError('Old generation launch fence is absent or changed')
        proof[role]=token
    return proof


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('folder','binary','overlay','jdk','console','retirement-console'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--family',choices=tuple(FAMILIES),required=True);p.add_argument('--bots',nargs=2,required=True)
    p.add_argument('--boundary',choices=tuple(HOLDS),default='fencing')
    p.add_argument('--fault-service',choices=('central','database','coordinator','game-supervisor','planet-supervisor'),default='central')
    args=p.parse_args()
    if args.fault_service=='database' and args.boundary!='authorizing':
        p.error('Database loss is reviewed at the authorizing boundary only')
    if args.fault_service=='coordinator' and args.boundary!='fencing':
        p.error('Coordinator loss is reviewed at the fencing boundary only')
    if (args.fault_service=='game-supervisor' and args.boundary!='stopping_games' or
        args.fault_service=='planet-supervisor' and args.boundary!='stopping_planet'):
        p.error('Supervisor loss requires its exact distributed stop boundary')
    if len(set(args.bots))!=2 or any(not re.fullmatch('[a-z]{3,16}',b) for b in args.bots):p.error('Two distinct dedicated bots required')
    project,schema,services=fixture(args.folder);base=args.folder.resolve()/'protocol-driver'
    bots=[identity(json.loads((base/(b+'.json')).read_text())) for b in args.bots]
    for bot in bots:unloaded(project,bot)
    original=snapshot(project,schema)
    output=base/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+args.fault_service+'-loss-'+args.family+'-'+secrets.token_hex(3));output.mkdir(mode=0o700)
    report=dict(schema_version=1,project=project,schema=schema,family=args.family,boundary=args.boundary,
        fault_service=args.fault_service,passed=False,
        fully_unloaded=False,created_images=0,created_databases=0,client_source_changed=False,visual_gameplay_verified=False,steps=[],signals=[])
    common=['--folder',str(args.folder),'--binary',str(args.binary),'--bots',*args.bots]
    restart=['--folder',str(args.folder),'--overlay',str(args.overlay),'--jdk',str(args.jdk),'--console',str(args.console),
        '--rryatt','--distributed-shutdown','--retirement-console',str(args.retirement_console),'--bots',*args.bots]
    query=lambda command:run(['docker','exec',project+'-central-1','/fixture/protocol-bot-console','127.0.0.1',command])
    try:
        stage=json.loads((args.folder/'runtime/stage5-report.json').read_text())
        if stage.get('occupied_retirement') or not stage.get('distributed_shutdown') or (stage['policy']['rryatt_capacity'],stage['policy']['ord_capacity'])!=(2,2):
            raise RuntimeError('Standard two-seat distributed fixture required')
        instances=native_snapshots(query)[1]
        report['baseline_families']={scene:needs_baseline_restart(instances,scene) for scene in FAMILIES.values()}
        if any(report['baseline_families'].values()):
            step,baseline=invoke([sys.executable,'devtools/zones/protocol_fixture_restart.py',*restart],output/'baseline-restart.log',args.folder)
            report['steps'].append(step)
            if not baseline.get('distributed_shutdown_preserved'):raise RuntimeError('Baseline lost shutdown policy')
        step,prepared=invoke([sys.executable,'devtools/zones/protocol_scenarios.py',*common,'--scenario','retirement_prepare_'+args.family],output/'prepare.log',args.folder)
        report['steps'].append(step);old=prepared['retirement_target'];report['old_generation']=old
        manifest=json.loads((args.overlay/'manifest.json').read_text())
        with operation_lock(REPO/'StarWarsGalaxies'):
            # All actors have fully unloaded before any service fault. Capture
            # the global census, original saves and actual configured supervisors.
            receipt=CentralLossReceipt.capture(args.folder,args.overlay,bots,query)
            report['pre_fault_receipt']=receipt.evidence()
            hold_role=HOLDS[args.boundary]
            hold=service_target(project,schema,receipt.services,manifest,hold_role)
            report['held_service']=hold
            secondary_role=SECONDARY_HOLDS.get(args.boundary)
            worker_hold=args.boundary in WORKER_HOLDS
            descriptor=dict(definition=FAMILIES[args.family],instance=old['instance'],generation=old['generation'])
            secondary=(observe_worker(project,schema,receipt.services,manifest,descriptor) if worker_hold else service_target(project,schema,receipt.services,manifest,secondary_role)) if secondary_role else None
            if secondary:report['secondary_hold']=secondary
            secondary_paused=False
            remote='/tmp/central-loss-'+output.name;staged=[];paused=False;lost=False
            adapters={};debugger=None
            def send(target,mode):
                value=signal(project,target,remote+'/signal',mode)
                report['signals'].append(dict(target=target,mode=mode,receipt=value));return value
            try:
                for role,source in [('central','fixture_central_signal.cpp'),(hold_role,'fixture_service_signal.cpp')]+([(secondary_role,'fixture_retirement_signal.cpp' if worker_hold else 'fixture_service_signal.cpp')] if secondary else []):
                    source=Path(__file__).with_name(source);binary=output/(role+'-signal')
                    subprocess.run(['g++','-m64','-std=gnu++03','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],check=True)
                    if binary.read_bytes()[:6]!=b'\x7fELF\x02\x01':raise RuntimeError('ELF64 pidfd adapter required')
                    container=project+'-'+role+'-1';run(['docker','exec',container,'mkdir','-m','700',remote]);staged.append(container)
                    run(['docker','cp',str(binary),container+':'+remote+'/signal'])
                    adapters[role]=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
                report['adapters']=adapters
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    if service_target(project,schema,receipt.services,manifest,hold_role)!=hold:raise RuntimeError('Held service identity changed')
                    fresh_sample(query)
                    send(hold,'--stop');paused=True
                    held_service(hold)
                    reply=run(['docker','exec',project+'-central-1','/fixture/protocol-bot-console','127.0.0.1','capacityRetireEmpty',FAMILIES[args.family],old['instance']])
                    report.setdefault('drain_attempts',[]).append(reply)
                    match=re.fullmatch('retirement=pending operation=([1-9][0-9]*)',reply)
                    if match:break
                    send(hold,'--continue');paused=False
                    if reply!='retirement=sampling_or_blocked':raise RuntimeError('Unexpected retirement refusal: '+reply)
                else:raise TimeoutError('Could not seal with a fresh sample')
                expected=dict(definition=FAMILIES[args.family],instance=old['instance'],generation=old['generation'],operation=match[1],workers='1')
                report['boundary_observations']=[]
                observed=await_boundary(query,expected,'authorizing' if secondary else args.boundary,len(stage['shutdown_nodes']),report['boundary_observations'])
                if args.boundary!='fencing':report['old_launch_fences']=launch_markers(project,receipt.restart_policy,expected)
                if secondary:
                    current=observe_worker(project,schema,receipt.services,manifest,descriptor) if worker_hold else service_target(project,schema,receipt.services,manifest,secondary_role)
                    if current!=secondary:raise RuntimeError('Secondary process changed before hold')
                    if worker_hold:
                        # Keep the worker alive for the native post-authorization
                        # resample. Pause Central only at its actual freeze
                        # dispatch, then hold the exact worker before dispatch.
                        receipt.scope(project,schema,args.overlay,bots)
                        debugger=FreezeBreakpoint(project,receipt.target,expected,remote,output,manifest)
                        report['freeze_debugger']=debugger.evidence;debugger.start()
                    else:
                        # The planet host must answer the all-node StopGames
                        # fence before its own StopPlanet phase can begin.
                        # Hold it only on the exact StopPlanet observation.
                        if args.boundary!='stopping_planet':
                            send(secondary,'--stop');secondary_paused=True;held_service(secondary)
                        receipt.scope(project,schema,args.overlay,bots)
                    if not worker_hold:
                        # The database may answer as soon as it resumes. Keep
                        # the one-second native fence fresh across that reply;
                        # the full package/identity audit belongs before it.
                        fresh_sample(query)
                    send(hold,'--continue');paused=False;report['database_resumed_for_progress']=True
                    if worker_hold:
                        debugger.hit(expected)
                        send(secondary,'--stop');secondary_paused=True;held_service(secondary)
                        debugger.release();debugger=None
                    if args.boundary=='stopping_planet':
                        def pause_planet_on_boundary(_):
                            nonlocal secondary_paused
                            send(secondary,'--stop');secondary_paused=True
                        observed=await_boundary(query,expected,args.boundary,len(stage['shutdown_nodes']),
                                                report['boundary_observations'],on_match=pause_planet_on_boundary)
                        held_service(secondary)
                    else:
                        observed=await_boundary(query,expected,'freezing' if worker_hold else args.boundary,
                                                len(stage['shutdown_nodes']),report['boundary_observations'])
                    if args.boundary=='committing':
                        if service_target(project,schema,receipt.services,manifest,hold_role)!=hold:raise RuntimeError('DB changed before commit hold')
                        send(hold,'--stop');paused=True;held_service(hold)
                        # Resume the worker only in the SAME live authorized
                        # operation, before any injected fault. It processes its
                        # real freeze request; DB stays paused before commit.
                        await_boundary(query,expected,'freezing',len(stage['shutdown_nodes']),report['boundary_observations'])
                        receipt.scope(project,schema,args.overlay,bots)
                        send(secondary,'--continue');secondary_paused=False
                        report['worker_resumed_before_fault_to_process_freeze']=True
                        observed=await_boundary(query,expected,'committing',len(stage['shutdown_nodes']),report['boundary_observations'])
                injection_hold=secondary if secondary_paused else hold
                current=observe_worker(project,schema,receipt.services,manifest,descriptor) if injection_hold.get('kind')=='worker' else service_target(project,schema,receipt.services,manifest,injection_hold['role'])
                if current!=injection_hold:raise RuntimeError('Hold identity changed before fault')
                held_service(injection_hold);report['hold_paused_before_kill']=True
                report['injection_hold']=injection_hold
                receipt.scope(project,schema,args.overlay,bots)
                if service_target(project,schema,receipt.services,manifest,'central')!=receipt.target:raise RuntimeError('Central changed before fault')
                observed=await_boundary(query,expected,args.boundary,len(stage['shutdown_nodes']),report['boundary_observations'])
                report['injection_boundary']=observed
                killed=send(receipt.target if args.fault_service=='central' else
                            injection_hold if args.fault_service in ('game-supervisor','planet-supervisor') else hold,'--kill');lost=True
                if args.fault_service=='coordinator':receipt.record_coordinator_loss(hold,killed)
                if args.fault_service in ('game-supervisor','planet-supervisor'):
                    receipt.record_supervisor_loss(injection_hold,killed)
            finally:
                if debugger is not None:
                    try:debugger.release()
                    except Exception as cleanup:report['debugger_cleanup_error']=str(cleanup)
                if secondary_paused:
                    if worker_hold:
                        # A failed pre-injection observation leaves Central
                        # alive and the worker held. Resume that exact worker
                        # before removing its pidfd adapter; after an injected
                        # loss, proven-stop maintenance must reap it instead.
                        central_live=False
                        if not lost:
                            try:central_live=service_target(project,schema,receipt.services,manifest,'central')==receipt.target
                            except RuntimeError:pass
                        if central_live:
                            send(secondary,'--continue');report['hold_resumed_after_failed_observation']=True
                        else:report['sealed_worker_left_paused_for_maintenance']=True
                    elif not (lost and args.fault_service in ('game-supervisor','planet-supervisor')):
                        send(secondary,'--continue');report['hold_resumed_after_fault']=True
                if paused and (not lost or args.fault_service=='central'):
                    send(hold,'--continue');report['hold_resumed_after_fault']=True
                for container in staged:
                    if lost and getattr(receipt,'stopped_role',None) and container==injection_hold['container']:
                        report['deferred_signal_cleanup']=dict(container=container,path=remote)
                        continue
                    if container==receipt.target['container'] and worker_hold:
                        run(['docker','exec',container,'rm','-rf',remote+'/debugger'])
                        run(['docker','exec',container,'rm','-f',remote+'/freezing.gdb',remote+'/release-debugger'])
                    run(['docker','exec',container,'rm','-f',remote+'/signal']);run(['docker','exec',container,'rmdir',remote])
            if not lost:raise RuntimeError('Central fault did not execute')
            deadline=time.monotonic()+20
            while True:
                if args.fault_service=='central':
                    try:dead_central(receipt.target);break
                    except RuntimeError:
                        if time.monotonic()>deadline:raise
                else:
                    fault_role={'database':'database','coordinator':'taskmanager',
                                'game-supervisor':'game','planet-supervisor':'planet'}[args.fault_service]
                    try:current=service_target(project,schema,receipt.services,manifest,fault_role)
                    except RuntimeError:break
                    if current!=(injection_hold if fault_role in ('game','planet') else hold):break
                    if time.monotonic()>deadline:raise RuntimeError('Original '+fault_role+' process survived the scoped fault')
                time.sleep(.1)
            report['original_fault_process_reaped_or_replaced']=True
            central_lost=args.fault_service=='central'
            if args.fault_service!='central':
                try:
                    dead_central(receipt.target)
                    central_lost=True
                except RuntimeError:
                    if service_target(project,schema,receipt.services,manifest,'central')!=receipt.target:
                        raise RuntimeError('Central changed without a proven original-process reap')
            report['central_lost_after_fault']=central_lost
        # The restart revalidates this fresh in-memory receipt immediately before
        # its Central-first stop. No saved file or CLI flag authorizes this path.
        with (output/'restart.log').open('x') as log,contextlib.redirect_stdout(log):
            protocol_fixture_restart.main(restart,recovery=receipt if central_lost or getattr(receipt,'stopped_role',None) else None)
        evidence=runtime_artifact(output/'restart.log',args.folder)
        maintenance=json.loads(Path(evidence['path']).read_text())
        report['steps'].append(dict(command=['in_process','protocol_fixture_restart.main',*restart],log=str(output/'restart.log'),artifact=evidence))
        if ((central_lost or getattr(receipt,'stopped_role',None)) and not maintenance.get('service_loss_recovery') or
                not maintenance.get('distributed_shutdown_preserved')):
            raise RuntimeError('Restart did not prove guarded service-loss recovery')
        if report.get('deferred_signal_cleanup'):
            held=report['deferred_signal_cleanup']
            current=fixture(args.folder)[2][receipt.stopped_role]
            if current['Id']!=injection_hold['container_id']:
                report['deferred_signal_cleanup_by_recreation']=True
            else:
                present=subprocess.run(['docker','exec',held['container'],'test','-d',held['path']],
                                       capture_output=True).returncode
                if present==0:
                    run(['docker','exec',held['container'],'rm','-f',held['path']+'/signal'])
                    run(['docker','exec',held['container'],'rmdir',held['path']])
                elif present!=1:
                    raise RuntimeError('Exact coordinator scratch cleanup check failed')
            report['deferred_signal_cleanup_completed']=True
        if args.boundary!='fencing':
            if launch_markers(project,receipt.restart_policy,expected)!=report['old_launch_fences']:raise RuntimeError('Old fences changed during maintenance')
            report['old_launch_fences_preserved']=True
        step,wake=invoke([sys.executable,'devtools/zones/protocol_scenarios.py',*common,'--scenario','retirement_wake_'+args.family],output/'wake.log',args.folder)
        report['steps'].append(step);new=wake['recovered_world'];report['new_generation']=new
        if new['instance']!=old['instance'] or int(new['generation'])<=int(old['generation']) or wake['retirement_proofs']['state']!='retired':
            raise RuntimeError('Higher-generation replacement did not complete retirement')
        for bot in bots:unloaded(project,bot)
        current=fixture(args.folder)[2]
        if snapshot(project,schema)!=original or any(current['oracle'][k]!=services['oracle'][k] for k in ('Id','Image','Mounts')):
            raise RuntimeError('Central recovery changed protected saves or Oracle')
        report.update(passed=True,fully_unloaded=True,original_characters_unchanged=True,originals_sha256=original['sha256'])
    except BaseException as exc:
        report['error']=str(exc);raise
    finally:
        (output/'result.json').write_text(json.dumps(report,indent=2)+'\n');print('Evidence: '+str(output),flush=True)

if __name__=='__main__':main()
