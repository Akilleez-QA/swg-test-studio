"""Explicit private-entry pilot on the existing complete positive public hosts.

This authorizes fixture setup only. It neither certifies a private family nor
changes canonical configuration or the remaining four private host policies.
"""
import hashlib
import json
import re
from capacity import REPO
from hosted_private_entry_contract import model as private_contract
from hosted_public_instances_fixture import validate as public_policy

MARKER='hosted-private-instances-fixture'
NATIVE=(
 'src/engine/server/application/CentralServer/src/shared/CentralServer_PrivateResume.cpp',
 'src/engine/server/library/serverGame/src/shared/network/PrivateArrivalPublications.h',
 'src/engine/server/library/serverGame/src/shared/network/GroupTravelRequests.h',
 'src/engine/server/library/serverScript/src/shared/ScriptMethodsObjectMove.cpp')


def policy(public):
    public_policy(public)
    contract=private_contract();hosts=sorted(row['definition'] for row in public['hosts'])
    families=sorted({row['family'] for row in contract['entries'] if row['definition'] in hosts})
    if 'mtp_hideout_instance' not in families:
        raise ValueError('The existing complete MTP host is required')
    digest=hashlib.sha256(json.dumps(public,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return dict(schema_version=1,hosts=hosts,families=families,
                private_contract_sha256=contract['contract_sha256'],public_policy_sha256=digest,
                private_player_admission=True,canonical_release=False)


def validate(value,public):
    expected=policy(public)
    try:equal=type(value) is dict and json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(expected,sort_keys=True,separators=(',',':'),allow_nan=False)
    except (TypeError,ValueError):equal=False
    if not equal:
        raise ValueError('Exact source-derived private fixture policy required')
    return value


def supports(manifest):
    pins=manifest.get('native_sources') if isinstance(manifest,dict) else None
    if not isinstance(pins,list):return False
    for name in NATIVE:
        found=[r for r in pins if isinstance(r,dict) and r.get('path')==name]
        if len(found)!=1 or found[0].get('sha256')!=hashlib.sha256((REPO/name).read_bytes()).hexdigest():return False
    return True


def clear(text):
    pattern=r'(?ms)^# '+MARKER+r' begin\n.*?^# '+MARKER+r' end\n?'
    starts=len(re.findall(r'(?m)^# '+MARKER+r' begin$',text))
    ends=len(re.findall(r'(?m)^# '+MARKER+r' end$',text))
    if starts!=ends or starts>1 or len(re.findall(pattern,text))!=starts:
        raise ValueError('Malformed owned private fixture block')
    return re.sub(pattern,'',text)


def disabled(text):
    plain=clear(text);section=''
    for line in plain.splitlines():
        if line.strip().startswith('['):section=line.strip()
        key,sep,value=line.strip().partition('=')
        if (sep and section in ('[CentralServer]','[GameServer]') and
                key=='capacityPrivatePlayerAdmissionEnabled' and value!='false'):
            raise ValueError('Unowned private admission flag must not survive fixture preparation')
    return plain


def configure(text,role,value,public):
    validate(value,public);plain=clear(text)
    if role not in ('central','game'):return plain
    section='';settings={}
    for line in plain.splitlines():
        if line.strip().startswith('['):section=line.strip()
        key,sep,val=line.strip().partition('=')
        if sep:settings.setdefault((section,key),[]).append(val)
    target='[CentralServer]' if role=='central' else '[GameServer]'
    for key in ('capacityAllFamiliesEnabled','capacityGroupTransferEnabled','capacityHostedPublicInstancesEnabled',
                'capacityEncounterLifecycleEnabled','capacityEncounterSaveEnabled'):
        if settings.get((target,key))!=['true']:
            raise ValueError('Explicit coordinated public/lifecycle gate required: '+key)
    if ('[CentralServer]','capacityPrivatePlayerAdmissionEnabled') in settings or ('[GameServer]','capacityPrivatePlayerAdmissionEnabled') in settings:
        raise ValueError('Private admission already belongs to another configuration source')
    if role=='central' and (settings.get((target,'zoneInstancePlayerAdmission'))!=['true'] or
                           settings.get((target,'capacityEncounterAutomaticBootstrapEnabled'))!=['true']):
        raise ValueError('Current native admission and automatic encounter bootstrap required')
    if settings.get(('[GameServer]','capacityPrivateMtpFixture'))!=['1']:
        raise ValueError('Explicit retained-schema MTP fixture required')
    trace='capacityHostedLoginTrace=true\n' if role=='game' else ''
    return plain.rstrip()+'\n# '+MARKER+' begin\n'+target+'\ncapacityPrivatePlayerAdmissionEnabled=true\n'+trace+'# '+MARKER+' end\n'
