"""Explicit private-only Echo Base fixture; no public-world duplication."""
import hashlib
import json
import re
import copy
from capacity import REPO
from hosted_capacity_layout import contracts
from hosted_login_contract import model as login_contract
from hosted_private_entry_contract import model as entry_contract

MARKER='hoth-heroic-fixture'
HOST='adventure2'
FAMILY='echo_base'
NATIVE=(
 'src/engine/server/library/serverUtility/src/shared/HostedPrivateEntryContract.h',
 'src/engine/server/library/serverGame/src/shared/network/CentralConnection.cpp',
 'src/engine/server/library/serverGame/src/shared/network/CentralConnection_PrivateArrival.cpp',
 'src/engine/server/library/serverGame/src/shared/network/CentralConnection_PrivateResume.cpp')
_policy_cache=None


def policy():
    global _policy_cache
    if _policy_cache is not None:
        value,inputs=_policy_cache
        if any(not (REPO/name).is_file() or hashlib.sha256((REPO/name).read_bytes()).hexdigest()!=digest for name,digest in inputs.items()):
            raise ValueError('Hoth source changed during fixture planning; restart with fresh provenance')
        return copy.deepcopy(value)
    layout=contracts();login=login_contract();entry=entry_contract()
    types=[r for r in layout['types'] if r['definition']==HOST]
    entrances=[r for r in entry['entries'] if r['definition']==HOST]
    roots=[r for r in login['roots'] if r['definition']==HOST]
    if (len(types)!=1 or types[0]['family']!=FAMILY or types[0]['kind']!=2 or
            types[0]['limit']!=8 or len(types[0]['rows'])!=9 or
            len(entrances)!=2 or {r['cell'] for r in entrances}!={'r15','none'} or
            len(roots)!=9 or any(r['family']!=FAMILY for r in roots) or
            types[0]['exit_definitions']!=['dathomir']):
        raise ValueError('Complete original nine-area/two-team Hoth host required')
    value=dict(schema_version=1,definition=HOST,family=FAMILY,capacity=72,
                rows=types[0]['rows'],maximum_instances=2,exits=['dathomir'],
                source_contracts=dict(layout=layout['contract_sha256'],login=login['contract_sha256'],entry=entry['contract_sha256']),
                private_only=True,canonical_release=False)
    inputs={name:digest for model in (layout,login,entry) for name,digest in model['input_sha256'].items()}
    _policy_cache=(copy.deepcopy(value),inputs)
    return value


def validate(value):
    try:equal=type(value) is dict and json.dumps(value,sort_keys=True,allow_nan=False)==json.dumps(policy(),sort_keys=True,allow_nan=False)
    except (TypeError,ValueError):equal=False
    if not equal:
        raise ValueError('Exact source-derived Hoth private host policy required')
    return value


def supports(manifest):
    pins=manifest.get('native_sources',[]) if isinstance(manifest,dict) else []
    if not isinstance(pins,list):return False
    for name in NATIVE:
        found=[r for r in pins if isinstance(r,dict) and r.get('path')==name]
        if len(found)!=1 or found[0].get('sha256')!=hashlib.sha256((REPO/name).read_bytes()).hexdigest():return False
    return True


def clear(text):
    pattern=r'(?ms)^# '+MARKER+r' begin\n.*?^# '+MARKER+r' end\n?'
    starts=len(re.findall(r'(?m)^# '+MARKER+r' begin$',text))
    if starts!=len(re.findall(r'(?m)^# '+MARKER+r' end$',text)) or starts>1 or len(re.findall(pattern,text))!=starts:
        raise ValueError('Malformed owned Hoth fixture block')
    return re.sub(pattern,'',text)


def configure(text,role,value):
    validate(value);plain=clear(text)
    if role not in ('central','game'):return plain
    target='[CentralServer]' if role=='central' else '[GameServer]'
    section='';keys={}
    for line in plain.splitlines():
        if line.strip().startswith('['):section=line.strip()
        key,sep,val=line.strip().partition('=')
        if sep:keys.setdefault((section,key),[]).append(val)
    for name in ('capacityAllFamiliesEnabled','capacityGroupTransferEnabled','capacityPrivatePlayerAdmissionEnabled'):
        if keys.get((target,name))!=['true']:raise ValueError('Coordinated explicit private/group fixture required: '+name)
    lines=['# '+MARKER+' begin',target]
    if role=='central':
        for key in ('zoneInstancePolicy','capacityGroupWorldLimit'):
            if any(v.strip('"').split()[0]==HOST for v in keys.get((target,key),[])):
                raise ValueError('Hoth policy already owned by another source')
        maxima=keys.get((target,'zoneInstanceMaximum'),[])
        if not maxima or not all(v.isdigit() for v in maxima) or int(maxima[-1])+2>64:
            raise ValueError('Bounded native host limit required')
        lines+=['zoneInstanceMaximum='+str(int(maxima[-1])+2),
                'zoneInstancePolicy="adventure2 echo_base content 72 1 2 75"',
                'capacityGroupWorldLimit="adventure2 72"']
    else:
        loads=keys.get(('[TaskManager]','maximumLoad'),[])
        if not loads or not all(v.isdigit() for v in loads):raise ValueError('Owned supervisor load required')
        lines+=['[TaskManager]','maximumLoad='+str(int(loads[-1])+1)]
    lines+=['# '+MARKER+' end']
    return plain.rstrip()+'\n'+'\n'.join(lines)+'\n'


def additions(report):
    value=report.get('hoth_heroic_fixture')
    if value is None:return []
    validate(value)
    return [HOST]+value['exits']
