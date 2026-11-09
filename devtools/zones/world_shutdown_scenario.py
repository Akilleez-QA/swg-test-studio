"""Live explicit empty-world retirement through Central, DB and all supervisors.

Only dedicated fixture actors enter/leave content. No arbitrary PID signals,
saved-character edits, image builds, database copies or client modifications.
"""
import json,re,time
from protocol_driver import run
from inspect_client_fixture import rows,native_snapshots
from rryatt_demand import Demand
from rryatt_group import SCENE,assert_stationary


def execute(s):
    a,b=s.bots;p=Demand(s)
    stage=json.loads((s.folder.parent.parent/'runtime/stage5-report.json').read_text())
    if not stage.get('distributed_shutdown') or not stage.get('rryatt_demand_instances') or stage['policy']['rryatt_capacity']!=2 or stage['policy']['rryatt_maximum_instances']!=2:
        raise RuntimeError('Explicit bounded distributed-shutdown fixture required')
    expected_nodes=stage.get('shutdown_nodes',[])
    if not expected_nodes:raise RuntimeError('Exact complete supervisor participant list required')
    console=lambda *args:run(['docker','exec',s.project+'-central-1','/fixture/protocol-bot-console','127.0.0.1',*args])
    for k in s.bots:
        r=s.row(k)
        if r['group'] not in ('null','0'):
            s.sessions[k].send('leaveGroup');s.sessions[k].wait('group_command',10)
        if r['scene']==SCENE:p.exit(k)
        elif r.get('family')=='npe_space_station':s.setup(k,'botKashyyykSetup')
        elif r['scene']!='kashyyyk_main':raise RuntimeError('Unexpected retirement actor baseline')
    warm=p.enter(a);second=p.enter(b)
    if warm['instance']!=second['instance']:raise RuntimeError('Both actors must fill the warm whole set')
    worlds=p.wait_growth(2);extra=[r for r in worlds if r['instance']!=warm['instance']]
    if len(extra)!=1:raise RuntimeError('Exact empty grown world required')
    target=extra[0];s.report['retirement_target']=target
    # Occupied and minimum-ready worlds cannot be drained. This request cannot
    # dispatch any supervisor message or mutate a worker when refused.
    denied=console('capacityRetireEmpty',SCENE,warm['instance'])
    if denied not in ('retirement=sampling_or_blocked','retirement=blocked'):raise RuntimeError('Occupied retirement was not refused: '+denied)
    s.report['occupied_retirement_refused']=denied
    denied=console('capacityRetireEmpty',SCENE,target['instance'])
    if denied not in ('retirement=sampling_or_blocked','retirement=blocked'):raise RuntimeError('Remaining capacity exhaustion did not block empty retirement: '+denied)
    s.report['remaining_headroom_refused']=denied
    p.exit(b);p.exit(a)
    retire_empty(s,SCENE,target,expected_nodes)
    # Demand remains full in the warm copy, so it must wake another complete
    # four-level copy with a new durable ID rather than reuse the retired one.
    p.enter(a);p.enter(b)
    current=p.wait_growth(2)
    replacement=[r for r in current if r['instance']!=warm['instance']]
    if len(replacement)!=1 or replacement[0]['instance']==target['instance']:raise RuntimeError('Retired ID reused by demand')
    s.report['replacement_world']=replacement[0]
    p.exit(b);entered=p.enter(b,1)
    if entered['instance']!=replacement[0]['instance']:raise RuntimeError('Normal gate advertised the wrong replacement world')
    if s.row(a)['instance']!=warm['instance']:raise RuntimeError('Warm actor moved during independent gate entry')
    s.record('normal_gate_enters_new_complete_world_without_reusing_retired_id')
    p.exit(b);p.exit(a)
    for k in s.bots:s.setup(k,'botKashyyykHome')
    s.record('distributed_shutdown_actors_returned_home')

def retire_empty(s,scene,target,expected_nodes,occupied=False):
    if type(occupied) is not bool:raise ValueError("Explicit occupied fixture policy required")
    console=lambda *args:run(['docker','exec',s.project+'-central-1','/fixture/protocol-bot-console','127.0.0.1',*args])
    before=s.record('actors_remain_at_own_positions_outside_the_retiring_family')
    end=time.monotonic()+90
    while time.monotonic()<end:
        reply=console('capacityRetireEmpty',scene,target['instance'])
        match=re.fullmatch(r'retirement=pending operation=([1-9][0-9]*)',reply)
        if match:break
        if reply not in ('retirement=sampling_or_blocked','retirement=blocked','retirement=encounter_sampling_or_blocked'):raise RuntimeError('Empty retirement request failed: '+reply)
        time.sleep(.25)
    else:raise TimeoutError('Fresh whole empty-world fence unavailable')
    operation=match[1];started=time.monotonic();seen=[]
    attempt={'target':dict(target),'operation':operation,'observations':[]}
    s.report.setdefault('retirement_attempts',[]).append(attempt)
    while time.monotonic()-started<70:
        status=console('capacityRetireStatus')
        if status.splitlines()[0]!='schema=1 automatic_retirement=0 occupied_retirement='+str(int(occupied)):raise RuntimeError('Retirement fixture policy changed')
        observed=rows(status)
        if len(observed)!=1:raise RuntimeError('Exact retirement operation disappeared')
        r=observed[0]
        if any(r[k]!=v for k,v in {'definition':scene,'instance':target['instance'],'generation':target['generation'],'operation':operation}.items()):raise RuntimeError('Retirement identity changed')
        if not seen or seen[-1]!=r['state']:
            seen.append(r['state'])
            attempt['observations'].append(dict(status=dict(r),elapsed_seconds=time.monotonic()-started))
            print('RETIREMENT '+r['state'],flush=True)
        if r['state']=='retired':
            workers=int(r['workers'])
            if workers<1 or any(int(r[k])!=workers for k in ('frozen','saved','game_reaps')) or int(r['reaped_launches'])!=workers+1 or int(r['fenced_nodes'])!=len(expected_nodes) or r['fenced_nodes']!=r['nodes']:
                raise RuntimeError('Retirement lacks complete freeze/commit/reap/queue proof: '+str(r))
            s.report['retirement_proofs']=r
            break
        if r['state']=='quarantined':
            attempt['failure']=dict(r)
            raise RuntimeError('Distributed shutdown quarantined at '+r.get('failed_at','unknown')+': '+r.get('failure_reason','unreported')+'; retain all evidence')
        time.sleep(.25)
    else:raise TimeoutError('Distributed retirement did not finish')
    for k in s.bots:assert_stationary(before[k],s.row(k))
    _,instances,_,_=native_snapshots(lambda command:console(command))
    retired=[r for r in instances if r['definition']==scene and r['instance']==target['instance']]
    if len(retired)!=1 or retired[0]['state']!='retired' or retired[0]['ready']!='0':raise RuntimeError('Retired generation still advertised as ready')
    s.report['distributed_retirement']={'operation':operation,'target':target,'states_observed':seen,'seconds':time.monotonic()-started,'retired':retired[0]}
    s.record('empty_whole_world_reaped_after_committed_freeze_while_other_world_actors_stay_online')
    s.report.setdefault('retirements',[]).append({'proofs':s.report['retirement_proofs'],'operation':s.report['distributed_retirement']})
    return s.report['distributed_retirement']
