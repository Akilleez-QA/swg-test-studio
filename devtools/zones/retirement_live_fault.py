"""Scoped live shutdown loss and generation recovery for every reviewed family."""
import hashlib,json,re,subprocess,time
from pathlib import Path
from protocol_driver import run,bot_query
from inspect_client_fixture import rows,native_snapshots
from rryatt_group import assert_stationary

FAMILIES={'falcon':'space_npe_falcon','ord':'space_ord_mantell','rryatt':'kashyyyk_rryatt_trail'}

def target(project,scene,world,generation,role,digest):
    if scene not in FAMILIES.values() or role not in ('game','planet') or not re.fullmatch('swg-cold-test-[a-f0-9]{8}',project):
        raise ValueError('Reviewed SWG fixture target required')
    if any(not re.fullmatch('[1-9][0-9]{0,18}',str(v)) or int(v)>9223372036854775807 for v in (world,generation)):
        raise ValueError('Exact positive world and generation required')
    container=project+'-'+role+'-1';meta=json.loads(run(['docker','inspect',container]))[0]
    labels=meta['Config'].get('Labels') or {}
    if labels.get('com.docker.compose.project')!=project or labels.get('com.docker.compose.service')!=role or not re.fullmatch('WGC_[A-F0-9]{12}',labels.get('whitengold.test.client','')) or not meta['State']['Running']:
        raise RuntimeError('Exact running copied-fixture role required')
    exe='/opt/whitengold/bin/'+('SwgGameServer' if role=='game' else 'PlanetServer');found=[]
    for line in run(['docker','exec',container,'ps','-eo','pid,args']).splitlines():
        fields=line.split()
        if len(fields)>2 and fields[1]==exe and 'sceneID='+scene in fields and 'zoneInstanceId='+str(world) in fields:
            if fields.count('sceneID='+scene)!=1 or fields.count('zoneInstanceId='+str(world))!=1 or fields.count('capacityAttempt='+str(world)+':'+str(generation))!=1:
                raise RuntimeError('Fault launch generation differs from native journal')
            pid=fields[0];stat=run(['docker','exec',container,'cat','/proc/'+pid+'/stat'])
            sha=run(['docker','exec',container,'sha256sum','/proc/'+pid+'/exe']).split()[0]
            if sha!=digest:raise RuntimeError('Fault binary differs from accepted overlay')
            found.append(dict(pid=pid,start_ticks=stat.rsplit(') ',1)[1].split()[19],scene=scene,world=str(world),generation=str(generation),role=role,sha256=sha,container_id=meta['Id'],image_id=meta['Image']))
    if len(found)!=1:raise RuntimeError('Expected exactly one exact-generation child')
    return found[0]

def fresh_sample(query,timeout=15,clock=time.monotonic,pause=time.sleep):
    # The diagnostic reader for ordinary readiness also fetches scene/instance
    # rows. A retirement fence is stricter (one second); request and retain a
    # NEW complete native nonce without spending that window on extra queries.
    previous=query('capacityContent').splitlines()[0]
    match=re.search(r' sample=([0-9]+)$',previous)
    if not match:raise RuntimeError('Native sample identity unavailable')
    if query('capacitySample')!='Content observation requested; use capacityContent (no travel or script reservations)':
        raise RuntimeError('Fresh retirement observation refused')
    end=clock()+timeout
    while clock()<end:
        header=query('capacityContent').splitlines()[0]
        current=re.fullmatch(r'schema=1 mode=observe_only state=collected sample=([1-9][0-9]*)',header)
        if current and current[1]!=match[1]:return header
        pause(.05)
    raise TimeoutError('New complete retirement sample unavailable')

