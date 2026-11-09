"""Fresh in-process maintenance authority after the fixture's Central is lost.

No serialized receipt or CLI switch can bypass normal live-empty preflight.
This proof is captured by the fault runner while Central and all roles are live.
"""
import copy,hashlib,json,math,re,time
from datetime import datetime,timezone
from pathlib import Path
from protocol_driver import fixture,run,saved,unloaded
from configure import ROLES,NODES
from protocol_preservation import snapshot
from retirement_fault_targets import service_target


def same_services(before,after,project,allowed_stopped=None):
    if not re.fullmatch('swg-cold-test-[a-f0-9]{8}',project) or set(before)!=set(after):
        raise RuntimeError('Exact retained SWG service roster required')
    for role,current in after.items():
        labels=current.get('Config',{}).get('Labels') or {}
        stopped = (allowed_stopped in ('taskmanager','game','planet') and role==allowed_stopped and
                   current.get('State',{}).get('Status')=='exited' and
                   current.get('State',{}).get('ExitCode')==137 and
                   not current.get('State',{}).get('Running'))
        if (role not in set(ROLES)|{'oracle','local_chat'} or labels.get('com.docker.compose.project')!=project or
                labels.get('com.docker.compose.service')!=role or
                not (current.get('State',{}).get('Running') or stopped) or
                labels!=(before[role].get('Config',{}).get('Labels') or {}) or
                any(current.get(k)!=before[role].get(k) for k in ('Id','Image','Mounts'))):
            raise RuntimeError('Fixture service or Oracle identity/mounts changed')


def dead_central(target,query=run):
    container=target['container'];exe='/opt/whitengold/bin/CentralServer'
    if (target.get('role')!='central' or target.get('executable')!=exe or
            not re.fullmatch('swg-cold-test-[a-f0-9]{8}-central-1',container) or
            not re.fullmatch('[1-9][0-9]{0,9}',target['pid'])):
        raise RuntimeError('Exact captured Central target required')
    for line in query(['docker','exec',container,'ps','-eo','pid,args']).splitlines():
        fields=line.split()
        if fields and (fields[0]==target['pid'] or any(exe==v or v=='[CentralServer]' for v in fields[1:])):
            raise RuntimeError('Original Central is not reaped or a replacement is present')
    value=query(['docker','exec',container,'sha256sum',exe]).split()
    if value!=[target['sha256'],exe]:raise RuntimeError('Captured Central package changed after fault')


def config_hashes(folder):
    root=folder/'runtime'
    names=['runtime.cfg','compose.json','stage5-report.json']+['config/'+role+'.cfg' for role in ROLES]
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}


def disabled_restart(folder,project,query=run,stopped_role=None,prior=None):
    # No included files or per-process overrides may hide a second setting.
    runtime=(folder/'runtime/runtime.cfg').read_text()
    def settings(text):
        section='';found=[]
        for raw in text.splitlines():
            line=raw.strip()
            if line.startswith(('@','.include')):raise RuntimeError('Unreviewed nested configuration include')
            if line.startswith('[') and line.endswith(']'):section=line[1:-1]
            elif section=='TaskManager' and re.match(r'restartCentral\s*=',line):found.append(line.split('=',1)[1].strip())
        return found
    include='.include "/opt/whitengold/exe/shared/servercommon.cfg"'
    included=[v.strip() for v in runtime.splitlines() if v.strip().startswith(('@','.include'))]
    if included not in ([],[include]):raise RuntimeError('Only the original shared server configuration may be included')
    if settings(runtime.replace(include,'')):raise RuntimeError('Runtime overrides Central restart policy')
    runtime_sha=hashlib.sha256(runtime.encode()).hexdigest();proof={}
    for role in NODES:
        config=(folder/'runtime/config'/(role+'.cfg')).read_text()
        if settings(config)!=['false']:raise RuntimeError('Explicit unique restartCentral=false required on every supervisor')
        if role==stopped_role:
            if (role not in ('taskmanager','game','planet') or not prior or role not in prior or
                    prior[role].get('config_sha256')!=hashlib.sha256(config.encode()).hexdigest()):
                raise RuntimeError('Stopped supervisor policy differs from captured input')
            proof[role]=prior[role]
            continue
        container=project+'-'+role+'-1'
        for name,digest in [('runtime.cfg',runtime_sha),('container.cfg',hashlib.sha256(config.encode()).hexdigest())]:
            remote='/run/whitengold/'+name
            if query(['docker','exec',container,'sha256sum',remote]).split()!=[digest,remote]:
                raise RuntimeError('Running supervisor configuration differs from captured input')
        processes=[line.split() for line in query(['docker','exec',container,'ps','-eo','pid,args']).splitlines()
                   if len(line.split())>1 and line.split()[1]=='/opt/whitengold/bin/TaskManager']
        if len(processes)!=1:raise RuntimeError('Exactly one configured supervisor required')
        args=processes[0][2:];includes=[v for v in args if v.startswith('@')]
        if (sorted(includes)!=['@/run/whitengold/container.cfg','@/run/whitengold/runtime.cfg'] or
                any('restartCentral=' in v for v in args)):
            raise RuntimeError('Unreviewed supervisor configuration arguments')
        shared={}
        if included:
            text=query(['docker','exec',container,'cat','/opt/whitengold/exe/shared/servercommon.cfg'])
            if settings(text):raise RuntimeError('Shared configuration overrides Central restart policy')
            shared['shared_text_sha256']=hashlib.sha256(text.encode()).hexdigest()
        proof[role]=dict(pid=processes[0][0],config_sha256=hashlib.sha256(config.encode()).hexdigest(),**shared)
    return proof


