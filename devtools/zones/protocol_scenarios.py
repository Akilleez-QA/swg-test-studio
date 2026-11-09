#!/usr/bin/env python3
"""Run normal ship/group protocol scenarios with two retained fixture bots.

Reward and terminal-proximity setup are explicitly recorded separately. No
Windows client, image, database, original player or game-code changes occur.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time

from studio_tool_bundle import zone_tool_hashes
from protocol_driver import (REPO, Session, bot_query, fixture, identity,
                             operation_lock, run, saved, settled, unloaded)


def matching_group(a, b, leader, expected_size=2):
    return (type(expected_size) is int and 2<=expected_size<=32 and
            a.get('group') not in (None, 'null', '0') and a.get('group') == b.get('group') and
            a.get('leader') == b.get('leader') == leader and
            a.get('members') == b.get('members') == str(expected_size))


def owned_ship(row, bot, ship, definition='space_ord_mantell'):
    if definition != 'space_ord_mantell':
        from world_runtime_policy import eligible
        if definition not in eligible() or not definition.startswith('space_'):
            return False
    return (row.get('scene') == definition and row.get('ship') == ship and
            row.get('owner') == row.get('pilot') == bot['player'] and
            row.get('instance') == row.get('ship_instance'))


def same_point(a, b, fields=('x', 'y', 'z'), tolerance=.01):
    return all(abs(float(a[k])-float(b[k])) <= tolerance for k in fields)


class Scenarios:
    def __init__(self, project, schema, folder, bots, sessions, report):
        self.project, self.schema, self.folder = project, schema, folder
        self.bots, self.sessions, self.report = bots, sessions, report
        self.setup_rows = {}
        self.ships = {key: bot['ship'] for key, bot in bots.items() if bot.get('ship')}

    def row(self, key):
        row = settled(self.project, self.bots[key])
        if row.get('outstanding') != 'false':
            raise RuntimeError('Unsettled native handoff: ' + key)
        return row

    def record(self, label):
        rows = {key: self.row(key) for key in self.bots}
        self.report['checks'].append({'name': label, 'at': datetime.now(timezone.utc).isoformat(), 'bots': rows})
        print('SCENARIO ' + label, flush=True)
        return rows

    def setup(self, key, command):
        entry = {'bot': key, 'kind': command, 'status': 'requested'}
        self.report['setup'].append(entry)
        try:
            result = bot_query(self.project, self.bots[key], command)
            entry['result'] = result
            if not result or result.get('accepted') != 'true':
                raise RuntimeError('Recorded fixture setup refused: ' + str(result))
            # Enemy setup changes no scene. A loading-complete acknowledgement
            # here would restart native combat history and distort the test.
            if command not in ('botRryattEnemySetup','botRryattEnemyCleanup'):
                requested=time.monotonic()
                self.sessions[key].send('awaitReady')
                self.sessions[key].wait('action_ready', 30, after=requested)
            self.setup_rows[key] = (bot_query(self.project,self.bots[key]) if command in (
                'botRryattEnemySetup','botRryattEnemyCleanup') else self.row(key))
            entry['observation'] = self.setup_rows[key]
        except Exception as error:
            entry.update(status='failed', error=str(error))
            raise
        entry['status'] = 'completed'
        return result

    def wait_copy(self, key, building, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = bot_query(self.project, self.bots[key])
            if row and row.get('building') == building:
                self.sessions[key].send('awaitReady')
                self.sessions[key].wait('action_ready', 30)
                return self.row(key)
            time.sleep(.5)
        raise TimeoutError('Expected public-copy arrival did not occur')

    def friend(self, key, friend, same=False):
        setup = self.setup(key, 'botFriendSetup')
        # Public rosters are published every twenty seconds. Opening the terminal
        # snapshots that roster for the dialog; allow one publication after a
        # fresh login/copy change before asserting a name is discoverable.
        time.sleep(22)
        self.report['setup'].append({'bot': key, 'kind': 'public_roster_publication_wait', 'seconds': 22})
        session = self.sessions[key]
        session.send('menu ' + setup['target'])
        menu = session.wait('menu', 15)
        if menu['target'] != setup['target'] or 21 not in [r['type'] for r in menu['items']]:
            raise RuntimeError('Friend Finder radial action not offered')
        session.send('select ' + setup['target'] + ' 21')
        def page(prompt, expected_name):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    result = session.wait('sui', max(.1, deadline-time.monotonic()))
                except TimeoutError:
                    self.report['friend_failure'] = bot_query(self.project, self.bots[key])
                    raise
                if result['name'] == expected_name and any(p['property'] == 'Text' and p['value'] == prompt
                        for p in result['properties']):
                    return result
            raise TimeoutError('Expected Friend Finder page missing')
        search = page('@npe:npe_instance_transfer_initial_prompt', 'Script.inputBox')
        session.send(f"answer {search['page']} ok {self.bots[friend]['character']}")
        session.wait('sui_answered', 10)
        results = page('@npe:npe_instance_transfer_select_player_prompt', 'Script.listBox')
        # Search the full unique dedicated name; selecting an unverified row
        # could travel to another player. Require its server-authored label.
        labels = [p['value'] for p in results['properties'] if p['property'] == 'Text' and
                  p['value'] == self.bots[friend]['character']]
        if len(labels) != 1:
            raise RuntimeError('Friend Finder did not return exactly the requested bot: ' + str(results))
        session.send(f"answer {results['page']} ok 0")
        session.wait('sui_answered', 10)
        if same:
            notice = page('@npe:npe_instance_transfer_in_instance', 'Script.messageBox')
            session.send(f"answer {notice['page']} ok")
            session.wait('sui_answered', 10)
        else:
            self.wait_copy(key, self.row(friend)['building'])

    def rryatt_entry(self, linked=False, pair=None, recovery=False):
        """Concurrent real gate requests and full saved logins across all six sets."""
        a, b = self.bots
        stage = json.loads((self.folder.parent.parent/'runtime/stage5-report.json').read_text())
        if stage.get('kashyyyk_entry_pilot') is not True:
            raise RuntimeError('Prepared Kashyyyk entry pilot required')
        from capacity import content_inventory, load_catalog
        self.report['kashyyyk_inventory'] = content_inventory(REPO, load_catalog())

        def use(key, target):
            session = self.sessions[key]
            session.send('menu '+target)
            menu = session.wait('menu', 15)
            if menu['target'] != target or 21 not in [r['type'] for r in menu['items']]:
                raise RuntimeError('Original gate did not offer ITEM_USE')
            session.send('select '+target+' 21')

        def approach_gate(key, command):
            for approach in range(8):
                target = self.setup(key, command)['target']
                if self.row(key).get('rryatt_gate_visible') == 'true':
                    return target
            raise RuntimeError('No visible nearby approach to the original Rryatt gate')

        def exit_trail(key):
            use(key, approach_gate(key, 'botRryattExitSetup'))
            scene = self.sessions[key].wait('scene_ready', 90)
            row = self.row(key)
            if (scene['scene'] != 'terrain/kashyyyk_main.trn' or row['instance'] != '0' or
                    not same_point(row, {'x':-63,'y':19,'z':827}, tolerance=.1)):
                raise RuntimeError('Original Rryatt exit missed the authored Kachirho return')

        # Normalize an interrupted prior run using its original exit.
        for key in self.bots:
            if recovery and self.row(key).get('dead')=='true':
                self.setup(key,'botRryattResurrect')
                deadline=time.monotonic()+20
                while self.row(key).get('dead')=='true' and time.monotonic()<deadline:
                    time.sleep(.5)
                if self.row(key).get('dead')!='false':
                    raise RuntimeError('Interrupted death setup cleanup did not resurrect bot')
            if self.row(key)['scene']=='kashyyyk_rryatt_trail':
                exit_trail(key)
        initial = self.record('rryatt_initial_station_actors')
        if any(r['group'] not in ('null', '0') or not (r['family']=='npe_space_station' or
               r['scene']=='kashyyyk_main') for r in initial.values()):
            raise RuntimeError('Rryatt pilot starts with independent station or Kachirho bots')
        for key in self.bots:
            if initial[key]['family']=='npe_space_station':
                self.setup(key, 'botKashyyykSetup')

        seen = set()
        controllers = set()
        self.report['rryatt_saves'] = []
        self.report['rryatt_prior_peer_events'] = []
        for first in ((pair*2,) if pair is not None else (0,2,4)):
            targets = {key:approach_gate(key, 'botRryattSetup') for key in self.bots}
            for key in self.bots:
                self.setup(key, 'botRryattDiagnostics')
            approaches = self.record('same_original_rryatt_gate_pair_'+str(first//2+1))
            if len(set(targets.values())) != 1 or any(r.get('rryatt_gate_visible') != 'true' for r in approaches.values()):
                raise RuntimeError('Concurrency requires the same visible original gate')
            expected = {}
            for item in approaches[a].get('rryatt_registry','').split(','):
                fields = item.split(':')
                if len(fields)==5 and fields[1:4]==['kashyyyk_rryatt_trail','rryatt_trail','0']:
                    expected[fields[4]] = fields[0].rsplit('_',1)[1]
            if set(expected) != {'0','4','8','12','16','20'}:
                raise RuntimeError('Expected six exact runtime-0 controller registrations')

            # Both requests precede either answer; reverse the selection order.
            for key in self.bots:
                use(key, targets[key])
            pages = {}
            for key in self.bots:
                try:
                    page = self.sessions[key].wait('sui', 30)
                except Exception:
                    self.report['rryatt_failure'] = {k:bot_query(self.project,bot) for k,bot in self.bots.items()}
                    raise
                labels = [p['value'] for p in page['properties'] if p['property']=='Text' and
                          p['value'].startswith('@travel/zone_transition:kachirho_rryatt ')]
                if page['name'] != 'Script.listBox' or len(labels) != 6:
                    raise RuntimeError('Expected all six original linked Rryatt sets')
                pages[key] = page['page']
            self.sessions[b].send(f'answer {pages[b]} ok {first+1}')
            self.sessions[a].send(f'answer {pages[a]} ok {first}')
            for key in (b, a):
                self.sessions[key].wait('sui_answered', 10)
                if self.sessions[key].wait('scene_ready', 90)['scene'] != 'terrain/kashyyyk_rryatt_trail.trn':
                    raise RuntimeError('Rryatt entry reached the wrong scene')
            before = self.record('distinct_linked_controllers_pair_'+str(first//2+1))
            pair_rows = {r['buildout_row'] for r in before.values()}
            if len(pair_rows)!=2 or pair_rows & seen:
                raise RuntimeError('Selections merged or repeated a linked set')
            for key, row in before.items():
                if (row['instance']!='0' or row['instance_controller']!=expected.get(row['buildout_row']) or
                        row['group'] not in ('null','0')):
                    raise RuntimeError('Selected linked set lost its exact registered controller')
                controllers.add(row['instance_controller'])
            seen.update(pair_rows)

            entrance_points = before
            if recovery:
                from rryatt_recovery import begin_mastery,audit_guides
                audit_guides(self,next(iter(self.bots)),'before_recovery_pair_'+str(first//2+1))
                for key in self.bots:
                    begin_mastery(self,key)
            if linked or recovery:
                def descend(key):
                    for index in (0,2,4,6):
                        self.rryatt_guide(key,index)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    for future in as_completed([pool.submit(descend,key) for key in self.bots]):
                        future.result()
                before = self.record('deepest_linked_row_before_save_pair_'+str(first//2+1))

            # Fully unload both actors, retain their original wire evidence, then
            # verify the stored coordinates and controller on a fresh login.
            if recovery:
                for key,command in zip(self.bots,['botRryattLegacy','botRryattStale']):
                    self.setup(key,command)
            previous = dict(self.sessions)
            for key in self.bots:
                previous[key].send('logout')
            for key in self.bots:
                old = previous[key]
                old.wait('logout_accepted', 45)
                if old.process.wait(timeout=10) != 0:
                    raise RuntimeError('Rryatt peer failed during logout')
                unloaded(self.project, self.bots[key])
                save = saved(self.project, self.schema, self.bots[key]['player'])
                if save['scene']!=before[key]['scene'] or save['instance']!=before[key]['instance'] or not same_point(save,before[key]):
                    raise RuntimeError('Rryatt save changed the selected linked placement')
                self.report['rryatt_saves'].append({'bot':key,'anchor':str(int(before[key]['buildout_row'])//4*4),'buildout_row':before[key]['buildout_row'],'saved':save})
                self.report['rryatt_prior_peer_events'].append({'bot':key,'anchor':before[key]['buildout_row'],'events':old.events})
                old.close()
            for key in self.bots:
                self.restart(key)
            after = self.record('full_unload_saved_controller_relogin_pair_'+str(first//2+1))
            for key in self.bots:
                if (after[key]['instance_controller']!=before[key]['instance_controller'] or
                        after[key]['buildout_row']!=before[key]['buildout_row'] or not same_point(after[key],before[key])):
                    raise RuntimeError('Rryatt relogin lost the saved controller or position')
            if recovery:
                self.report.setdefault('rryatt_controller_recoveries',[]).extend(
                    {'bot':key,'mode':mode,'before':before[key],'after':after[key]}
                    for key,mode in zip(self.bots,['missing_association','unavailable_saved_controller']))
            if recovery:
                from rryatt_recovery import complete_recovery
                for key in self.bots:
                    complete_recovery(self,key,entrance_points[key])
                audit_guides(self,next(iter(self.bots)),'after_recovery_pair_'+str(first//2+1))
            def finish(key):
                if linked:
                    for index in (7,5,3,1):
                        self.rryatt_guide(key,index)
                    for index in range(8):
                        self.rryatt_guide(key,index,returning=True)
                exit_trail(key)
            with ThreadPoolExecutor(max_workers=2 if linked else 1) as pool:
                for future in as_completed([pool.submit(finish,key) for key in self.bots]):
                    future.result()
            self.record('original_rryatt_exits_pair_'+str(first//2+1))

        expected_rows={str(pair*8),str(pair*8+4)} if pair is not None else {'0','4','8','12','16','20'}
        if seen!=expected_rows or len(controllers)!=len(expected_rows):
            raise RuntimeError('Selected linked sets must retain distinct controllers through saved login')
        self.report['rryatt_verified_anchor_rows'] = sorted(map(int,seen))
        for key in self.bots:
            self.setup(key, 'botKashyyykHome')
        self.record('recorded_bot_setup_restores_station_for_other_suites')

    def rryatt_clone(self):
        """Focused clone regression with explicit existing-trail fixture prerequisites."""
        from rryatt_recovery import clone
        before=self.record('existing_rryatt_clone_fixture')
        if any(r['scene']!='kashyyyk_rryatt_trail' or r['instance']!='0' or
               r['group'] not in ('null','0') or r['instance_controller'] in ('null','0') for r in before.values()):
            raise RuntimeError('Focused clone suite requires independent, valid saved Rryatt bots')
        for key in self.bots:
            if self.row(key).get('dead')=='true':
                self.setup(key,'botRryattResurrect')
                deadline=time.monotonic()+20
                while self.row(key).get('dead')=='true' and time.monotonic()<deadline:time.sleep(.5)
                if self.row(key).get('dead')!='false':raise RuntimeError('Dead fixture cleanup failed')
            clone(self,key)
        self.record('clone_respawns_in_own_linked_set')

    def rryatt_guide(self, key, index, returning=False):
        """Use an offered original NPC response, then verify its authored offset."""
        from rryatt_linked import assert_arrival, matches_point
        for attempt in range(16):
            setup = self.setup(key, 'botRryattGuide'+str(index))
            if self.setup_rows[key].get('guide_visible') == 'true':
                break
        else:
            raise RuntimeError('Original guide has no visible nearby approach')
        before = self.setup_rows[key]
        session = self.sessions[key]
        session.send('converse '+setup['target'])
        options = session.wait('conversation_responses', 20)
        name = 'rryatt_trail_guide_up' if index % 2 else 'rryatt_trail_guide'
        token = ('s_92' if returning else 's_88') if index % 2 else ('s_67' if returning else 's_63')
        response = 'conversation/'+name+':'+token
        if options['target'] != setup['target'] or response not in options['responses']:
            raise RuntimeError('Authored guide response was not offered')
        session.send('respond '+response)
        session.wait('conversation_answered', 10)
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            row = bot_query(self.project, self.bots[key])
            if row and matches_point(row,setup,returning):
                session.send('awaitReady')
                session.wait('action_ready',30)
                row = self.row(key)
                assert_arrival(before,row,setup,index,returning)
                self.report.setdefault('rryatt_routes',[]).append({
                    'bot':key,'index':index,'returning':returning,'setup':setup,'before':before,'after':row})
                print('SCENARIO guide '+key+' '+setup['route']+(' return' if returning else ''),flush=True)
                return row
            time.sleep(.5)
        raise RuntimeError('Guide travel did not reach its authored offset: '+str(row))

    def split_friend(self):
        a, b = self.bots
        for key in self.bots:
            if self.row(key)['scene'] == 'space_ord_mantell':
                self.land(key)
        initial = self.record('ungrouped_station_baseline')
        if any(r['family'] != 'npe_space_station' or r['group'] not in ('null', '0') for r in initial.values()):
            raise RuntimeError('Requires ungrouped station bots')
        if initial[a]['building'] == initial[b]['building']:
            self.setup(b, 'botSplitStation')
        rows = self.record('deliberately_separate_public_copies')
        if rows[a]['building'] == rows[b]['building']:
            raise RuntimeError('Separate-copy setup did not separate bots')
        self.friend(a, b)
        rows = self.record('friend_finder_search_and_cross_copy_transfer')
        if rows[a]['building'] != rows[b]['building'] or any(r['group'] not in ('null', '0') for r in rows.values()):
            raise RuntimeError('Friend Finder destination/group identity mismatch')
        self.friend(a, b, same=True)
        self.record('friend_finder_same_copy_notice')
        self.setup(b, 'botSplitStation')
        before = self.record('separate_copy_group_setup')
        self.group(a, b)
        after = self.wait_copy(b, before[a]['building'])
        if after['room'] != before[b]['room'] or not same_point(after, before[b]):
            raise RuntimeError('Consolidation did not preserve matching room/local position')
        rows = self.record('group_consolidation_preserves_member_position')
        if not matching_group(rows[a], rows[b], self.bots[a]['player']):
            raise RuntimeError('Consolidation lost authoritative group')
        self.sessions[b].send('leaveGroup')
        self.sessions[b].wait('group_command', 10)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if all(self.row(key)['group'] in ('null', '0') for key in self.bots):
                break
            time.sleep(1)
        else:
            raise TimeoutError('Cleanup group departure did not settle')
        self.record('split_copy_suite_clean_ungrouped_station_saves')

    def group(self, leader, member, expected_size=2):
        if type(expected_size) is not int or not 2<=expected_size<=len(self.bots):
            raise ValueError('Explicit current fixture group size required')
        self.sessions[leader].send('invite ' + self.bots[member]['player'])
        self.sessions[leader].wait('group_command', 10)
        # The invitation is asynchronous; join retries are safe and bounded.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            self.sessions[member].send('join ' + self.bots[leader]['player'])
            self.sessions[member].wait('group_command', 10)
            time.sleep(1)
            a, b = self.row(leader), self.row(member)
            if matching_group(a, b, self.bots[leader]['player'], expected_size):
                return
        raise TimeoutError('Normal group invitation/acceptance did not settle')

    def setup_pilot(self, key, expected_ship=None):
        setup = bot_query(self.project, self.bots[key], 'botPilotSetup')
        self.report['setup'].append({'bot': key, 'kind': 'pilot_reward_and_terminal_position', 'result': setup})
        if not setup or setup.get('accepted') != 'true':
            raise RuntimeError('Pilot fixture setup refused: ' + str(setup))
        if expected_ship is not None and setup['ship'] != expected_ship:
            raise RuntimeError('Pilot setup did not resolve the tracked original ship')
        self.ships[key] = setup['ship']
        self.bots[key]['ship'] = setup['ship']
        (self.folder.parent / (key + '.json')).write_text(json.dumps(self.bots[key], indent=2) + '\n')
        self.sessions[key].send('awaitReady')
        self.sessions[key].wait('action_ready', 30)
        self.sessions[key].send('trackShip ' + setup['ship'])
        self.sessions[key].wait('ship_tracked', 10)
        time.sleep(2)
        self.row(key)
        return setup['target']

    def promote(self, leader, member):
        self.sessions[leader].send('makeLeader ' + self.bots[member]['player'])
        self.sessions[leader].wait('group_command', 10)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if matching_group(self.row(leader), self.row(member), self.bots[member]['player']):
                return
            time.sleep(1)
        raise TimeoutError('Normal leadership promotion did not settle')

    def launch(self, key, terminal):
        self.request_launch(key, terminal)
        return self.finish_launch(key)

    def request_launch(self, key, terminal):
        session = self.sessions[key]
        session.send('menu ' + terminal)
        menu = session.wait('menu', 15)
        if menu['target'] != terminal or 21 not in [r['type'] for r in menu['items']]:
            raise RuntimeError('Normal launch action not offered')
        session.send('select ' + terminal + ' 21')
        session.wait('menu_selected', 10)

    def finish_launch(self, key):
        session = self.sessions[key]
        scene = session.wait('scene_ready', 90)
        row = self.row(key)
        if scene['scene'] != 'terrain/space_ord_mantell.trn' or not owned_ship(row, self.bots[key], self.ships[key]):
            raise RuntimeError('Launch lost original owned ship/pilot/runtime')
        return row

    def capacity_race(self):
        policy = json.loads((self.folder.parent.parent/'runtime/stage5-report.json').read_text())['policy']
        if policy['ord_capacity'] != 2 or policy['ord_maximum_instances'] != 2:
            raise RuntimeError('Capacity race requires the reviewed two-world/two-seat fixture policy')
        for key in self.bots:
            if self.row(key)['scene'] == 'space_ord_mantell':
                self.land(key)
        initial = self.record('five_ungrouped_station_actors')
        if any(r['family'] != 'npe_space_station' or r['group'] not in ('null', '0') for r in initial.values()):
            raise RuntimeError('Capacity race requires ungrouped station bots')
        terminals = {key: self.setup_pilot(key) for key in self.bots}
        began = time.monotonic()
        # Send every real radial request before waiting for any arrival. The
        # fixture has two Ord worlds with two seats each; the fifth must wait
        # and fail cleanly rather than oversubscribe the last seat.
        for key in self.bots:
            self.request_launch(key, terminals[key])
        samples = []
        # GroupTravelRequests retains voluntary intent for at most 300 seconds,
        # including retries while capacity is full. Observe its actual bound;
        # absence of a dispatched grant is not proof that the queue expired.
        deadline = began + 330
        winners = []
        while time.monotonic() < deadline:
            rows = {key: bot_query(self.project, bot) for key, bot in self.bots.items()}
            spaces = {key: row for key, row in rows.items() if row and row['scene'] == 'space_ord_mantell'}
            counts = {}
            for row in spaces.values():
                counts[row['instance']] = counts.get(row['instance'], 0) + 1
            if len(spaces) > 4 or any(count > 2 for count in counts.values()) or len(counts) > 2:
                raise RuntimeError('Concurrent launch exceeded verified fixture seat/world budget')
            samples.append({'seconds': time.monotonic()-began, 'bots': rows, 'world_counts': counts})
            if len(spaces) == 4:
                losers = [key for key in self.bots if key not in spaces]
                failed = rows[losers[0]]
                if (time.monotonic()-began >= 310 and failed and
                        failed['pending'] == failed['outstanding'] == 'false'):
                    winners = list(spaces)
                    break
            time.sleep(1)
        self.report['capacity_samples'] = samples
        if len(winners) != 4:
            raise TimeoutError('Four-seat growth/full-capacity request did not settle within bound')
        loser = next(key for key in self.bots if key not in winners)
        for key in winners:
            self.finish_launch(key)
        held = self.row(loser)
        if held['family'] != 'npe_space_station':
            raise RuntimeError('Exhausted entrant lost safe original station placement')
        self.record('two_worlds_four_seats_fifth_expires_without_overcommit')
        self.land(winners[0])
        self.launch(loser, terminals[loser])
        self.record('released_seat_accepts_fresh_request')
        for key in self.bots:
            if self.row(key)['scene'] == 'space_ord_mantell':
                self.land(key)
        self.record('capacity_race_all_original_ships_returned')

    def space_split(self):
        a, b, filler = self.bots
        policy = json.loads((self.folder.parent.parent/'runtime/stage5-report.json').read_text())['policy']
        if policy['ord_capacity'] != 2 or policy['ord_maximum_instances'] != 2:
            raise RuntimeError('Separate-space setup requires the reviewed two-world/two-seat policy')
        initial = self.record('three_ungrouped_station_bots')
        if any(row['group'] not in ('null', '0') or row['family'] != 'npe_space_station' for row in initial.values()):
            raise RuntimeError('Separate-space suite requires ungrouped station bots')
        terminals = {key: self.setup_pilot(key) for key in self.bots}
        leader = self.launch(a, terminals[a])
        occupied = self.launch(filler, terminals[filler])
        if leader['instance'] != occupied['instance']:
            raise RuntimeError('Fixture did not fill the first world before overflow')
        member = self.launch(b, terminals[b])
        if member['instance'] == leader['instance']:
            raise RuntimeError('Overflow entrant exceeded the two-seat first world')
        self.record('normal_ungrouped_launches_create_separate_ord_copies')
        self.land(filler)
        before = self.record('one_free_seat_for_common_group_destination')
        self.group(a, b)
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            row = bot_query(self.project, self.bots[b])
            if row and row['instance'] == before[a]['instance']:
                self.sessions[b].send('awaitReady')
                self.sessions[b].wait('action_ready', 30)
                break
            time.sleep(.5)
        else:
            raise TimeoutError('Same-family space consolidation did not arrive')
        rows = self.record('original_owned_ship_consolidates_at_matching_space_point')
        if (not matching_group(rows[a], rows[b], self.bots[a]['player']) or
                not owned_ship(rows[b], self.bots[b], self.ships[b]) or
                not same_point(rows[b], before[b], ('ship_x', 'ship_y', 'ship_z')) or
                not same_point(rows[a], before[a], ('ship_x', 'ship_y', 'ship_z'))):
            raise RuntimeError('Space consolidation changed original ship, pilot, group or stopped position')
        if (rows[filler]['cell'] != before[filler]['cell'] or
                not same_point(rows[filler], before[filler]) or rows[filler]['group'] not in ('null', '0')):
            raise RuntimeError('Unrelated capacity filler was moved or grouped')
        self.sessions[b].send('leaveGroup')
        self.sessions[b].wait('group_command', 10)
        time.sleep(2)
        self.land(b)
        self.land(a)
        self.record('space_split_original_ships_returned')

    def land(self, key):
        # Normal recovery cleanup waits for native settlement. The separate
        # request_land action keeps combat-window requests immediate.
        self.row(key)
        self.request_land(key)
        return self.finish_land(key)

    def request_land(self, key):
        setup = bot_query(self.project, self.bots[key], 'botLandingSetup')
        self.report['setup'].append({'bot': key, 'kind': 'space_station_proximity', 'result': setup})
        if not setup or setup.get('accepted') != 'true' or setup.get('ship') != self.ships[key]:
            raise RuntimeError('Station proximity setup refused: ' + str(setup))
        session = self.sessions[key]
        session.send('awaitReady')
        session.wait('action_ready', 30)
        session.send('converse ' + setup['target'])
        deadline = time.monotonic() + 20
        while True:
            options = session.wait('conversation_responses', max(.1, deadline-time.monotonic()))
            if options['target'] == setup['target']:
                break
        response = 'conversation/station_ord_mantell:s_76'
        if response not in options['responses']:
            raise RuntimeError('Server did not offer normal permission-to-land response: ' + str(options))
        session.send('respond ' + response)
        session.wait('conversation_answered', 10)

    def finish_land(self, key, protection=False):
        session = self.sessions[key]
        scene = session.wait('scene_ready', 90)
        first = bot_query(self.project, self.bots[key])
        row = self.row(key)
        if scene['scene'] != 'terrain/dungeon1.trn' or row.get('family') != 'npe_space_station':
            raise RuntimeError('Normal comm landing did not reach Tansaari')
        if protection:
            elapsed = time.monotonic() - scene['received_monotonic']
            self.report.setdefault('protection_windows', []).append({'first': first, 'settled': row, 'seconds': elapsed})
            if not first or first['protected'] != 'true' or elapsed < 9 or elapsed > 25:
                raise RuntimeError('Movable arrival protection did not last the required ten seconds')
        return row

    def combat_windows(self):
        a, b = self.bots
        for key in self.bots:
            if self.row(key)['scene'] == 'space_ord_mantell':
                self.land(key)
        terminals = {key: self.setup_pilot(key) for key in self.bots}
        self.launch(a, terminals[a])
        self.group(a, b)
        self.launch(b, terminals[b])
        self.record('grouped_original_ships_before_combat')
        # Setup places this owned ship 250m along X from the station. Its
        # unchanged forward orientation fires into empty space along Z.
        self.setup(b, 'botLandingSetup')
        session = self.sessions[b]
        session.send('fire')
        session.wait('shot_requested', 10)
        self.request_land(b)
        time.sleep(4)
        session.send('fire')
        second = session.wait('shot_requested', 10)['received_monotonic']
        samples = []
        while time.monotonic() - second < 9.5:
            row = bot_query(self.project, self.bots[b])
            samples.append({'seconds': time.monotonic()-second, 'bot': row})
            if not row or row['scene'] != 'space_ord_mantell':
                raise RuntimeError('Landing departed before ten continuous quiet seconds after the second shot')
            time.sleep(.3)
        self.report['quiet_samples'] = samples
        self.finish_land(b, protection=True)
        self.record('second_shot_restarts_quiet_period_then_protected_landing')
        terminals[b] = self.setup_pilot(b)
        self.launch(b, terminals[b])
        self.setup(b, 'botLandingSetup')
        session.send('fire')
        session.wait('shot_requested', 10)
        self.request_land(b)
        session.send('leaveGroup')
        session.wait('group_command', 10)
        time.sleep(15)
        row = self.row(b)
        if row['scene'] != 'space_ord_mantell' or row['group'] not in ('null', '0'):
            raise RuntimeError('Group departure failed to cancel the queued landing')
        self.record('group_departure_cancels_pending_landing')
        # Fresh ungrouped travel remains possible after cancellation.
        self.land(b)
        self.land(a)
        self.record('combat_suite_original_ships_returned_without_stale_request')

    def execute(self):
        a, b = self.bots
        for key in self.bots:
            if self.row(key)['scene'] == 'space_ord_mantell':
                self.land(key)
                self.report['setup'].append({'bot': key, 'kind': 'normal_comm_return_from_prior_run'})
        initial = self.record('two_independent_station_logins')
        if any(r.get('family') != 'npe_space_station' or r.get('group') not in ('null', '0') for r in initial.values()):
            raise RuntimeError('Requires two ungrouped retained station bots')
        terminals = {key: self.setup_pilot(key) for key in self.bots}
        self.record('explicit_bot_ship_reward_setup')
        self.launch(a, terminals[a])
        rows = self.record('leader_launch_member_stays_ground')
        if rows[b]['family'] != 'npe_space_station':
            raise RuntimeError('Uninvited member moved during leader launch')
        ground = rows[b]
        self.group(a, b)
        rows = self.record('cross_family_group_does_not_summon')
        if rows[b]['cell'] != ground['cell'] or not same_point(rows[b], ground):
            raise RuntimeError('Group formation summoned ground member')
        self.launch(b, terminals[b])
        rows = self.record('follower_launch_joins_leader_runtime')
        if rows[a]['instance'] != rows[b]['instance'] or not matching_group(rows[a], rows[b], self.bots[a]['player']):
            raise RuntimeError('Follower launch split the group/runtime')
        previous = rows
        self.promote(a, b)
        rows = self.record('group_leadership_change_preserves_ships_and_positions')
        for key in self.bots:
            if (not owned_ship(rows[key], self.bots[key], self.ships[key]) or
                    rows[key]['instance'] != previous[key]['instance'] or
                    not same_point(rows[key], previous[key], ('ship_x', 'ship_y', 'ship_z'))):
                raise RuntimeError('Leadership change moved an original ship')
        self.promote(b, a)
        self.land(b)
        rows = self.record('member_lands_leader_stays_space')
        if not owned_ship(rows[a], self.bots[a], self.ships[a]) or not matching_group(rows[a], rows[b], self.bots[a]['player']):
            raise RuntimeError('Landing disrupted leader ship/group/connection')
        terminals[b] = self.setup_pilot(b)
        self.launch(b, terminals[b])
        rows = self.record('original_ship_relaunch_group_retained')
        if rows[a]['instance'] != rows[b]['instance'] or not matching_group(rows[a], rows[b], self.bots[a]['player']):
            raise RuntimeError('Relaunch split original group')
        self.sessions[b].send('leaveGroup')
        self.sessions[b].wait('group_command', 10)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            rows = {key: self.row(key) for key in self.bots}
            if all(r.get('group') in ('null', '0') for r in rows.values()):
                break
            time.sleep(1)
        else:
            raise TimeoutError('Normal group departure did not dissolve two-member group')
        self.record('group_departure_keeps_both_original_ships')
        for key in self.bots:
            self.land(key)
        self.record('independent_landing_after_group_departure')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', required=True, type=Path)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--bots', nargs='+', required=True, metavar='BOT')
    parser.add_argument('--studio-actions', type=Path, help='Run a bounded Studio action plan on these dedicated registries')
    parser.add_argument('--scenario', choices=('kachirho_single','ground_cell_group','ground_cell_recovery','encounter_withdrawal','encounter_enrollment','encounter_offline','encounter_load','encounter_reuse','encounter_recovery','encounter_root_claim','encounter_automatic','encounter_bootstrap','encounter_census','encounter_origins','hosted_public_myyydril','hosted_public_nova','hosted_public_instance_myyydril','hosted_public_instance_nova','whole_world_family', 'hosted_capacity', 'private_solo_admission', 'private_owned_lifecycle','hosted_private_mtp','hosted_private_mtp_join', 'private_ship_round_trip', 'heroic_group_ejection', 'ship_group', 'split_friend', 'space_split', 'capacity_race', 'combat_windows', 'pending_faults', 'rryatt_entry', 'rryatt_linked', 'rryatt_recovery', 'rryatt_group', 'rryatt_clone', 'rryatt_live_capacity', 'rryatt_live_faults', 'rryatt_demand', 'rryatt_demand_content', 'rryatt_demand_capacity', 'rryatt_demand_combat', 'rryatt_demand_faults', 'world_save', 'distributed_shutdown', 'reviewed_shutdown', 'automatic_retirement_rryatt', 'automatic_retirement_ord', 'retirement_occupied_rryatt', 'retirement_occupied_ord', 'retirement_occupied_outside_rryatt', 'retirement_occupied_outside_ord', 'retirement_occupied_combat_rryatt', 'retirement_occupied_combat_ord', 'retirement_occupied_interrupted_rryatt', 'retirement_occupied_interrupted_ord', 'group_affinity_rryatt', 'group_affinity_ord', *('retirement_'+mode+'_'+family for mode in ('prepare','fault','wake') for family in ('falcon','ord','rryatt')), *('retirement_offline_'+mode+'_'+family for mode in ('prepare','verify') for family in ('rryatt','ord','falcon'))), default='ship_group')
    parser.add_argument('--heroic-family', choices=('heroic_ig88','heroic_axkva_min','heroic_exar_kun','heroic_star_destroyer','echo_base_team1','echo_base_team2'))
    parser.add_argument('--rryatt-group-mode',choices=('full','affinity','combat','leases'),help='bounded public linked-set flow')
    parser.add_argument('--rryatt-pair',type=int,choices=range(3),help='one bounded linked-set pair')
    parser.add_argument('--offline-evidence',type=Path,help='exact prior retired-copy setup artifact; verify scenarios only')
    parser.add_argument('--offline-evidence-sha256',help='immutable setup artifact digest')
    from world_runtime_policy import eligible as world_definitions
    parser.add_argument('--world-family',choices=sorted(world_definitions()))
    args = parser.parse_args()
    studio_plan = None
    if args.studio_actions:
        if (args.scenario != 'ship_group' or args.heroic_family is not None or args.world_family is not None or
                args.rryatt_group_mode is not None or args.rryatt_pair is not None or
                args.offline_evidence is not None or args.offline_evidence_sha256 is not None):
            parser.error('Studio actions cannot be combined with other scenario or fixture modes')
        from studio_actions import load
        try:
            studio_plan = load(args.studio_actions, args.bots)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    if args.scenario in ('ground_cell_group','ground_cell_recovery'):
        from ground_cell_fixture import SCENES
        if args.world_family not in SCENES:parser.error('Ground recovery requires one original public ground definition')
    if (args.scenario in ('whole_world_family','ground_cell_group','ground_cell_recovery')) != (args.world_family is not None):
        parser.error('Whole-world scenario requires exactly one explicit --world-family')
    if args.scenario.startswith('retirement_offline_verify_') != (args.offline_evidence is not None and args.offline_evidence_sha256 is not None) or ((args.offline_evidence is not None or args.offline_evidence_sha256 is not None) and not args.scenario.startswith('retirement_offline_verify_')):
        parser.error('Offline verification requires both exact evidence path and digest')
    if args.rryatt_pair is not None and args.scenario not in ('rryatt_linked','rryatt_recovery','rryatt_group'):
        parser.error('Linked pair selection requires the linked-guide scenario')
    if args.rryatt_group_mode is not None and args.scenario!='rryatt_group':
        parser.error('Public linked-set mode requires the public group scenario')
    if (args.scenario=='heroic_group_ejection') != (args.heroic_family is not None):
        parser.error('Live heroic scenario requires exactly one reviewed family')
    count = 4 if args.scenario in ('ground_cell_group','heroic_group_ejection') else 5 if args.scenario in ('capacity_race','rryatt_demand_capacity') else 3 if args.scenario in ('ground_cell_recovery','space_split','rryatt_live_capacity','group_affinity_rryatt','group_affinity_ord') or args.scenario.startswith(('retirement_offline_','retirement_occupied_')) else 2
    if args.heroic_family in ('echo_base_team1','echo_base_team2'):count=5
    if studio_plan is not None:
        count = len(args.bots)
    if len(args.bots) != count or len(set(args.bots)) != count or any(not re.fullmatch('[a-z]{3,16}', k) for k in args.bots):
        parser.error('Scenario requires ' + str(count) + ' distinct retained bot registry keys')
    binary = args.binary.resolve(strict=True)
    raw = binary.read_bytes()
    proof = json.loads(binary.with_suffix('.build.json').read_text())
    digest = hashlib.sha256(Path(__file__).with_name('protocol_driver64.cpp').read_bytes()).hexdigest()
    if (raw[:6] != b'\x7fELF\x02\x01' or raw[18:20] != b'\x3e\x00' or
            proof.get('source_sha256') != digest or proof.get('companion_header_sha256') != hashlib.sha256(Path(__file__).with_name('ProtocolCompanionRoster.h').read_bytes()).hexdigest() or proof.get('binary_sha256') != hashlib.sha256(raw).hexdigest()):
        parser.error('Fresh matching ELF64 driver build required')
    os.umask(0o077)
    with operation_lock(REPO / 'StarWarsGalaxies'):
        project, schema, services = fixture(args.folder)
        if studio_plan is not None and any((args.folder / 'fixture/teststudio').glob('*.control')):
            raise ValueError('Stop the active recording before replay')
        base = args.folder.resolve() / 'protocol-driver'
        bots = {key: identity(json.loads((base / (key + '.json')).read_text())) for key in args.bots}
        if len({b['player'] for b in bots.values()}) != count or len({b['account'] for b in bots.values()}) != count:
            raise ValueError('Distinct saved bot accounts and players required')
        offline_prior=None
        if args.scenario.startswith('retirement_offline_verify_'):
            from retirement_offline import evidence
            offline_prior=evidence(args.offline_evidence,args.offline_evidence_sha256,base,project,schema,list(bots))
        for bot in bots.values():
            unloaded(project, bot)
        operation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-ships-' + secrets.token_hex(3)
        folder = base / operation
        folder.mkdir(mode=0o700)
        destination = '/tmp/protocol-driver-' + operation
        container = project + '-game-1'
        sessions = {}
        configs = {}
        report = {'schema_version': 1, 'project': project, 'schema': schema, 'operation': operation,
                  'bots': bots, 'binary_sha256': hashlib.sha256(raw).hexdigest(), 'source_sha256': digest,
                  'game_image_id': services['game']['Image'], 'oracle_container_id': services['oracle']['Id'],
                  'checks': [], 'setup': [], 'saved': {}, 'passed': False,
                  'backend_sources': zone_tool_hashes(),
                  'created_images': 0, 'created_databases': 0, 'client_source_changed': False,
                  'visual_gameplay_verified': False}
        if studio_plan is not None:
            report['studio_actions'] = studio_plan
        run(['docker', 'exec', container, 'mkdir', '-m', '700', destination])
        run(['docker', 'cp', str(binary), container + ':' + destination + '/driver'])
        run(['docker', 'exec', container, 'chmod', '700', destination + '/driver'])
        from protocol_preservation import snapshot
        original = snapshot(project, schema)
        (folder/'originals-before.json').write_text(json.dumps(original, indent=2)+'\n')
        report['originals_before'] = {k: original[k] for k in ('objects', 'sha256')}
        scenarios = Scenarios(project, schema, folder, bots, sessions, report)
        try:
            login_keys=list(bots)
            if args.scenario=='heroic_group_ejection':
                from heroic_group_live import login_order
                login_keys=login_order(login_keys,hoth=count==5)
            report['login_order']=login_keys
            for key in login_keys:
                bot=bots[key]
                companions = ''.join('companion='+v['player']+'\ncompanionName='+v['character']+'\n' for k,v in bots.items() if k!=key)
                config = folder / (key + '.cfg')
                configs[key] = config
                # This scenario tracks its temporary POB only after the native
                # helper proves the exact creator, PCD and owner. A retained
                # fixture registry may still name an earlier removed POB.
                tracked_ship='' if args.scenario=='private_ship_round_trip' else bot.get('ship','')
                config.write_text(f"[ProtocolDriver64]\nproject={project}\naccount={bot['account']}\ncharacter={bot['character']}\n{companions}ship={tracked_ship}\ntimeoutSeconds=900\n")
                run(['docker', 'cp', str(config), container + ':' + destination + '/' + key + '.cfg'])
                session = Session(project, destination + '/driver', destination + '/' + key + '.cfg', folder / (key + '.log'))
                sessions[key] = session
                scene = session.wait('scene_ready', 90)
                if scene['character'] != bot['player']:
                    raise RuntimeError('Retained bot identity changed')
                if studio_plan is not None:
                    auth = next(e for e in session.events if e['event'] == 'authenticated')
                    if str(auth['station_id']) != bot['station']:
                        raise RuntimeError('Retained Studio station identity changed')
                # Recover an interrupted prior run one actor at a time. Logging
                # every saved space actor in before returning any can itself
                # exhaust the four-seat fixture before the intended race.
                if (studio_plan is None and scene['scene'] == 'terrain/space_ord_mantell.trn' and
                        not args.scenario.startswith('retirement_offline_verify_')):
                    scenarios.land(key)
                    report['setup'].append({'bot': key, 'kind': 'normal_comm_return_before_next_login'})
            recovery_counts = {}
            def restart(key):
                recovery_counts[key] = recovery_counts.get(key, 0)+1
                log = folder/(key+'-recovery-'+str(recovery_counts[key])+'.log')
                session = Session(project, destination+'/driver', destination+'/'+key+'.cfg', log)
                report.setdefault('recovery_logs', []).append({'bot':key,'path':str(log)})
                sessions[key] = session
                scene = session.wait('scene_ready', 120)
                if scene['character'] != bots[key]['player']:
                    raise RuntimeError('Recovery login changed dedicated bot identity')
            scenarios.restart = restart
            if studio_plan is not None:
                from studio_actions import execute
                execute(scenarios, studio_plan)
            elif args.scenario=='heroic_group_ejection':
                from heroic_group_live import execute, FAMILIES
                execute(scenarios,4+int(args.heroic_family[-1])-1 if count==5 else FAMILIES.index(args.heroic_family))
            elif args.scenario=='ground_cell_group':
                from ground_group_live import execute
                execute(scenarios,args.world_family)
            elif args.scenario=='ground_cell_recovery':
                from ground_cell_live import execute
                execute(scenarios,args.world_family)
            elif args.scenario=='encounter_withdrawal':
                from encounter_withdrawal_live import execute
                execute(scenarios)
            elif args.scenario=='encounter_enrollment':
                from encounter_enrollment_live import execute
                execute(scenarios)
            elif args.scenario=='encounter_offline':
                from encounter_offline_live import execute
                execute(scenarios)
            elif args.scenario=='encounter_load':
                from encounter_load_live import execute
                execute(scenarios)
            elif args.scenario in ('encounter_reuse','encounter_recovery'):
                from encounter_reuse_live import execute as reuse
                from encounter_recovery_live import execute as recover
                execute=reuse if args.scenario=='encounter_reuse' else recover
                execute(scenarios)
            elif args.scenario=='encounter_root_claim':
                from encounter_root_claim_live import execute
                execute(scenarios)
            elif args.scenario=='encounter_bootstrap':
                from encounter_bootstrap_live import execute
                execute(scenarios)
            elif args.scenario=='encounter_automatic':
                from encounter_root_claim_live import execute
                execute(scenarios,automatic=True)
            elif args.scenario=='encounter_census':
                from encounter_census_live import execute
                execute(scenarios)
            elif args.scenario=='encounter_origins':
                from encounter_origin_live import execute
                execute(scenarios)
            elif args.scenario in ('hosted_public_myyydril','hosted_public_nova','hosted_public_instance_myyydril','hosted_public_instance_nova'):
                from hosted_public_live import execute
                execute(scenarios,'myyydril_caverns' if args.scenario.endswith('myyydril') else 'nova_orion_station',
                    positive_hosts=args.scenario.startswith('hosted_public_instance_'))
            elif args.scenario=='whole_world_family':
                from whole_world_live import execute
                execute(scenarios,args.world_family)
            elif args.scenario=='hosted_capacity':
                from hosted_family_live import execute
                execute(scenarios)
            elif args.scenario=='private_owned_lifecycle':
                from private_owned_lifecycle import execute
                execute(scenarios)
            elif args.scenario=='private_ship_round_trip':
                from private_ship_round_trip import execute
                execute(scenarios)
            elif args.scenario in ('hosted_private_mtp','hosted_private_mtp_join'):
                from hosted_private_mtp_live import execute
                execute(scenarios,active_join=args.scenario=='hosted_private_mtp_join')
            elif args.scenario=='private_solo_admission':
                from private_solo_admission import execute
                execute(scenarios)
            elif args.scenario.startswith('group_affinity_'):
                from group_affinity_lifecycle import execute
                execute(scenarios,args.scenario.rsplit('_',1)[1])
            elif args.scenario.startswith('retirement_occupied_'):
                from retirement_occupied import execute
                execute(scenarios,args.scenario.rsplit('_',1)[1],outside='_outside_' in args.scenario,combat='_combat_' in args.scenario,interrupted='_interrupted_' in args.scenario)
            elif args.scenario.startswith('retirement_offline_'):
                from retirement_offline import execute
                execute(scenarios,args.scenario.rsplit('_',1)[1],offline_prior)
            elif args.scenario=='kachirho_single':
                from kachirho_single_live import execute
                execute(scenarios)
            elif args.scenario in ('rryatt_entry','rryatt_linked','rryatt_recovery'):
                scenarios.rryatt_entry(linked=args.scenario=='rryatt_linked',pair=args.rryatt_pair,recovery=args.scenario=='rryatt_recovery')
            elif args.scenario == 'distributed_shutdown':
                from world_shutdown_scenario import execute
                execute(scenarios)
            elif args.scenario.startswith('automatic_retirement_'):
                from automatic_retirement_scenario import execute
                execute(scenarios,args.scenario.rsplit('_',1)[1])
            elif args.scenario.startswith('retirement_prepare_'):
                from retirement_live_fault import Live,FAMILIES
                family=args.scenario.rsplit('_',1)[1]
                Live(scenarios,FAMILIES[family]).grow()
            elif args.scenario.startswith(('retirement_fault_','retirement_wake_')):
                from retirement_live_fault import execute
                execute(scenarios,args.scenario.rsplit('_',1)[1],wake=args.scenario.startswith('retirement_wake_'))
            elif args.scenario == 'reviewed_shutdown':
                from reviewed_shutdown import execute
                execute(scenarios)
            elif args.scenario == 'world_save':
                from world_save_scenario import execute
                execute(scenarios)
            elif args.scenario == 'rryatt_demand_faults':
                from rryatt_demand_fault import execute
                execute(scenarios)
            elif args.scenario in ('rryatt_demand_capacity','rryatt_demand_combat','rryatt_demand_content'):
                from importlib import import_module
                import_module(args.scenario).execute(scenarios)
            elif args.scenario == 'rryatt_demand':
                from rryatt_demand import execute
                execute(scenarios)
            elif args.scenario == 'rryatt_live_faults':
                from rryatt_fault import execute
                execute(scenarios)
            elif args.scenario == 'rryatt_live_capacity':
                from rryatt_live import capacity
                capacity(scenarios)
            elif args.scenario == 'rryatt_group':
                from rryatt_group import execute
                execute(scenarios,args.rryatt_pair or 0,args.rryatt_group_mode or 'full')
            elif args.scenario == 'rryatt_clone':
                scenarios.rryatt_clone()
            elif args.scenario == 'space_split':
                scenarios.space_split()
            elif args.scenario == 'pending_faults':
                from protocol_fault_scenarios import execute
                execute(scenarios)
            elif args.scenario == 'combat_windows':
                scenarios.combat_windows()
            elif args.scenario == 'capacity_race':
                scenarios.capacity_race()
            elif args.scenario == 'split_friend':
                scenarios.split_friend()
            else:
                scenarios.execute()
            for key, session in sessions.items():
                session.send('logout')
            for key, session in sessions.items():
                session.wait('logout_accepted', 45)
                if session.process.wait(timeout=10) != 0:
                    raise RuntimeError('Peer failure during logout')
                unloaded(project, bots[key])
                report['saved'][key] = saved(project, schema, bots[key]['player'])
                before = report['checks'][-1]['bots'][key]
                after = report['saved'][key]
                if (after['scene'] != before['scene'] or after['instance'] != before['instance'] or
                        after['container'] != before['cell'] or not same_point(before, after)):
                    raise RuntimeError('Final save differs from settled placement')
            for bot in bots.values():unloaded(project,bot)
            if args.scenario=='private_ship_round_trip':
                from private_ship_round_trip import verify_saved_cleanup
                verify_saved_cleanup(scenarios)
            report['fully_unloaded'] = True
            report['passed'] = True
        except Exception as exc:
            report['error'] = str(exc)
            print('SCENARIO_FAILURE ' + str(exc), flush=True)
            raise
        finally:
            if studio_plan is not None and not report['passed'] and report.get('studio_started_solo'):
                try:
                    from studio_actions import cleanup_group
                    cleanup_group(scenarios)
                except Exception as exc:
                    report['studio_cleanup_error'] = str(exc)
            if args.scenario in ('rryatt_group','retirement_occupied_combat_rryatt'):
                try:
                    from rryatt_group import cleanup
                    cleanup(scenarios)
                except Exception as exc:
                    report['rryatt_cleanup_error']=str(exc);report['passed']=False
            report['events'] = {}
            # Each peer owns a different character/socket. Close them together
            # so failure cleanup does not multiply the server's logout timers.
            with ThreadPoolExecutor(max_workers=max(1, len(sessions))) as pool:
                closing = {pool.submit(session.close): key for key, session in sessions.items()}
                for future in as_completed(closing):
                    key = closing[future]
                    try:
                        future.result()
                    except Exception as exc:
                        report.setdefault('close_errors', {})[key] = str(exc)
                        report['passed'] = False
                    report['events'][key] = sessions[key].events
            report['cleanup'] = {}
            for key in bots:
                try:
                    unloaded(project, bots[key])
                    report['cleanup'][key] = {'fully_unloaded': True, 'saved': saved(project, schema, bots[key]['player'])}
                except Exception as exc:
                    report['cleanup'][key] = {'fully_unloaded': False, 'error': str(exc)}
                    report['passed'] = False
            try:
                after = snapshot(project, schema)
                report['fully_unloaded']=len(report['cleanup'])==len(bots) and all(v.get('fully_unloaded') is True for v in report['cleanup'].values())
                (folder/'originals-after.json').write_text(json.dumps(after, indent=2)+'\n')
                report['originals_after'] = {k: after[k] for k in ('objects', 'sha256')}
                report['original_characters_unchanged'] = after == original
                if after != original:
                    report['passed'] = False
                    report['preservation_error'] = 'Original saved objects or scoped variables changed'
            except Exception as exc:
                report['passed'] = False
                report['preservation_error'] = str(exc)
            (folder / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            print('Evidence: ' + str(folder), flush=True)
            for name in ['driver', *(key + '.cfg' for key in configs)]:
                run(['docker', 'exec', container, 'rm', '-f', destination + '/' + name])
            run(['docker', 'exec', container, 'rmdir', destination])
        if not report['passed']:
            raise RuntimeError('Scenario cleanup did not verify full unload')


if __name__ == '__main__':
    main()
