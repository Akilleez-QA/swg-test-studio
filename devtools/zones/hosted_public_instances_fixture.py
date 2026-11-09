"""Explicit isolated positive public-host profile; never canonical release approval.

Whole-host budgets include every authored private, snapshot and public room.
The public login gate does not authorize access to a private session.
"""
import re
import copy

from hosted_content import inventory
from hosted_capacity_layout import contracts
from hosted_snapshot_contract import model as snapshots
from hosted_login_contract import model as login_contract

MARKER = 'hosted-public-instances-fixture'
HOSTS = ('dungeon1', 'kashyyyk_pob_dungeons')
PUBLIC = {'npe_space_station', 'npe_space_dungeon', 'nova_orion_station', 'myyydril_caverns'}


def policy(limit, maximum=2):
    if type(limit) is not int or not 2 <= limit <= 16384 or type(maximum) is not int or not 1 <= maximum <= 4:
        raise ValueError('Explicit finite public room and bounded host counts required')
    source = inventory(); layout = contracts(source); physical = snapshots(); login = login_contract()
    values = []
    for definition in HOSTS:
        families = {}
        exits = set()
        for row in layout['types']:
            if row['definition'] != definition:
                continue
            count = len(row['rows'])
            if row['kind'] == 1 and not row['static_footprint']:
                roots = [r for r in physical['roots'] if (r['definition'], r['family']) == (definition, row['family'])]
                if not roots or any(r['limit'] != row['limit'] for r in roots):
                    raise ValueError('Complete matching original snapshot footprint required')
                count = len(roots)
            if row['kind'] == 3:
                if row['family'] not in PUBLIC or row['limit'] or row['static_footprint']:
                    raise ValueError('Unreviewed public host family')
                room_limit = limit
            elif row['kind'] in (1, 2):
                room_limit = row['limit']
                exits.update(row['exit_definitions'])
            else:
                raise ValueError('Unreviewed hosted lifecycle')
            if not count or not 1 <= room_limit <= 16384 or count * room_limit > 1000000:
                raise ValueError('Incomplete or unbounded whole-host footprint')
            families[row['family']] = count * room_limit
        public = sorted(f for f in families if f in PUBLIC)
        capacity = sum(families.values())
        if not public or not exits or not 1 <= capacity <= 16384:
            raise ValueError('Complete public host and original returns required')
        values.append(dict(definition=definition, family=public[0], capacity=capacity,
                           families=families, exits=sorted(exits), maximum_instances=maximum))
    inputs = dict(layout_sha256=layout['contract_sha256'], snapshot_sha256=physical['contract_sha256'],
                  login_sha256=login['contract_sha256'])
    return dict(schema_version=1, hosts=values, public_limit=limit, source_contracts=inputs,
                positive_public_host_worlds=True, private_player_admission=False, canonical_release=False)


def validate(value):
    if not isinstance(value, dict) or not isinstance(value.get('hosts'), list) or not value['hosts']:
        raise ValueError('Typed positive public-host fixture policy required')
    expected = policy(value.get('public_limit'), value['hosts'][0].get('maximum_instances'))
    if value != expected:
        raise ValueError('Stale or modified positive public-host fixture policy')
    return value


def configuration_state(state,value,sources):
    """Derive the preparer's owned base budget before rendering any config."""
    from runtime_policy import base_profile,validate_state
    validate(value)
    if not isinstance(state,dict):raise ValueError('Typed fixture state required')
    profile=base_profile(state)
    if not isinstance(profile,dict) or type(profile.get('public_world_capacity')) is not int or not 50<=profile['public_world_capacity']<=16384:
        raise ValueError('Typed finite base public-world capacity required')
    if not isinstance(sources,(list,tuple)) or not all(isinstance(s,str) for s in sources) or not {'kashyyyk_dead_forest','space_nova_orion'}<=set(sources):
        raise ValueError('Both original public portal source worlds must be explicitly selected')
    dungeon=[r['capacity'] for r in value['hosts'] if r['definition']=='dungeon1']
    if len(dungeon)!=1:raise ValueError('One complete physical Dungeon1 host required')
    result=copy.deepcopy(state)
    target=result['base'] if result['schema_version']==5 else result
    target['public_world_capacity']=max(target['public_world_capacity'],dungeon[0])
    validate_state(result)
    return result


def clear(text):
    pattern = r'(?ms)^# ' + MARKER + r' begin\n.*?^# ' + MARKER + r' end\n?'
    starts = len(re.findall(r'(?m)^# ' + MARKER + r' begin$', text))
    ends = len(re.findall(r'(?m)^# ' + MARKER + r' end$', text))
    if starts != ends or starts > 1 or len(re.findall(pattern, text)) != starts:
        raise ValueError('Malformed owned public-host fixture block')
    return re.sub(pattern, '', text)


