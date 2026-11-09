"""Live whole-group evacuation through the ordinary server transfer executor."""
import json
import time

from inspect_client_fixture import rows, native_snapshots
from protocol_driver import bot_query, run
from protocol_scenarios import matching_group, owned_ship, same_point
from rryatt_demand import Demand
from rryatt_group import assert_stationary

FAMILIES = {'rryatt': 'kashyyyk_rryatt_trail', 'ord': 'space_ord_mantell'}


def retained_position(before, after, family, bot):
    if after['scene'] != before['scene'] or after['instance'] == before['instance']:
        raise RuntimeError('Retirement did not change only the runtime copy')
    if family == 'rryatt':
        if (after['buildout_row'] != before['buildout_row'] or after['cell'] != before['cell'] or
                not same_point(before, after, tolerance=.15)):
            raise RuntimeError('Retirement changed the member\'s own level or position')
    elif (not owned_ship(after, bot, before['ship']) or after['cell'] != before['cell'] or
          not same_point(before, after, ('ship_x', 'ship_y', 'ship_z'), .15)):
        raise RuntimeError('Retirement lost the original ship, pilot or stopped space position')


def execute(s, family, outside=False, combat=False, interrupted=False):
    scene = FAMILIES[family]
    a, b, pressure = s.bots
    p = Demand(s, (a, b))
    stage = json.loads((s.folder.parent.parent/'runtime/stage5-report.json').read_text())
    if (not stage.get('occupied_retirement') or not stage.get('distributed_shutdown') or
            (stage['policy']['rryatt_capacity'], stage['policy']['ord_capacity']) != (4, 5) or
            stage['policy']['rryatt_maximum_instances'] != 2 or stage['policy']['ord_maximum_instances'] != 2):
        raise RuntimeError('Explicit bounded occupied-retirement fixture required')
    query = lambda *args: run(['docker', 'exec', s.project+'-central-1',
                              '/fixture/protocol-bot-console', '127.0.0.1', *args])
    if query('capacityRetireStatus').splitlines()[0] != 'schema=1 automatic_retirement=0 occupied_retirement=1':
        raise RuntimeError('Unexpected retirement policy')

    def worlds(count=2):
        deadline = time.monotonic()+180
        while time.monotonic() < deadline:
            current = [r for r in rows(query('capacityInstances')) if r['definition'] == scene and
                       r['state'] not in ('stopped', 'retired')]
            if len(current) > 2:
                raise RuntimeError('Fixture exceeded its two-world bound')
            if len(current) == count and all(r['state'] == 'running' and r['ready'] == '1' for r in current):
                return current
            time.sleep(1)
        raise TimeoutError('Complete destination did not become ready')

    for k in s.bots:
        if s.row(k)['group'] not in ('null', '0'):
            s.sessions[k].send('leaveGroup')
            s.sessions[k].wait('group_command', 10)
    for k in s.bots:
        r = s.row(k)
        if r['scene'] == 'space_ord_mantell':
            s.land(k)
        elif r['scene'] == 'kashyyyk_rryatt_trail':
            p.exit(k)
            s.setup(k, 'botKashyyykHome')
        elif r['scene'] == 'kashyyyk_main':
            s.setup(k, 'botKashyyykHome')
        if s.row(k)['family'] != 'npe_space_station':
            raise RuntimeError('Dedicated actor must start at the station')

    if family == 'rryatt':
        for k in s.bots:
            s.setup(k, 'botKashyyykSetup')
            p.enter(k, 0)
        live = worlds()
        if not outside:
            p.exit(pressure)
        if not combat:
            for index in (0, 2, 4, 6):
                s.rryatt_guide(b, index)
    else:
        for k in s.bots:
            s.launch(k, s.setup_pilot(k))
        live = worlds()
        if not outside:
            s.land(pressure)
    if s.row(a)['instance'] != s.row(b)['instance']:
        raise RuntimeError('Evacuation actors did not share the source copy')
    if combat and family == 'rryatt':
        # The guarded enemy factory needs the original clone mesh floor.
        # Place the ungrouped actor there before normal group formation.
        s.setup(b, 'botRryattCombatSetup')
    s.group(a, b)
    if family == 'rryatt':
        fixed = s.row(b)
        s.rryatt_guide(a, 0)
        if combat:
            # Levels one/two share row zero; level three is another child.
            s.rryatt_guide(a, 2)
        assert_stationary(fixed, s.row(b))
        s.record('leader_level_change_leaves_member_at_own_level')
    # Evacuate one grouped member plus a solo actor while the leader remains
    # outside this family. This must neither summon the leader nor move the
    # member to the leader's unrelated scene.
    if outside:
        if family == 'rryatt':
            p.exit(a)
        else:
            s.land(a)
    evacuating = (b, pressure) if outside else (a, b)
    stationary = a if outside else pressure
    s.report['occupied_roles'] = dict(evacuating=list(evacuating), stationary=stationary,
                                     outside_leader=outside)
    if combat:
        from retirement_combat_windows import start
        start(s, p, b, family)
    before = s.record('occupied_source_cohorts_and_stationary_actor')
    source = next(r for r in live if r['instance'] == before[evacuating[0]]['instance'])
    destination = next(r for r in live if r['instance'] != source['instance'])
    if before[stationary]['scene'] == scene:
        raise RuntimeError('Stationary actor still occupies the retiring family')
    if family == 'rryatt' and before[evacuating[0]]['buildout_row'] == before[evacuating[1]]['buildout_row']:
        raise RuntimeError('Linked retirement requires members on distinct levels')
    s.report['occupied_source'] = source
    s.report['occupied_destination'] = destination
    if interrupted:
        s.sessions[b].send('holdArrival')
        s.sessions[b].wait('arrival_held', 10)
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        reply = query('capacityRetireOccupied', scene, source['instance'])
        if reply == 'occupied=planning':
            break
        if reply != 'occupied=sampling_or_blocked':
            raise RuntimeError('Occupied retirement refused: '+reply)
        time.sleep(.25)
    else:
        raise TimeoutError('Fresh source owner unavailable')

    started = time.monotonic()
    if interrupted:
        from retirement_interrupted_arrival import execute as recover
        recover(s, p, family, before, source, destination, query, stage)
        return
    if combat:
        from retirement_combat_windows import interrupt_and_wait
        interrupt_and_wait(s, p, b, family, source)
    observations, arrivals, protected = [], {}, {}
    s.report['occupied_observations'] = observations
    s.report['occupied_arrivals'] = arrivals
    s.report['occupied_arrival_events'] = {}
    while time.monotonic()-started < 360:
        status = query('capacityRetireOccupiedStatus')
        if not observations or observations[-1]['status'] != status:
            observations.append({'seconds': time.monotonic()-started, 'status': status})
            print('OCCUPIED '+status.splitlines()[0], flush=True)
        header = dict(part.split('=', 1) for part in status.splitlines()[0].split())
        if header.get('state') in ('cancelled', 'quarantined'):
            raise RuntimeError('Occupied retirement did not complete: '+status)
        for k in evacuating:
            r = bot_query(s.project, s.bots[k])
            if s.sessions[k].process.poll() is not None:
                raise RuntimeError('Actor disconnected during evacuation: '+k)
            # Inspection can briefly have no authoritative body during handoff.
            # The live peer and completed native grant are separate requirements.
            if not r or r.get('connected') != 'true':
                continue
            if r['instance'] == destination['instance']:
                if r.get('pending') != 'false' or r.get('outstanding') != 'false':
                    continue
                retained_position(before[k], r, family, s.bots[k])
                if r.get('protected') == 'true':
                    protected[k] = True
                if k not in arrivals:
                    arrivals[k] = r
                    s.report['occupied_arrival_events'][k] = s.sessions[k].wait('scene_ready', 30, after=started)
            elif r['instance'] != source['instance']:
                raise RuntimeError('Evacuation selected a third runtime copy')
        if header.get('state') == 'complete':
            break
        time.sleep(.25)
    else:
        raise TimeoutError('Occupied retirement deadline; last status: '+status)
    s.report['occupied_observations'] = observations
    if set(arrivals) != set(evacuating) or set(protected) != set(evacuating):
        raise RuntimeError('Every evacuee must arrive through a protected transfer')
    after = s.record('outside_leader_stays_while_grouped_and_solo_actors_evacuate' if outside else
                     'whole_group_evacuated_at_each_members_own_position')
    if not matching_group(after[a], after[b], s.bots[a]['player']):
        raise RuntimeError('Evacuation changed group identity or leadership')
    assert_stationary(before[stationary], after[stationary])
    for k in evacuating:
        retained_position(before[k], after[k], family, s.bots[k])
        if after[k]['protected'] != 'false' or after[k]['pending'] != 'false' or after[k]['outstanding'] != 'false':
            raise RuntimeError('Transfer or protection did not settle')
    proof = rows(query('capacityRetireStatus'))
    if len(proof) != 1:
        raise RuntimeError('Exact distributed retirement receipt required')
    proof = proof[0]
    workers = int(proof['workers'])
    if (any(proof[k] != v for k, v in {'definition': scene, 'instance': source['instance'],
                                     'generation': source['generation'], 'state': 'retired'}.items()) or
            workers < 1 or any(int(proof[k]) != workers for k in ('frozen', 'saved', 'game_reaps')) or
            int(proof['reaped_launches']) != workers+1 or
            int(proof['fenced_nodes']) != len(stage['shutdown_nodes']) or proof['nodes'] != proof['fenced_nodes']):
        raise RuntimeError('Evacuation lacks complete freeze/save/reap/queue proof')
    s.report['occupied_retirement_proof'] = proof
    _, instances, _, _ = native_snapshots(lambda command: query(command))
    retired = [r for r in instances if r['definition'] == scene and r['instance'] == source['instance']]
    if len(retired) != 1 or retired[0]['state'] != 'retired' or retired[0]['ready'] != '0':
        raise RuntimeError('Retired source is still advertised')
    if family == 'rryatt':
        fixed = s.row(a)
        s.rryatt_guide(b, 0 if combat else 7)
        assert_stationary(fixed, s.row(a))
        s.record('member_level_change_after_retirement_does_not_move_leader')
        for k in reversed(evacuating):
            p.exit(k)
        # The guarded home setup requires ordinary group departure to settle.
        p.leave(b)
        for k in s.bots:
            if s.row(k)['scene'] == 'kashyyyk_main':
                s.setup(k, 'botKashyyykHome')
            elif s.row(k)['family'] != 'npe_space_station':
                raise RuntimeError('Unexpected retirement cleanup location')
    else:
        for k in reversed(evacuating):
            s.land(k)
        p.leave(b)
    s.record('retirement_actors_returned_to_station')