class CentralLossReceipt:
    @classmethod
    def capture(cls,folder,overlay,bots,query,clock=time.monotonic):
        from protocol_fixture_restart import require_empty_fixture
        result=cls();result.folder=folder.resolve();result.overlay=overlay.resolve();result.clock=clock
        result.project,result.schema,services=fixture(folder)
        result.services=copy.deepcopy(services);result.bots=copy.deepcopy(bots);result.players=sorted(b['player'] for b in bots)
        for bot in bots:unloaded(result.project,bot)
        manifest=json.loads((overlay/'manifest.json').read_text())
        result.target=service_target(result.project,result.schema,services,manifest,'central')
        result.restart_policy=disabled_restart(folder,result.project)
        result.configs=config_hashes(folder);result.manifest_sha256=hashlib.sha256((overlay/'manifest.json').read_bytes()).hexdigest()
        result.saved_players=[saved(result.project,result.schema,b['player']) for b in bots]
        result.original=snapshot(result.project,result.schema)
        result.empty_proof=require_empty_fixture(query);result.created=clock()
        result.captured_utc=datetime.now(timezone.utc).isoformat()
        return result

    def record_coordinator_loss(self,target,signal_receipt):
        if (target.get('role')!='taskmanager' or target.get('container')!=self.project+'-taskmanager-1' or
                target.get('container_id')!=self.services['taskmanager']['Id'] or
                target.get('image_id')!=self.services['taskmanager']['Image'] or
                not re.fullmatch(r'verified_pid='+re.escape(target['pid'])+r' start_ticks='+re.escape(target['start_ticks'])+
                                 r' signal=9 role=coordinator',signal_receipt)):
            raise RuntimeError('Exact scoped coordinator pidfd fault receipt required')
        self.coordinator_loss=copy.deepcopy(target)
        self.stopped_role='taskmanager'

    def record_supervisor_loss(self,target,signal_receipt):
        role=target.get('role')
        expected={'game':'game-supervisor','planet':'planet-supervisor'}
        if (role not in expected or target.get('container')!=self.project+'-'+role+'-1' or
                target.get('container_id')!=self.services[role]['Id'] or
                target.get('image_id')!=self.services[role]['Image'] or
                not re.fullmatch(r'verified_pid='+re.escape(target['pid'])+r' start_ticks='+re.escape(target['start_ticks'])+
                                 r' signal=9 role='+expected[role],signal_receipt)):
            raise RuntimeError('Exact scoped supervisor pidfd fault receipt required')
        self.supervisor_loss=copy.deepcopy(target)
        self.stopped_role=role

    def scope(self,project,schema,overlay,bots):
        age=self.clock()-self.created
        if (not math.isfinite(age) or not 0<=age<=180 or project!=self.project or schema!=self.schema or
                overlay.resolve()!=self.overlay or sorted(b['player'] for b in bots)!=self.players):
            raise RuntimeError('Fresh exact in-process Central-loss receipt required')

    def authorize(self,project,schema,services,bots,overlay):
        self.scope(project,schema,overlay,bots)
        stopped=getattr(self,'stopped_role',None)
        same_services(self.services,services,project,stopped)
        if (config_hashes(self.folder)!=self.configs or
                hashlib.sha256((overlay/'manifest.json').read_bytes()).hexdigest()!=self.manifest_sha256):
            raise RuntimeError('Captured policy, configuration or package changed')
        if stopped:
            manifest=json.loads((overlay/'manifest.json').read_text())
            try:
                dead_central(self.target)
            except RuntimeError:
                if service_target(project,schema,services,manifest,'central')!=self.target:
                    raise RuntimeError('Central changed during scoped coordinator loss')
        else:
            dead_central(self.target)
        if disabled_restart(self.folder,project,stopped_role=stopped,
                            prior=self.restart_policy if stopped else None)!=self.restart_policy:
            raise RuntimeError('Running supervisor policy changed after fault')
        if bots!=self.bots or [saved(project,schema,b['player']) for b in bots]!=self.saved_players:
            raise RuntimeError('Dedicated saved characters changed after their proven unload')
        if snapshot(project,schema)!=self.original:raise RuntimeError('Protected saves changed after Central loss')
        self.scope(project,schema,overlay,bots)
        return self.empty_proof

    def evidence(self):
        return dict(captured_utc=self.captured_utc,maximum_age_seconds=180,project=self.project,schema=self.schema,
            coordinator_loss=getattr(self,'coordinator_loss',None),
            supervisor_loss=getattr(self,'supervisor_loss',None),
            players=self.players,saved_players=self.saved_players,target=self.target,restart_policy=self.restart_policy,configs=self.configs,
            manifest_sha256=self.manifest_sha256,originals_sha256=self.original['sha256'],empty_fixture_proof=self.empty_proof)
