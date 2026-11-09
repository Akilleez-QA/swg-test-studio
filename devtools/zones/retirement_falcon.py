"""Falcon session-timer cleanup followed by empty hosting-world retirement."""
import time,math,re
from protocol_driver import bot_query,saved,run,sql
from inspect_client_fixture import native_snapshots,rows
from protocol_scenarios import Scenarios
from retirement_live_fault import Live,fresh_sample
from rryatt_group import assert_stationary

SCENE='space_npe_falcon'

def assert_room(row,room,bot):
    if (row.get('scene')!=SCENE or row.get('pending')!='false' or row.get('outstanding')!='false' or
        row.get('protected')!='false' or room.get('phase')!='2' or
        room.get('owner')!=bot['player'] or room.get('player')!=bot['player'] or
        room.get('participants')!='1' or int(room.get('session','0'))<=0 or
        room.get('session')!=room.get('player_session') or room.get('room')!=row.get('building') or
        room.get('cell')!=row.get('cell') or room.get('instance')!=row.get('instance') or
        int(room.get('end','0'))<=int(room.get('now','0'))):
        raise RuntimeError('Falcon phase, solo ownership, cell or live session mismatch')

def inspect(s,key):
    row=s.row(key);room=bot_query(s.project,s.bots[key],'botFalconInspect')
    assert_room(row,room,s.bots[key]);return row,room

def saved_session(s,key):
    player=s.bots[key]['player']
    if not re.fullmatch('[1-9][0-9]{0,18}',player) or not re.fullmatch('WGC_[A-F0-9]{12}',s.schema):raise ValueError('Exact copied actor required')
    values=sql(s.project,s.schema,f"select json_object('name' value name,'value' value value) from {s.schema}.object_variables_view where object_id={player} and (name like 'space_dungeon_route.%' or name in ('npe.phase_number','currentInstanceControllerId','space_dungeon.dungeon_id','space_dungeon.session_id','space.launch.ship'));")
    return {r['name']:r['value'] for r in values}


def assert_saved(row,room,save,variables):
    # PositionUpdateTracker deliberately saves players aboard ships at the
    # ship's world origin/parent, not at an interior cell. The retained private
    # ticket identifies the exact owned room on the next ordinary login.
    expected={'npe.phase_number':'2','currentInstanceControllerId':room['room'],
        'space_dungeon.dungeon_id':room['room'],'space_dungeon.session_id':room['session'],
        'space.launch.ship':room['room'],'space_dungeon_route.dungeon_id':room['room'],
        'space_dungeon_route.session_id':room['session'],'space_dungeon_route.scene':SCENE,
        'space_dungeon_route.zone_instance_id':room['instance']}
    if (save.get('scene')!=SCENE or save.get('instance')!=room['instance'] or save.get('container')!='0' or
        any(variables.get(k)!=v for k,v in expected.items())):
        difference={k:dict(expected=v,actual=variables.get(k)) for k,v in expected.items() if variables.get(k)!=v}
        raise RuntimeError('Falcon save lost its exact private session route: '+str(dict(save=save,difference=difference)))
    for axis in ('x','y','z'):
        actual=float(save[axis]);point=float(row['ship_'+axis])
        if not math.isfinite(actual) or not math.isfinite(point) or abs(actual-point)>.15:raise RuntimeError('Falcon save lost its ship world point')


def travel(s,key,command,scene):
    # Explicit fixture request calls the original allocator/exit; it is not a
    # claim of Windows conversation or tutorial sequence acceptance.
    requested=time.monotonic()
    result=bot_query(s.project,s.bots[key],command)
    s.report['setup'].append(dict(bot=key,kind=command,result=result))
    if not result or result.get('accepted')!='true':raise RuntimeError('Falcon production request refused')
    ready=s.sessions[key].wait('scene_ready',120,after=requested)
    if ready.get('scene')!='terrain/'+scene+'.trn':raise RuntimeError('Falcon request reached wrong scene')
    return s.row(key)

