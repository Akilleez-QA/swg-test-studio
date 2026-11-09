"""Real offline saves in retired linked worlds and owned-ship worlds.

No saved-object edits: three dedicated actors fill the warm two-seat world,
then the third enters the grown world through normal gameplay and logs out.
"""
import hashlib,json,math,re,time
from protocol_driver import run,saved,unloaded
from protocol_scenarios import Scenarios,owned_ship
from rryatt_demand import Demand
from rryatt_group import assert_stationary
from inspect_client_fixture import native_snapshots
from world_shutdown_scenario import retire_empty

FAMILIES={'falcon':'space_npe_falcon','rryatt':'kashyyyk_rryatt_trail','ord':'space_ord_mantell'}


def evidence(path,digest,base,project,schema,keys):
    path=path.resolve(strict=True)
    if not path.is_relative_to(base.resolve()) or path.name!='result.json' or not re.fullmatch('[a-f0-9]{64}',digest):
        raise ValueError('Exact prior fixture artifact required')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Offline setup evidence changed')
    data=json.loads(path.read_text())
    if (not data.get('passed') or not data.get('fully_unloaded') or data.get('project')!=project or
            data.get('schema')!=schema or set(data.get('bots',{}))!=set(keys) or
            data.get('offline_actor',{}).get('key')!=keys[-1]):
        raise ValueError('Passed matching offline setup required')
    target=data['retirement_target'];offline=data['offline_actor']
    if (target.get('definition') not in FAMILIES.values() or data['retirement_proofs'].get('state')!='retired' or
            any(data['retirement_proofs'].get(k)!=target.get(k) for k in ('definition','instance','generation')) or
            any(not re.fullmatch('[1-9][0-9]{0,18}',target.get(k,'')) or int(target[k])>9223372036854775807 for k in ('instance','generation')) or
            offline['saved'].get('scene')!=target['definition'] or offline['saved'].get('instance')!=target['instance'] or
            offline['before'].get('instance')!=target['instance']):
        raise ValueError('Offline save must precede proven retirement of its exact world')
    if target['definition']=='space_npe_falcon':
        from retirement_falcon import assert_room,assert_saved
        room=data.get('falcon_room',{})
        try:
            assert_room(offline['before'],room,data['bots'][keys[-1]])
            assert_saved(offline['before'],room,offline['saved'],offline.get('variables',{}))
        except (ValueError,KeyError,TypeError,RuntimeError) as exc:raise ValueError('Missing exact owned Falcon session evidence') from exc
        isolation=data.get('different_player_fresh_session',{})
        other=isolation.get('new_player',{});retained=isolation.get('offline_owner_retained',{})
        if (other.get('player')!=data['bots'][keys[1]]['player'] or other.get('owner')!=other.get('player') or
            other.get('participants')!='1' or other.get('instance')!=target['instance'] or
            other.get('room')==room['room'] or other.get('session')==room['session'] or
            retained.get('controller')!=room['room'] or retained.get('session')!=room['session']):
            raise ValueError('Missing different-player isolation from the offline owned session')
        content=data.get('expired_content',[])
        if (not data.get('retained_session_blocker') or len(content)!=124 or
            len({r.get('controller') for r in content})!=124 or any(r.get('scene')!=target['definition'] or
            r.get('zone_instance_id')!=target['instance'] or r.get('session')!='-1' or r.get('players')!='0' or
            r.get('locked')!='0' for r in content)):
            raise ValueError('Missing timer cleanup and retained-session refusal evidence')
    return data


def assert_recovered(before,after,bot,family,retired):
    if (family not in FAMILIES or before.get('scene')!=FAMILIES[family] or after.get('scene')!=before['scene'] or
            not re.fullmatch('[1-9][0-9]{0,18}',after.get('instance','')) or after['instance']==retired or
            after.get('pending')!='false' or after.get('outstanding')!='false' or after.get('protected')!='false'):
        raise RuntimeError('Retired save did not settle in a live same-family world')
    fields=('x','y','z')
    if family=='rryatt':
        if after.get('buildout_row')!=before.get('buildout_row') or after.get('cell')!=before.get('cell'):
            raise RuntimeError('Retired linked save lost its own level or cell')
    else:
        if not owned_ship(after,bot,before['ship']) or after.get('cell')!=before.get('cell'):
            raise RuntimeError('Retired space save lost its original owned ship or pilot containment')
        # packShip unpilots the owner and saves it at shipLoc; the live
        # Creature location can still be the earlier launch position.
        before=dict(before,**{k:before['ship_'+k] for k in ('x','y','z')})
        fields+=('ship_x','ship_y','ship_z')
    for k in fields:
        if not math.isfinite(float(before[k])) or not math.isfinite(float(after[k])) or abs(float(after[k])-float(before[k]))>.15:
            raise RuntimeError('Retired save changed its own '+k+' position')


