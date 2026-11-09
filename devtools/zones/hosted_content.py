"""Authored hosted-content contracts, independent of runtime release eligibility.

Locations and buildout rows are source identities, never live NetworkIds.
This inventory does not grant admission or mark a host safe to retire.
"""
import hashlib
import math
import re
from pathlib import Path

from capacity import REPO, SERVER_TABLES, content_inventory, load_catalog, read_table, scene_names
from template_controller_evidence import Templates


def _location(value, separator, label):
    parts = value.split(separator)
    if len(parts) != 4 or not parts[3]:
        raise ValueError('Missing authored location: ' + label)
    try:
        coordinates = [float(p) for p in parts[:3]]
    except ValueError as error:
        raise ValueError('Invalid authored coordinates: ' + label) from error
    if not all(math.isfinite(n) for n in coordinates):
        raise ValueError('Nonfinite authored coordinates: ' + label)
    # Preserve decimal spelling and cell/scene identity from the original table.
    return dict(zip(('x', 'y', 'z', 'target'), parts))


def _positive(value, default, label):
    value = value or str(default)
    if not re.fullmatch(r'[1-9][0-9]*', value):
        raise ValueError('Invalid authored capacity/time: ' + label)
    return int(value)


def inventory(repo=REPO, catalog=None, content=None):
    repo = Path(repo)
    known = scene_names(repo)
    catalog = load_catalog(known=known) if catalog is None else catalog
    content = content_inventory(repo, catalog) if content is None else content
    inputs = dict(content['input_sha256'])
    areas = content['areas']
    declarations = content['controller_declarations']
    hosted = []
    templates = Templates(repo)
    controller_cache = {}
    controller_gaps = []

    def table(name):
        relative = SERVER_TABLES / name
        path = repo / relative
        inputs[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return read_table(path)

    def placements(scene, area):
        return [dict(scene=a['scene'], area=a['area'], source=a['source'],
                     rows=[p['buildout_row'] for p in a['placements']])
                for a in areas if a['scene'] == scene and a['area'] == area]

    def controllers(scene, area, name):
        cache_key=scene,area,name
        if cache_key in controller_cache:return controller_cache[cache_key]
        explicit=[d for d in declarations if d['scene']==scene and
                  (d['area']==area or name in d['declarations'].values())]
        area_names={d['area'] for d in explicit}|{a['area'] for a in areas if a['scene']==scene and a['area']==area}
        found={(d['source'],d['line']):dict(d) for d in explicit}
        for candidate in sorted(area_names):
            relative=SERVER_TABLES/'buildout'/scene/(candidate+'.tab')
            for line,row in table('buildout/'+scene+'/'+candidate+'.tab'):
                # Root declarations, including non-building outdoor controllers.
                if row.get('container','0') not in ('0',''):continue
                template=row.get('server_template_crc','')
                try:inherited=templates.resolve(template)
                except ValueError as error:
                    controller_gaps.append(dict(scene=scene,area=candidate,source=relative.as_posix(),line=line,reason=str(error)))
                    continue
                if not inherited['complete']:
                    controller_gaps.append(dict(scene=scene,area=candidate,source=relative.as_posix(),line=line,missing=inherited['missing']))
                values=dict(inherited['declarations'])
                packed=dict(re.findall(r'(?:^|\|)(instance_name|isControllerObject|space_dungeon\.name|instance\.data_table)\|[04]\|([^|]+)',row.get('objvars','')))
                values.update(packed)
                scripts=list(dict.fromkeys(inherited['scripts']+[v for v in row.get('scripts','').split(':') if v]))
                if values.get('instance_name')!=name and values.get('space_dungeon.name')!=name:continue
                record=dict(scene=scene,area=candidate,source=relative.as_posix(),line=line,
                    source_object_id=row.get('objid',''),source_container_id=row.get('container',''),template=template,
                    scripts=scripts,declarations=values,placement_rows=[p['buildout_row'] for a in areas
                        if a['scene']==scene and a['area']==candidate for p in a['placements']],
                    template_sources=inherited['sources'],template_declarations_complete=inherited['complete'])
                found[(relative.as_posix(),line)]=record
        controller_cache[cache_key]=[found[k] for k in sorted(found)]
        return controller_cache[cache_key]

    for line, row in table('dungeon/space_dungeon.tab'):
        scene, exit_scene, name = row['planet'], row['exit_planet'], row['dungeon']
        if scene not in known or exit_scene not in known:
            raise ValueError('Unknown dungeon host or exit: ' + name)
        area = row.get('dungeon_area', '')
        hosted.append(dict(name=name, kind='dungeon', scene=scene,
            source=(SERVER_TABLES/'dungeon/space_dungeon.tab').as_posix(), line=line,
            area=area, placements=placements(scene, area),
            controllers=controllers(scene, area, name),
            max_players=_positive(row['max_players'], 8, name),
            time_limit=_positive(row['time_limit'], 3600, name),
            entry_cell=row.get('start_cell_name', ''), entry_radius=row['start_loc_radius'],
            session_types=row.get('instanceType') or 'dungeon_default',
            lockout=row.get('lockoutTimer') or '0',
            success_string=row.get('success_string',''), failure_string=row.get('failure_string',''),
            player_script=row.get('player_script',''),
            entry_position={axis: row['start_loc_'+axis] for axis in ('x','y','z')},
            exit_scene=exit_scene,
            exit_position={axis: row['exit_loc_'+axis] for axis in ('x','y','z')},
            exit_radius=row['exit_loc_radius'],
            ownership='single_player' if row['max_players']=='1' else 'session',
            runtime_registration_verified=False))

    for line, row in table('instance/instance_datatable.tab'):
        name = row['dungeon']
        matches = [a for a in areas if a['area'] == name]
        hosts = {a['scene'] for a in matches}
        if len(hosts) != 1:
            raise ValueError('Private content needs one authored host: ' + name)
        scene = next(iter(hosts))
        entrances, exits = [], []
        for suffix in ('one','two'):
            if row.get('enter_'+suffix):
                entrance = _location(row['enter_'+suffix], ',', name+' entry '+suffix)
                # Typed defaults apply only to an entrance which is actually used.
                exit_ = _location(row.get('exit_'+suffix) or '0,0,0,tatooine', ',', name+' exit '+suffix)
                if exit_['target'] not in known:
                    raise ValueError('Unknown private exit: ' + name)
                entrances.append(entrance); exits.append(exit_)
        if not entrances:
            raise ValueError('Private instance lacks an authored entrance: ' + name)
        maximum = _positive(row.get('max_players'), 8, name)
        minimum = int(row.get('min_players') or 0)
        if minimum < 0 or minimum > maximum:
            raise ValueError('Invalid private minimum: ' + name)
        hosted.append(dict(name=name, kind='private_instance', scene=scene, area=name,
            source=(SERVER_TABLES/'instance/instance_datatable.tab').as_posix(), line=line,
            placements=placements(scene,name), controllers=controllers(scene,name,name),
            entrances=entrances, exits=exits, min_players=minimum, max_players=maximum,
            time_limit=_positive(row.get('time_limit'),3600,name),
            lockout=row.get('lockoutTimer') or 'none', key_required=row.get('key_required') or 'none',
            player_script=row.get('player_script') or 'none', vehicle_allowed=row.get('vehicle_allowed')=='1',
            ownership='single_player' if maximum==1 else 'private_group',
            runtime_registration_verified=False))

    public = {}
    for line, row in table('travel/zone_transition.tab'):
        parts = row.get('destination','').split(':')
        if parts[0] != 'instance':
            continue
        if len(parts)!=7 or parts[2] not in known:
            raise ValueError('Invalid public-instance destination: ' + row['zoneLine'])
        name, scene = parts[1:3]
        key = name, scene
        public.setdefault(key,[]).append(dict(name=row['zoneLine'], line=line,
            destination=row['destination'], entry_cell=parts[3],
            position=_location(':'.join(parts[4:7])+':'+parts[3], ':', row['zoneLine']),
            initial_required_flag=row.get('initialRequiredFlag',''),
            final_required_flag=row.get('finalRequiredFlag',''), script=row.get('script','')))
    for (name, scene), routes in sorted(public.items()):
        observed = controllers(scene,name,name)
        logical_areas = {d['area'] for d in observed}
        hosted.append(dict(name=name, kind='public_instance', scene=scene,
            source=(SERVER_TABLES/'travel/zone_transition.tab').as_posix(), entry_routes=routes,
            placements=[p for area in sorted(logical_areas) for p in placements(scene,area)],
            controllers=observed, ownership='public', linked_levels=name=='rryatt_trail',
            runtime_registration_verified=False))
    keys = [(r['kind'],r['name']) for r in hosted]
    if len(keys)!=len(set(keys)):
        raise ValueError('Duplicate hosted content identity')
    inputs.update(templates.inputs)
    return dict(schema_version=1, scenes=sorted(known),
                template_controller_gaps=controller_gaps,
                hosted_content=sorted(hosted,key=lambda r:(r['scene'],r['kind'],r['name'])),
                input_sha256=inputs, runtime_registration_verified=False)


def main():
    import argparse
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='fresh private JSON report')
    args=parser.parse_args()
    report=inventory()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(schema_version=1,scenes=len(report['scenes']),
        hosted_content=len(report['hosted_content']),source_inputs=len(report['input_sha256']),
        runtime_registration_verified=False,path=str(args.output),
        sha256=hashlib.sha256(args.output.read_bytes()).hexdigest())))


if __name__=='__main__':
    main()
