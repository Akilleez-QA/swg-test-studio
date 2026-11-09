"""Ordinary owned MTP entry/close with an outside witness and authored exit."""
import json
import re
import time

from protocol_driver import bot_query, run
from protocol_scenarios import same_point


def require_owned_room(state, row, player, world=0):
    world_text=str(world)
    if isinstance(world,bool) or not re.fullmatch('0|[1-9][0-9]{0,18}',world_text) or int(world_text)>9223372036854775807:
        raise ValueError('Exact canonical private-room world required')
    if (not state or state.get('inside')!='true' or state.get('owned')!='true' or
            state.get('owner')!=player or state.get('root') in (None,'null','0') or
            not 0<int(state.get('session','0'))<=2147483647 or
            state.get('session')!=state.get('sequence') or state.get('limit')!='1' or
            state.get('scene')!='dungeon1' or state.get('instance')!=world_text or
            row.get('building')!=state['root'] or row.get('scene')!='dungeon1' or row.get('instance')!=world_text or
            row.get('room')!='entryb' or row.get('group') not in ('null','0') or
            not same_point(row,dict(x=3.6,y=-12,z=29.7),tolerance=.15)):
        raise ValueError('Original owned MTP entrance/lease is not proven: '+str(state)+' '+str(row))


def execute(s, cycles=(1,2), on_entry=None, on_exit=None,positive=False):
    actor,witness=s.bots
    stage=json.loads((s.folder.parent.parent/'runtime/stage5-report.json').read_text())
    if type(positive) is not bool:raise ValueError('Explicit typed private pilot required')
    if stage.get('private_mtp_pilot') is not True or 'corellia' not in stage.get('selected',[]):
        raise RuntimeError('Explicit MTP fixture with its original single Corellia exit required')
    if any(s.row(k).get('group') not in ('null','0') for k in s.bots):
        raise RuntimeError('Owned solo room scenario requires independent actors')
    observed=s.row(witness)
    if observed.get('family')!='npe_space_station':
        raise RuntimeError('Outside witness must remain at the retained station')
    world='0'
    if positive:
        from hosted_private_instances_fixture import validate
        validate(stage.get('hosted_private_instances_fixture'),stage.get('hosted_public_instances_fixture'))
        from inspect_client_fixture import native_snapshots
        def query(command):
            if command not in ('capacityContent','capacitySample','capacityScenes','capacityInstances'):
                raise ValueError('Read-only current host proof required')
            return run(['docker','exec',s.project+'-central-1','/fixture/client-console','127.0.0.1',command])
        _,instances,_,_=native_snapshots(query)
        ready=[r for r in instances if r.get('definition')=='dungeon1' and r.get('state')=='running' and
               r.get('ready')=='1' and r.get('recovered')=='0' and re.fullmatch('[1-9][0-9]{0,18}',r.get('instance',''))]
        if len(ready)!=1 or int(ready[0]['instance'])>9223372036854775807:
            raise ValueError('This private pilot requires one independently proved ready positive host')
        world=ready[0]['instance']
    if observed.get('scene')!='dungeon1' or observed.get('instance')!=world:
        raise ValueError('Witness is outside the explicitly proved private pilot host')
    report=s.report.setdefault('private_owned_lifecycle',{'entries':[],'actions':[],'observations':[]})
    report.update(positive=positive,world=world)
    close_requested=False

    def unchanged():
        row=s.row(witness)
        if (row['scene'],row['instance'],row['building'],row['cell'],row['group'])!=(observed['scene'],observed['instance'],observed['building'],observed['cell'],observed['group']) or not same_point(row,observed):
            raise RuntimeError('Outside witness moved or changed group during solo entry/close')

    def state():
        return bot_query(s.project,s.bots[actor],'botPrivateMtpInspect')

    def action(command,setup=False):
        item={'bot':actor,'kind':command,'setup':setup,'status':'requested'}
        report['actions'].append(item)
        if setup:s.report['setup'].append(item)
        result=bot_query(s.project,s.bots[actor],command)
        item['result']=result
        if not result or result.get('accepted')!='true':
            item['status']='failed'
            raise RuntimeError('Private owner action refused: '+command+' '+str(result))
        item['status']='queued' if result.get('queued')=='true' else 'accepted'
        return result

    def wait(predicate,label,timeout=90):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            current=state()
            if current and predicate(current):return current
            if current and (current.get('request_result')=='refused' or current.get('request_result','').startswith('error:')):
                raise RuntimeError(label+' refused in the actor callback: '+str(current))
            time.sleep(.5)
        raise TimeoutError(label+' did not settle: '+str(current))

    def ready():
        sent=time.monotonic()
        s.sessions[actor].send('awaitReady')
        s.sessions[actor].wait('action_ready',30,after=sent)

    def original_exit():
        wait(lambda r:r.get('inside')=='false' and r.get('scene')=='corellia' and r.get('instance')=='0','Original Corellia exit')
        ready();row=s.row(actor)
        if row.get('scene')!='corellia' or row.get('instance')!='0' or not same_point(row,dict(x=-516,y=28,z=-4433),tolerance=.2):
            raise RuntimeError('Private close missed its original Corellia exit: '+str(row))
        unchanged()
        return row

    def home():
        action('botPrivateMtpHome',setup=True)
        wait(lambda r:r.get('scene')=='dungeon1' and r.get('instance')==world and
             r.get('enabled')=='0' and r.get('phase')=='3','Original public station return')
        ready()

    def idle_roots():
        from private_lease_observation import collect
        deadline=time.monotonic()+180
        while True:
            run(['docker','exec',s.project+'-central-1','/fixture/client-console','127.0.0.1','capacitySample'])
            try:
                # The owner has already taken the authored Corellia exit.
                # Observe that same host through the stationary witness; never
                # invent a station position for the exited owner.
                collect(s,keys=(witness,))
                report['observations'].append(s.report['private_lease_observation'])
                return
            except ValueError as error:
                report.setdefault('pending_observations',[]).append(str(error))
                if time.monotonic()>=deadline:raise
                time.sleep(.5)

    try:
        initial=state()
        if initial and initial.get('inside')=='true':
            close_requested=True;action('botPrivateMtpClose');original_exit()
            s.report['setup'].append({'bot':actor,'kind':'normal_owner_close_to_clean_up_interrupted_test'})
        if state().get('scene')=='corellia':
            home()
        if s.row(actor).get('family')!='npe_space_station':
            raise RuntimeError('MTP fixture setup requires a retained station actor')
        before=s.row(actor)
        if before.get('scene')!='dungeon1' or before.get('instance')!=world:
            raise ValueError('Owner is outside the explicitly proved private pilot host')
        action('botPrivateMtpPrepare',setup=True)
        if not same_point(before,s.row(actor)) or s.row(actor)['building']!=before['building']:
            raise RuntimeError('Private phase setup unexpectedly moved the actor')
        idle_roots();unchanged()
        report['quiet_setup_seconds']=20
        time.sleep(20)
        prior=None
        for cycle in cycles:
            close_requested=False
            action('botPrivateMtpEnter')
            wait(lambda r:r.get('connected')=='true' and r.get('inside')=='true' and r.get('owned')=='true','Original private entry')
            ready();current=state();row=s.row(actor)
            require_owned_room(current,row,s.bots[actor]['player'],world)
            if positive and current.get('managed')!='true':raise ValueError('Native private admission is not enabled in the actual owner worker')
            identity=(current['root'],int(current['session']))
            if prior and (identity==prior or identity[0]==prior[0] and identity[1]<=prior[1]):
                raise RuntimeError('Repeated private entry reused the previous owner lease identity')
            report['entries'].append({'cycle':cycle,'lease':current,'arrival':row})
            if on_entry is not None:on_entry(current,row)
            prior=identity;unchanged()
            # Exercise the original five-second sequencer opening; this is not
            # a quest completion or an NPC cleanup-completion assertion.
            time.sleep(6)
            require_owned_room(state(),s.row(actor),s.bots[actor]['player'],world)
            s.record('ordinary_owned_solo_entry_'+str(cycle))
            close_requested=True;action('botPrivateMtpClose')
            report['entries'][-1]['exit']=original_exit()
            if on_exit is not None:on_exit(current,report['entries'][-1]['exit'])
            idle_roots();s.record('normal_owner_close_and_original_corellia_exit_'+str(cycle))
            if cycle==1:time.sleep(12)
        home()
        current=state();row=s.row(actor)
        if current.get('enabled')!='0' or current.get('phase')!='3' or row.get('family')!='npe_space_station' or row['building']!=before['building']:
            raise RuntimeError('Recorded fixture restoration did not return the original station copy')
        unchanged();s.record('private_owner_fixture_restored_without_summoning_witness')
    except Exception:
        # Never replay an uncertain close. Recover only a still-owned room
        # before the first close request, then use its ordinary authored exit.
        try:
            current=state()
            if current and current.get('inside')=='true' and not close_requested:
                close_requested=True;action('botPrivateMtpClose');original_exit()
            if state().get('scene')=='corellia':
                home()
        except Exception as cleanup:
            report['cleanup_error']=str(cleanup)
        raise