def logout(s,key):
    peer=s.sessions[key];row=s.row(key)
    from world_runtime_policy import eligible
    scene=row.get('scene')
    if scene in eligible() and scene.startswith('space_'):
        if not owned_ship(row,s.bots[key],row.get('ship'),scene):raise RuntimeError('Owned pilot required for space disconnect')
        # The authored logoutServer command forbids pilotingShip (state 29).
        # The unchanged client menu disconnects to character selection instead.
        # Reuse the existing driver transport action, then wait for the full
        # native link-dead unload/save; a closed socket is not save proof.
        peer.send('quit');peer.wait('disconnect_requested',10);mode='space_disconnect'
    else:
        peer.send('logout');peer.wait('logout_accepted',45);mode='ground_logout'
    s.report.setdefault('offline_exit_modes',[]).append({'bot':key,'mode':mode})
    if peer.process.wait(timeout=10)!=0:raise RuntimeError('Offline actor failed normal logout')
    peer.close();s.report.setdefault('offline_events',[]).append({'bot':key,'events':peer.events})
    unloaded(s.project,s.bots[key]);del s.sessions[key]
    return saved(s.project,s.schema,s.bots[key]['player'])


def execute(s,family,prior=None):
    if family not in FAMILIES:raise ValueError('Reviewed linked/owned-ship family required')
    if family=='falcon':
        from retirement_falcon import execute as falcon
        return falcon(s,prior)
    keys=list(s.bots);a,b,c=keys;scene=FAMILIES[family]
    stage=json.loads((s.folder.parent.parent/'runtime/stage5-report.json').read_text())
    if not stage.get('distributed_shutdown') or not stage.get('world_save_probes') or any(stage['policy'].get(k)!=2 for k in ('rryatt_capacity','rryatt_maximum_instances','ord_capacity','ord_maximum_instances')):
        raise RuntimeError('Exact bounded Stage 7 fixture required')
    query=lambda command:run(['docker','exec',s.project+'-central-1','/fixture/protocol-bot-console','127.0.0.1',command])
    def worlds(count):
        end=time.monotonic()+180
        while time.monotonic()<end:
            _,instances,_,_=native_snapshots(query)
            active=[r for r in instances if r['definition']==scene and r['state'] not in ('stopped','retired')]
            if len(active)>2:raise RuntimeError('Exceeded two-world fixture bound')
            if (count is None and 1<=len(active)<=2 or len(active)==count) and all(r['state']=='running' and r['ready']=='1' for r in active):return active
            time.sleep(1)
        raise TimeoutError('Offline recovery world readiness')
    if prior is not None:
        if prior['retirement_target']['definition']!=scene:raise ValueError('Recovery family differs from setup')
        target=prior['retirement_target'];s.report['retirement_target']=target
        _,instances,_,_=native_snapshots(query)
        retired=[r for r in instances if r['definition']==scene and r['instance']==target['instance']]
        if len(retired)!=1 or retired[0]['state']!='retired' or retired[0]['ready']!='0':raise RuntimeError('Central restart forgot retired identity')
        before=prior['offline_actor']['before'];restored=s.row(c)
        assert_recovered(before,restored,s.bots[c],family,target['instance'])
        if not any(r['instance']==restored['instance'] and r['state']=='running' and r['ready']=='1' for r in instances):raise RuntimeError('Recovered destination not currently ready')
        fixed={k:s.row(k) for k in (a,b)}
        s.report['offline_recovery']={'before':before,'after':restored,'retired_after_restart':retired[0]}
        s.record('retired_offline_save_recovers_own_level_or_original_ship_and_point_after_central_restart')
        new_save=logout(s,c);s.restart(c);repeat=s.row(c)
        assert_recovered(restored,repeat,s.bots[c],family,target['instance'])
        if repeat['instance']!=restored['instance']:raise RuntimeError('Settled replacement save was not reused')
        for k in (a,b):assert_stationary(fixed[k],s.row(k))
        s.report['replacement_save']=new_save
        s.record('full_unload_and_repeat_login_retain_replacement_world_and_exact_point')
        if family=='rryatt':
            s.rryatt_guide(c,7);Demand(s,actors=(a,b)).exit(c);s.setup(c,'botKashyyykHome')
        else:s.land(c)
        s.record('recovered_actor_can_use_original_exit_without_moving_outside_witnesses')
        for k in (a,b):assert_stationary(fixed[k],s.row(k))
        return
    for k in keys:
        row=s.row(k)
        # A failed prior run may have left this dedicated actor saved in the
        # tested family. Re-enter normally, then use its authored exit first.
        if row['scene']=='kashyyyk_rryatt_trail':
            Demand(s,actors=(a,b)).exit(k);s.setup(k,'botKashyyykHome');row=s.row(k)
        elif row['scene']=='kashyyyk_main':
            s.setup(k,'botKashyyykHome');row=s.row(k)
        if row['group'] not in ('null','0'):
            s.sessions[k].send('leaveGroup');s.sessions[k].wait('group_command',10)
        if row['family']!='npe_space_station':raise RuntimeError('Ungrouped station baseline required')
    live=worlds(None);warm=min(live,key=lambda r:int(r['instance']))
    if family=='rryatt':
        p=Demand(s,actors=(a,b))
        for k in keys:s.setup(k,'botKashyyykSetup')
        for k in (a,b):p.enter(k)
        live=worlds(2);target=next(r for r in live if r['instance']!=warm['instance'])
        p.enter(c,1)
        for index in (0,2,4,6):s.rryatt_guide(c,index)
        for k in (a,b):p.exit(k);s.setup(k,'botKashyyykHome')
    else:
        # A prior space recovery may already have grown the empty peer. Fill
        # one known world through real leader affinity, rather than assume an
        # unbound dispatcher chooses the same world twice. The third stays solo.
        s.group(a,b)
        for k in (a,b):s.launch(k,s.setup_pilot(k))
        warm=next(r for r in worlds(2) if r['instance']==s.row(a)['instance'])
        if s.row(b)['instance']!=warm['instance']:raise RuntimeError('Grouped capacity fill split worlds')
        live=worlds(2);target=next(r for r in live if r['instance']!=warm['instance'])
        launched=s.launch(c,s.setup_pilot(c))
        # A launch-point save could pass even if recovery reset to the default
        # entrance. Reuse the recorded station-proximity fixture action first.
        setup=s.setup(c,'botLandingSetup');positioned=s.row(c)
        if (positioned['instance']!=launched['instance'] or not owned_ship(positioned,s.bots[c],launched['ship']) or
                max(abs(float(positioned[k])-float(launched[k])) for k in ('ship_x','ship_y','ship_z'))<100):
            raise RuntimeError('Non-default owned-ship point was not established')
        s.report['non_default_ship_point']={'launch':launched,'positioned':positioned,'setup':setup}
        for k in (a,b):s.land(k)
    before=s.row(c)
    if before['instance']!=target['instance']:raise RuntimeError('Offline actor did not enter actual grown world')
    s.report['retirement_target']=target
    save=logout(s,c)
    expected={k:before[('ship_' if family=='ord' else '')+k] for k in ('x','y','z')}
    if save['scene']!=scene or save['instance']!=target['instance'] or save['container']!=before['cell'] or any(not math.isfinite(float(expected[k])) or abs(float(save[k])-float(expected[k]))>.15 for k in ('x','y','z')):
        raise RuntimeError('Full offline save differs from actual placement')
    s.report['offline_actor']={'key':c,'before':before,'saved':save,'expected_save_point':expected}
    if family=='ord':s.report['offline_actor']['packed_ship']=saved(s.project,s.schema,before['ship'])
    # The offline actor is intentionally absent. Only the two live witnesses
    # supply stationary assertions; the offline save is independently re-read.
    witness=Scenarios(s.project,s.schema,s.folder,{k:s.bots[k] for k in (a,b)},s.sessions,s.report)
    retire_empty(witness,scene,target,stage['shutdown_nodes'])
    if saved(s.project,s.schema,s.bots[c]['player'])!=save:raise RuntimeError('Retirement rewrote the offline actor save')
    s.report['offline_save_unchanged_after_retirement']=True
    witness.record('real_offline_save_remains_in_retired_copy_until_next_login')