def execute(s,prior=None):
    from retirement_offline import logout
    from world_shutdown_scenario import retire_empty
    a,b,c=list(s.bots);witness=Scenarios(s.project,s.schema,s.folder,{k:s.bots[k] for k in (a,b)},s.sessions,s.report)
    live=Live(witness,SCENE)
    if prior is not None:
        target=prior['retirement_target'];s.report['retirement_target']=target
        _,instances,_,_=native_snapshots(lambda command:live.query(command))
        old=[r for r in instances if r['definition']==SCENE and r['instance']==target['instance']]
        if len(old)!=1 or old[0]['state']!='retired' or old[0]['ready']!='0':raise RuntimeError('Restart reopened retired Falcon world')
        restored,room=inspect(s,c);before=prior['offline_actor']['before'];oldroom=prior['falcon_room']
        if (restored['instance']==target['instance'] or room['room']==oldroom['room'] or room['cell']==oldroom['cell'] or
            not any(r['definition']==SCENE and r['instance']==restored['instance'] and r['state']=='running' and r['ready']=='1' for r in instances)):
            raise RuntimeError('Expired Falcon did not receive a fresh private room in a live world')
        fixed={k:s.row(k) for k in (a,b)}
        s.report['offline_recovery']=dict(before=before,after=restored,room=room,retired_after_restart=old[0])
        s.record('expired_falcon_recovers_phase_two_in_fresh_solo_ship_after_retirement_and_restart')
        # Verify the production tutorial manager is attached to this exact owner/session.
        end=time.monotonic()+40
        while time.monotonic()<end:
            _,room=inspect(s,c)
            if room.get('sequence_player')==s.bots[c]['player'] and room.get('sequence_started')=='true' and room.get('manager_session')==room['session'] and room.get('han') not in (None,'null','0') and room.get('chewie') not in (None,'null','0'):break
            time.sleep(1)
        else:raise RuntimeError('Fresh Falcon tutorial manager did not initialize its owner/session')
        s.report['initialized_falcon_room']=room
        replacement_before=s.row(c);s.report['replacement_pre_logout_variables']=saved_session(s,c)
        replacement=logout(s,c);replacement_variables=saved_session(s,c)
        s.report['replacement_save']=replacement;s.report['replacement_variables']=replacement_variables
        assert_saved(replacement_before,room,replacement,replacement_variables)
        s.restart(c);again,repeat=inspect(s,c);s.report['repeat_falcon_room']=repeat
        if again['instance']!=restored['instance']:raise RuntimeError('Replacement login changed hosting world')
        if repeat['room']!=room['room'] or repeat['session']!=room['session']:raise RuntimeError('Unexpired private room/session was not retained')
        if (repeat.get('event_started')!='true' or repeat.get('han')!=room['han'] or repeat.get('chewie')!=room['chewie'] or
            repeat.get('end')!=room['end'] or int(repeat.get('main_index','-1'))<int(room['main_index'])):
            raise RuntimeError('Retained session restarted NPCs, extended its timer, or lost tutorial progress')
        s.report['replacement_save']=replacement;s.report['replacement_variables']=replacement_variables;s.report['repeat_falcon_room']=repeat
        s.record('replacement_falcon_full_unload_and_relogin_retains_unexpired_owned_session')
        for k in (a,b):assert_stationary(fixed[k],s.row(k))
        travel(s,c,'botFalconExit','dungeon1')
        s.record('production_falcon_exit_reaches_station_without_moving_outside_witnesses')
        for k in (a,b):assert_stationary(fixed[k],s.row(k))
        return
    # A failed attempt may leave the dedicated actor in a valid Falcon. Use
    # its original exit; do not alter its save or bypass private ownership.
    if s.row(c)['scene']==SCENE:travel(s,c,'botFalconExit','dungeon1')
    for k in s.bots:
        r=s.row(k)
        if r['group'] not in ('null','0'):
            s.sessions[k].send('leaveGroup');s.sessions[k].wait('group_command',10)
        if r['family']!='npe_space_station':raise RuntimeError('Station baseline required')
    warm=live.worlds(1)[0][0];claimed=False
    try:
        claimed=True;live.claim(warm['instance'],'fixtureRetirementFill')
        worlds,_=live.worlds(2);target=next(r for r in worlds if r['instance']!=warm['instance'])
        travel(s,c,'botFalconEnter',SCENE)
        before,room=inspect(s,c)
        if before['instance']!=target['instance']:raise RuntimeError('Falcon allocator did not choose grown world')
    finally:
        if claimed:live.claim(warm['instance'],'fixtureRetirementClear')
    s.report['retirement_target']=target;s.report['falcon_room']=room
    armed=bot_query(s.project,s.bots[c],'botFalconArm')
    if not armed or armed.get('accepted')!='true' or armed.get('room')!=room['room'] or armed.get('session')!=room['session']:raise RuntimeError('Exact dedicated room expiry was not armed')
    s.report['setup'].append(dict(kind='arm_exact_offline_session_expiry',result=armed))
    # Even the fixture expiry action must refuse an online/LD occupant.
    def expire():return run(['docker','exec',s.project+'-central-1','/fixture/falcon-retirement-console','127.0.0.1','fixtureRetirementExpire',str(before['worker']),room['room']])
    if expire()!='fixture=not-empty-owned-session':raise RuntimeError('Expiry fixture accepted a live occupant')
    save=logout(s,c)
    variables=saved_session(s,c);assert_saved(before,room,save,variables)
    s.report['offline_actor']=dict(key=c,before=before,saved=save,variables=variables)
    # With the original owner fully offline, a DIFFERENT ungrouped actor uses
    # the same hosting world, but must receive a separate unused private ship.
    claimed=False
    try:
        claimed=True;live.claim(warm['instance'],'fixtureRetirementFill',count=2)
        travel(s,b,'botFalconEnter',SCENE)
        second,second_room=inspect(s,b)
        _,_,snapshot,_=native_snapshots(lambda command:live.query(command))
        retained=[r for r in snapshot if r.get('controller')==room['room'] and r.get('zone_instance_id')==target['instance']]
        if len(retained)!=1 or retained[0].get('session')!=room['session']:raise RuntimeError('Offline owner session changed during another player entry')
        if (second['instance']!=target['instance'] or second_room['room']==room['room'] or
            second_room['session']==room['session']):raise RuntimeError('Different player reused an already-started Falcon session')
        s.report['different_player_fresh_session']=dict(original=room,new_player=second_room,offline_owner_retained=retained[0])
        witness.record('different_player_gets_fresh_solo_session_without_joining_offline_owners_started_session')
        armed_second=bot_query(s.project,s.bots[b],'botFalconArm')
        if armed_second.get('accepted')!='true':raise RuntimeError('Second dedicated room cleanup arm refused')
        travel(s,b,'botFalconExit','dungeon1')
        # The original exit may already have reset the room. If still leased,
        # expire only its armed session through the same production timer.
        response=run(['docker','exec',s.project+'-central-1','/fixture/falcon-retirement-console','127.0.0.1','fixtureRetirementExpire',str(second['worker']),second_room['room']])
        if response not in ('fixture=expiry-dispatched','fixture=not-empty-owned-session'):raise RuntimeError('Second room cleanup refused')
        s.report['setup'].append(dict(kind='second_owned_session_cleanup',room=second_room['room'],result=response))
    finally:
        if claimed:live.claim(warm['instance'],'fixtureRetirementClear')
    # A retained session must block retirement even with zero loaded players.
    fresh_sample(live.query)
    denied=live.query('capacityRetireEmpty',SCENE,target['instance'])
    if denied not in ('retirement=sampling_or_blocked','retirement=blocked'):raise RuntimeError('Unexpired owned Falcon session was retired')
    _,_,content,_=native_snapshots(lambda command:live.query(command))
    match=[r for r in content if r.get('controller')==room['room'] and r.get('zone_instance_id')==target['instance']]
    if len(match)!=1 or match[0].get('session')!=room['session']:raise RuntimeError('Retirement refusal lacks retained session proof')
    s.report['retained_session_blocker']=dict(reply=denied,content=match[0])
    if expire()!='fixture=expiry-dispatched':raise RuntimeError('Exact unloaded session expiry refused')
    s.report['setup'].append(dict(kind='advance_only_owned_room_deadline',handler='handleSessionTimerUpdate',room=room['room'],session=room['session'],synthetic=True))
    end=time.monotonic()+45
    while time.monotonic()<end:
        fresh_sample(live.query)
        _,_,content,_=native_snapshots(lambda command:live.query(command))
        local=[r for r in content if r.get('scene')==SCENE and r.get('zone_instance_id')==target['instance']]
        if len(local)==124 and all(r['session']=='-1' and r['players']=='0' and r['locked']=='0' for r in local):break
        time.sleep(.5)
    else:raise TimeoutError('Production timer did not release all Falcon sessions')
    s.report['expired_content']=local
    if expire()!='fixture=not-empty-owned-session':raise RuntimeError('Consumed expiry fixture replay was accepted')
    retire_empty(witness,SCENE,target,live.stage['shutdown_nodes'])
    if saved(s.project,s.schema,s.bots[c]['player'])!=save:raise RuntimeError('Timer/retirement rewrote offline player save')
    s.report['offline_save_unchanged_after_retirement']=True
    witness.record('falcon_timer_releases_session_before_empty_world_retirement_without_editing_offline_save')
