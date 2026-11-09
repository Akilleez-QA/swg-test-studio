"""Normal leader disband, independent solo travel and replacement-group affinity."""
import json
import time

from inspect_client_fixture import native_snapshots
from protocol_driver import bot_query, run, settled, unloaded
from protocol_scenarios import matching_group, owned_ship, same_point
from retirement_occupied import retained_position
from rryatt_demand import Demand
from rryatt_group import assert_stationary


def execute(s, family):
    a, b, c = s.bots
    p = Demand(s, (a, b))
    stage = json.loads((s.folder.parent.parent/'runtime/stage5-report.json').read_text())
    policy = stage['policy']
    if (stage.get('occupied_retirement') or not stage.get('distributed_shutdown') or
            (policy['rryatt_capacity'], policy['ord_capacity']) != (2, 2) or
            (policy['rryatt_maximum_instances'], policy['ord_maximum_instances']) != (2, 2)):
        raise RuntimeError('Explicit two-copy/two-seat group lifecycle fixture required')
    scene = 'kashyyyk_rryatt_trail' if family == 'rryatt' else 'space_ord_mantell'
    if family not in ('rryatt', 'ord'):
        raise ValueError('Reviewed public group family required')
    query = lambda *args: run(['docker', 'exec', s.project+'-central-1',
                              '/fixture/protocol-bot-console', '127.0.0.1', *args])

    def stationary(before, after, key):
        assert_stationary(before, after)
        if before['scene'] == 'space_ord_mantell' and (
                not owned_ship(after, s.bots[key], before['ship']) or
                not same_point(before, after, ('ship_x', 'ship_y', 'ship_z'), .15)):
            raise RuntimeError('Independent actor lost its original stopped ship position')

    def solo(keys):
        end = time.monotonic()+30
        while time.monotonic() < end:
            current = {k: s.row(k) for k in keys}
            if all(v['group'] in ('null', '0') and v['leader'] in ('null', '0') and
                   v['members'] == '0' for v in current.values()):
                return current
            time.sleep(.25)
        raise TimeoutError('Disband did not clear authoritative group membership')

    def disband(leader, members):
        fixed = {k: s.row(k) for k in s.bots}
        s.sessions[leader].send('disband')
        s.sessions[leader].wait('group_command', 10)
        solo(members)
        for k in s.bots:
            stationary(fixed[k], s.row(k), k)
        s.record('leader_disband_clears_group_without_moving_any_member')

    def arrive(key, world, before):
        end = time.monotonic()+90
        while time.monotonic() < end:
            row = bot_query(s.project, s.bots[key])
            if row and row['instance'] == world and row['pending'] == row['outstanding'] == row['protected'] == 'false':
                retained_position(before, row, family, s.bots[key])
                return row
            if s.sessions[key].process.poll() is not None:
                raise RuntimeError('Group lifecycle actor disconnected during consolidation')
            time.sleep(.25)
        raise TimeoutError('Replacement group did not consolidate to its own leader')

    def exit_family(key):
        if family == 'rryatt':
            p.exit(key)
            s.setup(key, 'botKashyyykHome')
        else:
            s.land(key)

    for k in s.bots:
        if s.row(k)['group'] not in ('null', '0'):
            s.sessions[k].send('leaveGroup')
            s.sessions[k].wait('group_command', 10)
    for k in s.bots:
        row = s.row(k)
        if row['scene'] == 'space_ord_mantell':
            s.land(k)
        elif row['scene'] == 'kashyyyk_rryatt_trail':
            p.exit(k)
            s.setup(k, 'botKashyyykHome')
        elif row['scene'] == 'kashyyyk_main':
            s.setup(k, 'botKashyyykHome')
        if s.row(k)['family'] != 'npe_space_station':
            raise RuntimeError('Dedicated lifecycle actor must start at the station')
    if family == 'rryatt':
        for k in s.bots:
            s.setup(k, 'botKashyyykSetup')
        p.enter(a, 0)
        p.enter(b, 0)
        p.wait_growth(2)
        p.enter(c, 1)
        for index in (0, 2, 4, 6):
            s.rryatt_guide(b, index)
    else:
        for k in (a, b, c):
            s.launch(k, s.setup_pilot(k))
    baseline = s.record('old_pair_and_independent_future_leader_in_separate_copies')
    source, target = baseline[b]['instance'], baseline[c]['instance']
    if baseline[a]['instance'] != source or source == target:
        raise RuntimeError('Old pair and future leader must occupy distinct copies')
    s.group(a, b)
    old_group = s.row(b)['group']
    disband(a, (a, b))
    fixed = s.row(b)
    s.group(c, a)
    arrive(a, target, baseline[a])
    intermediate_group = s.row(a)['group']
    s.report['group_lifecycle_ids'] = dict(original=old_group, intermediate=intermediate_group)
    stationary(fixed, s.row(b), b)
    s.record('former_member_does_not_follow_old_leader_into_another_group')
    disband(c, (c, a))
    exit_family(a)  # Free a real seat before the new member joins this copy.
    exit_family(b)
    if family == 'rryatt':
        s.setup(b, 'botKashyyykSetup')
        solo_entry = p.enter(b, 0)
    else:
        solo_entry = s.launch(b, s.setup_pilot(b))
    if solo_entry['instance'] != source or solo_entry['group'] not in ('null', '0'):
        raise RuntimeError('Solo entry followed the obsolete group binding')
    s.record('disbanded_member_enters_independently_as_a_solo_player')
    if family == 'rryatt':
        for index in (0, 2, 4, 6):
            s.rryatt_guide(b, index)
    before = s.row(b)
    fixed = s.row(a)
    s.group(c, b)
    restored = arrive(b, target, before)
    if not matching_group(s.row(c), restored, s.bots[c]['player']) or restored['group'] in (old_group, intermediate_group):
        raise RuntimeError('Replacement group kept the old identity or leader')
    stationary(fixed, s.row(a), a)
    solo((a,))
    s.report['group_lifecycle_ids']['replacement'] = restored['group']
    s.record('former_member_follows_only_the_new_group_at_own_level_or_original_ship')
    # The old leader enters this same family independently in the other copy.
    if family == 'rryatt':
        s.setup(a, 'botKashyyykSetup')
        p.enter(a, 0)
    else:
        s.launch(a, s.setup_pilot(a))
    stationary(restored, s.row(b), b)
    solo((a,))
    if s.row(a)['instance'] != source:
        raise RuntimeError('Old leader did not enter the independent witness copy')
    if family == 'rryatt':
        fixed = {k: s.row(k) for k in (a, b)}
        s.rryatt_guide(c, 0)
        for k in (a, b):
            stationary(fixed[k], s.row(k), k)
    s.record('old_leader_travel_cannot_replace_new_group_affinity')
    disband(c, (c, b))
    before = s.row(b)
    peer = s.sessions[b]
    peer.send('quit' if family == 'ord' else 'logout')
    if family != 'ord':
        peer.wait('logout_accepted', 40)
    if peer.process.wait(timeout=15) != 0:
        raise RuntimeError('Solo relogin peer did not close normally')
    peer.close()
    unloaded(s.project, s.bots[b])
    s.restart(b)
    after = settled(s.project, s.bots[b], timeout=90)
    # Same copy on relogin; retained_position deliberately requires a copy change.
    stationary(before, after, b)
    if family == 'ord' and after['ship'] != before['ship']:
        raise RuntimeError('Disband relogin replaced the original ship')
    solo((a, b, c))
    s.record('full_unload_and_solo_relogin_do_not_restore_any_disbanded_group')
    for k in (b, c, a):
        exit_family(k)
    _, current, _, _ = native_snapshots(lambda command: query(command))
    extra = next(r for r in current if r['definition'] == scene and r['instance'] == target and r['state'] == 'running')
    from world_shutdown_scenario import retire_empty
    retire_empty(s, scene, extra, stage['shutdown_nodes'])
    s.record('group_lifecycle_actors_returned_home_with_one_warm_copy')
