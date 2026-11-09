"""Saved public linked-set affinity and real ground-combat protocol scenarios."""
import math
import time
from protocol_driver import bot_query

SCENE='kashyyyk_rryatt_trail'

def anchor(row):
    if row.get('scene')!=SCENE or row.get('instance')!='0':
        raise RuntimeError('Expected reviewed runtime-zero Rryatt placement')
    value=int(row['buildout_row'])
    if not 0<=value<24 or row.get('instance_controller') in (None,'null','0'):
        raise RuntimeError('Unknown public linked-set identity')
    return value//4*4

def assert_translation(before,after,origin,destination):
    if (anchor(before)!=anchor(origin) or anchor(after)!=anchor(destination) or
        int(before['buildout_row'])%4!=int(after['buildout_row'])%4 or
        after['instance_controller']!=destination['instance_controller']):
        raise RuntimeError('Consolidation changed the level or selected the wrong linked set')
    for name in ('x','z'):
        expected=float(before[name])+float(destination[name])-float(origin[name])
        if not math.isfinite(expected) or abs(float(after[name])-expected)>.15:
            raise RuntimeError('Consolidation failed to preserve matching '+name+' position')
    # Both geometry and expected height must agree; platforms can settle from
    # the authored spawn height onto the native floor during the first frame.
    if (abs(float(after['y'])-float(before['y']))>3 or
        (before.get('on_floor')=='true' and after.get('on_floor')!='true')):
        raise RuntimeError('Consolidation lost the matching platform floor')

def assert_stationary(before,after):
    """Set affinity must not turn a guide action into a summon."""
    fields=('scene','instance','instance_controller','buildout_row','cell','pending','outstanding')
    if any(before.get(k)!=after.get(k) for k in fields):
        raise RuntimeError('Another player changed level, set or transfer state')
    for k in ('x','y','z'):
        if not math.isfinite(float(after[k])) or abs(float(before[k])-float(after[k]))>.15:
            raise RuntimeError('Another player moved during independent level travel')

