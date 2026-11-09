"""Typed public-portal fixture policy; no positive host worlds or release authority."""
import re
from hosted_public_contract import contract
from hosted_capacity_layout import contracts as layout
from hosted_content import inventory

MARKER='hosted-public-fixture'


def policy(families,limit):
    if (not isinstance(families,list) or not families or len(families)>2 or
        any(not isinstance(f,str) for f in families) or len(set(families))!=len(families) or
        type(limit) is not int or not 2<=limit<=16384):
        raise ValueError('Distinct supported public families and an explicit finite room limit required')
    # Validate both views against one fresh source inventory. Rewalking the
    # complete template/buildout tree for each view is costly on a host mount,
    # and can mix two different input revisions inside a single policy value.
    snapshot=inventory();original=contract(snapshot);available={r['family']:r for r in original['controllers']}
    if not set(families)<=set(available):raise ValueError('Unsupported public portal family')
    values=[];source_layout=layout(snapshot);world_budgets={}
    for family in sorted(families):
        source=available[family]
        values.append(dict(definition=source['definition'],family=family,limit=limit,roots=source['roots']))
    for definition in {r['definition'] for r in values}-{'dungeon1'}:
        total=0
        for source in source_layout['types']:
            if source['definition']!=definition:continue
            if source['kind'] in (1,2) and source['static_footprint']:
                total+=len(source['rows'])*source['limit']
            elif source['kind']==3 and source['family'] in families:
                total+=len(source['rows'])*limit
            else:raise ValueError('Complete original public host footprint required for its aggregate budget')
        if not total:raise ValueError('Missing original public host footprint')
        world_budgets[definition]=min(16384,total)
    return dict(schema_version=1,families=values,source_contract_sha256=original['contract_sha256'],
        layout_sha256=source_layout['contract_sha256'],world_budgets=world_budgets,
        positive_host_worlds=False,canonical_release=False)


def clear(text):
    """Remove only our complete block, including when a profile is deselected."""
    pattern=r'(?ms)^# '+MARKER+r' begin\n.*?^# '+MARKER+r' end\n?'
    starts=len(re.findall(r'(?m)^# '+MARKER+r' begin$',text));ends=len(re.findall(r'(?m)^# '+MARKER+r' end$',text))
    if starts!=ends or starts>1 or len(re.findall(pattern,text))!=starts:
        raise ValueError('Malformed owned public fixture block')
    return re.sub(pattern,'',text)


def configure(text,role,value):
    if (not isinstance(value,dict) or set(value)!={'schema_version','families','source_contract_sha256','layout_sha256','world_budgets','positive_host_worlds','canonical_release'} or
        value.get('schema_version')!=1 or value.get('positive_host_worlds') is not False or value.get('canonical_release') is not False):
        raise ValueError('Explicit original-host public fixture policy required')
    rows=value['families']
    if not isinstance(rows,list) or not rows:raise ValueError('Public fixture families required')
    expected=policy([r['family'] for r in rows],rows[0]['limit'])
    if value!=expected:raise ValueError('Stale or modified public fixture contract')
    if role not in ('central','game'):return text
    # Remove only this tool's complete, paired block. Never accept arbitrary cfg
    # lines from a manifest or silently override an existing unreviewed setting.
    plain=clear(text)
    section='';enabled=False;existing=set()
    for line in plain.splitlines():
        if line.strip().startswith('['):section=line.strip()
        if section!=('[CentralServer]' if role=='central' else '[GameServer]'):continue
        key,sep,val=line.strip().partition('=')
        if key=='capacityAllFamiliesEnabled':
            if not sep or val!='true':raise ValueError('Native full-family activation must already be explicit')
            enabled=True
        if key=='capacityHostedPublicLimit':raise ValueError('Public policy already belongs to another config source')
        if key=='capacityGroupWorldLimit' and sep:
            words=val.strip().strip('"').split()
            existing.add(words[0] if words else '')
    if not enabled:raise ValueError('Public fixture requires the explicitly enabled native full-family path')
    lines=['# '+MARKER+' begin','[CentralServer]' if role=='central' else '[GameServer]']
    lines += ['capacityHostedPublicLimit="%s %s %d"'%(r['definition'],r['family'],r['limit']) for r in rows]
    if role=='central':
        for definition,maximum in sorted(value['world_budgets'].items()):
            if definition in existing:raise ValueError('Public aggregate world budget already configured externally')
            lines.append('capacityGroupWorldLimit="'+definition+' '+str(maximum)+'"')
    lines.append('# '+MARKER+' end')
    return plain.rstrip()+'\n'+'\n'.join(lines)+'\n'