class Live:
    def __init__(self,s,scene):
        self.s=s;self.scene=scene
        self.stage=json.loads((s.folder.parent.parent/'runtime/stage5-report.json').read_text())
        if not self.stage.get('distributed_shutdown') or not self.stage.get('world_save_probes') or self.stage['policy']['rryatt_capacity']!=2 or self.stage['policy']['ord_capacity']!=2:
            raise RuntimeError('Exact bounded Stage 7 fixture required')
    def query(self,*args):
        return run(['docker','exec',self.s.project+'-central-1','/fixture/protocol-bot-console','127.0.0.1',*args])
    def worlds(self,count):
        end=time.monotonic()+180
        while time.monotonic()<end:
            _,instances,content,_=native_snapshots(lambda c:self.query(c))
            live=[r for r in instances if r['definition']==self.scene and r['state'] not in ('stopped','retired')]
            if len(live)>2:raise RuntimeError('Exceeded bounded family count')
            if len(live)==count and all(r['state']=='running' and r['ready']=='1' for r in live):return live,content
            time.sleep(1)
        raise TimeoutError('Reviewed family readiness: '+self.scene)
    def claim(self,world,action,count=None):
        _,content=self.worlds(count if count is not None else (1 if action in ('fixtureRetirementClaim','fixtureRetirementFill') else 2))
        matches=[r for r in content if r.get('scene')==self.scene and r.get('zone_instance_id')==world]
        if len(matches)!=124:raise RuntimeError('Exactly 124 Falcon controllers required')
        r=matches[0]
        expected={'fixtureRetirementClaim':93,'fixtureRetirementFill':124,'fixtureRetirementClear':0}[action]
        # CWD lock contention can reject a callback after dispatch. Clear is
        # idempotent and fenced by the fixture tag plus matching native/CWD
        # session; retry it only after observing that its tagged leases remain.
        for attempt in range(3 if action=='fixtureRetirementClear' else 1):
            value=run(['docker','exec',self.s.project+'-central-1','/fixture/falcon-retirement-console','127.0.0.1',action,r['owner'],r['controller']])
            self.s.report['setup'].append(dict(kind=action,world=world,synthetic=True,result=value,attempt=attempt+1))
            if value!='fixture=dispatched':raise RuntimeError('Tagged fixture lease setup refused')
            deadline=time.monotonic()+(10 if action=='fixtureRetirementClear' else 30)
            while time.monotonic()<deadline:
                # Require a nonce collected AFTER this asynchronous mutation.
                # A previously complete diagnostic is not a mutation receipt.
                fresh_sample(self.query)
                _,_,content,_=native_snapshots(lambda command:self.query(command))
                tagged=[x for x in content if x.get('scene')==self.scene and x.get('zone_instance_id')==world and 2000000<=int(x.get('session','-1'))<2000124]
                if len(tagged)==expected:return
                time.sleep(.5)
        raise TimeoutError('Exact tagged Falcon pressure/cleanup did not publish')
    def grow(self):
        s=self.s;a,b=s.bots
        for k in s.bots:
            if s.row(k)['group'] not in ('null','0'):
                s.sessions[k].send('leaveGroup');s.sessions[k].wait('group_command',10)
            if s.row(k)['scene']=='kashyyyk_main':
                # A prior linked-set case may leave this dedicated fixture actor
                # at the authored Kashyyyk return. Reuse its bounded home action
                # before the station-only growth setup on a rerun.
                s.setup(k,'botKashyyykHome')
            if s.row(k)['family']!='npe_space_station':raise RuntimeError('Station baseline required')
        first=self.worlds(1)[0][0]
        if self.scene==FAMILIES['rryatt']:
            from rryatt_demand import Demand
            p=Demand(s)
            for k in s.bots:s.setup(k,'botKashyyykSetup')
            p.enter(a);p.enter(b);live,_=self.worlds(2)
            p.exit(b);p.exit(a)
            for k in s.bots:s.setup(k,'botKashyyykHome')
        elif self.scene==FAMILIES['ord']:
            s.launch(a,s.setup_pilot(a));live,_=self.worlds(2);s.land(a)
        else:
            claimed=False
            try:
                self.claim(first['instance'],'fixtureRetirementClaim');claimed=True
                live,_=self.worlds(2)
            finally:
                if claimed:self.claim(first['instance'],'fixtureRetirementClear')
        extra=next(r for r in live if r['instance']!=first['instance'])
        # Always request a NEW sample after travel/lease cleanup. Cached content
        # may still describe the earlier source occupancy.
        end=time.monotonic()+40
        self.query('capacitySample')
        while time.monotonic()<end:
            _,_,content,_=native_snapshots(lambda c:self.query(c))
            if self.scene!=FAMILIES['falcon'] or all(int(r['session'])<0 for r in content if r.get('scene')==self.scene):break
            time.sleep(.5)
        else:raise TimeoutError('Tagged Falcon leases were not cleared')
        s.report['retirement_target']=extra
        s.record('empty_extra_world_prepared_with_both_actors_outside_fault_scope')
        return extra