def configure(text, role, value):
    validate(value)
    if role not in ('central', 'game', 'database'):
        return text
    plain = clear(text)
    if role=='database':
        section=''
        for line in plain.splitlines():
            if line.strip().startswith('['):section=line.strip()
            if section=='[dbProcess]' and line.strip().partition('=')[0]=='capacityHostedSavedContextEnabled':
                raise ValueError('Saved-source capture already belongs to another configuration source')
        return plain.rstrip()+'\n# '+MARKER+' begin\n[dbProcess]\ncapacityHostedSavedContextEnabled=true\n# '+MARKER+' end\n'
    section = ''; keys = {}; definitions = set(); budgets = {}
    for line in plain.splitlines():
        if line.strip().startswith('['): section = line.strip()
        if section != ('[CentralServer]' if role == 'central' else '[GameServer]'): continue
        key, sep, val = line.strip().partition('=')
        if not sep: continue
        keys.setdefault(key, []).append(val)
        if key in ('zoneInstancePolicy', 'capacityGroupWorldLimit'):
            words = val.strip('"').split()
            if not words: raise ValueError('Malformed external host policy')
            if key == 'zoneInstancePolicy':definitions.add(words[0])
            else:
                if len(words)!=2 or not words[1].isdigit() or words[0] in budgets:
                    raise ValueError('One finite externally owned world budget required')
                budgets[words[0]]=int(words[1])
    if keys.get('capacityAllFamiliesEnabled') != ['true']:
        raise ValueError('Explicit full-family activation required')
    for key in ('capacityHostedPublicInstancesEnabled', 'capacityHostedLoginTrace', 'capacityNpePublicLimit', 'capacityHostedPublicLimit', 'npeMaxInstancePopulation'):
        if key in keys: raise ValueError('Public-host option already belongs to another source: ' + key)
    if role == 'central' and (definitions & set(HOSTS) or keys.get('zoneInstancePlayerAdmission') != ['true'] or
                              keys.get('capacityGroupTransferEnabled') != ['true']):
        raise ValueError('Explicit native admission/group gates and unconfigured hosts required')
    lines = ['# ' + MARKER + ' begin', '[CentralServer]' if role == 'central' else '[GameServer]',
             'capacityNpePublicLimit=' + str(value['public_limit'])]
    for definition, family in [('dungeon1', 'nova_orion_station'), ('kashyyyk_pob_dungeons', 'myyydril_caverns')]:
        lines.append('capacityHostedPublicLimit="%s %s %d"' % (definition, family, value['public_limit']))
    if role == 'central':
        maxima = keys.get('zoneInstanceMaximum', [])
        if len(maxima) != 1 or not maxima[0].isdigit(): raise ValueError('One owned native world bound required')
        # The last configuration value wins in the original ConfigFile reader.
        # Keep the old bound in its owning block; removing this block restores it.
        maximum = int(maxima[0]) + sum(r['maximum_instances'] for r in value['hosts'])
        if maximum > 64: raise ValueError('Complete fixture exceeds native world bound')
        lines += ['zoneInstanceMaximum=' + str(maximum), 'capacityHostedPublicInstancesEnabled=true', 'capacityHostedLoginTrace=true']
        for row in value['hosts']:
            if row['definition'] in budgets and budgets[row['definition']]<row['capacity']:
                raise ValueError('External world budget cannot undercount the complete physical host')
            lines.append('zoneInstancePolicy="%s %s content %d 1 %d 75"' %
                         (row['definition'], row['family'], row['capacity'], row['maximum_instances']))
            if row['definition'] not in budgets:
                lines.append('capacityGroupWorldLimit="%s %d"' % (row['definition'], min(16384, row['capacity'])))
    else:
        # The original NPE script and native sampler both consume this producer;
        # the Central capacity policy must agree with it exactly.
        lines += ['npeMaxInstancePopulation=' + str(value['public_limit']), 'capacityHostedPublicInstancesEnabled=true']
        section = ''; loads = []
        for line in plain.splitlines():
            if line.strip().startswith('['): section = line.strip()
            if section == '[TaskManager]' and line.startswith('maximumLoad='):
                loads.append(line.partition('=')[2])
        if len(loads) != 1 or not loads[0].isdigit(): raise ValueError('One owned game supervisor bound required')
        lines += ['[TaskManager]', 'maximumLoad=' + str(int(loads[0]) + sum(r['maximum_instances'] - 1 for r in value['hosts']))]
    lines.append('# ' + MARKER + ' end')
    return plain.rstrip() + '\n' + '\n'.join(lines) + '\n'


def additions(report):
    value = report.get('hosted_public_instances_fixture')
    if value is None: return []
    validate(value)
    return sorted(set(HOSTS) | {s for row in value['hosts'] for s in row['exits']})


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, required=True)
    parser.add_argument('--maximum', type=int, default=2)
    args = parser.parse_args()
    print(json.dumps(policy(args.limit, args.maximum), sort_keys=True, indent=2))
