#!/usr/bin/env python3
"""Prove saved hosted geometry and original exits; never grant session access."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from capacity import REPO,SERVER_TABLES,SHARED_TABLES,read_table
from hosted_content import inventory
from hosted_capacity_layout import contracts
from hosted_snapshot_contract import model as snapshots,TABLE as SNAPSHOT_TABLE
from instance_scope import load as scope

HEADER=REPO/'src/engine/server/library/serverUtility/src/shared/HostedLoginContract.h'
HOSTS=('adventure1','adventure2','dungeon1','kashyyyk_north_dungeons',
       'kashyyyk_pob_dungeons','kashyyyk_south_dungeons')
IGNORED=('client_portal_restore','snapshot_portal_restore','snapshot_functional_restore',
 'snapshot_terminal_restore','snapshot_transport_restore','snapshot_collision_restore',
 'snapshot_inherited_functional_restore','snapshot_remaining_tangible_restore','snapshot_mob_spawner_restore')


def finite(values):
    if not all(math.isfinite(v) and abs(v)<=1000000 for v in values):
        raise ValueError('Bounded finite original coordinates required')
    return values


def model():
    report=inventory();layout=contracts(report);snapshot=snapshots()
    expected={r['definition'] for r in scope()['definitions'] if r['mode']=='session_host'}-{'space_npe_falcon'}
    if expected!=set(HOSTS):raise ValueError('Every dedicated session host requires explicit login geometry')
    inputs=dict(layout['input_sha256']);inputs.update(snapshot['input_sha256']);tables={}
    def table(relative):
        if relative not in tables:
            inputs[relative.as_posix()]=hashlib.sha256((REPO/relative).read_bytes()).hexdigest()
            tables[relative]=read_table(REPO/relative)
        return [r for _,r in tables[relative]]
    scene_order=[r['sceneName'] for r in table(SHARED_TABLES/'buildout/buildout_scenes.tab')]
    if len(set(scene_order))!=len(scene_order) or len(scene_order)>256:raise ValueError('Unique original scene order required')
    shared_id_source=Path('src/engine/shared/library/sharedGame/src/shared/core/SharedBuildoutAreaManager.cpp')
    native_source=Path('src/engine/server/library/serverGame/src/shared/core/ServerBuildoutManager.cpp')
    shared_text=(REPO/shared_id_source).read_text();native_text=(REPO/native_source).read_text()
    base=re.search(r'int BuildoutArea::getSharedBaseId\(\) const\s*\{\s*return -\(areaIndex\+1\)\*(\d+);\s*\}',shared_text)
    offset=re.search(r'const int cs_buildingObjIdOffset = (\d+);',native_text)
    if not base or not offset:raise ValueError('Original legacy allocator namespace requires review')
    stride,bound=int(base[1]),int(offset[1])
    if not 1<bound<stride:raise ValueError('Disjoint bounded legacy shared namespace required')
    for path in (shared_id_source,native_source):inputs[path.as_posix()]=hashlib.sha256((REPO/path).read_bytes()).hexdigest()
    families=[];areas=[];roots=[];cells=[];legacy_slots=[];entries=[];seen_roots=set();seen_cells=set()
    by_family={(r['scene'],r['name']):r for r in report['hosted_content']}
    for definition in HOSTS:
        area_rows=table(SHARED_TABLES/('buildout/areas_'+definition+'.tab'))
        for row,area in enumerate(area_rows):
            if area['area'] in IGNORED:continue
            bounds=finite([float(area[k]) for k in ('x1','z1','x2','z2')])
            if bounds[0]>=bounds[2] or bounds[1]>=bounds[3]:raise ValueError('Nonempty original area required')
            areas.append(dict(definition=definition,row=row,bounds=bounds))
        for item in layout['types']:
            if item['definition']!=definition:continue
            original=by_family[(definition,item['family'])]
            exits=[]
            if item['kind']==1:
                exits=[dict(destination=original['exit_scene'],point=finite([float(original['exit_position'][k]) for k in ('x','y','z')]))]
            elif item['kind']==2:
                exits=[dict(destination=e['target'],point=finite([float(e[k]) for k in ('x','y','z')])) for e in original['exits']]
            elif item['kind']!=3:raise ValueError('Unreviewed hosted login kind')
            # Current private team exits coincide. A future divergent team exit
            # needs its own authenticated team proof, not a default team guess.
            if exits and any(e!=exits[0] for e in exits):raise ValueError('Distinct team exits require explicit recovery proof')
            if item['kind']<=2 and (not exits or exits[0]['point']==[0.0,0.0,0.0]):
                raise ValueError('Explicit non-origin authored private exit required')
            families.append(dict(definition=definition,family=item['family'],kind=item['kind'],
                exit=exits[0] if exits else None,player_script=original.get('player_script','none')))
            if item['kind']==3:
                routes=original.get('entry_routes',[])
                if len(routes)!=1:raise ValueError('One original public recovery entrance requires explicit review')
                route=routes[0];parts=route['destination'].split(':')
                if len(parts)!=7 or parts[:3]!=['instance',item['family'],definition] or not re.fullmatch('[a-z][a-z0-9_]{0,48}',parts[3]):
                    raise ValueError('Exact original public named-cell route required')
                point=finite([float(value) for value in parts[4:]])
                if point==[0.0]*3:raise ValueError('Original public entrance must not use an origin fallback')
                entries.append(dict(definition=definition,family=item['family'],route=route['name'],cell=parts[3],point=point))
            for controller in original['controllers']:
                source=Path(controller['source']);objects=table(source)
                if not objects:raise ValueError('Nonempty original controller table required')
                legacy='objid' not in objects[0]
                if any(('objid' not in r)!=legacy for r in objects):raise ValueError('Mixed buildout schemas are invalid')
                authored=[r for line,r in tables[source] if line==controller['line'] and
                    (int(r['cell_index'])==0 if legacy else r['objid']==controller['source_object_id'] and int(r['container'])==0)]
                if len(authored)!=1:raise ValueError('One exact original controller root required')
                root=authored[0];source_id=0 if legacy else int(root['objid'])
                for row in controller['placement_rows']:
                    area=area_rows[row]
                    if area['area']!=controller['area'] or area.get('eventRequired') or int(area.get('useOrigin') or 0):
                        raise ValueError('Unconditional original area placement required')
                    mask=(scene_order.index(definition)*100+row+1)<<48
                    native_id=source_id^mask if source_id<0 else source_id
                    # A legacy allocator's ID also depends on native shared
                    # template portal/visibility metadata. Keep a row-only
                    # descriptor until that allocator proves the exact ID;
                    # zero is never accepted by root()/cell() as an identity.
                    if legacy:
                        roots.append(dict(definition=definition,family=item['family'],kind=item['kind'],row=row,root=0))
                        first=-(scene_order.index(definition)*100+row+1)*stride
                        legacy_slots.append(dict(definition=definition,family=item['family'],row=row,first=first,end=first+bound-1))
                        continue
                    key=(definition,native_id)
                    if key in seen_roots:raise ValueError('Ambiguous original root')
                    seen_roots.add(key)
                    roots.append(dict(definition=definition,family=item['family'],kind=item['kind'],row=row,root=native_id))
                    for child in objects:
                        if int(child['container'])!=source_id or child['server_template_crc']!='object/cell/cell.iff':continue
                        identity=int(child['objid']);identity=identity^mask if identity<0 else identity
                        if (definition,identity) in seen_cells:raise ValueError('Ambiguous original cell')
                        seen_cells.add((definition,identity))
                        cells.append(dict(definition=definition,cell=identity,root=native_id))
    snapshot_rows=table(SNAPSHOT_TABLE)
    for root in snapshot['roots']:
        identity=root['snapshot_id'];definition=root['definition']
        if (definition,identity) in seen_roots:raise ValueError('Snapshot root duplicates buildout geometry')
        seen_roots.add((definition,identity))
        roots.append(dict(definition=definition,family=root['family'],kind=1,row=-1,root=identity))
        for child in snapshot_rows:
            if int(child['container'])!=identity:continue
            if child['server_template_crc']!='object/cell/cell.iff':raise ValueError('Original snapshot portal graph required')
            cell=int(child['objid'])
            if (definition,cell) in seen_cells:raise ValueError('Snapshot cell duplicates buildout geometry')
            seen_cells.add((definition,cell));cells.append(dict(definition=definition,cell=cell,root=identity))
    if {r['definition'] for r in roots}!=set(HOSTS):raise ValueError('Every host requires proved original roots')
    for family in families:
        if not any((r['definition'],r['family'])==(family['definition'],family['family']) for r in roots):
            raise ValueError('Every hosted family requires proved login geometry')
    inputs['devtools/zones/hosted_login_contract.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for rows,keys in ((families,('definition','family')),(areas,('definition','row')),
                      (roots,('definition','root','row')),(cells,('definition','cell')),(legacy_slots,('definition','row')),
                      (entries,('definition','family'))):
        rows.sort(key=lambda r:tuple(r[k] for k in keys))
    data=dict(schema_version=1,layout_sha256=layout['contract_sha256'],snapshot_sha256=snapshot['contract_sha256'],
              families=families,areas=areas,roots=roots,cells=cells,legacy=legacy_slots,entries=entries,input_sha256=inputs)
    data['contract_sha256']=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return data


def render(data):
    q=json.dumps
    out=['// Generated by devtools/zones/hosted_login_contract.py.',
         '// Saved geometry/exit evidence only. Never session, access or launch authority.',
         '#ifndef INCLUDED_HostedLoginContract_H','#define INCLUDED_HostedLoginContract_H',
         '#include "HostedContentContract.h"','#include "HostedSnapshotContract.h"','#include "ZoneInstanceScope.h"',
         '#include <stdint.h>','#include <limits>','#include <string>',
         'namespace HostedLoginContract','{',
         '    struct Family {char const *definition,*name,*destination,*playerScripts;int kind;float x,y,z;};',
         '    struct Area {char const *definition;int row;float x1,z1,x2,z2;};',
         '    struct Root {char const *definition,*family;int row,kind;int64_t id;};',
         '    struct Cell {char const *definition;int64_t id,root;};',
         '    struct Legacy {char const *definition,*family;int row;int64_t first,end;};',
         '    struct Entry {char const *definition,*family,*route,*cell;float x,y,z;};',
         '    inline char const *sourceDigest(){return '+q(data['contract_sha256'])+';}',
         '    inline bool current(){return std::string(HostedContentContract::sourceDigest())=='+q(data['layout_sha256'])+' &&',
         '        std::string(HostedSnapshotContract::sourceDigest())=='+q(data['snapshot_sha256'])+';}']
    for name,typ,fields in (('families','Family',('definition','family','exit','player_script','kind')),
                            ('areas','Area',()),('roots','Root',()),('cells','Cell',()),('legacy','Legacy',()),('entries','Entry',())):
        out+=['    inline '+typ+' const *'+name+'(unsigned int &count)','    {','        static '+typ+' const rows[]={']
        for row in data[name]:
            if name=='families':
                e=row['exit'];values=','.join(q(v) for v in (row['definition'],row['family'],e['destination'] if e else '',row['player_script']))
                values+=','+str(row['kind'])+','+','.join(repr(v)+'f' for v in (e['point'] if e else [0.0]*3))
            elif name=='areas':values=q(row['definition'])+','+str(row['row'])+','+','.join(repr(v)+'f' for v in row['bounds'])
            elif name=='roots':values=','.join((q(row['definition']),q(row['family']),str(row['row']),str(row['kind']),str(row['root'])+'L'))
            elif name=='cells':values=','.join((q(row['definition']),str(row['cell'])+'L',str(row['root'])+'L'))
            elif name=='entries':values=','.join(q(row[key]) for key in ('definition','family','route','cell'))+','+','.join(repr(v)+'f' for v in row['point'])
            else:values=','.join((q(row['definition']),q(row['family']),str(row['row']),str(row['first'])+'L',str(row['end'])+'L'))
            out.append('            {'+values+'},')
        out+=['        };','        count=sizeof(rows)/sizeof(rows[0]);return rows;','    }']
    out+=['    inline bool finite(float v){float const m=1000000.0f;return v>=-m && v<=m;}',
     '    inline Family const *family(std::string const &scene,std::string const &name)',
     '    {if(!current())return 0;unsigned int count=0;Family const *rows=families(count);',
     '     for(unsigned int n=0;n<count;++n){if(scene==rows[n].definition && name==rows[n].name)return rows+n;}',
     '     return 0;}',
     '    inline int exitIndex(std::string const &scene,std::string const &name)',
     '    {if(!current())return 0;unsigned int count=0;Family const *rows=families(count);',
     '     for(unsigned int n=0;n<count;++n){if(scene==rows[n].definition && name==rows[n].name && rows[n].kind<=2 && rows[n].destination[0])return static_cast<int>(n+1);}',
     '     return 0;}',
     '    inline Family const *exitAt(int index)',
     '    {if(!current() || index<=0)return 0;unsigned int count=0;Family const *rows=families(count);',
     '     if(static_cast<unsigned int>(index)>count)return 0;',
     '     Family const &f=rows[index-1];',
     '     return f.kind<=2 && f.destination[0] && ZoneInstanceScope::mode(f.definition)==ZoneInstanceScope::SessionHost?',
     '         &f:0;}',
     '    inline Root const *root(std::string const &scene,int64_t id)',
     '    {if(!current() || !id)return 0;unsigned int count=0;Root const *rows=roots(count);',
     '     for(unsigned int n=0;n<count;++n){if(scene==rows[n].definition && id==rows[n].id)return rows+n;}',
     '     return 0;}',
     '    inline Root const *cell(std::string const &scene,int64_t id)',
     '    {if(!current() || !id)return 0;unsigned int count=0;Cell const *rows=cells(count);',
     '     for(unsigned int n=0;n<count;++n){if(scene==rows[n].definition && id==rows[n].id)return root(scene,rows[n].root);}',
     '     return 0;}',
     '    // Original parent namespaces identify source families only. They never',
     '    // prove a named cell, local point, current session or entry permission.',
     '    inline Root const *parentRoot(std::string const &scene,int64_t parent)',
     '    {',
     '        if(!current() || !parent)return 0;',
     '        Root const *r=cell(scene,parent);if(!r)r=root(scene,parent);if(r)return r;',
     '        unsigned int count=0;Legacy const *ls=legacy(count);Root const *result=0;',
     '        for(unsigned int n=0;n<count;++n)if(scene==ls[n].definition && parent>=ls[n].first && parent<ls[n].end)',
     '        {',
     '            unsigned int size=0;Root const *rs=roots(size);Root const *candidate=0;',
     '            for(unsigned int k=0;k<size;++k)if(scene==rs[k].definition && ls[n].row==rs[k].row && std::string(ls[n].family)==rs[k].family)',
     '            {candidate=rs+k;break;}',
     '            if(!candidate || (result && (std::string(result->family)!=candidate->family || result->row!=candidate->row)))return 0;',
     '            result=candidate;',
     '        }',
     '        return result;',
     '    }',
     '    inline Family const *source(std::string const &scene,int64_t container,int64_t actor,float x,float y,float z)',
     '    {',
     '        if(!current() || actor<=0 || !container || !finite(x) || !finite(y) || !finite(z))return 0;',
     '        Root const *r=root(scene,container);if(r)return family(scene,r->family);',
     '        if(container!=actor)return 0; // An unknown parent is never guessed from coordinates.',
     '        unsigned int count=0;Area const *rows=areas(count);int found=-1;',
     '        for(unsigned int n=0;n<count;++n)if(scene==rows[n].definition && x>=rows[n].x1 && x<=rows[n].x2 && z>=rows[n].z1 && z<=rows[n].z2)found=rows[n].row;',
     '        if(found<0)return 0;',
     '        Root const *rootsList=roots(count);Family const *result=0;',
     '        for(unsigned int n=0;n<count;++n)if(scene==rootsList[n].definition && found==rootsList[n].row)',
     '        {Family const *candidate=family(scene,rootsList[n].family);if(result && result!=candidate)return 0;result=candidate;}',
     '        return result;',
     '    }',
     '    // Saved-family evidence for old cells whose IDs depend on native template',
     '    // classification. The shared namespace AND original saved world row',
     '    // must agree. This cannot identify a cell or authorize session entry.',
     '    inline Family const *savedSource(std::string const &scene,int64_t parent,int64_t actor,float x,float y,float z)',
     '    {',
     '        if(!current() || actor<=0 || !finite(x) || !finite(y) || !finite(z))return 0;',
     '        Root const *r=cell(scene,parent);if(!r)r=root(scene,parent);',
     '        Family const *f=r?family(scene,r->family):0;',
     '        if(!parent || parent==actor)f=source(scene,actor,actor,x,y,z);',
     '        if(f)return f;',
     '        unsigned int count=0;Area const *as=areas(count);int row=-1;',
     '        for(unsigned int n=0;n<count;++n)if(scene==as[n].definition && x>=as[n].x1 && x<=as[n].x2 && z>=as[n].z1 && z<=as[n].z2)row=as[n].row;',
     '        Legacy const *ls=legacy(count);',
     '        for(unsigned int n=0;n<count;++n)if(scene==ls[n].definition && row==ls[n].row && parent>=ls[n].first && parent<ls[n].end)',
     '        {return family(scene,ls[n].family);}',
     '        return 0;',
     '    }',
     '    inline Family const *exitSource(std::string const &scene,int64_t parent,int64_t actor,float x,float y,float z)',
     '    {',
     '        if(!current() || actor<=0 || !finite(x) || !finite(y) || !finite(z))return 0;',
     '        Root const *r=x==0 && y==0 && z==0?parentRoot(scene,parent):0;',
     '        Family const *f=r?family(scene,r->family):savedSource(scene,parent,actor,x,y,z);',
     '        return f && exitIndex(scene,f->name)?f:0;',
     '    }',
     '    inline bool publicFamily(std::string const &scene,std::string const &name)',
     '    {Family const *f=family(scene,name);return f && f->kind==3;}',
     '    inline Entry const *entrance(std::string const &scene,std::string const &name)',
     '    {if(!current())return 0;unsigned int count=0;Entry const *es=entries(count);',
     '     for(unsigned int n=0;n<count;++n)if(scene==es[n].definition && name==es[n].family)return es+n;',
     '     return 0;}',
     '    // A missing, unrecognized parent can recover only to an authored public',
     '    // entrance. This never proves a cell or permits retaining local coordinates.',
     '    inline Family const *publicEntranceSource(std::string const &scene,int64_t parent,int64_t actor,float x,float y,float z)',
     '    {',
     '        if(!current() || actor<=0 || !finite(x) || !finite(y) || !finite(z))return 0;',
     '        Family const *f=savedSource(scene,parent,actor,x,y,z);if(f)return f->kind==3?f:0;',
     '        if(root(scene,parent) || cell(scene,parent))return 0;',
     '        unsigned int count=0;Legacy const *ls=legacy(count);',
     '        for(unsigned int n=0;n<count;++n)if(scene==ls[n].definition && parent>=ls[n].first && parent<ls[n].end)return 0;',
     '        f=source(scene,actor,actor,x,y,z);return f && f->kind==3?f:0;',
     '    }',
     '    // Descriptors and durable charges still require current native publisher',
     '    // and placement proofs. Recognizing a root is not room admission.',
     '    inline bool publicRoot(std::string const &scene,int64_t id,std::string const &name,int row)',
     '    {',
     '        if(!id || row< -1 || row>65535 || !publicFamily(scene,name))return false;',
     '        Root const *r=root(scene,id);',
     '        bool const npe=scene=="dungeon1" && (name=="npe_space_station" || name=="npe_space_dungeon");',
     '        if(r)return r->kind==3 && name==r->family && row==r->row;',
     '        unsigned int count=0;Legacy const *ls=legacy(count);',
     '        for(unsigned int n=0;n<count;++n)if(scene==ls[n].definition && name==ls[n].family && row==ls[n].row && id>=ls[n].first && id<ls[n].end)return true;',
     '        if(!npe || id<=0)return false;',
     '        if(row==-1)return true; // Original NPE publishers may own persisted roots.',
     '        Root const *rs=roots(count);',
     '        for(unsigned int n=0;n<count;++n)if(scene==rs[n].definition && name==rs[n].family && row==rs[n].row)return true;',
     '        return false;',
     '    }',
     '    inline bool publicRootIdentity(std::string const &scene,int64_t id)',
     '    {',
     '        if(!current() || !id)return false;',
     '        Root const *r=root(scene,id);if(r)return r->kind==3;',
     '        unsigned int count=0;Legacy const *ls=legacy(count);',
     '        for(unsigned int n=0;n<count;++n)if(scene==ls[n].definition && id>=ls[n].first && id<ls[n].end && publicFamily(scene,ls[n].family))return true;',
     '        return id>0 && scene=="dungeon1" && publicFamily(scene,"npe_space_station") && publicFamily(scene,"npe_space_dungeon");',
     '    }','}','#endif','']
    return '\n'.join(out)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--write-header',action='store_true');parser.add_argument('--output',type=Path)
    args=parser.parse_args();data=model();expected=render(data)
    if args.write_header:HEADER.write_text(expected)
    if not HEADER.exists() or HEADER.read_text()!=expected:raise SystemExit('Hosted login geometry is stale; regenerate explicitly')
    if args.output:
        with args.output.open('x') as stream:json.dump(data,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(hosts=len(HOSTS),families=len(data['families']),roots=len(data['roots']),
        row_only_roots=sum(not r['root'] for r in data['roots']),cells=len(data['cells']),contract_sha256=data['contract_sha256'],runtime_activated=False)))


if __name__=='__main__':main()