def execute(s,family,wake=False):
    if family not in FAMILIES:raise ValueError('Unknown reviewed family')
    live=Live(s,FAMILIES[family]);extra=live.grow()
    if wake:
        s.report['recovered_world']=extra
        if family=='rryatt':
            from rryatt_demand import Demand
            p=Demand(s)
            for k in s.bots:s.setup(k,'botKashyyykSetup')
            a,b=s.bots;p.enter(a,1)
            if s.row(a)['instance']!=extra['instance']:raise RuntimeError('Recovered linked world not enterable')
            s.rryatt_guide(a,0);s.rryatt_guide(a,2);p.exit(a)
            for k in s.bots:s.setup(k,'botKashyyykHome')
        s.record('maintenance_allows_one_new_generation_without_reopening_old_fence')
        from world_shutdown_scenario import retire_empty
        retire_empty(s,live.scene,extra,live.stage['shutdown_nodes'])
        return
    stage=live.stage;manifest=json.loads((Path(stage['overlay'])/'manifest.json').read_text())
    digests={r:manifest['files']['bin/'+n]['sha256'] for r,n in [('game','SwgGameServer'),('planet','PlanetServer')]}
    originals={role:target(s.project,live.scene,extra['instance'],extra['generation'],role,digests[role]) for role in ('game','planet')}
    source=Path(__file__).with_name('fixture_retirement_signal.cpp');binary=s.folder/'retirement-signal'
    subprocess.run(['g++','-m64','-std=gnu++03','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],check=True)
    if binary.read_bytes()[:6]!=b'\x7fELF\x02\x01':raise RuntimeError('ELF64 scoped fault adapter required')
    remote='/tmp/retirement-fault-'+s.report['operation'];paths=[]
    for role in originals:
        container=s.project+'-'+role+'-1';run(['docker','exec',container,'mkdir','-m','700',remote]);run(['docker','cp',str(binary),container+':'+remote+'/signal']);paths.append(container)
    s.report['fault_adapter']={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}
    def signal(role,mode,recheck=True):
        old=originals[role]
        if recheck and target(s.project,live.scene,extra['instance'],extra['generation'],role,digests[role])!=old:raise RuntimeError('Exact child identity changed before signal')
        receipt=run(['docker','exec',s.project+'-'+role+'-1',remote+'/signal',old['pid'],old['start_ticks'],live.scene,extra['instance'],role,mode])
        s.report.setdefault('signals',[]).append(dict(target=old,mode=mode,receipt=receipt))
    paused=False;sealed=False
    try:
        before=s.record('outside_actors_captured_before_worker_partition')
        # Pause the verified EMPTY worker before drain. Only a recent cached
        # complete sample can permit sealing; resume/resample on pre-seal refusal.
        # After sealing, never resume that generation or forge its freeze receipt.
        sealed=False;paused=False
        end=time.monotonic()+90
        while time.monotonic()<end:
            if target(s.project,live.scene,extra['instance'],extra['generation'],'game',digests['game'])!=originals['game']:
                raise RuntimeError('Exact empty worker changed before fresh sample')
            s.report.setdefault('fresh_fault_samples',[]).append(fresh_sample(live.query))
            # pidfd adapter rechecks PID start/exe/scene/world immediately. The
            # slower parent image/hash/generation audit happened BEFORE sampling.
            signal('game','--stop',recheck=False);paused=True
            reply=live.query('capacityRetireEmpty',live.scene,extra['instance'])
            match=re.fullmatch('retirement=pending operation=([1-9][0-9]*)',reply)
            s.report.setdefault('drain_attempts',[]).append(reply)
            if match:sealed=True;break
            signal('game','--continue');paused=False
            if reply!='retirement=sampling_or_blocked':raise RuntimeError('Unexpected drain refusal: '+reply)
            time.sleep(.25)
        else:raise RuntimeError('Could not seal within the fresh sample interval')
        operation=match[1];started=time.monotonic();seen=[];injected=False
        while time.monotonic()-started<80:
            status=rows(live.query('capacityRetireStatus'))
            if len(status)!=1:raise RuntimeError('Shutdown operation disappeared')
            r=status[0]
            if any(r[k]!=v for k,v in {'definition':live.scene,'instance':extra['instance'],'generation':extra['generation'],'operation':operation}.items()):raise RuntimeError('Shutdown identity changed')
            if not seen or seen[-1]!=r['state']:
                seen.append(r['state']);print('FAULT '+family+' '+r['state'],flush=True)
            if r['state']=='retired':raise RuntimeError('Paused worker falsely supplied committed/reap proof')
            if not injected and int(r['fenced_nodes'])==len(stage['shutdown_nodes']) and r['state'] in ('fencing','authorizing','freezing'):
                s.report['injection_boundary']=dict(r)
                signal('game','--kill');paused=False;injected=True
            if r['state']=='quarantined':break
            time.sleep(.1)
        else:raise TimeoutError('Uncertain shutdown did not quarantine')
        if not injected or r['frozen']!='0' or r['saved']!='0' or r['game_reaps']!='0' or r['reaped_launches']!='0' or int(r['fenced_nodes'])!=len(stage['shutdown_nodes']):
            raise RuntimeError('Loss produced unearned proof or incomplete launch fencing: '+str(r))
        marker=live.scene+'-'+extra['instance']+'-'+extra['generation']+'.fence'
        proof=[]
        # All supervisors persisted the seal, including nodes with no launches.
        from configure import NODES
        for role in NODES:
            container=s.project+'-'+role+'-1'
            raw=run(['docker','exec',container,'cat','/world-launch-fences/'+marker])
            mode=run(['docker','exec',container,'stat','-c','%a','/world-launch-fences/'+marker])
            digest=run(['docker','exec',container,'sha256sum','/world-launch-fences/'+marker]).split()[0]
            if raw!=operation or mode!='600' or digest!=hashlib.sha256((operation+'\n').encode()).hexdigest():raise RuntimeError('Durable exact-operation supervisor marker missing')
            proof.append(dict(role=role,marker=marker,operation=raw,mode=mode,sha256=digest))
        for k in s.bots:assert_stationary(before[k],bot_query(s.project,s.bots[k],worker=before[k]['worker']))
        s.report['partition']={'seconds':time.monotonic()-started,'states':seen,'status':r,'markers':proof}
        # Terminate the remaining verified EMPTY controller. The dead worker
        # and controller must stay absent behind the durable generation fence.
        signal('planet','--kill')
        time.sleep(5)
        for role in originals:
            text=run(['docker','exec',s.project+'-'+role+'-1','ps','-eo','pid,args'])
            if any('sceneID='+live.scene in line.split() and 'zoneInstanceId='+extra['instance'] in line.split() for line in text.splitlines()):
                raise RuntimeError('Fenced generation resurrected after exact-child loss')
        end=time.monotonic()+40
        while time.monotonic()<end:
            try:
                _,instances,_,_=native_snapshots(lambda c:live.query(c))
                record=next(r for r in instances if r['definition']==live.scene and r['instance']==extra['instance'])
                if record['state']=='uncertain' and record['ready']=='0':break
            except RuntimeError:pass
            time.sleep(1)
        else:raise TimeoutError('Lost sealed generation advertised or not quarantined')
        s.report['quarantined_instance']=record
        s.record('old_generation_stays_fenced_after_worker_and_controller_loss')
    finally:
        if paused and not sealed:signal('game','--continue')
        for container in paths:
            run(['docker','exec',container,'rm','-f',remote+'/signal']);run(['docker','exec',container,'rmdir',remote])
