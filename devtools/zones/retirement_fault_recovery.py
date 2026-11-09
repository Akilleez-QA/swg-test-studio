#!/usr/bin/env python3
"""Saved live shutdown fault, proven-stop restart and fresh-generation acceptance."""
import argparse,json,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from protocol_driver import fixture,identity,unloaded,run
from inspect_client_fixture import native_snapshots
from protocol_preservation import snapshot
from protocol_test_sets import runtime_artifact
from retirement_live_fault import FAMILIES

def invoke(argv,log,folder):
    with log.open('x') as stream:subprocess.run(argv,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=1200)
    evidence=runtime_artifact(log,folder)
    return dict(command=argv,log=str(log),artifact=evidence),json.loads(Path(evidence['path']).read_text())

def needs_baseline_restart(instances,scene):
    if scene not in FAMILIES.values():raise ValueError('Reviewed fault family required')
    live=[r for r in instances if r['definition']==scene and r['state'] not in ('stopped','retired')]
    if (not 1<=len(live)<=2 or len({r['instance'] for r in live})!=len(live) or
            any(r['state']!='running' or r['ready']!='1' or
                any(not re.fullmatch('[1-9][0-9]{0,18}',r[k]) or int(r[k])>9223372036854775807
                    for k in ('instance','generation')) for r in live)):
        raise RuntimeError('Healthy one/two-copy fault baseline required; uncertain worlds need explicit recovery')
    return len(live)==2


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('folder','binary','overlay','jdk','console','retirement-console'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--family',choices=tuple(FAMILIES),required=True);p.add_argument('--bots',nargs=2,required=True)
    args=p.parse_args()
    if len(set(args.bots))!=2 or any(not re.fullmatch('[a-z]{3,16}',b) for b in args.bots):p.error('Two distinct dedicated bot identities required')
    project,schema,services=fixture(args.folder);base=args.folder.resolve()/'protocol-driver'
    bots=[identity(json.loads((base/(b+'.json')).read_text())) for b in args.bots]
    for bot in bots:unloaded(project,bot)
    original=snapshot(project,schema)
    output=base/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-retirement-'+args.family)
    output.mkdir(mode=0o700)
    report=dict(schema_version=1,project=project,schema=schema,family=args.family,passed=False,fully_unloaded=False,created_images=0,created_databases=0,client_source_changed=False,visual_gameplay_verified=False,steps=[])
    common=['--folder',str(args.folder),'--binary',str(args.binary),'--bots',*args.bots]
    restart=[sys.executable,'devtools/zones/protocol_fixture_restart.py','--folder',str(args.folder),'--overlay',str(args.overlay),'--jdk',str(args.jdk),'--console',str(args.console),'--rryatt','--distributed-shutdown','--retirement-console',str(args.retirement_console),'--bots',*args.bots]
    try:
        policy=json.loads((args.folder/'runtime/stage5-report.json').read_text())
        if (policy.get('occupied_retirement') or not policy.get('distributed_shutdown') or
                (policy['policy']['rryatt_capacity'],policy['policy']['ord_capacity'])!=(2,2)):
            raise RuntimeError('Exact standard two-seat distributed fault fixture required')
        query=lambda command:run(['docker','exec',project+'-central-1','/fixture/protocol-bot-console','127.0.0.1',command])
        instances=native_snapshots(query)[1]
        report['baseline_families']={scene:needs_baseline_restart(instances,scene) for scene in FAMILIES.values()}
        report['baseline_restart_required']=any(report['baseline_families'].values())
        if report['baseline_restart_required']:
            # Earlier growth/group suites legitimately leave two healthy copies.
            # The existing restart owns global zero-player proof, full saves,
            # Central-first stop, Oracle preservation and one-warm readiness.
            step,baseline=invoke(restart,output/'baseline-restart.log',args.folder);report['steps'].append(step)
            if not baseline.get('distributed_shutdown_preserved'):raise RuntimeError('Baseline restart lost retirement gates')
        step,fault=invoke([sys.executable,'devtools/zones/protocol_scenarios.py',*common,'--scenario','retirement_fault_'+args.family],output/'fault.log',args.folder);report['steps'].append(step)
        old=fault['retirement_target'];report['old_generation']=old
        step,maintenance=invoke(restart,output/'restart.log',args.folder);report['steps'].append(step)
        if not maintenance.get('distributed_shutdown_preserved'):raise RuntimeError('Restart lost retirement gates')
        step,wake=invoke([sys.executable,'devtools/zones/protocol_scenarios.py',*common,'--scenario','retirement_wake_'+args.family],output/'wake.log',args.folder);report['steps'].append(step)
        new=wake['recovered_world'];report['new_generation']=new
        if new['instance']!=old['instance'] or int(new['generation'])<=int(old['generation']):raise RuntimeError('Proven-stop recovery did not reuse the stopped ID with a higher generation')
        if wake['retirement_proofs']['state']!='retired':raise RuntimeError('Fresh generation did not complete distributed retirement')
        # Markers must survive every supervisor/container recreation. New
        # generation retirement creates separate receipts, never overwrites old.
        marker=FAMILIES[args.family]+'-'+old['instance']+'-'+old['generation']+'.fence'
        for entry in fault['partition']['markers']:
            value=run(['docker','exec',project+'-'+entry['role']+'-1','cat','/world-launch-fences/'+marker])
            if value!=entry['operation']:raise RuntimeError('Maintenance removed or changed an old launch fence')
        for bot in bots:unloaded(project,bot)
        after=snapshot(project,schema);current=fixture(args.folder)[2]
        if after!=original or current['oracle']['Id']!=services['oracle']['Id'] or current['oracle']['Mounts']!=services['oracle']['Mounts']:raise RuntimeError('Recovery changed protected saves or Oracle identity/mounts')
        report.update(passed=True,fully_unloaded=True,original_characters_unchanged=True,originals_sha256=after['sha256'],oracle_container_id=current['oracle']['Id'],old_launch_fences_preserved=True)
    except Exception as exc:
        report['error']=str(exc);raise
    finally:
        (output/'result.json').write_text(json.dumps(report,indent=2)+'\n');print('Evidence: '+str(output),flush=True)

if __name__=='__main__':main()
