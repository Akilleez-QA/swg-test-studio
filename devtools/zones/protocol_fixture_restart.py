#!/usr/bin/env python3
"""Saved, Oracle-preserving maintenance restart before cold demand growth."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from protocol_driver import fixture, identity, run, unloaded
from protocol_preservation import snapshot
from inspect_client_fixture import native_snapshots


def require_empty_fixture(query):
    text=native_snapshots(query,include_text=True)[4]
    if 'observed_players=0 (includes retained authoritative players)' not in text:
        raise RuntimeError('Fixture maintenance requires zero authoritative or retained players')
    return text


def require_retirement_profile(restored, previous, occupied):
    """Only the explicitly selected fixture budgets may change during restart."""
    if type(occupied) is not bool:
        raise ValueError('Explicit occupied-retirement selection required')
    expected = dict(previous['policy'])
    expected.update(rryatt_capacity=4 if occupied else 2, ord_capacity=5 if occupied else 2)
    if (any(restored.get(k) != previous.get(k) for k in ('distributed_shutdown', 'world_save_probes', 'shutdown_nodes')) or
            restored.get('policy') != expected or restored.get('occupied_retirement', False) != occupied or
            any(restored.get(k) != previous.get(k) for k in
                ('automatic_retirement','automatic_retirement_idle_ms',
                 'automatic_retirement_uptime_ms','automatic_retirement_cooldown_ms'))):
        raise RuntimeError('Maintenance changed reviewed shutdown policy or participants')
    return expected != previous['policy']


def stopped_warm_wakes(scenes, instances, rryatt):
    """Return only managed fixture families whose saved workers are proven stopped."""
    baseline = {'tatooine', 'tutorial', 'dungeon1'}
    if rryatt:
        baseline.add('kashyyyk_main')
    if not baseline.issubset({r['scene'] for r in scenes if r['instance']=='0' and
                               r['preload']=='finished' and r['heartbeat_fresh']=='1'}):
        return []
    names = ['space_npe_falcon', 'space_ord_mantell']
    if rryatt:
        names.append('kashyyyk_rryatt_trail')
    wakes = []
    for name in names:
        family = [r for r in instances if r['definition']==name]
        if any(r['state'] not in ('stopped', 'retired') for r in family):
            continue
        wakes.append(name)
    return wakes


def main(argv=None, recovery=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--overlay', type=Path, required=True)
    parser.add_argument('--jdk', type=Path, required=True)
    parser.add_argument('--console', type=Path, required=True)
    parser.add_argument('--rryatt',action='store_true',help='restore the reviewed complete-set demand fixture after a scoped fault')
    parser.add_argument('--bots', nargs='+', required=True)
    parser.add_argument('--distributed-shutdown',action='store_true',help='preserve the reviewed Stage 7 flags and reinstall its Falcon helper')
    parser.add_argument('--retirement-console',type=Path)
    parser.add_argument('--occupied-retirement',action='store_true',help='use the explicit four-seat Rryatt/five-seat Ord evacuation fixture')
    args = parser.parse_args(argv)
    if args.occupied_retirement and not args.distributed_shutdown:parser.error('Occupied retirement requires distributed shutdown')
    if args.distributed_shutdown and (not args.rryatt or args.retirement_console is None):
        parser.error('Distributed restart requires linked demand and its matching Falcon console')
    if args.retirement_console is not None and not args.distributed_shutdown:
        parser.error('Falcon console requires distributed restart')
    count=2 if args.rryatt else 5
    if len(args.bots)!=count or len(set(args.bots)) != count or any(not re.fullmatch('[a-z]{3,16}', key) for key in args.bots):
        parser.error('Distinct retained dedicated bots matching the explicit restart mode required')
    project, schema, services = fixture(args.folder,
        allow_stopped_role=getattr(recovery,'stopped_role',None) if recovery is not None else None)
    if args.rryatt:
        policy=json.loads((args.folder/'runtime/stage5-report.json').read_text()) if (args.folder/'runtime/stage5-report.json').exists() else json.loads((args.folder.parent/'runtime/stage5-report.json').read_text())
        expected=(4,5) if policy.get('occupied_retirement') else (2,2)
        if (not policy.get('rryatt_demand_instances') or policy['policy']['rryatt_maximum_instances']!=2 or
            (policy['policy']['rryatt_capacity'],policy['policy']['ord_capacity'])!=expected):raise ValueError('Exact bounded linked-set fixture required')
    if args.distributed_shutdown and (not policy.get('distributed_shutdown') or not policy.get('world_save_probes')):
        parser.error('Existing Stage 7 shutdown and persistence gates required')
    base = args.folder.resolve()/'protocol-driver'
    bots = [identity(json.loads((base/(key+'.json')).read_text())) for key in args.bots]
    if recovery is None:
        for bot in bots:
            unloaded(project, bot)
        empty_proof=require_empty_fixture(lambda command:run(['docker','exec',project+'-central-1','/fixture/protocol-bot-console','127.0.0.1',command]))
    else:
        from central_loss_recovery import CentralLossReceipt
        if type(recovery) is not CentralLossReceipt:raise ValueError('Trusted in-process Central-loss receipt required')
        empty_proof=recovery.authorize(project,schema,services,bots,args.overlay)
    before = snapshot(project, schema)
    output = base/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-restart-'+secrets.token_hex(3))
    output.mkdir(mode=0o700)
    report = {'schema_version':1, 'project':project, 'schema':schema, 'passed':False,
              'fully_unloaded':False, 'occupied_retirement':args.occupied_retirement, 'created_images':0, 'created_databases':0,
              'oracle_before':services['oracle']['Id'], 'originals_before':before['sha256'],'empty_fixture_proof':empty_proof,
              'warm_wakes':[]}
    if recovery is not None:
        report['service_loss_recovery']=recovery.evidence()
        if not getattr(recovery,'stopped_role',None):
            report['central_loss_recovery']=report['service_loss_recovery']
    helper = [sys.executable, 'devtools/zones/prepare_stage5_client_fixture64.py',
              '--folder', str(args.folder), '--overlay', str(args.overlay)]
    if args.rryatt:helper+=['--kashyyyk','--rryatt-groups','--rryatt-instances','--rryatt-set-limit','4' if args.occupied_retirement else '2','--rryatt-maximum-instances','2','--ord-capacity','5' if args.occupied_retirement else '2']
    if args.occupied_retirement:helper+=['--occupied-retirement']
    if args.distributed_shutdown:helper+=['--world-save-probes','--distributed-shutdown']
    if args.distributed_shutdown and policy.get('automatic_retirement'):
        helper+=['--automatic-retirement']
        for key,flag in (('automatic_retirement_idle_ms','--automatic-retirement-idle-ms'),
                         ('automatic_retirement_uptime_ms','--automatic-retirement-uptime-ms'),
                         ('automatic_retirement_cooldown_ms','--automatic-retirement-cooldown-ms')):
            helper += [flag,str(policy[key])]
    try:
        for mode in ('--stop', '--start'):
            with (output/(mode[2:]+'.log')).open('x') as log:
                subprocess.run(helper+[mode], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        # Container creation returns before its overlay/bootstrap copy finishes.
        # Use the retained diagnostic console to wait for actual world readiness
        # before installing the helper into that populated runtime tree.
        console = ['docker','exec',project+'-central-1','/fixture/protocol-bot-console','127.0.0.1']
        query = lambda command: run(console+[command])
        deadline = time.monotonic()+300
        wakes_requested = set()
        while time.monotonic() < deadline:
            try:
                scenes, instances, _, _ = native_snapshots(query)
                for definition in stopped_warm_wakes(scenes, instances, args.rryatt):
                    if definition in wakes_requested:
                        continue
                    reply = run(console+['capacityInstanceWake',definition])
                    if reply != 'status=2 definition= instance=0':
                        raise RuntimeError('Managed fixture warm wake refused: '+reply)
                    wakes_requested.add(definition)
                    report['warm_wakes'].append({'definition':definition,'reply':reply})
                live = [r for r in instances if r['definition']=='space_ord_mantell' and r['state']=='running']
                linked=[r for r in instances if r['definition']=='kashyyyk_rryatt_trail' and r['state']=='running']
                if (len(scenes)==(7 if args.rryatt else 5) and (not args.rryatt or len(linked)==1 and linked[0]['ready']=='1') and len(live)==1 and live[0]['ready']=='1' and
                        all(r['preload']=='finished' and r['heartbeat_fresh']=='1' for r in scenes)):
                    break
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            time.sleep(3)
        else:
            raise TimeoutError('Restart readiness deadline')
        prepare = [sys.executable, 'devtools/zones/prepare_protocol_driver.py', '--folder', str(args.folder),
                   '--console', str(args.console), '--jdk', str(args.jdk), '--script-classes', str(args.overlay/'classes'),
                   '--output', str(output/'helper'), '--apply']
        with (output/'prepare.log').open('x') as log:
            subprocess.run(prepare, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        if args.distributed_shutdown:
            prepare_retirement=[sys.executable,'devtools/zones/prepare_retirement_fixture.py','--folder',str(args.folder),
                '--console',str(args.retirement_console),'--jdk',str(args.jdk),'--script-classes',str(args.overlay/'classes'),
                '--output',str(output/'retirement-helper'),'--apply']
            with (output/'retirement-helper.log').open('x') as log:
                subprocess.run(prepare_retirement,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
            restored=json.loads((args.folder/'runtime/stage5-report.json').read_text())
            report['fixture_profile_changed']=require_retirement_profile(restored,policy,args.occupied_retirement)
            report['policy_before']=policy['policy'];report['policy_after']=restored['policy']
            report['distributed_shutdown_preserved']=True
        inspector = [sys.executable, 'devtools/zones/inspect_client_fixture.py', '--folder', str(args.folder),
                     '--stage5', '--expected-instances', '1', '--expected-ord-instances', '1',
                     '--overlay', str(args.overlay), '--output', str(output/'ready.json')]
        with (output/'ready.log').open('x') as log:
            subprocess.run(inspector, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        current = fixture(args.folder)[2]
        if current['oracle']['Id'] != services['oracle']['Id']:
            raise RuntimeError('Maintenance replaced the original Oracle container')
        for bot in bots:
            unloaded(project, bot)
        after = snapshot(project, schema)
        report.update(originals_after=after['sha256'], original_characters_unchanged=after==before,
                      fully_unloaded=True, ready=json.loads((output/'ready.json').read_text()),
                      oracle_after=current['oracle']['Id'], login_maintenance_tested=True)
        if after != before:
            raise RuntimeError('Maintenance changed protected original objects or variables')
        report['passed'] = True
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        (output/'result.json').write_text(json.dumps(report, indent=2)+'\n')
        print('Evidence: '+str(output), flush=True)


if __name__ == '__main__':
    main()
