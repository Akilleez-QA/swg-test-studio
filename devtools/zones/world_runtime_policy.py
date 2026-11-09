"""Typed whole-world extension of the retained NPE/linked-set profile.

Recognition is not release acceptance. Operations must check matching native,
script and saved-suite provenance before applying a schema-5 profile.
"""
import runtime_policy as base
from instance_scope import load


def eligible():
    return {r['definition'] for r in load()['definitions'] if r['mode']=='piloted_space' or
            (r['mode']=='dynamic_area' and r['definition']!='kashyyyk_rryatt_trail')}


def validate_state(state):
    if (not isinstance(state,dict) or set(state)!={'schema_version','mode','base','world_families'} or
            type(state['schema_version']) is not int or state['schema_version']!=5 or state['mode']!='world_instances' or
            not isinstance(state['base'],dict) or state['base'].get('schema_version')!=4 or
            not isinstance(state['world_families'],list) or not state['world_families']):
        raise ValueError('Typed schema-5 world-family policy required')
    base.validate_state(state['base'])
    known=eligible()-{base.ORD};seen=set();total=state['base']['maximum_instances']+state['base']['ord_maximum_instances']+state['base']['rryatt_maximum_instances']
    for row in state['world_families']:
        if (not isinstance(row,dict) or set(row)!={'definition','capacity','minimum_ready','maximum_instances','growth_percent'} or
                not isinstance(row['definition'],str) or row['definition'] not in known or row['definition'] in seen):
            raise ValueError('World families must be distinct eligible canonical definitions')
        for key,low,high in [('capacity',2,16384),('minimum_ready',1,64),('maximum_instances',1,64),('growth_percent',25,90)]:
            if type(row[key]) is not int or not low<=row[key]<=high:raise ValueError('Invalid world '+key)
        if row['minimum_ready']>row['maximum_instances']:raise ValueError('World warm floor exceeds maximum')
        seen.add(row['definition']);total+=row['maximum_instances']
    if total>64:raise ValueError('World-family profile exceeds the native 64-world bound')
    return state


def report(state,selected):
    validate_state(state)
    names={r['definition'] for r in state['world_families']}
    if not names<=set(selected):raise ValueError('Every managed world family must be explicitly selected')
    result=base.report(state['base'],selected)
    result.update(schema_version=5,mode='world_instances',world_families=[dict(r) for r in state['world_families']])
    result['managed_definitions']+=sorted(names)
    result['warm_scenes']=[s for s in result['warm_scenes'] if s not in names]
    result['maximum_game_workers']+=sum(r['maximum_instances']-1 for r in state['world_families'])
    # Additional families remain separate from the accepted retirement profile
    # until their complete content/freeze/save/stop gates have passed.
    result['retirement_definitions']=[base.ORD,'kashyyyk_rryatt_trail'] if result['retirement'] else []
    return result


def config(text,role,state,selected):
    capacity=report(state,selected)
    result=base.config(text,role,state['base'],selected)
    if role=='central':
        before=state['base']['maximum_instances']+state['base']['ord_maximum_instances']+state['base']['rryatt_maximum_instances']
        after=before+sum(r['maximum_instances'] for r in state['world_families'])
        needle='zoneInstanceMaximum='+str(before)+'\n'
        if result.count(needle)!=1:raise ValueError('Expected one owned native world bound')
        result=result.replace(needle,'zoneInstanceMaximum='+str(after)+'\n',1)
        result+='# capacity-runtime begin\n[CentralServer]\ncapacityAllFamiliesEnabled=true\n'
        for r in state['world_families']:
            name=r['definition']
            result+=f'zoneInstancePolicy="{name} {name} players {r["capacity"]} {r["minimum_ready"]} {r["maximum_instances"]} {r["growth_percent"]}"\n'
            result+=f'capacityGroupWorldLimit="{name} {r["capacity"]}"\n'
        result+='# capacity-runtime end\n'
    if role=='game':
        section='';lines=[]
        for line in result.splitlines():
            if line.startswith('['):section=line.strip()
            if section=='[TaskManager]' and line.partition('=')[0]=='maximumLoad':line='maximumLoad='+str(capacity['maximum_game_workers']+1)
            lines.append(line)
        result='\n'.join(lines)+'\n# capacity-runtime begin\n[GameServer]\ncapacityAllFamiliesEnabled=true\n'
        # Ord also uses its original server-authored point under this profile.
        for name in [base.ORD]+sorted(r['definition'] for r in state['world_families']):result+='capacityWorldFamily='+name+'\n'
        result+='# capacity-runtime end\n'
    return result
