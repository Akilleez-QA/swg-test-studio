#!/usr/bin/env python3
"""Read isolated client fixture identity, routing and journal ownership."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from prepare_client_fixture_schema import run, target_root, REPO
from disposable_database import validate


def rows(text):
    lines=text.splitlines()
    if len(lines)<2:
        raise RuntimeError('Native diagnostic snapshot unavailable; retry after startup')
    header=lines[1].split('\t')
    return [dict(zip(header,line.split('\t'))) for line in lines[2:] if '\t' in line]


def native_snapshots(query, timeout=15, clock=time.monotonic, pause=time.sleep, include_text=False):
    """Refresh the short-lived observation before content-dependent readiness.

    Native collection is asynchronous. Registry changes can invalidate it, and
    its ten-second lifetime must include the subsequent instance-status query.
    Keep unknown/expired evidence unavailable; never invent an empty snapshot.
    """
    deadline=clock()+timeout
    refreshes=0
    while clock()<deadline:
        content=query('capacityContent')
        status=content.splitlines()[0] if content else ''
        if not status.startswith('schema=1 mode=observe_only state=collected '):
            if not status.startswith('schema=1 mode=observe_only state=pending '):
                query('capacitySample');refreshes+=1
            pause(.25)
            continue
        scenes=rows(query('capacityScenes'))
        instances=rows(query('capacityInstances'))
        checked=query('capacityContent')
        if not checked or checked.splitlines()[0]!=status:
            pause(.25)
            continue
        result=(scenes,instances,rows(checked),refreshes)
        return result+(checked,) if include_text else result
    raise RuntimeError('Fresh native content snapshot unavailable after bounded refresh')


def fixture_scene_selection(report):
    expected=['tatooine','tutorial','dungeon1','space_npe_falcon','space_ord_mantell']
    for key in ('kashyyyk_entry_pilot','private_mtp_pilot'):
        if key in report and type(report[key]) is not bool:
            raise ValueError('Typed fixture scene option required: '+key)
    if report.get('kashyyyk_entry_pilot') is True:
        expected += ['kashyyyk_main','kashyyyk_rryatt_trail']
    if report.get('private_mtp_pilot') is True:
        expected.append('corellia')
    from world_family_fixture import additions
    from hosted_public_selection import additions as public_additions
    from hosted_public_instances_fixture import additions as public_instance_additions
    from hoth_heroic_fixture import additions as hoth_additions
    expected=list(dict.fromkeys(expected+additions(report)+public_additions(report)+public_instance_additions(report)+hoth_additions(report)))
    if report.get('selected')!=expected:
        raise ValueError('Unexpected fixture pilot selection')
    return expected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='fresh evidence path')
    parser.add_argument('--expected-instances',type=int,choices=(1,2),default=2)
    parser.add_argument('--stage5',action='store_true',help='verify canonical Ord and the two additional admission journals')
    parser.add_argument('--expected-rryatt-instances',type=int,choices=range(1,65),default=1)
    parser.add_argument('--expected-ord-instances',type=int,choices=(1,2),default=1)
    parser.add_argument('--overlay',type=Path,help='verify all staged overlay files in the running game container')
    args=parser.parse_args()
    folder=args.folder.resolve(strict=True)
    root,_,volume=target_root(folder.parent)
    proof=json.loads((folder/'schema-report.json').read_text())
    stage=folder/'runtime'
    staged=json.loads((stage/'report.json').read_text())
    if (not proof.get('passed') or staged['schema']!=proof['schema'] or
            staged['project']!=root.name or not staged['schema'].startswith('WGC_') or
            args.output.exists()):parser.error('Verified isolated folder and fresh output required')
    release=json.loads((REPO/'StarWarsGalaxies/instance-release.json').read_text())
    compose=json.loads((stage/'compose.json').read_text())
    stage5=json.loads((stage/'stage5-report.json').read_text()) if args.stage5 else None
    if stage5 and (stage5.get('project')!=root.name or stage5.get('schema')!=staged['schema'] or stage5.get('stage')!=5):
        parser.error('Matching Stage 5 fixture preparation required')
    expected_counts={'space_npe_falcon':args.expected_instances}
    selection=['tatooine','tutorial','dungeon1']
    if args.stage5:
        # Validate the authored profiles once before taking a live snapshot.
        # Full source validation can take minutes on a Windows-mounted checkout.
        selection=fixture_scene_selection(stage5)
        expected_counts['space_ord_mantell']=args.expected_ord_instances
        if stage5.get('rryatt_demand_instances') is True:
            expected_counts['kashyyyk_rryatt_trail']=args.expected_rryatt_instances
        if stage5.get('whole_world_families'):
            expected_counts.update({row['definition']:row['minimum_ready'] for row in stage5['policy']['world_families']})
        if stage5.get('hosted_public_instances_fixture') is not None:
            from hosted_public_instances_fixture import HOSTS
            expected_counts.update({name:1 for name in HOSTS})
        if stage5.get('hoth_heroic_fixture') is not None:
            from hoth_heroic_fixture import HOST as HOTH_HOST
            expected_counts[HOTH_HOST]=1
    names=run(['docker','ps','-aq','--filter','label=com.docker.compose.project='+root.name]).split()
    inspected=json.loads(run(['docker','inspect']+names))
    services={row['Config']['Labels']['com.docker.compose.service']:row for row in inspected}
    validate(services['oracle'],root,volume)
    checks={}
    for role,pinned in release['roles'].items():
        row=services[role]
        checks[role]=row['Image']==pinned['image_id'] and row['State']['Running'] and \
            row['Config']['Labels'].get('whitengold.test.client')==staged['schema']
    def query(command,*arguments):
        return run(['docker','exec',root.name+'-central-1','/fixture/client-console',
                    '127.0.0.1',command]+list(arguments))
    scenes,instances,content,snapshot_refreshes=native_snapshots(query)
    ships=[row for row in content if row.get('family')=='npe_space' and row.get('scene')=='space_npe_falcon']
    counts={}
    for instance_id in sorted(set(row['zone_instance_id'] for row in ships)):
        local=[row for row in ships if row['zone_instance_id']==instance_id]
        counts[instance_id]={'ships':len(local),'reserved':sum(int(row['session'])>=0 for row in local),
            'free':sum(row['session']=='-1' for row in local),
            'game_ids':sorted(set(row['owner'] for row in local)),
            'free_controllers':[row['controller'] for row in local if row['session']=='-1']}
    journals={}
    journal_paths=[('central','/capacity-journal/instances'),('database','/login-journal/records')]
    if args.stage5:journal_paths += [('central','/capacity-journal/admission'),('central','/capacity-journal/family-logins')]
    for role,path in journal_paths:
        container=root.name+'-'+role+'-1'
        metadata=run(['docker','exec',container,'stat','-c','%u:%g %a',path])
        lock='owner' if role=='central' else '.lock'
        run(['docker','exec',container,'test','-f',path+'/'+lock])
        held=subprocess.run(['docker','exec',container,'flock','--exclusive','--nonblock',path+'/'+lock,'true'],
            text=True,capture_output=True).returncode==1
        journals[path]={'owner_mode':metadata,'exclusive':held}
    published={role:services[role]['NetworkSettings']['Ports'] for role in ('login','connection')}
    expected={('login',45053),('login',45060),('connection',45063),('connection',45062)}
    actual=set()
    for role,bindings in published.items():
        for private,hosts in bindings.items():
            for host in hosts or []:
                if host['HostIp']!='127.0.0.1' or private!=host['HostPort']+'/udp':
                    raise RuntimeError('Unexpected fixture ingress binding')
                actual.add((role,int(host['HostPort'])))
    active=[r for r in instances if r['state'] not in ('stopped','retired')]
    active_ids={r['instance'] for r in active if r['definition']=='space_npe_falcon'}
    active_counts={name:sum(r['definition']==name for r in active) for name in expected_counts}
    expected_scenes={(name,'0') for name in selection if name not in expected_counts} | \
        {(r['definition'],r['instance']) for r in active}
    overlay_check=None
    if args.overlay:
        overlay=args.overlay.resolve(strict=True)
        manifest_path=overlay/'manifest.json'
        manifest=json.loads(manifest_path.read_text())
        destinations={'bin':'/opt/whitengold/bin','lib':'/opt/whitengold/lib',
            'classes':'/opt/whitengold/data/sku.0/sys.server/compiled/game',
            'validation':'/opt/whitengold/validation'}
        lines=[]
        for name,row in manifest['files'].items():
            relative=Path(name)
            if (relative.is_absolute() or '..' in relative.parts or len(relative.parts)<2 or
                    relative.parts[0] not in destinations or '\n' in name or '\r' in name):
                raise ValueError('Unexpected overlay path: '+name)
            digest=row['sha256']
            if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid overlay digest')
            lines.append(digest+'  '+destinations[relative.parts[0]]+'/'+relative.relative_to(relative.parts[0]).as_posix())
        checked=subprocess.run(['docker','exec','-i',root.name+'-game-1','sha256sum','-c','-'],
            input='\n'.join(lines)+'\n',text=True,capture_output=True)
        overlay_check={'manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'files':len(lines),'verified':bool(lines) and checked.returncode==0 and
            len(checked.stdout.splitlines())==len(lines)}
        if not overlay_check['verified']:
            overlay_check['failures']=[line for line in checked.stdout.splitlines() if not line.endswith(': OK')]
            overlay_check['error']=checked.stderr
        if args.stage5:
            native_lines=[line for line in lines if '  /opt/whitengold/bin/' in line or '  /opt/whitengold/lib/' in line]
            native_checks={}
            for role in ('central','database'):
                tested=subprocess.run(['docker','exec','-i',root.name+'-'+role+'-1','sha256sum','-c','-'],
                    input='\n'.join(native_lines)+'\n',text=True,capture_output=True)
                native_checks[role]=bool(native_lines) and tested.returncode==0 and len(tested.stdout.splitlines())==len(native_lines)
            overlay_check['native_roles']=native_checks
            overlay_check['verified']=overlay_check['verified'] and all(native_checks.values())
    ready=all(checks.values()) and actual==expected and \
        all(v['owner_mode']=='0:0 700' and v['exclusive'] for v in journals.values()) and \
        {(r['scene'],r['instance']) for r in scenes if r.get('preload')=='finished' and r.get('heartbeat_fresh')=='1'}== \
        expected_scenes and \
        len(active)==sum(expected_counts.values()) and active_counts==expected_counts and all(r['state']=='running' and r['ready']=='1' for r in active) and \
        set(counts)==active_ids and all(c['ships']==124 for c in counts.values()) and \
        (overlay_check is None or overlay_check['verified'])
    result={'schema_version':1,'checked_at':datetime.now(timezone.utc).isoformat(),
        'project':root.name,'schema':staged['schema'],'images_match':checks,'scenes':scenes,
        'instances':instances,'content':counts,'journals':journals,'published':published,
        'expected_instances':args.expected_instances,'expected_definitions':expected_counts,'overlay':overlay_check,
        'ready':ready,'diagnostic_snapshot_refreshes':snapshot_refreshes,
        'client_gameplay_verified':False,'canonical_mutations':False}
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if not ready:raise SystemExit(1)


if __name__=='__main__':main()