class PublicGroup:
    def __init__(self,s,actors=None):
        self.s=s;self.a,self.b=actors if actors is not None else s.bots;self.workers={}
        if self.a==self.b or self.a not in s.bots or self.b not in s.bots:raise ValueError('Distinct retained actors required')
    def raw(self,key):
        row=bot_query(self.s.project,self.s.bots[key],worker=self.workers.get(key))
        if row is None and key in self.workers:row=bot_query(self.s.project,self.s.bots[key])
        if row:self.workers[key]=row["worker"]
        if not row or row.get('connected')!='true':raise RuntimeError('Dedicated bot disconnected')
        if row.get('fixture_version')!='stage6-public-group-v1':raise RuntimeError('Matching public-group fixture helper required')
        return row
    def wait(self,key,predicate,label,timeout=45):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            row=self.raw(key)
            if predicate(row):return row
            time.sleep(.25)
        raise TimeoutError(label+': '+str(row))
    def ready(self,key):
        requested=time.monotonic()
        self.s.sessions[key].send('awaitReady');self.s.sessions[key].wait('action_ready',30,after=requested)
        return self.s.row(key)
    def use(self,key,target):
        peer=self.s.sessions[key];peer.send('menu '+target);menu=peer.wait('menu',15)
        if menu['target']!=target or 21 not in [v['type'] for v in menu['items']]:
            raise RuntimeError('Original public gate action missing')
        peer.send('select '+target+' 21')
    def approach(self,key,exit=False):
        for attempt in range(8):
            target=self.s.setup(key,'botRryattExitSetup' if exit else 'botRryattSetup')['target']
            if self.raw(key).get('rryatt_gate_visible')=='true':return target
        raise RuntimeError('Original gate not visible from bounded floor approaches')
    def request_entry(self,key,selection,hold=False,target=None):
        if target is None:target=self.approach(key)
        peer=self.s.sessions[key]
        if hold:
            peer.send('holdArrival');peer.wait('arrival_held',10)
        self.use(key,target)
        page=peer.wait('sui',30)
        labels=[v['value'] for v in page['properties'] if v['property']=='Text' and v['value'].startswith('@travel/zone_transition:kachirho_rryatt ')]
        if page['name']!='Script.listBox' or len(labels)!=6:raise RuntimeError('Six original public choices required')
        peer.send('answer '+str(page['page'])+' ok '+str(selection));peer.wait('sui_answered',10)
    def finish_entry(self,key):
        peer=self.s.sessions[key]
        scene=peer.wait('scene_ready',90)
        if scene['scene']!='terrain/'+SCENE+'.trn':raise RuntimeError('Gate entered another scene')
        return self.s.row(key)
    def enter(self,key,selection):
        self.request_entry(key,selection)
        return self.finish_entry(key)
    def exit(self,key):
        self.use(key,self.approach(key,True));scene=self.s.sessions[key].wait('scene_ready',90)
        row=self.s.row(key)
        if scene['scene']!='terrain/kashyyyk_main.trn' or row['instance']!='0':raise RuntimeError('Original trail exit failed')
        return row
    def leave(self,key):
        self.s.sessions[key].send('leaveGroup');self.s.sessions[key].wait('group_command',10)
        for bot in self.s.bots:self.wait(bot,lambda r:r['group'] in ('null','0'),'Group departure did not settle',20)
    def settle_copy(self,key,controller):
        self.wait(key,lambda r:r['instance_controller']==controller and r['pending']=='false' and r['outstanding']=='false','Expected public linked arrival',90)
        return self.ready(key)
    def enemy(self,key):
        result=self.s.setup(key,'botRryattEnemySetup')
        row=self.wait(key,lambda r:r.get('enemy_serial')==result['serial'] and r.get('enemy_pending')=='false' and r['enemy'] not in ('null','0'),'Owned enemy creation receipt',15)
        self.s.report.setdefault('rryatt_enemy_setup',[]).append({'bot':key,'request':result,'observation':row})
        return row['enemy']
    def attack(self,key,target):
        # base_class.WEAPON_TYPE_UNARMED; command-table mask numbering differs.
        if self.raw(key).get("weapon_type")!="6":raise RuntimeError("Reviewed unarmed fixture weapon required")
        peer=self.s.sessions[key];peer.send('attack '+target);peer.wait('attack_requested',10)
        before=self.raw(key);health=int(before['enemy_health'])
        return self.wait(key,lambda r:r['combat']!='0' or int(r['enemy_health'])<health,'Normal ground attack did not start',15)
    def peace(self,key):
        start=time.monotonic()
        peer=self.s.sessions[key];peer.send('peace');peer.wait('peace_requested',10)
        self.s.setup(key,'botRryattEnemyCleanup')
        self.wait(key,lambda r:r['combat']=='0' and r.get('owned_enemy_count')=='0','Combat and owned enemy cleanup did not end',30)
        return start
    def hold_copy(self,key,controller,start,seconds,label):
        samples=[]
        while time.monotonic()-start<seconds:
            row=self.raw(key);samples.append({'seconds':time.monotonic()-start,'bot':row})
            if row['instance_controller']!=controller or row['scene']!=SCENE:raise RuntimeError(label)
            time.sleep(.2)
        self.s.report.setdefault('rryatt_quiet_samples',[]).append({'name':label,'samples':samples})
    def protection(self,key,controller):
        first=self.wait(key,lambda r:r['instance_controller']==controller and r['pending']=='false' and r['outstanding']=='false','Movable protected arrival',90)
        start=time.monotonic()
        if first['protected']!='true' or first['enemy'] in ('null','0') or first['can_attack']!='false' or first['can_be_attacked']!='false':
            raise RuntimeError('Arrival did not protect both combat directions: '+str(first))
        target=first['enemy'];health=int(first['enemy_health']);samples=[]
        peer=self.s.sessions[key];peer.send('attack '+target);peer.wait('attack_requested',10)
        while True:
            row=self.raw(key);elapsed=time.monotonic()-start;samples.append({'seconds':elapsed,'bot':row})
            if row['protected']=='false':break
            if row['combat']!='0' or row['can_attack']!='false' or row['can_be_attacked']!='false' or int(row['enemy_health'])<health:
                raise RuntimeError('Combat or damage bypassed the arrival window')
            if elapsed>15:raise RuntimeError('Arrival protection failed to expire')
            time.sleep(.2)
        if elapsed<8 or row['can_attack']!='true' or row['can_be_attacked']!='true':
            raise RuntimeError('Protection shortened or normal combat did not restore: '+str(row))
        self.s.report.setdefault('rryatt_protection',[]).append({'first':first,'samples':samples,'observed_seconds':elapsed})
        self.attack(key,target)
        # Destination fixture belongs to the leader. Only its explicit owner
        # can remove it; the normal peace command still comes from the attacker.
        peer.send('peace');peer.wait('peace_requested',10)
        self.s.setup(self.a,'botRryattEnemyCleanup')
        self.wait(key,lambda r:r['combat']=='0','Post-protection combat did not clear',20)
        return self.s.row(key)
    def guide_alone(self,key,index):
        from protocol_scenarios import matching_group
        other=next(k for k in self.s.bots if k!=key)
        before=self.s.row(other)
        leader=self.s.bots[self.a]['player']
        if not matching_group(self.raw(key),before,leader):raise RuntimeError('Independent level test lost its group')
        self.s.rryatt_guide(key,index)
        samples=[]
        for unused in range(3):
            after=self.raw(other);assert_stationary(before,after)
            if not matching_group(self.raw(key),after,leader):raise RuntimeError('Guide action lost its group')
            samples.append(after);time.sleep(.5)
        self.s.report.setdefault('rryatt_independent_levels',[]).append({'mover':key,'guide':index,'stationary':other,'before':before,'samples':samples})
    def reconnect(self,key):
        from protocol_driver import saved
        from protocol_scenarios import same_point
        s=self.s;other=next(k for k in s.bots if k!=key)
        before=s.row(key);fixed=s.row(other);old=s.sessions[key]
        old.send('logout');old.wait('logout_accepted',45)
        if old.process.wait(timeout=10)!=0:raise RuntimeError('Rryatt logout peer failed')
        deadline=time.monotonic()+240;retained=[]
        while True:
            row=bot_query(s.project,s.bots[key],worker=self.workers.get(key))
            assert_stationary(fixed,self.raw(other))
            if row is None:break
            if row['connected']!='false':raise RuntimeError('Logout did not disconnect native actor')
            if anchor(row)!=anchor(before) or row['instance_controller']!=before['instance_controller']:
                raise RuntimeError('Retained actor lost the linked set')
            retained.append(row)
            if time.monotonic()>=deadline:raise TimeoutError('Linked actor did not fully unload')
            time.sleep(2)
        stored=saved(s.project,s.schema,s.bots[key]['player'])
        if stored['scene']!=before['scene'] or stored['instance']!=before['instance'] or not same_point(before,stored):
            raise RuntimeError('Linked reconnect save changed the retained point')
        s.report.setdefault('rryatt_prior_peer_events',[]).append({'bot':key,'events':old.events})
        old.close();s.restart(key);after=s.row(key)
        assert_stationary(before,after);assert_stationary(fixed,self.raw(other))
        s.report.setdefault('rryatt_reconnects',[]).append({'bot':key,'before':before,'retained_samples':retained,'saved':stored,'after':after})
        # Two-member groups may dissolve on ordinary full logout. Re-form using
        # normal commands; group persistence is not part of this capacity gate.
        if self.raw(key)['group'] in ('null','0'):s.group(self.a,self.b)
    def affinity(self,pair,reconnect=False):
        s=self.s;a,b=self.a,self.b;first=pair*2
        left=self.enter(a,first);right=self.enter(b,first+1)
        if anchor(left)!=first*4 or anchor(right)!=(first+1)*4:raise RuntimeError('Ungrouped choices did not remain separate')
        # Original guides place the member deep in its own four-level set.
        for guide in (0,2,4,6):s.rryatt_guide(b,guide)
        before=s.record('public_split_deepest_level_pair_'+str(pair))
        s.group(a,b)
        after=self.settle_copy(b,left['instance_controller'])
        assert_translation(before[b],after,right,left)
        s.report.setdefault('rryatt_group_translations',[]).append({'pair':pair,'before':before[b],'after':after,'origin':right,'destination':left})
        s.record('group_preserves_member_level_and_matching_position_pair_'+str(pair))
        # The leader changes levels while the member stays at its own deepest
        # point. Member travel likewise must not move the leader at all.
        for guide in (0,2,4,6):self.guide_alone(a,guide)
        for guide in (7,5,3,1):self.guide_alone(b,guide)
        if reconnect:self.reconnect(b)
        for guide in (7,5,3,1):self.guide_alone(a,guide)
        if anchor(s.row(b))!=anchor(left):raise RuntimeError('Guide split the grouped linked set')
        self.exit(a);time.sleep(2)
        if anchor(s.row(b))!=anchor(left):raise RuntimeError('Leader exit summoned a trail member')
        # The existing member wins even when the leader elects another menu copy.
        entered=self.enter(a,first+1)
        if entered['instance_controller']!=left['instance_controller']:raise RuntimeError('Leader ignored the sole existing occupant')
        s.record('sole_member_affinity_overrides_leader_menu_pair_'+str(pair))
        self.leave(b)
        self.exit(a);self.exit(b)
    def combat(self,existing=None):
        s=self.s;a,b=self.a,self.b
        if existing is None:left=self.enter(a,0);right=self.enter(b,1)
        else:left,right=existing;s.report["rryatt_combat_reused_split"]={a:left,b:right}
        for key in (a,b):s.setup(key,'botRryattCombatSetup')
        left=s.row(a);right=s.row(b)
        self.enemy(a);enemy=self.enemy(b)
        self.attack(b,enemy);s.group(a,b);first=self.peace(b)
        self.hold_copy(b,right['instance_controller'],first,2,'First quiet interval bypassed')
        enemy=self.enemy(b);self.attack(b,enemy);second=self.peace(b)
        self.hold_copy(b,right['instance_controller'],second,9,'Second attack failed to restart quiet interval')
        after=self.protection(b,left['instance_controller'])
        assert_translation(right,after,right,left)
        s.record('continuous_ground_quiet_and_two_way_arrival_protection')
        self.leave(b)
        self.exit(b);self.enter(b,1);s.setup(b,'botRryattCombatSetup')
        separate=s.row(b);enemy=self.enemy(b)
        self.attack(b,enemy);s.group(a,b);self.leave(b);self.peace(b)
        self.hold_copy(b,separate['instance_controller'],time.monotonic(),15,'Group departure left a stale consolidation')
        s.record('group_departure_cancels_pending_public_consolidation')
        self.exit(a);self.exit(b)
    def execute(self,pair,mode="full"):
        from pathlib import Path
        import json
        s=self.s;s.report["rryatt_group_mode"]=mode;s.report["rryatt_pair"]=pair
        stage=json.loads((s.folder.parent.parent/'runtime/stage5-report.json').read_text())
        if stage.get('rryatt_public_group_pilot') is not True:raise RuntimeError('Explicit public group pilot required')
        for key in s.bots:
            row=self.raw(key)
            if row['group'] not in ('null','0'):self.leave(key)
        for key in s.bots:
            peer=s.sessions[key];peer.send('stand');peer.wait('stand_requested',10)
            self.wait(key,lambda r:r.get('posture')=='0','Normal standing posture',15)
        initial={key:s.row(key) for key in s.bots}
        reuse=(mode=="combat" and all(initial[k]['scene']==SCENE and initial[k]['instance']=='0' for k in (self.a,self.b)) and
               anchor(initial[self.a])==0 and anchor(initial[self.b])==4)
        for key in s.bots:
            row=initial[key]
            s.setup(key,'botRryattEnemyCleanup')
            if reuse:continue
            if row['scene']==SCENE:self.exit(key)
            elif row.get('family')=='npe_space_station':s.setup(key,'botKashyyykSetup')
            elif row['scene']!='kashyyyk_main':raise RuntimeError('Unexpected initial fixture scene')
        if mode not in ("full","affinity","combat","leases"):raise ValueError("Unknown public group mode")
        if mode!="combat":self.affinity(pair,reconnect=mode=="leases")
        if mode=="combat" or (mode=="full" and pair==0):self.combat((initial[self.a],initial[self.b]) if reuse else None)
        for key in s.bots:s.setup(key,'botKashyyykHome')
        s.record('public_group_suite_returns_ungrouped_bots_to_station')

def execute(s,pair=0,mode="full"):PublicGroup(s).execute(pair,mode)


def cleanup(s):
    """One bounded cleanup attempt per owned fixture enemy; never replay a mutation."""
    for key in s.bots:
        peer=s.sessions.get(key)
        if peer is not None and peer.process.poll() is None:
            try:
                peer.send('peace');peer.wait('peace_requested',5)
            except (RuntimeError,TimeoutError,BrokenPipeError):
                pass
        result=bot_query(s.project,s.bots[key],'botRryattEnemyCleanup')
        s.report.setdefault('rryatt_enemy_cleanup',[]).append({'bot':key,'result':result})
        if result is not None and result.get('accepted')!='true':
            raise RuntimeError('Owned temporary enemy cleanup was refused')
