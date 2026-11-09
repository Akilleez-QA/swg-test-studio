"""Read-only source contract for three original public-cell fixture targets."""
import hashlib
import math
import re
from pathlib import Path
from capacity import REPO,SERVER_TABLES,SHARED_TABLES,read_table
from template_controller_evidence import Templates
from studio_tool_bundle import TOOLS_ROOT

SOURCE_SCENES=('kashyyyk_dead_forest','kashyyyk_hunting','kashyyyk_main')
# Main remains an original geometry input; it is never a dynamic test target.
SCENES=('kashyyyk_dead_forest','kashyyyk_hunting')
# Hunting uses the original Rodian camp hut, away from the poacher combat camp.
ROOTS=(-30000,-3029978,-6030000)


def model(repo=REPO):
    repo=Path(repo);templates=Templates(repo);result=[];inputs={}
    scene_table=SHARED_TABLES/'buildout/buildout_scenes.tab'
    scene_order=[r['sceneName'] for _,r in read_table(repo/scene_table)]
    if len(scene_order)>256 or len(set(scene_order))!=len(scene_order):raise ValueError('Bounded unique original buildout scene order required')
    inputs[scene_table.as_posix()]=hashlib.sha256((repo/scene_table).read_bytes()).hexdigest()
    for scene,original in zip(SOURCE_SCENES,ROOTS):
        areas=SHARED_TABLES/('buildout/areas_'+scene+'.tab')
        indexed=list(enumerate(read_table(repo/areas)))
        selected=[(i,area) for i,(_,area) in indexed if area['area']==scene]
        if len(selected)!=1:raise ValueError('One original public buildout area required')
        index,area=selected[0]
        if int(area.get('useOrigin') or '0') or area.get('eventRequired',''):
            raise ValueError('Unconditional original public area required')
        table=SERVER_TABLES/'buildout'/scene/(scene+'.tab');rows=[r for _,r in read_table(repo/table)]
        if len({r['objid'] for r in rows})!=len(rows):raise ValueError('Unambiguous buildout rows required')
        roots=[r for r in rows if int(r['objid'])==original and int(r['container'])==0 and int(r['cell_index'])==0]
        if len(roots)!=1:raise ValueError('Exact original world root required')
        root=roots[0];proof=templates.resolve(root['server_template_crc'])
        if not proof['complete']:raise ValueError('Complete original root template required')
        for row in rows:
            declarations=templates.resolve(row['server_template_crc'])['declarations']
            if any(k in declarations or k+'|' in row['objvars'] for k in ('isControllerObject','instance_name','space_dungeon.name')):
                raise ValueError('Private/controller areas cannot supply public-cell setup')
        cells=[r for r in rows if int(r['container'])==original and int(r['cell_index'])==1 and r['server_template_crc']=='object/cell/cell.iff']
        if len(cells)!=1:raise ValueError('Exact first original portal cell required')
        point=[float(root['px'])+float(area['x1']),float(root['py']),float(root['pz'])+float(area['z1'])]
        if not all(math.isfinite(v) and abs(v)<=16000 for v in point):raise ValueError('Finite original root point required')
        # SharedBuildoutAreaManager::install assigns the global scene slot,
        # not merely the row within this scene's area table.
        scene_index=scene_order.index(scene);native_index=scene_index*100+index
        result.append(dict(scene=scene,root=original^((native_index+1)<<48),cell=int(cells[0]['objid'])^((native_index+1)<<48),
                           template=root['server_template_crc'],point=point,area_index=index,scene_index=scene_index,native_area_index=native_index))
        for path in (areas,table):inputs[path.as_posix()]=hashlib.sha256((repo/path).read_bytes()).hexdigest()
    inputs.update(templates.inputs)
    return dict(schema_version=1,targets=result,scene_order=scene_order,input_sha256=inputs,point_kind='bounded_fixture_search_checked_by_original_floor_reader')


def verify_source(repo=REPO):
    result=model(repo);source=(TOOLS_ROOT/'zones/fixtures/ground_cell_entry.java').read_text()
    def array(name):
        found=re.search(r'\b'+name+r'=\{(.*?)\};',source,re.S)
        if not found:raise ValueError('Missing typed fixture array: '+name)
        return found[1]
    for name,key in (('SCENES','scene'),('TEMPLATES','template')):
        if re.findall(r'"([^"]+)"',array(name))!=[r[key] for r in result['targets']]:raise ValueError('Fixture source identity changed: '+name)
    for name,key in (('ROOTS','root'),('CELLS','cell')):
        if [int(v) for v in re.findall(r'(-?[0-9]+)L',array(name))]!=[r[key] for r in result['targets']]:raise ValueError('Fixture native ID changed: '+name)
    if [int(v) for v in re.findall(r'[0-9]+',array('SCENE_ROWS'))]!=[r['scene_index'] for r in result['targets']]:raise ValueError('Fixture scene-order proof changed')
    points=re.findall(r'\{([^{}]+)\}',array('POINTS'))
    if len(points)!=3:raise ValueError('Three explicit source points required')
    for text,row in zip(points,result['targets']):
        values=[float(v.strip().removesuffix('f')) for v in text.split(',')]
        if len(values)!=3 or any(not math.isfinite(v) or abs(v-expected)>.01 for v,expected in zip(values,row['point'])):
            raise ValueError('Fixture root point differs from original buildout')
    return result
