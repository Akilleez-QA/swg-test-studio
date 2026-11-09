#!/usr/bin/env python3
"""Recover authored dungeon portal roots outside area-row placement tables."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from capacity import REPO,SERVER_TABLES,SHARED_TABLES,read_table
from template_controller_evidence import Templates

TABLE=SERVER_TABLES/'buildout/dungeon1/snapshot_portal_restore.tab'
AREAS=SHARED_TABLES/'buildout/areas_dungeon1.tab'
HEADER=REPO/'src/engine/server/library/serverUtility/src/shared/HostedSnapshotContract.h'


def model(repo=REPO):
    repo=Path(repo)
    path=repo/TABLE
    rows=list(read_table(path))
    if not (repo/AREAS).is_file():raise ValueError('Original snapshot area placement required')
    placements=[(line,row) for line,row in read_table(repo/AREAS) if row['area']==TABLE.stem]
    if len(placements)!=1:raise ValueError('One unambiguous original snapshot area placement required')
    area_line,area=placements[0]
    bounds={k:float(area[k]) for k in ('x1','z1','x2','z2')}
    if (not all(math.isfinite(v) and abs(v)<=1000000 for v in bounds.values()) or
        bounds['x1']>=bounds['x2'] or bounds['z1']>=bounds['z2'] or int(area.get('useOrigin') or '0')):
        raise ValueError('Finite original snapshot area bounds without an origin override required')
    ids={}
    for line,row in rows:
        identity=int(row['objid'])
        if not 0<identity<2**63 or identity in ids:raise ValueError('Invalid or duplicate snapshot object ID')
        ids[identity]=(line,row)
    templates=Templates(repo)
    families={}
    for _,row in read_table(repo/SERVER_TABLES/'dungeon/space_dungeon.tab'):
        if row['dungeon'] in families:raise ValueError('Duplicate original dungeon identity')
        families[row['dungeon']]=row
    roots=[];seen=set()
    for line,row in rows:
        if int(row['container'])!=0:continue
        if int(row['cell_index'])!=0:raise ValueError('Top-level snapshot portal must use exterior cell zero')
        template=row['server_template_crc']
        proof=templates.resolve(template)
        family=proof['declarations'].get('space_dungeon.name')
        if not family:continue
        if not proof['complete'] or 'theme_park.dungeon.space_dungeon_controller' not in proof['scripts']:
            raise ValueError('Incomplete original snapshot dungeon controller')
        if row['scripts'].strip():raise ValueError('Unreviewed snapshot controller-script override')
        authored=families.get(family)
        if not authored or authored['planet']!='dungeon1':raise ValueError('Snapshot dungeon disagrees with original route')
        limit=int(authored['max_players'])
        if not 0<limit<=16384:raise ValueError('Invalid authored snapshot capacity')
        values=[float(row[k]) for k in ('px','py','pz','qw','qx','qy','qz')]
        if not all(math.isfinite(v) and abs(v)<1000000 for v in values):raise ValueError('Invalid snapshot transform')
        if abs(sum(v*v for v in values[3:])-1)>1e-5:raise ValueError('Snapshot orientation is not normalized')
        table_position=values[:3]
        # Match ServerBuildoutManager: only exterior/root positions add rect.x0
        # and rect.y0. Interior cell positions remain local to their parent.
        values[0]+=bounds['x1'];values[2]+=bounds['z1']
        if not (bounds['x1']<=values[0]<bounds['x2'] and bounds['z1']<=values[2]<bounds['z2']):
            raise ValueError('Snapshot root lies outside its authored area')
        key=(family,template,*values[:3])
        if key in seen:raise ValueError('Ambiguous snapshot dungeon slot')
        seen.add(key)
        children=[r for _,r in rows if int(r['container'])==int(row['objid'])]
        indices=[int(r['cell_index']) for r in children]
        if not children or sorted(indices)!=list(range(1,len(children)+1)) or any(r['server_template_crc']!='object/cell/cell.iff' for r in children):
            raise ValueError('Incomplete or ambiguous snapshot portal cell graph')
        crc=row['objvars'].split('|')
        if len(crc)!=5 or crc[:2]!=['portalProperty.crc','0'] or crc[3:]!=['$',''] or not 0<int(crc[2])<2**32:
            raise ValueError('Missing original portal CRC')
        roots.append(dict(definition='dungeon1',family=family,snapshot_id=int(row['objid']),template=template,
            position=values[:3],orientation=values[3:],cells=len(children),portal_crc=int(crc[2]),
            table_position=table_position,area_origin=[bounds['x1'],bounds['z1']],
            limit=limit,publisher='theme_park.dungeon.space_dungeon_controller',source_line=line))
    if not roots:raise ValueError('No original snapshot dungeon roots')
    inputs=dict(templates.inputs)
    for relative in (TABLE,AREAS,SERVER_TABLES/'dungeon/space_dungeon.tab',Path('devtools/zones/hosted_snapshot_contract.py'),
                     Path('devtools/zones/template_controller_evidence.py')):
        inputs[relative.as_posix()]=hashlib.sha256((repo/relative).read_bytes()).hexdigest()
    roots.sort(key=lambda r:(r['definition'],r['family'],r['snapshot_id']))
    digest=hashlib.sha256(json.dumps(dict(roots=roots,inputs=inputs),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return dict(schema_version=1,roots=roots,input_sha256=inputs,contract_sha256=digest)


def render(data):
    q=json.dumps
    lines=['// Generated by devtools/zones/hosted_snapshot_contract.py.',
        '// Authored placement evidence only; no launch, access or retirement permission.',
        '#ifndef INCLUDED_HostedSnapshotContract_H','#define INCLUDED_HostedSnapshotContract_H',
        '#include <cmath>','#include <string>','namespace HostedSnapshotContract','{',
        '    struct Root {char const *definition,*family,*objectTemplate,*publisher;unsigned long snapshotId,portalCrc;unsigned int cells,limit;float x,y,z,qw,qx,qy,qz;};',
        '    inline char const *sourceDigest(){return '+q(data['contract_sha256'])+';} '
        ,'    inline Root const *roots(unsigned int &count)','    {','        static Root const rows[]={']
    for r in data['roots']:
        text=','.join(q(r[k]) for k in ('definition','family','template','publisher'))
        integers=','.join(str(r[k]) for k in ('snapshot_id','portal_crc','cells','limit'))
        numbers=','.join(repr(v)+'f' for v in r['position']+r['orientation'])
        lines.append('            {'+text+','+integers+','+numbers+'},')
    lines+=['        };','        count=sizeof(rows)/sizeof(rows[0]);return rows;','    }',
        '    inline unsigned int count(std::string const &definition,std::string const &family)',
        '    {unsigned int size=0,total=0;Root const *values=roots(size);',
        '     for(unsigned int n=0;n<size;++n)if(definition==values[n].definition && family==values[n].family)++total;',
        '     return total;}',
        '    inline Root const *sourceSlot(std::string const &definition,std::string const &family,unsigned long snapshotId)',
        '    {unsigned int size=0;Root const *values=roots(size);Root const *found=0;',
        '     for(unsigned int n=0;n<size;++n)if(definition==values[n].definition && family==values[n].family && snapshotId==values[n].snapshotId)',
        '     {if(found)return 0;found=values+n;}return found;}',
        '    inline bool near(float a,float b,float tolerance){return std::fabs(a-b)<=tolerance;}',
        '    inline Root const *root(std::string const &definition,std::string const &family,std::string const &objectTemplate,',
        '        float x,float y,float z,float qw,float qx,float qy,float qz,unsigned int cells,unsigned long portalCrc)',
        '    {',
        '        unsigned int count=0;Root const *values=roots(count);Root const *found=0;',
        '        for(unsigned int n=0;n<count;++n)',
        '        {',
        '            Root const &r=values[n];',
        '            if(definition!=r.definition || family!=r.family || objectTemplate!=r.objectTemplate ||',
        '               cells!=r.cells || portalCrc!=r.portalCrc || !near(x,r.x,.001f) || !near(y,r.y,.001f) || !near(z,r.z,.001f))continue;',
        '            bool const direct=near(qw,r.qw,.00001f) && near(qx,r.qx,.00001f) && near(qy,r.qy,.00001f) && near(qz,r.qz,.00001f);',
        '            bool const reversed=near(qw,-r.qw,.00001f) && near(qx,-r.qx,.00001f) && near(qy,-r.qy,.00001f) && near(qz,-r.qz,.00001f);',
        '            if(!direct && !reversed)continue;',
        '            if(found)return 0;',
        '            found=&r;',
        '        }',
        '        return found;',
        '    }','}','#endif','']
    return '\n'.join(lines)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-header',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();data=model();expected=render(data)
    if args.write_header:HEADER.write_text(expected)
    if not HEADER.exists() or HEADER.read_text()!=expected:raise SystemExit('Snapshot-root contract is stale; regenerate explicitly')
    if args.output:
        with args.output.open('x') as stream:json.dump(data,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(roots=len(data['roots']),families=sorted({r['family'] for r in data['roots']}),contract_sha256=data['contract_sha256'])))
