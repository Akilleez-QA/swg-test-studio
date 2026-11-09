"""Real pending evacuation disconnect, changed-cohort cancellation and relogin."""
import hashlib
import re
import time

from inspect_client_fixture import rows, native_snapshots
from protocol_driver import bot_query, run, saved, settled, unloaded
from retirement_occupied import retained_position
from rryatt_group import assert_stationary


def descriptor(project, bot, grant, scene, world):
    if (not re.fullmatch(r'swg-cold-test-[a-f0-9]{8}', project) or
            scene not in ('kashyyyk_rryatt_trail', 'space_ord_mantell') or
            any(not isinstance(v, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', v)
                or int(v) > 9223372036854775807 for v in (grant, world, bot['player']))):
        raise ValueError('Exact dedicated actor, reviewed scene and positive dispatch world required')
    raw = run(['docker', 'exec', project+'-central-1', 'cat',
               '/capacity-journal/admission/records/'+grant])
    fields = raw.split('\t')
    if len(fields) < 14 or fields[0:2] != ['1', grant]:
        raise RuntimeError('Invalid durable evacuation descriptor')
    count = int(fields[6])
    offset = 7+4*count
    if (count != (2 if scene == 'kashyyyk_rryatt_trail' else 1) or len(fields) != offset+3 or
            fields[offset:offset+2] != ['1', bot['player']] or
            not re.fullmatch(r'(?:[0-9a-f]{2}){1,8192}', fields[-1]) or
            any(fields[7+4*n:9+4*n] != [scene, world] for n in range(count))):
        raise RuntimeError('Descriptor does not charge the exact actor destination')
    return dict(grant=grant, world=world, sha256=hashlib.sha256(raw.encode()).hexdigest(), record=raw)


def execute(s, p, family, before, source, destination, query, stage):
    a, b, pressure = s.bots
    scene = source['definition']
    observations = []
    s.report['interrupted_evacuation'] = report = dict(observations=observations)
    deadline = time.monotonic()+120
    while time.monotonic() < deadline:
        row = bot_query(s.project, s.bots[b])
        status = query('capacityRetireOccupiedStatus')
        if not observations or observations[-1]['status'] != status:
            observations.append(dict(status=status))
        if (row and row.get('instance') == destination['instance'] and
                row.get('stage') == 'pending' and row.get('pending') == 'true'):
            break
        if s.sessions[b].process.poll() is not None:
            raise RuntimeError('Held actor disconnected before the intended fault')
        time.sleep(.25)
    else:
        raise TimeoutError('No real pending evacuation reached the held destination')
    retained_position(before[b], row, family, s.bots[b])
    report['pending'] = row
    receipt = descriptor(s.project, s.bots[b], row['grant'], scene, destination['instance'])
    report['descriptor_before_disconnect'] = receipt
    assert_stationary(before[a], s.row(a))
    assert_stationary(before[pressure], s.row(pressure))
    # This is an ordinary peer disconnect, not a process or database fault.
    old = s.sessions[b]
    old.send('quit')
    if old.process.wait(timeout=15) != 0:
        raise RuntimeError('Held peer did not close normally')
    old.close()
    report['disconnect_events'] = old.events
    s.sessions[a].send('leaveGroup')
    s.sessions[a].wait('group_command', 10)
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        status = query('capacityRetireOccupiedStatus')
        observations.append(dict(status=status))
        header = dict(part.split('=', 1) for part in status.splitlines()[0].split())
        if header.get('state') == 'cancelled':
            break
        if header.get('state') in ('complete', 'quarantined'):
            raise RuntimeError('Changed cohort must cancel before any source shutdown: '+status)
        time.sleep(.5)
    else:
        raise TimeoutError('Changed group did not cancel the held evacuation')
    unloaded(s.project, s.bots[b])
    report['fully_unloaded_before_relogin'] = True
    report['saved_before_relogin'] = stored = saved(s.project, s.schema, s.bots[b]['player'])
    if stored['scene'] != scene or stored['instance'] != destination['instance']:
        raise RuntimeError('Pending unload did not retain the actual destination')
    report['descriptor_after_unload'] = descriptor(s.project, s.bots[b], row['grant'], scene, destination['instance'])
    if report['descriptor_after_unload'] != receipt:
        raise RuntimeError('Disconnect or cancellation changed the uncertain dispatched charge')
    # A normal fresh peer must reconcile the original charged arrival. No saved
    # record edit, scene-ready bypass, maintenance restart or second seat.
    counter = ['docker', 'exec', s.project+'-central-1', 'cat', '/capacity-journal/admission/ids/next']
    report['grant_high_water_before_relogin'] = high_water = run(counter)
    if not re.fullmatch(r'[1-9][0-9]{0,18}', high_water) or int(high_water) < int(row['grant']):
        raise RuntimeError('Invalid admission high-water proof')
    s.restart(b)
    restored = settled(s.project, s.bots[b], timeout=90)
    retained_position(before[b], restored, family, s.bots[b])
    if restored['instance'] != destination['instance']:
        raise RuntimeError('Relogin selected a different destination')
    report['restored'] = restored
    report['grant_high_water_after_relogin'] = run(counter)
    if report['grant_high_water_after_relogin'] != high_water:
        raise RuntimeError('Relogin allocated another admission grant')
    run(['docker', 'exec', s.project+'-central-1', 'test', '!', '-e',
         '/capacity-journal/admission/records/'+row['grant']])
    report['original_grant_settled'] = True
    s.record('pending_evacuation_relogin_reconciles_original_destination_and_placement')
    time.sleep(30)
    assert_stationary(before[a], s.row(a))
    assert_stationary(before[pressure], s.row(pressure))
    if any(s.row(k)['group'] not in ('null', '0') for k in s.bots):
        raise RuntimeError('Cancelled cohort or unloaded group reappeared')
    _, current, _, _ = native_snapshots(lambda command: query(command))
    live = [v for v in current if v['definition'] == scene and v['state'] not in ('stopped', 'retired')]
    if len(live) != 2 or any(v['state'] != 'running' or v['ready'] != '1' for v in live):
        raise RuntimeError('Cancellation did not retain both live worlds')
    s.record('cancelled_retirement_never_summons_remaining_actors_or_replays_late')
    for k in (b, a):
        if family == 'rryatt':
            p.exit(k)
            s.setup(k, 'botKashyyykHome')
        else:
            s.land(k)
    if family == 'rryatt' and s.row(pressure)['scene'] == 'kashyyyk_main':
        s.setup(pressure, 'botKashyyykHome')
    # Restore a single warm world through the normal empty retirement protocol.
    from world_shutdown_scenario import retire_empty
    retire_empty(s, scene, source, stage['shutdown_nodes'], occupied=True)
    s.record('interrupted_evacuation_actors_returned_to_station')
