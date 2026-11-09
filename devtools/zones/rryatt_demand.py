"""Real gate, guide, group and reconnect coverage for complete demand worlds."""
import json,re,time
from pathlib import Path
from protocol_driver import run,unloaded,saved
from rryatt_group import PublicGroup,SCENE,assert_stationary
from inspect_client_fixture import rows,native_snapshots

def menu_choice(instances,selection,offered):
    """Select numeric runtime order through the real lexical CWD-key order.

    public_instance_travel labels CWD's std::map iteration, not the durable
    journal's numeric order. Include the underscore delimiter: 10 sorts before
    1 in keys rryatt_trail_10_... and rryatt_trail_1_....
    """
    ready=[r['instance'] for r in instances if r['state']=='running' and r['ready']=='1']
    if type(selection) is not int or len(ready)!=offered or len(set(ready))!=len(ready) or not 0<=selection<len(ready):
        raise RuntimeError('Current complete menu/world identities required')
    if any(not re.fullmatch('[1-9][0-9]{0,18}',v) or int(v)>9223372036854775807 for v in ready):
        raise RuntimeError('Canonical positive runtime IDs required')
    wanted=sorted(ready,key=int)[selection]
    ordered=sorted(ready,key=lambda v:'rryatt_trail_'+v+'_')
    return ordered.index(wanted),wanted,ordered

class Demand(PublicGroup):
    def enter(self,key,choice=0):
        target=self.approach(key);peer=self.s.sessions[key];self.use(key,target)
        event=peer.wait_any(('sui','scene_ready'),90)
        if event['event']=='sui':
            labels=[v['value'] for v in event['properties'] if v['property']=='Text' and v['value'].startswith('@travel/zone_transition:kachirho_rryatt ')]
            if event['name']!='Script.listBox' or not 1<=len(labels)<=64 or not 0<=choice<len(labels):raise RuntimeError('Typed live-copy choices required')
            # Arrival protection can outlive the ten-second telemetry cache.
            # Refresh native readiness before correlating the visible menu.
            query=lambda command:run(['docker','exec',self.s.project+'-central-1','/fixture/protocol-bot-console','127.0.0.1',command])
            _,current,_,_=native_snapshots(query)
            offered=[r for r in current if r['definition']==SCENE and r['state'] not in ('stopped','retired')]
            index,wanted,ordered=menu_choice(offered,choice,len(labels))
            self.s.report.setdefault('rryatt_menu_choices',[]).append(dict(numeric_choice=choice,requested_world=wanted,menu_worlds=ordered,selected_row=index))
            peer.send('answer '+str(event['page'])+' ok '+str(index));peer.wait('sui_answered',10);event=peer.wait('scene_ready',90)
        elif choice:raise RuntimeError('Requested second copy before its native registration')
        if event['scene']!='terrain/'+SCENE+'.trn':raise RuntimeError('Wrong canonical trail definition')
        row=self.s.row(key)
        if int(row['instance'])<=0 or not 0<=int(row['buildout_row'])<4 or row['family']!='rryatt_trail':raise RuntimeError('Demand entry did not bind a complete original set')
        return row
    def instances(self):
        text=run(['docker','exec',self.s.project+'-central-1','/fixture/protocol-bot-console','127.0.0.1','capacityInstances'])
        return [r for r in rows(text) if r['definition']==SCENE and r['state'] not in ('stopped','retired')]
    def wait_growth(self,count):
        end=time.monotonic()+150
        while time.monotonic()<end:
            active=self.instances()
            if len(active)>count:raise RuntimeError('Rryatt exceeded its bounded complete-set count')
            if len(active)==count and all(r['state']=='running' and r['ready']=='1' for r in active):return active
            time.sleep(2)
        raise TimeoutError('Demand-created complete Rryatt set was not ready')

def execute(s):
    a,b=s.bots;p=Demand(s)
    stage=json.loads((s.folder.parent.parent/'runtime/stage5-report.json').read_text())
    if not stage.get('rryatt_demand_instances') or stage['policy']['rryatt_capacity']!=2 or stage['policy']['rryatt_maximum_instances']!=2:raise RuntimeError('Explicit bounded two-world/two-seat demand fixture required')
    for k in s.bots:
        row=s.row(k)
        if row['group'] not in ('null','0'):
            s.sessions[k].send('leaveGroup');s.sessions[k].wait('group_command',10)
    for k in s.bots:
        s.sessions[k].send('stand');s.sessions[k].wait('stand_requested',10);r=s.row(k)
        if r['scene']==SCENE:p.exit(k)
        elif r.get('family')=='npe_space_station':s.setup(k,'botKashyyykSetup')
        elif r['scene']!='kashyyyk_main':raise RuntimeError('Unexpected demand fixture baseline')
    first=p.enter(a);second=p.enter(b)
    if first['instance']!=second['instance']:raise RuntimeError('Unbound entries did not fill the existing ready set first')
    s.report['rryatt_demand_growth']=p.wait_growth(2)
    fixed=s.row(a)
    for index in (0,2,4,6):
        s.rryatt_guide(b,index);assert_stationary(fixed,p.raw(a))
    deep=s.record('live_capacity_grows_a_second_complete_set_and_keeps_four_levels')[b]
    old=s.sessions[b];old.send('logout');old.wait('logout_accepted',40);old.process.wait(timeout=10);old.close();unloaded(s.project,s.bots[b])
    s.report.setdefault('rryatt_demand_saves',[]).append(saved(s.project,s.schema,s.bots[b]['player']))
    s.restart(b);restored=s.row(b)
    assert_stationary(deep,restored)
    s.record('demand_login_restores_own_deep_level_and_exact_saved_point')
    # Both grown copies remain alive (retirement is a later stage). Ordinary
    # independent entry deliberately chooses the other copy before grouping.
    p.exit(b);p.exit(a);p.wait_growth(2)
    leader=p.enter(a,0);member=p.enter(b,1)
    if leader['instance']==member['instance']:raise RuntimeError('Independent menu choices did not select distinct live copies')
    for index in (0,2,4,6):s.rryatt_guide(b,index)
    before=s.row(b);fixed=s.row(a);s.group(a,b)
    p.wait(b,lambda r:r['instance']==fixed['instance'] and r['pending']=='false' and r['outstanding']=='false','Cross-world group consolidation',90)
    peer=s.sessions[b];peer.wait('scene_ready',30);after=s.row(b)
    if after['buildout_row']!=before['buildout_row'] or any(abs(float(after[k])-float(before[k]))>.15 for k in ('x','y','z')):raise RuntimeError('Consolidation changed own level or corresponding position')
    assert_stationary(fixed,p.raw(a));s.record('group_consolidates_canonical_worlds_at_each_members_own_level_and_point')
    fixed=s.row(b)
    for index in (0,2):s.rryatt_guide(a,index);assert_stationary(fixed,p.raw(b))
    fixed=s.row(a);s.rryatt_guide(b,7);assert_stationary(fixed,p.raw(a))
    s.record('leader_and_member_level_changes_never_transport_another_player')
    p.exit(b);p.exit(a)
    for k in s.bots:
        if p.raw(k)['group'] not in ('null','0'):
            s.sessions[k].send('leaveGroup');s.sessions[k].wait('group_command',10)
    for k in s.bots:s.setup(k,'botKashyyykHome')
    s.record('demand_scenario_returns_both_dedicated_actors_to_station')
