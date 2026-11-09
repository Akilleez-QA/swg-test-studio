"""Typed Rryatt demand policy; one complete four-row set per canonical world."""
import re
import runtime_policy as base

SCENE='kashyyyk_rryatt_trail'
SHARED_HOST_EXITS={
    'kashyyyk_north_dungeons':('kashyyyk_main','kashyyyk_dead_forest'),
    'kashyyyk_south_dungeons':('kashyyyk_hunting',),
    'kashyyyk_pob_dungeons':('kashyyyk_main','kashyyyk_dead_forest'),
}
EXTRA={'rryatt_capacity','rryatt_maximum_instances','rryatt_growth_percent'}
RETIREMENT_KEY='automatic_retirement'
RR_KEYS={'capacityRryattGroupEnabled','capacityRryattInstancesEnabled','capacityRryattSetLimit',
         'capacityAutomaticRetirementEnabled'}

def base_state(state):
    fields={'schema_version','mode','growth_percent','epoch','maximum_instances','ord_maximum_instances','ord_capacity','public_world_capacity'}|EXTRA
    if (not isinstance(state,dict) or set(state) not in (fields,fields|{RETIREMENT_KEY}) or
            type(state['schema_version']) is not int or state['schema_version']!=4 or state['mode']!='npe_instances'):
        raise ValueError('Typed schema-4 Rryatt policy required')
    if RETIREMENT_KEY in state and type(state[RETIREMENT_KEY]) is not bool:
        raise ValueError('Invalid automatic retirement setting')
    for key,low,high in [('rryatt_capacity',2,16384),('rryatt_maximum_instances',1,64),('rryatt_growth_percent',25,90)]:
        if type(state[key]) is not int or not low<=state[key]<=high:raise ValueError('Invalid '+key)
    value={k:v for k,v in state.items() if k not in EXTRA|{RETIREMENT_KEY}};value['schema_version']=3
    return base.validate_state(value)

def validate_state(state):
    base_state(state);return state

def report(state,selected):
    if not {SCENE,'kashyyyk_main'}<=set(selected):raise ValueError('Rryatt demand requires the selected canonical trail and its Kachirho exit dependency')
    for host,exits in SHARED_HOST_EXITS.items():
        if host in selected and not set(exits)<=set(selected):raise ValueError('Selected shared host requires its authored exits: '+host)
    result=base.report(base_state(state),selected)
    result['pinned_shared_hosts']={host:list(exits) for host,exits in SHARED_HOST_EXITS.items() if host in selected}
    result.update(schema_version=4,rryatt_capacity=state['rryatt_capacity'],rryatt_maximum_instances=state['rryatt_maximum_instances'],rryatt_growth_percent=state['rryatt_growth_percent'],rryatt_copies_per_world=1,rryatt_active_rows=[0,1,2,3],rryatt_original_rows=24)
    result['retirement']=state.get(RETIREMENT_KEY,False)
    result['managed_definitions'].append(SCENE)
    result['warm_scenes']=[s for s in result['warm_scenes'] if s!=SCENE]
    result['maximum_game_workers']-=1
    result['maximum_game_workers']+=state['rryatt_maximum_instances']
    return result

def config(text,role,state,selected):
    capacity=report(state,selected);section='';clean=[]
    for line in text.splitlines():
        if line.startswith('['):section=line.strip()
        if section in ('[CentralServer]','[GameServer]') and (line.partition('=')[0].strip() in RR_KEYS or (line.startswith('capacityGroupWorldLimit=') and SCENE in line)):continue
        clean.append(line)
    result=base.config('\n'.join(clean)+'\n',role,base_state(state),selected)
    if role=='central':
        before=state['maximum_instances']+state['ord_maximum_instances'];after=before+state['rryatt_maximum_instances']
        needle='zoneInstanceMaximum='+str(before)+'\n'
        if result.count(needle)!=1:raise ValueError('Expected one owned instance worker bound')
        result=result.replace(needle,'zoneInstanceMaximum='+str(after)+'\n',1)
        result+=('# capacity-runtime begin\n[CentralServer]\ncapacityRryattGroupEnabled=true\ncapacityRryattInstancesEnabled=true\n'
                 f'capacityAutomaticRetirementEnabled={str(state.get(RETIREMENT_KEY,False)).lower()}\n'
                 f'zoneInstancePolicy="{SCENE} rryatt_trail players {state["rryatt_capacity"]} 1 {state["rryatt_maximum_instances"]} {state["rryatt_growth_percent"]}"\n'
                 f'capacityGroupWorldLimit="{SCENE} {state["rryatt_capacity"]}"\n# capacity-runtime end\n')
    if role=='game':
        lines=[];section=''
        for line in result.splitlines():
            if line.startswith('['):section=line.strip()
            if section=='[TaskManager]' and line.partition('=')[0]=='maximumLoad':line='maximumLoad='+str(capacity['maximum_game_workers']+1)
            lines.append(line)
        result='\n'.join(lines)+'\n'
        result+=('# capacity-runtime begin\n[GameServer]\ncapacityRryattGroupEnabled=true\ncapacityRryattInstancesEnabled=true\n'
                 f'capacityRryattSetLimit={state["rryatt_capacity"]}\n# capacity-runtime end\n')
    return result
