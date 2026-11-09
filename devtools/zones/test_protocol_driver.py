#!/usr/bin/env python3
"""Fixture isolation, authoritative lifecycle and peer failure regressions."""
import queue
import contextlib
import io
import unittest
from test_central_loss_recovery import CentralLossTests
from test_retirement_fault_baseline import RetirementFaultBaselineTests
from test_retirement_interrupted_arrival import InterruptedEvacuationTests
from test_rryatt_group_actions import PublicGroupActionTests
from test_rryatt_linked import LinkedRouteTests
from test_rryatt_recovery_actions import RecoveryActionTests
from test_protocol_bot_console import BotConsoleTests
from test_protocol_clone import CloneChoiceTests
from unittest.mock import patch
import protocol_driver as driver
import protocol_test_sets as sets
import protocol_scenarios as scenarios
from pathlib import Path
import copy
import json
import subprocess
import signal
import re
import protocol_preservation as preservation
import tempfile
import stage5_release_evidence as release
import fixture_overlay


class PeerExitTests(unittest.TestCase):
    def test_ground_loading_waits_for_the_destination_before_acknowledging(self):
        from unittest.mock import Mock
        peer=Mock();peer.wait.return_value={'scene':'terrain/dungeon1.trn'}
        expected=dict(scene='dungeon1',family='npe_space_dungeon',room='cave_entrance')
        target=dict(expected,connected='true',cell='88',instance='12',x='1',y='2',z='3',pending='true',protected='true')
        calls=[];ticks=iter(range(100))
        def query(command):
            calls.append(command)
            if len(calls)==1:
                peer.send.assert_not_called()
                return dict(target,family='npe_space_station')
            peer.send.assert_not_called()
            return target
        result=driver.complete_ground_arrival(peer,query,expected,clock=lambda:next(ticks),sleep=lambda _:None)
        self.assertEqual(result['observed_destination'],target)
        self.assertEqual(calls,['botInspect','botInspect'])
        peer.send.assert_called_once_with('awaitReady')
        self.assertEqual(peer.wait.call_args.args,('action_ready',30))
        self.assertIsNotNone(peer.wait.call_args.kwargs['after'])

    def test_ground_loading_wrong_unplaced_or_disconnected_arrival_sends_nothing(self):
        from unittest.mock import Mock
        expected=dict(scene='dungeon1',family='npe_space_dungeon',room='cave_entrance')
        good=dict(expected,connected='true',cell='88',instance='12',x='1',y='2',z='3')
        for change in ({'family':'npe_space_station'},{'room':'wrong'},{'connected':'false'},{'cell':'null'},{'x':'nan'},{'instance':'missing'}):
            peer=Mock();ticks=iter(range(20))
            with self.subTest(change=change),self.assertRaises(TimeoutError):
                driver.complete_ground_arrival(peer,lambda _:dict(good,**change),expected,timeout=5,clock=lambda:next(ticks),sleep=lambda _:None)
            peer.send.assert_not_called()

    def test_ground_loading_requires_fresh_readiness_in_the_correct_scene(self):
        from unittest.mock import Mock
        expected=dict(scene='dungeon1',family='npe_space_dungeon',room='cave_entrance')
        row=dict(expected,connected='true',cell='88',instance='12',x='1',y='2',z='3')
        for response in (TimeoutError('no fresh ready'),{'scene':'terrain/tatooine.trn'}):
            peer=Mock()
            if isinstance(response,Exception):peer.wait.side_effect=response
            else:peer.wait.return_value=response
            with self.subTest(response=response),self.assertRaises((TimeoutError,RuntimeError)):
                driver.complete_ground_arrival(peer,lambda _:row,expected)

    def test_terminal_positioning_is_a_saved_setup_lifecycle(self):
        data=json.loads((sets.SETS/'terminal_position_setup.json').read_text());sets.validate(data)
        argv=sets.command(data['tests'][0],{'actor':'eta'},Path('/fixture'),Path('/driver'))
        self.assertIn('--position-terminal-only',argv)
        self.assertNotIn('--prepare-terminal',argv)
        for change in ({'create':True},{'prepare_terminal':True},{'stage_station':True},{'terminal':'123','prompt':'expected'}):
            bad=copy.deepcopy(data);bad['tests'][0]['options'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):sets.validate(bad)

    def test_terminal_positioning_rejects_wrong_option_types(self):
        data=json.loads((sets.SETS/'terminal_position_setup.json').read_text())
        for value in (1,'true',None):
            data['tests'][0]['options']['position_terminal_only']=value
            with self.subTest(value=value),self.assertRaises(ValueError):sets.validate(data)

    def test_station_setup_only_accepts_living_reviewed_original_worlds(self):
        self.assertEqual(driver.station_setup_command(dict(dead='false',instance='0',scene='tutorial')),'botStation')
        self.assertEqual(driver.station_setup_command(dict(dead='false',instance='0',scene='kashyyyk_main')),'botKashyyykHome')
        for change in ({'dead':'true'},{'instance':'1'},{'scene':'space_ord_mantell'}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):driver.station_setup_command(dict(dict(dead='false',instance='0',scene='kashyyyk_main'),**change))

    def test_clone_save_requires_exact_world_parent_and_finite_point(self):
        before=dict(scene='kashyyyk_main',instance='0',cell='null',x='1',y='2',z='3')
        saved=dict(scene='kashyyyk_main',instance='0',container='0',x=1,y=2,z=3)
        driver.assert_saved_point(before,saved)
        for change in ({'instance':'1'},{'scene':'kashyyyk_hunting'},{'container':'42'},{'x':4},{'z':float('nan')}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):driver.assert_saved_point(before,dict(saved,**change))

    def test_logout_and_disconnect_require_their_own_milestone(self):
        from unittest.mock import Mock
        for disconnect in (False, True):
            peer=Mock();peer.process.wait.return_value=0
            self.assertEqual(driver.finish_peer(peer,disconnect),0)
            peer.send.assert_called_once_with('quit' if disconnect else 'logout')
            peer.wait.assert_called_once_with('disconnect_requested' if disconnect else 'logout_accepted',10 if disconnect else 40)

    def test_exit_refusal_never_falls_back_or_claims_success(self):
        from unittest.mock import Mock
        for disconnect in (False, True):
            peer=Mock();peer.wait.side_effect=TimeoutError('refused')
            with self.assertRaises(TimeoutError):driver.finish_peer(peer,disconnect)
            self.assertEqual(peer.send.call_count,1);peer.process.wait.assert_not_called()
            peer=Mock();peer.process.wait.return_value=1
            with self.assertRaises(RuntimeError):driver.finish_peer(peer,disconnect)


class RetiredOfflineTests(unittest.TestCase):
    def test_falcon_suite_is_exactly_scoped_to_three_dedicated_actors(self):
        data=json.loads((sets.SETS/'stage7_falcon_expired_room.json').read_text());sets.validate(data)
        self.assertEqual(data['tests'][1]['options']['family'],'falcon')
        for key,value in [('family','space_npe_falcon_2'),('room','123'),('offline','leader'),('timer',0)]:
            bad=copy.deepcopy(data);bad['tests'][1]['options'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):sets.validate(bad)

    def test_falcon_recovery_rejects_wrong_owner_session_phase_and_placement(self):
        from retirement_falcon import assert_room
        row=dict(scene='space_npe_falcon',pending='false',outstanding='false',protected='false',building='42',cell='43',instance='1')
        room=dict(phase='2',player='7',owner='7',participants='1',session='123',player_session='123',room='42',cell='43',instance='1',end='1000',now='100')
        assert_room(row,room,{'player':'7'})
        for change in ({'owner':'8'},{'participants':'2'},{'phase':'1'},{'room':'44'},{'cell':'0'},{'instance':'2'},{'player_session':'124'},{'end':'100'}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):assert_room(row,dict(room,**change),{'player':'7'})
        for change in ({'scene':'tutorial'},{'pending':'true'},{'outstanding':'true'},{'protected':'true'}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):assert_room(dict(row,**change),room,{'player':'7'})

    @staticmethod
    def falcon_saved_vars(room):
        return {'npe.phase_number':'2','currentInstanceControllerId':room['room'],'space_dungeon.dungeon_id':room['room'],
                'space_dungeon.session_id':room['session'],'space.launch.ship':room['room'],'space_dungeon_route.dungeon_id':room['room'],
                'space_dungeon_route.session_id':room['session'],'space_dungeon_route.scene':'space_npe_falcon','space_dungeon_route.zone_instance_id':room['instance']}

    def test_falcon_save_uses_ship_origin_and_exact_session_route(self):
        from retirement_falcon import assert_saved
        row=dict(ship_x='6000',ship_y='0',ship_z='-3000');room=dict(room='42',session='123',instance='14')
        save=dict(scene='space_npe_falcon',instance='14',container='0',x=6000,y=0,z=-3000);variables=self.falcon_saved_vars(room)
        assert_saved(row,room,save,variables)
        for change in ({'container':'43'},{'x':0},{'y':float('nan')},{'instance':'15'},{'scene':'tutorial'}):
            with self.assertRaises(RuntimeError):assert_saved(row,room,dict(save,**change),variables)
        for key in variables:
            bad=dict(variables);bad.pop(key)
            with self.subTest(key=key),self.assertRaises(RuntimeError):assert_saved(row,room,save,bad)

    def test_falcon_offline_evidence_requires_isolation_and_complete_timer_cleanup(self):
        import hashlib
        from retirement_offline import evidence
        target=dict(definition='space_npe_falcon',instance='14',generation='2')
        row=dict(scene=target['definition'],instance='14',building='42',cell='43',pending='false',outstanding='false',protected='false',ship_x='6000',ship_y='0',ship_z='-3000')
        room=dict(phase='2',player='7',owner='7',participants='1',session='123',player_session='123',room='42',cell='43',instance='14',end='1000',now='100')
        other=dict(room,player='8',owner='8',session='124',player_session='124',room='44',cell='45')
        content=[dict(controller=str(i),scene=target['definition'],zone_instance_id='14',session='-1',players='0',locked='0') for i in range(124)]
        data=dict(passed=True,fully_unloaded=True,project='fixture',schema='copied',bots=dict(beta={'player':'6'},gamma={'player':'8'},delta={'player':'7'}),retirement_target=target,
                  retirement_proofs=dict(target,state='retired'),offline_actor=dict(key='delta',before=row,saved=dict(scene=target['definition'],instance='14',container='0',x=6000,y=0,z=-3000),variables=self.falcon_saved_vars(room)),
                  falcon_room=room,expired_content=content,retained_session_blocker={'reply':'retirement=blocked'},
                  different_player_fresh_session=dict(original=room,new_player=other,offline_owner_retained={'controller':'42','session':'123'}))
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);path=base/'result.json'
            def verify(value):
                path.write_text(json.dumps(value));return evidence(path,hashlib.sha256(path.read_bytes()).hexdigest(),base,'fixture','copied',['beta','gamma','delta'])
            self.assertEqual(verify(data),data)
            for field,value in [('owner','7'),('room','42'),('session','123'),('instance','15'),('participants','2')]:
                bad=copy.deepcopy(data);bad['different_player_fresh_session']['new_player'][field]=value
                with self.subTest(field=field),self.assertRaises(ValueError):verify(bad)
            for field,value in [('different_player_fresh_session',{}),('expired_content',content[:-1]),('retained_session_blocker',{})]:
                with self.subTest(field=field),self.assertRaises(ValueError):verify(dict(data,**{field:value}))
            bad=copy.deepcopy(data);bad['expired_content'][0]['session']='123'
            with self.assertRaises(ValueError):verify(bad)

    def test_failed_offline_logout_remains_owned_by_failure_cleanup(self):
        from retirement_offline import logout
        from unittest.mock import Mock
        peer=Mock();peer.wait.side_effect=TimeoutError('no accepted logout')
        actor=Mock();actor.sessions={'delta':peer}
        with self.assertRaises(TimeoutError):logout(actor,'delta')
        self.assertIs(actor.sessions['delta'],peer)

    def test_owned_space_logout_uses_client_disconnect_and_full_native_unload(self):
        from retirement_offline import logout
        from unittest.mock import Mock
        peer=Mock();peer.process.wait.return_value=0
        actor=Mock();actor.sessions={'delta':peer};actor.bots={'delta':{'player':'7'}}
        actor.row.return_value=dict(scene='space_ord_mantell',instance='4',ship_instance='4',ship='42',owner='7',pilot='7')
        actor.report={}
        with patch('retirement_offline.unloaded') as unload,patch('retirement_offline.saved',return_value={'instance':'4'}):
            self.assertEqual(logout(actor,'delta'),{'instance':'4'})
        peer.send.assert_called_once_with('quit');peer.wait.assert_called_once_with('disconnect_requested',10)
        unload.assert_called_once_with(actor.project,actor.bots['delta']);self.assertNotIn('delta',actor.sessions)
        self.assertEqual(actor.report['offline_exit_modes'][0]['mode'],'space_disconnect')
    def test_space_disconnect_cannot_claim_an_unowned_or_mismatched_ship(self):
        from retirement_offline import logout
        from unittest.mock import Mock
        for change in ({'pilot':'8'},{'owner':'8'},{'ship_instance':'5'}):
            peer=Mock();actor=Mock();actor.sessions={'delta':peer};actor.bots={'delta':{'player':'7'}}
            actor.row.return_value=dict(dict(scene='space_ord_mantell',instance='4',ship_instance='4',ship='42',owner='7',pilot='7'),**change)
            with self.subTest(change=change),self.assertRaises(RuntimeError):logout(actor,'delta')
            peer.send.assert_not_called();self.assertIn('delta',actor.sessions)

    def test_offline_suite_requires_three_exact_actors_and_reviewed_families(self):
        data=json.loads((sets.SETS/'stage7_retired_offline_recovery.json').read_text());sets.validate(data)
        cases=data['tests'][1:]
        self.assertEqual({c['options']['family'] for c in cases},{'rryatt','ord'})
        for key,value in [('family','tutorial'),('offline','member'),('sql','update objects'),('instance',4)]:
            bad=copy.deepcopy(data);bad['tests'][1]['options'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):sets.validate(bad)
        native={'overlay':Path('/overlay'),'jdk':Path('/jdk')}
        with self.assertRaises(ValueError):sets.command(cases[0],{},Path('/fixture'),Path('/driver'),native,Path('/console'))
        argv=sets.command(cases[0],{'leader':'beta','member':'gamma','offline':'delta'},Path('/fixture'),Path('/driver'),native,Path('/console'),Path('/retirement-console'))
        self.assertEqual(argv[-3:],['beta','gamma','delta'])
    def test_recovery_preserves_own_level_point_and_original_ship(self):
        from retirement_offline import assert_recovered
        before=dict(scene='kashyyyk_rryatt_trail',instance='14',buildout_row='3',cell='0',x='4',y='5',z='6')
        after=dict(before,instance='16',pending='false',outstanding='false',protected='false')
        assert_recovered(before,after,{},'rryatt','14')
        for change in ({'instance':'14'},{'buildout_row':'0'},{'x':'nan'},{'z':'6.2'},{'outstanding':'true'}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):assert_recovered(before,dict(after,**change),{},'rryatt','14')
        before.update(scene='space_ord_mantell',ship='42',ship_instance='14',owner='7',pilot='7',ship_x='123',ship_y='456',ship_z='789')
        after=dict(before,instance='16',ship_instance='16',pending='false',outstanding='false',protected='false',x='123',y='456',z='789')
        assert_recovered(before,after,{'player':'7'},'ord','14')
        self.assertEqual(before['x'],'4') # Canonical comparison never mutates the live diagnostic row.
        for change in ({'ship':'43'},{'pilot':'8'},{'ship_instance':'14'},{'ship_x':'0'},{'cell':'8'},{'x':'4'},{'x':'200','y':'150','z':'600'}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):assert_recovered(before,dict(after,**change),{'player':'7'},'ord','14')
    def test_offline_setup_rejects_tampering_and_unrelated_evidence(self):
        import hashlib
        from retirement_offline import evidence
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);sub=base/'case';sub.mkdir();path=sub/'result.json'
            target=dict(definition='kashyyyk_rryatt_trail',instance='14',generation='2')
            data=dict(passed=True,fully_unloaded=True,project='fixture',schema='copied',bots=dict(beta={},gamma={},delta={}),retirement_target=target,retirement_proofs=dict(target,state='retired'),offline_actor=dict(key='delta',before=dict(instance='14'),saved=dict(scene=target['definition'],instance='14')))
            path.write_text(json.dumps(data));sha=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(evidence(path,sha,base,'fixture','copied',['beta','gamma','delta']),data)
            for change in ({'passed':False},{'schema':'original'},{'fully_unloaded':False},{'retirement_proofs':dict(target,state='quarantined')},{'retirement_proofs':dict(target,state='retired',generation='1')}):
                bad=dict(data,**change);path.write_text(json.dumps(bad));digest=hashlib.sha256(path.read_bytes()).hexdigest()
                with self.subTest(change=change),self.assertRaises(ValueError):evidence(path,digest,base,'fixture','copied',['beta','gamma','delta'])
            with self.assertRaises(ValueError):evidence(path,sha,base,'fixture','copied',['beta','gamma','delta'])
            with self.assertRaises(ValueError):evidence(path,hashlib.sha256(path.read_bytes()).hexdigest(),sub/'elsewhere','fixture','copied',['beta','gamma','delta'])


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.bot = {'schema_version': 1, 'account': 'capbot_abcdef0',
                    'character': 'Capabcdefghijkl', 'player': '2562923411', 'station': '903905304'}

    def test_retirement_fault_suite_covers_only_all_reviewed_families(self):
        data=json.loads((sets.SETS/'stage7_live_fault_recovery.json').read_text());sets.validate(data)
        cases=[c for c in data['tests'] if c['kind']=='retirement_fault_recovery']
        self.assertEqual({c['options']['family'] for c in cases},{'falcon','ord','rryatt'})
        for name,value in [('family','tatooine'),('pid','100'),('command','kill'),('member','leader')]:
            bad=copy.deepcopy(data);bad['tests'][1]['options'][name]=value
            with self.assertRaises(ValueError):sets.validate(bad)
        native={'overlay':Path('/overlay'),'jdk':Path('/jdk')}
        with self.assertRaises(ValueError):sets.command(cases[0],{},Path('/fixture'),Path('/driver'),native,Path('/console'))
        argv=sets.command(cases[0],{'leader':'beta','member':'gamma'},Path('/fixture'),Path('/driver'),native,Path('/console'),Path('/retirement-console'))
        self.assertEqual(argv[-5:],['--family',cases[0]['options']['family'],'--bots','beta','gamma'])

    def test_retirement_fault_target_rejects_non_fixture_or_unreviewed_scope(self):
        from retirement_live_fault import target
        for project,scene,world,generation,role in [
            ('starwarsgalaxies','space_npe_falcon','2','1','game'),
            ('swg-cold-test-1234abcd','tatooine','2','1','game'),
            ('swg-cold-test-1234abcd','space_ord_mantell','0','1','game'),
            ('swg-cold-test-1234abcd','space_ord_mantell','2','01','planet'),
            ('swg-cold-test-1234abcd','kashyyyk_rryatt_trail','2','1','central')]:
            with patch('retirement_live_fault.run') as execute:
                with self.assertRaises(ValueError):target(project,scene,world,generation,role,'a'*64)
                execute.assert_not_called()

    def test_retirement_fault_identity_binds_generation_and_overlay_before_signalling(self):
        from retirement_live_fault import target
        labels={'com.docker.compose.project':'swg-cold-test-1234abcd','com.docker.compose.service':'game','whitengold.test.client':'WGC_AE80ACB41011'}
        metadata=[dict(Config=dict(Labels=labels),State=dict(Running=True),Id='container',Image='image')]
        values=[json.dumps(metadata),'42 /opt/whitengold/bin/SwgGameServer -- sceneID=space_ord_mantell zoneInstanceId=14 capacityAttempt=14:6',
                '42 (game) '+' '.join(['S']+['0']*18+['771'])+'\n','a'*64+' /proc/42/exe']
        with patch('retirement_live_fault.run',side_effect=values) as execute:
            row=target('swg-cold-test-1234abcd','space_ord_mantell','14','6','game','a'*64)
            self.assertEqual((row['pid'],row['start_ticks'],row['generation']),('42','771','6'))
            self.assertFalse(any('kill' in c.args[0] for c in execute.call_args_list))
        with patch('retirement_live_fault.run',side_effect=values):
            with self.assertRaisesRegex(RuntimeError,'generation'):target('swg-cold-test-1234abcd','space_ord_mantell','14','7','game','a'*64)
        values[-1]='b'*64+' /proc/42/exe'
        with patch('retirement_live_fault.run',side_effect=values):
            with self.assertRaisesRegex(RuntimeError,'overlay'):target('swg-cold-test-1234abcd','space_ord_mantell','14','6','game','a'*64)

    def test_fault_sample_requires_new_complete_nonce_before_stopping_worker(self):
        from retirement_live_fault import fresh_sample
        replies=['schema=1 mode=observe_only state=collected sample=4',
            'Content observation requested; use capacityContent (no travel or script reservations)',
            'schema=1 mode=observe_only state=collected sample=4',
            'schema=1 mode=observe_only state=pending sample=5',
            'schema=1 mode=observe_only state=collected sample=5']
        query=unittest.mock.Mock(side_effect=replies)
        value=fresh_sample(query,pause=lambda _:None)
        self.assertTrue(value.endswith('sample=5'))
        self.assertEqual(query.call_args_list[1].args,('capacitySample',))

    def test_fault_sample_does_not_use_pending_or_stale_sample_on_timeout(self):
        from retirement_live_fault import fresh_sample
        query=unittest.mock.Mock(side_effect=['schema=1 mode=observe_only state=collected sample=4',
            'Content observation requested; use capacityContent (no travel or script reservations)',
            'schema=1 mode=observe_only state=pending sample=5'])
        with self.assertRaises(TimeoutError):fresh_sample(query,timeout=1,clock=unittest.mock.Mock(side_effect=[1,1,3]),pause=lambda _:None)

    def test_rryatt_choice_maps_runtime_ids_to_actual_cwd_menu_order(self):
        from rryatt_demand import menu_choice
        rows=lambda ids:[dict(instance=str(v),state='running',ready='1') for v in ids]
        self.assertEqual(menu_choice(rows([5,14]),0,2),(1,'5',['14','5']))
        self.assertEqual(menu_choice(rows([5,14]),1,2),(0,'14',['14','5']))
        self.assertEqual(menu_choice(rows([1,10,100]),0,3),(2,'1',['100','10','1']))
        # Previously accepted fault cases used 5/8 and retain the same choices.
        self.assertEqual(menu_choice(rows([5,8]),1,2),(1,'8',['5','8']))
        self.assertEqual(menu_choice(rows([5,4294967301]),1,2),(0,'4294967301',['4294967301','5']))

    def test_rryatt_choice_refuses_unknown_duplicate_or_unready_menu_bindings(self):
        from rryatt_demand import menu_choice
        good=dict(instance='5',state='running',ready='1')
        for rows,selection,count in [([good],0,2),([good,good],0,2),([dict(good,ready='0')],0,1),([good],True,1),([good],1,1),([dict(good,instance='05')],0,1)]:
            with self.assertRaises(RuntimeError):menu_choice(rows,selection,count)

    def test_all_instance_suite_covers_every_original_scene_and_managed_family(self):
        from retirement_inventory import inventory
        report=inventory()
        self.assertEqual(len(report['scenes']),46)
        self.assertEqual(report['canonical_definitions'],39)
        self.assertEqual(sum(r['alias'] for r in report['scenes']),7)
        self.assertEqual({r['scene'] for r in report['scenes'] if r['retirement']=='reviewed'},
                         {'space_npe_falcon','space_ord_mantell','kashyyyk_rryatt_trail'})
        self.assertTrue({'avatar_platform','trando_slave_camp','monster_island_hracca',
                         'the_bet_bocctyyy','kash_the_arena','obiwan_crystal_cave',
                         'rryatt_trail','myyydril_caverns'} <= {r['name'] for r in report['hosted_content']})
        suite=json.loads((sets.SETS/'stage7_all_instances.json').read_text());sets.validate(suite)
        self.assertTrue({'distributed_shutdown','reviewed_shutdown','rryatt_demand','ship_group','protocol_session'} <=
                        {c['kind'] for c in suite['tests']})

    def test_reviewed_retirement_suite_cannot_inject_scene_or_runtime_setup(self):
        suite=json.loads((sets.SETS/'stage7_all_instances.json').read_text())
        case=next(c for c in suite['tests'] if c['kind']=='reviewed_shutdown')
        argv=sets.command(case,{'leader':'beta','member':'gamma'},Path('/fixture'),Path('/driver'))
        self.assertEqual(argv[-2:],['--scenario','reviewed_shutdown'])
        for option in ('scene','command','retire_occupied','pid'):
            bad=copy.deepcopy(suite)
            next(c for c in bad['tests'] if c['kind']=='reviewed_shutdown')['options'][option]='arbitrary'
            with self.assertRaises(ValueError):sets.validate(bad)

    def test_recovery_suite_has_bounded_pairs_and_typed_backend(self):
        data=json.loads((sets.SETS/'kashyyyk_recovery.json').read_text())
        sets.validate(data)
        runtime=[c for c in data['tests'] if c['kind']=='rryatt_recovery']
        self.assertEqual([c['options']['pair'] for c in runtime],[0,1,2])
        for bad in [True,-1,3,'0']:
            broken=copy.deepcopy(data);broken['tests'][-1]['options']['pair']=bad
            with self.assertRaises(ValueError):sets.validate(broken)
        argv=sets.command(runtime[0],{'leader':'beta','member':'gamma'},Path('/fixture'),Path('/driver'))
        self.assertIn('rryatt_recovery',argv)
        self.assertEqual(argv[-2:],['--rryatt-pair','0'])

    def test_public_group_suite_has_three_bounded_pairs_and_native_combat_gates(self):
        data=json.loads((sets.SETS/'kashyyyk_public_group.json').read_text());sets.validate(data)
        cases=[c for c in data['tests'] if c['kind']=='rryatt_group']
        self.assertEqual([c['options']['pair'] for c in cases],[0,1,2,0])
        self.assertEqual([c['options']['mode'] for c in cases],['affinity']*3+['combat'])
        for bad in (True,-1,3,'0'):
            broken=copy.deepcopy(data);broken['tests'][-1]['options']['pair']=bad
            with self.assertRaises(ValueError):sets.validate(broken)
        argv=sets.command(cases[0],{'leader':'beta','member':'gamma'},Path('/fixture'),Path('/driver'))
        self.assertEqual(argv[-4:],['--rryatt-pair','0','--rryatt-group-mode','affinity']);self.assertIn('rryatt_group',argv)
        for bad in ('arbitrary',True,{},['combat']):
            broken=copy.deepcopy(data);broken['tests'][-1]['options']['mode']=bad
            with self.assertRaises(ValueError):sets.validate(broken)
        sets.validate(json.loads((sets.SETS/'kashyyyk_public_combat.json').read_text()))

    def test_linked_capacity_suite_retains_all_pairs_and_typed_reconnect_mode(self):
        data=json.loads((sets.SETS/'kashyyyk_capacity.json').read_text());sets.validate(data)
        cases=[c for c in data['tests'] if c['kind']=='rryatt_group']
        self.assertEqual([c['options']['pair'] for c in cases],[0,1,2])
        self.assertEqual([c['options']['mode'] for c in cases],['leases']*3)
        argv=sets.command(cases[0],{'leader':'beta','member':'gamma'},Path('/fixture'),Path('/driver'))
        self.assertEqual(argv[-4:],['--rryatt-pair','0','--rryatt-group-mode','leases'])
        for mode in ('reconnect-shell',True,{},[]):
            broken=copy.deepcopy(data);broken['tests'][-1]['options']['mode']=mode
            with self.assertRaises(ValueError):sets.validate(broken)

    def test_live_rryatt_capacity_requires_three_distinct_roles(self):
        data=json.loads((sets.SETS/'kashyyyk_live_capacity.json').read_text());sets.validate(data)
        case=data['tests'][-1]
        argv=sets.command(case,{'leader':'beta','member':'gamma','filler':'delta'},Path('/fixture'),Path('/driver'))
        self.assertIn('rryatt_live_capacity',argv);self.assertEqual(argv[-3:],['beta','gamma','delta'])
        case['options']['filler']='member'
        with self.assertRaises(ValueError):sets.validate(data)

    def test_enemy_setup_does_not_acknowledge_a_scene_load(self):
        for action in ('botRryattEnemySetup','botRryattEnemyCleanup'):
            report={'setup':[]}
            case=scenarios.Scenarios('fixture','schema',Path('/tmp'),{'actor':self.bot},{},report)
            with patch.object(scenarios,'bot_query',return_value={'accepted':'true'}),patch.object(case,'row',side_effect=AssertionError('Enemy setup must not wait through a transfer')):
                case.setup('actor',action)
            self.assertEqual(report['setup'][0]['status'],'completed')

    def test_worker_hint_is_read_only_bounded_and_keeps_identity_checks(self):
        with patch.object(driver,'run',return_value='protocol_bot=present player=2562923411') as run:
            row=driver.bot_query('fixture',self.bot,worker=14)
            self.assertEqual(row['worker'],14)
            self.assertEqual(run.call_count,1)
            self.assertIn('botInspect',run.call_args[0][0])
        for worker in (True,0,-1,2147483648,'14'):
            with self.assertRaises(ValueError):driver.bot_query('fixture',self.bot,worker=worker)
        with self.assertRaises(ValueError):driver.bot_query('fixture',self.bot,'botRryattEnemyCleanup',worker=14)
        with patch.object(driver,'run',return_value='protocol_bot=invalid-identity'):
            with self.assertRaises(RuntimeError):driver.bot_query('fixture',self.bot,worker=14)

    def test_retired_worker_hint_falls_back_to_current_authoritative_worker(self):
        from types import SimpleNamespace
        from rryatt_group import PublicGroup
        calls=[]
        def query(argv,**unused):
            calls.append(argv)
            if argv[-1].endswith('runtime.log'):
                return 'Adding server 14 for scene kashyyyk_rryatt_trail\nAdding server 15 for scene kashyyyk_main'
            if argv[6]=='14':return 'No game servers available to service request'
            return 'protocol_bot=present connected=true fixture_version=stage6-public-group-v1'
        public=PublicGroup(SimpleNamespace(project='fixture',bots={'leader':self.bot,'member':self.bot}))
        public.workers['member']=14
        with patch.object(driver,'run',side_effect=query):
            row=public.raw('member')
        self.assertEqual(row['worker'],15)
        self.assertEqual(public.workers['member'],15)
        self.assertEqual(sum(a[-1].endswith('runtime.log') for a in calls),1)

    def test_landing_setup_waits_for_authoritative_arrival_settlement(self):
        from unittest.mock import Mock
        case=scenarios.Scenarios('fixture','schema',Path('/tmp'),{'actor':self.bot},{},{'setup':[]})
        case.row=Mock(side_effect=TimeoutError('arrival remains pending'))
        with patch.object(scenarios,'bot_query') as query, self.assertRaisesRegex(TimeoutError,'arrival remains pending'):
            case.land('actor')
        case.row.assert_called_once_with('actor');query.assert_not_called()

    def test_failed_setup_retains_requested_action_before_native_error(self):
        report={'setup':[]}
        case=scenarios.Scenarios('fixture','schema',Path('/tmp'),{'actor':self.bot},{},report)
        with patch.object(scenarios,'bot_query',side_effect=RuntimeError('native setup failed')):
            with self.assertRaisesRegex(RuntimeError,'native setup failed'):
                case.setup('actor','botKashyyykSetup')
        self.assertEqual(report['setup'],[{'bot':'actor','kind':'botKashyyykSetup',
                         'status':'failed','error':'native setup failed'}])

    def test_existing_user_and_long_legacy_account_refused(self):
        self.assertEqual(driver.identity(self.bot), self.bot)
        for change in ({'account': 'cekis'}, {'character': 'Eaka Ized'},
                       {'account': 'capbot_abcdef0123456789'}, {'schema_version': 2},
                       {'ship': '1\ncreate=true'}, {'player': '-1'}, {'station': '1;delete'}):
            with self.assertRaises(ValueError):
                driver.identity(dict(self.bot, **change))

    def test_setup_phases_cannot_overlap_terminal_acceptance(self):
        for flags in (['--create', '--stage-station'], ['--create', '--prepare-terminal'],
                      ['--stage-station', '--prepare-terminal']):
            args = ['protocol_driver.py', '--folder', '/not-a-fixture', '--binary', '/not-a-binary', '--bot', 'alpha'] + flags
            with patch.object(driver.sys, 'argv', args), patch.object(driver, 'fixture') as fixture, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                driver.main()
            self.assertEqual(result.exception.code, 2)
            fixture.assert_not_called()

    def test_auth_override_and_wrong_section_refused(self):
        text = '[LoginServer]\ndoSessionLogin=false\nvalidateStationKey=false\n'
        self.assertTrue(driver.local_auth(text))
        self.assertFalse(driver.local_auth(text + 'doSessionLogin=true\n'))
        self.assertFalse(driver.local_auth(text.replace('LoginServer', 'ConnectionServer')))
        self.assertFalse(driver.local_auth('[LoginServer]\n# doSessionLogin=false\nvalidateStationKey=false'))

    def test_unrelated_dialog_cannot_be_confirmed_as_terminal(self):
        page = {'name': 'Script.messageBox', 'properties': [{'widget': 'Prompt.lblPrompt',
                'property': 'Text', 'value': '@npe:gamma_shuttle_prompt'}]}
        self.assertTrue(driver.expected_prompt(page, '@npe:gamma_shuttle_prompt'))
        self.assertFalse(driver.expected_prompt(page, '@saga_system:pgc_terms_of_service_text'))
        self.assertFalse(driver.expected_prompt(dict(page, name='Script.inputBox'), '@npe:gamma_shuttle_prompt'))

    def test_shuttle_direction_uses_original_return_room_not_general_entrance(self):
        root = Path(__file__).resolve().parents[2]
        scripts = root/'dsrc/sku.0/sys.server/compiled/game/script'
        original = (scripts/'library/npe.scriptlib').read_text()
        special = re.search(r'FROM_ORD_SPACE_TO_STATION_CELL\s*=\s*"([^"]+)"', original).group(1)
        rows = (scripts.parent/'datatables/travel/zone_transition.tab').read_text().splitlines()
        destinations = {row.split('\t')[0]: row.split('\t')[1].split(':')[3]
                        for row in rows if row.startswith(('npe_space_station\t', 'npe_space_dungeon\t'))}
        self.assertEqual(driver.authored_shuttle_room('npe_space_dungeon', 'npe_space_station'), special)
        self.assertNotEqual(special, destinations['npe_space_station'])
        self.assertEqual(driver.authored_shuttle_room('npe_space_station', 'npe_space_dungeon'), destinations['npe_space_dungeon'])
        for source, destination in (('', 'npe_space_station'), ('npe_space_station', 'npe_space_station'),
                                    ('npe_space_dungeon', 'unknown')):
            with self.assertRaises(ValueError):
                driver.authored_shuttle_room(source, destination)

    def test_saved_object_requires_unique_undeleted_identity(self):
        with patch.object(driver, 'sql', return_value=[{'id': '2562923411', 'deleted': 0}]) as query:
            self.assertEqual(driver.saved('project', 'WGC_AE80ACB41011', self.bot['player'])['deleted'], 0)
            self.assertNotIn('update ', query.call_args.args[2].lower())
        for rows in ([], [{'deleted': 1}], [{'deleted': 0}, {'deleted': 0}]):
            with patch.object(driver, 'sql', return_value=rows), self.assertRaises(RuntimeError):
                driver.saved('project', 'WGC_AE80ACB41011', self.bot['player'])
        with self.assertRaises(ValueError):
            driver.saved('project', 'WGC_AE80ACB41011', '1;delete')

    def test_mutation_targets_only_authoritative_worker(self):
        calls = []
        def run(argv, **_):
            calls.append(argv)
            if argv[-1].endswith('runtime.log'):
                return 'Adding server 9 for scene dungeon1\nAdding server 10 for scene tutorial'
            if argv[5] == 'botInspect':
                return 'protocol_bot=present connected=true' if argv[6] == '10' else 'protocol_bot=absent'
            return 'protocol_bot=prepared accepted=true'
        with patch.object(driver, 'run', side_effect=run):
            self.assertEqual(driver.bot_query('project', self.bot, 'botPrepare')['worker'], 10)
        mutations = [a for a in calls if 'botPrepare' in a]
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0][6], '10')

    def test_sequential_handoff_census_is_discarded_before_acceptance(self):
        header='Adding server 9 for scene dungeon1\nAdding server 10 for scene tutorial'
        for command in ('botInspect','botPrepare'):
            calls=[]; censuses=0
            def query(argv, **unused):
                nonlocal censuses
                calls.append(argv)
                if argv[-1].endswith('runtime.log'):
                    censuses+=1
                    return header
                if argv[5]!='botInspect':return 'protocol_bot=prepared accepted=true'
                if censuses==(1 if command=='botInspect' else 2):return 'protocol_bot=present'
                return 'protocol_bot=absent' if argv[6]=='9' else 'protocol_bot=present'
            with patch.object(driver,'run',side_effect=query):
                self.assertEqual(driver.bot_query('fixture',self.bot,command)['worker'],10)
            self.assertEqual(sum(a[5]=='botPrepare' for a in calls if len(a)>5),int(command=='botPrepare'))
            self.assertEqual(censuses,2 if command=='botInspect' else 3)

    def test_persistent_duplicate_census_is_bounded_and_never_mutates(self):
        header='Adding server 9 for scene dungeon1\nAdding server 10 for scene tutorial'
        calls=[]
        def query(argv, **unused):
            calls.append(argv)
            return header if argv[-1].endswith('runtime.log') else 'protocol_bot=present'
        with patch.object(driver,'run',side_effect=query), self.assertRaisesRegex(RuntimeError,'Multiple authoritative'):
            driver.bot_query('fixture',self.bot,'botPrepare')
        self.assertEqual(sum(a[-1].endswith('runtime.log') for a in calls),3)
        self.assertFalse(any('botPrepare' in a for a in calls))

    def test_duplicate_or_invalid_actor_blocks_evidence(self):
        for response in ('protocol_bot=present', 'protocol_bot=invalid-identity'):
            def run(argv, **_):
                if argv[-1].endswith('runtime.log'):
                    return 'Adding server 9 for scene dungeon1\nAdding server 10 for scene tutorial'
                return response
            with patch.object(driver, 'run', side_effect=run), self.assertRaises(RuntimeError):
                driver.bot_query('project', self.bot)

    def test_observation_retries_are_bounded_and_never_replay_a_mutation(self):
        header = 'Adding server 9 for scene dungeon1'
        with patch.object(driver, 'run', side_effect=[header, RuntimeError('temporary console failure'),
                'protocol_bot=absent']) as query, patch.object(driver.time, 'sleep'):
            self.assertIsNone(driver.bot_query('project', self.bot))
            self.assertEqual(query.call_count, 3)
        with patch.object(driver, 'run', side_effect=[header, 'No game servers available to service request']), \
                self.assertRaisesRegex(RuntimeError, 'No current fixture worker'):
            driver.bot_query('project', self.bot)
        with patch.object(driver, 'run', side_effect=[header, header, 'protocol_bot=present', RuntimeError('uncertain mutation')]) as query:
            with self.assertRaisesRegex(RuntimeError, 'uncertain mutation'):
                driver.bot_query('project', self.bot, 'botPrepare')
            self.assertEqual(sum('botPrepare' in call.args[0] for call in query.call_args_list), 1)

    def test_empty_setup_reply_requires_fresh_matching_receipt_without_replay(self):
        for changes in ({},{'fixture_setup_serial':'4'},{'fixture_setup_action':'botRryattResurrect'},
                        {'fixture_setup_accepted':'false'},{'scene':'tatooine'}):
            before={'scene':'kashyyyk_rryatt_trail','instance':'0','fixture_setup_serial':'4'}
            after=dict(before,fixture_setup_serial='5',fixture_setup_action='botRryattDeath',fixture_setup_accepted='true',**{})
            after.update(changes);inspections=[before,after];calls=[]
            def run(argv,**_):
                calls.append(argv)
                if argv[-1].endswith('runtime.log'):return 'Adding server 9 for scene kashyyyk_rryatt_trail'
                if argv[5]=='botInspect':return 'protocol_bot=present '+' '.join(k+'='+v for k,v in inspections.pop(0).items())
                return ''
            with self.subTest(changes=changes),patch.object(driver,'run',side_effect=run):
                if not changes:
                    result=driver.bot_query('project',self.bot,'botRryattDeath')
                    self.assertEqual(result['receipt'],'authoritative-observation')
                else:
                    with self.assertRaises(RuntimeError):driver.bot_query('project',self.bot,'botRryattDeath')
            self.assertEqual(sum('botRryattDeath' in a for a in calls),1)

    def test_link_dead_actor_is_not_full_unload(self):
        with patch.object(driver, 'bot_query', side_effect=[{'connected': 'false'}, None]) as query, \
                patch.object(driver.time, 'sleep'):
            driver.unloaded('project', self.bot)
            self.assertEqual(query.call_count, 2)
        with patch.object(driver, 'bot_query', return_value={'connected': 'true'}), self.assertRaises(RuntimeError):
            driver.unloaded('project', self.bot)

    def test_protection_and_wrong_family_block_settlement(self):
        row = {'connected': 'true', 'pending': 'false', 'protected': 'false', 'outstanding':'false', 'family': 'npe_space_station'}
        samples = [dict(row, pending='true'), dict(row, protected='true'), dict(row, family='npe_space_dungeon'), row]
        with patch.object(driver, 'bot_query', side_effect=samples), patch.object(driver.time, 'sleep'):
            self.assertEqual(driver.settled('project', self.bot, 'npe_space_station'), row)

    def test_peer_failure_cannot_become_a_pass(self):
        session = driver.Session.__new__(driver.Session)
        session.lines = queue.Queue()
        session.events = []
        session.error = None
        session.lines.put({'schema_version': 1, 'event': 'failure', 'reason': 'login denied'})
        with self.assertRaisesRegex(RuntimeError, 'login denied'):
            session.wait('scene_ready', 1)
        session.lines.put(None)
        with self.assertRaisesRegex(RuntimeError, 'exited before'):
            session.wait('scene_ready', 1)

    def test_all_saved_suites_validate(self):
        for path in sets.SETS.glob('*.json'):
            self.assertEqual(sets.validate(json.loads(path.read_text()))['id'], path.stem)

    def test_manifests_cannot_execute_arbitrary_commands_or_duplicate_cases(self):
        valid = json.loads((sets.SETS / 'station_shuttle.json').read_text())
        for modify in (lambda d: d.update(argv=['rm', '-rf', '/']),
                       lambda d: d['tests'].append(copy.deepcopy(d['tests'][0])),
                       lambda d: d['tests'][0].update(kind='shell'),
                       lambda d: d['tests'][0]['options'].update(command='runScript anything'),
                       lambda d: d['tests'][0]['options'].update(create='true'),
                       lambda d: d['tests'][0]['options'].update(role='unbound')):
            value = copy.deepcopy(valid)
            modify(value)
            with self.assertRaises(ValueError):
                sets.validate(value)

    def test_suite_argv_preserves_literal_prompt_and_requires_runtime_inputs(self):
        case = {'kind': 'protocol_session', 'options': {'role': 'actor', 'terminal': '-123',
                'prompt': 'literal $(secret) `text`', 'answer': 'cancel'}}
        argv = sets.command(case, {'actor': 'beta'}, Path('/tmp/fixture'), Path('/tmp/driver'))
        self.assertIn('literal $(secret) `text`', argv)
        self.assertNotIn('shell', argv)
        with self.assertRaises(ValueError):
            sets.command(case, {'actor': 'beta'}, None, None)

    def test_group_and_ship_assertions_reject_wrong_owner_runtime_and_partial_group(self):
        group = {'group': '123', 'leader': '1', 'members': '2'}
        self.assertTrue(scenarios.matching_group(group, group, '1'))
        self.assertFalse(scenarios.matching_group(group, dict(group, members='1'), '1'))
        self.assertFalse(scenarios.matching_group(group, dict(group, group='124'), '1'))
        ship = {'scene': 'space_ord_mantell', 'ship': '42', 'owner': '1', 'pilot': '1', 'instance': '3', 'ship_instance': '3'}
        self.assertTrue(scenarios.owned_ship(ship, {'player': '1'}, '42'))
        for change in ({'owner': '2'}, {'pilot': '2'}, {'ship_instance': '4'}, {'ship': '43'}):
            self.assertFalse(scenarios.owned_ship(dict(ship, **change), {'player': '1'}, '42'))

    def test_backend_timeout_interrupts_cleanup_and_never_becomes_a_pass(self):
        with patch.object(sets.subprocess, 'Popen') as start:
            process = start.return_value
            process.wait.side_effect = [subprocess.TimeoutExpired(['driver'], 1), 0]
            process.returncode = 0
            code, timed_out = sets.execute(['driver'], io.StringIO(), timeout=1)
            self.assertEqual(code, 0)
            self.assertTrue(timed_out)
            process.send_signal.assert_called_once_with(signal.SIGINT)
            process.kill.assert_not_called()

    def test_operator_interrupt_waits_for_backend_cleanup(self):
        with patch.object(sets.subprocess, 'Popen') as start:
            process = start.return_value
            process.wait.side_effect = [KeyboardInterrupt(), 0]
            with self.assertRaises(KeyboardInterrupt):
                sets.execute(['driver'], io.StringIO())
            process.send_signal.assert_called_once_with(signal.SIGINT)
            self.assertEqual(process.wait.call_count, 2)
            process.kill.assert_not_called()

    def test_linked_pair_selection_is_typed_and_cannot_change_other_scenarios(self):
        data=json.loads((sets.SETS/'kashyyyk_linked.json').read_text())
        sets.validate(data)
        case=data['tests'][2]
        argv=sets.command(case,{'leader':'beta','member':'gamma'},Path('/tmp/fixture'),Path('/tmp/driver'))
        self.assertEqual(argv[-2:],['--rryatt-pair','0'])
        for pair in (-1,3,'1',True):
            value=copy.deepcopy(data);value['tests'][2]['options']['pair']=pair
            with self.subTest(pair=pair),self.assertRaises(ValueError):
                sets.validate(value)
        value=copy.deepcopy(data);value['tests'][2]['kind']='ship_group'
        with self.assertRaises(ValueError):
            sets.validate(value)

    def test_capacity_and_space_suite_roles_cannot_be_dropped_or_aliased(self):
        data = json.loads((sets.SETS/'capacity_race.json').read_text())
        for change in (lambda d: d['roles'].pop(),
                       lambda d: d['roles'].append('sixth'),
                       lambda d: d['tests'][0]['options'].update(actors=['first']*5)):
            value = copy.deepcopy(data)
            change(value)
            with self.assertRaises(ValueError):
                sets.validate(value)
        case = json.loads((sets.SETS/'space_split.json').read_text())['tests'][0]
        argv = sets.command(case, {'leader':'beta', 'member':'gamma', 'filler':'epsilon'}, Path('/tmp/fixture'), Path('/tmp/driver'))
        self.assertEqual(argv[-3:], ['beta', 'gamma', 'epsilon'])

    def test_native_gates_cannot_select_unregistered_programs(self):
        data = json.loads((sets.SETS/'stage5_native.json').read_text())
        data['tests'][0]['options']['gate'] = '../../anything'
        with self.assertRaises(ValueError):
            sets.validate(data)
        with self.assertRaises(ValueError):
            sets.command({'kind':'native_gate','options':{'gate':'combat'}}, {}, None, None)

    def test_preservation_scope_is_read_only_and_requires_complete_rows(self):
        ids = [{'id':str(n)} for n in range(1,46)]
        rows = [{'kind':'object','row':{'id':str(n)}} for n in range(1,46)]
        with patch.object(preservation, 'sql', side_effect=[ids, rows]) as query:
            result = preservation.snapshot('swg-cold-test-d9d6e6af','WGC_AE80ACB41011')
            self.assertEqual(result['objects'],45)
            self.assertTrue(all('update ' not in call.args[2].lower() and 'delete ' not in call.args[2].lower()
                                for call in query.call_args_list))
        with patch.object(preservation, 'sql', side_effect=[ids, rows[:-1]]), self.assertRaises(RuntimeError):
            preservation.snapshot('swg-cold-test-d9d6e6af','WGC_AE80ACB41011')
        with patch.object(preservation, 'sql') as query, self.assertRaises(ValueError):
            preservation.snapshot('starwarsgalaxies','SWG')
        query.assert_not_called()

    def test_exit_zero_cannot_hide_missing_unload_or_multiple_runtime_results(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            operation = folder/'protocol-driver/op'
            operation.mkdir(parents=True)
            (operation/'result.json').write_text(json.dumps({'passed':True,'fully_unloaded':False}))
            log = folder/'case.log'
            log.write_text('Evidence: '+str(operation)+'\n')
            with self.assertRaises(ValueError):
                sets.runtime_artifact(log, folder)
            (operation/'result.json').write_text(json.dumps({'passed':True,'fully_unloaded':True}))
            log.write_text(('Evidence: '+str(operation)+'\n')*2)
            with self.assertRaises(ValueError):
                sets.runtime_artifact(log, folder)

    def test_release_gate_refuses_partial_and_stale_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            result = folder/'test-sets/op/result.json'
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({'schema_version':1,'suite':'stage5_release','passed':True,'cases':[]}))
            with patch.object(release,'FIXTURE',folder), self.assertRaisesRegex(ValueError,'Complete passing'):
                release.verify(result,'0'*64)
            data = json.loads(result.read_text())
            data['source_hashes'] = dict(sets.source_hashes(), **{'protocol_driver64.cpp':'0'*64})
            result.write_text(json.dumps(data))
            with patch.object(release,'FIXTURE',folder), self.assertRaises(ValueError):
                release.verify(result,'0'*64)


class FixtureOverlayTests(unittest.TestCase):
    def test_gameplay_corpus_wins_and_only_fixture_helpers_overlay_it(self):
        with tempfile.TemporaryDirectory(prefix='swg-fixture-overlay-') as directory:
            root=Path(directory);overlay=root/'overlay';fixture=root/'fixture';target=root/'installed'
            for name in ('bin','lib','validation','classes/script/library'):
                (overlay/name).mkdir(parents=True)
            for name in ('script/library','script/fixture'):
                (fixture/'classes'/name).mkdir(parents=True)
            gameplay='classes/script/library/space_dungeon.class'
            (overlay/gameplay).write_bytes(b'current verified gameplay')
            (fixture/gameplay).write_bytes(b'obsolete fixture gameplay')
            (fixture/'classes/script/fixture/protocol_bot.class').write_bytes(b'fixture helper')
            (target/'lib').mkdir(parents=True)
            golden=root/'native-original';golden.write_bytes(b'unchanged native library')
            installed=target/'lib/native.so';installed.hardlink_to(golden)
            (overlay/'lib/native.so').write_bytes(golden.read_bytes())
            before=installed.stat()
            script=fixture_overlay.GAME_BOOT.replace('$$','$').replace('/fixture/classes',str(fixture/'classes'))
            script=script.replace('/overlay',str(overlay)).replace('/opt/whitengold',str(target))
            subprocess.run(['sh','-ec',script,'sh','true'],check=True,capture_output=True)
            classes=target/'data/sku.0/sys.server/compiled/game'
            self.assertEqual((classes/'script/library/space_dungeon.class').read_bytes(),b'current verified gameplay')
            self.assertEqual((classes/'script/fixture/protocol_bot.class').read_bytes(),b'fixture helper')
            self.assertEqual((installed.stat().st_ino,installed.stat().st_mtime_ns),(before.st_ino,before.st_mtime_ns))

    def test_known_old_game_copy_is_upgraded_without_changing_role_arguments(self):
        old_copy='cp -a /fixture/classes/. /opt/whitengold/data/sku.0/sys.server/compiled/game/; exec "$$@"'
        for old in (fixture_overlay.BOOT,fixture_overlay.BOOT.replace('exec "$$@"',old_copy),
                    fixture_overlay.GAME_BOOT):
            entry=['/bin/sh','-ec',old,'sh','/opt/whitengold/container-entrypoint']
            fixture_overlay.refresh_game(entry)
            self.assertEqual(entry[2],fixture_overlay.GAME_BOOT)
            self.assertEqual(entry[3:],['sh','/opt/whitengold/container-entrypoint'])

    def test_unknown_game_recipe_is_rejected(self):
        with self.assertRaises(ValueError):
            fixture_overlay.refresh_game(['/bin/sh','-ec','unreviewed command','sh'])


class MilestoneFenceTests(unittest.TestCase):
    def test_native_settlement_waits_for_generic_handoff_completion(self):
        pending=dict(connected='true',pending='false',protected='false',outstanding='true')
        done=dict(pending,outstanding='false')
        with patch.object(driver,'bot_query',side_effect=[pending,done]) as query,patch.object(driver.time,'sleep'):
            self.assertEqual(driver.settled('fixture',{},timeout=1),done)
        self.assertEqual(query.call_count,2)
    def test_demand_capacity_requires_five_exact_roles(self):
        data=json.loads((sets.SETS/'kashyyyk_demand_capacity.json').read_text());sets.validate(data)
        case=data['tests'][-1];bindings=dict(zip(data['roles'],('beta','gamma','delta','epsilon','zeta')))
        argv=sets.command(case,bindings,Path('/fixture'),Path('/driver'))
        self.assertEqual(argv[-5:],list(bindings.values()));self.assertIn('rryatt_demand_capacity',argv)
        case['options']['actors']=data['roles'][:-1]
        with self.assertRaises(ValueError):sets.validate(data)
    def test_demand_combat_rejects_self_group_and_arbitrary_options(self):
        data=json.loads((sets.SETS/'kashyyyk_demand_combat.json').read_text());sets.validate(data)
        for patch in ({'member':'leader'},{'mode':'combat'},{'world':16}):
            bad=json.loads(json.dumps(data));bad['tests'][-1]['options'].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):sets.validate(bad)
    def test_demand_suite_has_typed_distinct_roles(self):
        data=json.loads((sets.SETS/'kashyyyk_demand.json').read_text());sets.validate(data)
        case=data['tests'][-1];argv=sets.command(case,{'leader':'beta','member':'gamma'},Path('/fixture'),Path('/driver'))
        self.assertIn('rryatt_demand',argv)
        case['options']['member']='leader'
        with self.assertRaises(ValueError):sets.validate(data)
    def test_automatic_arrival_and_menu_share_a_fenced_wait(self):
        for milestone in ('sui','scene_ready'):
            peer=object.__new__(driver.Session);peer.lines=queue.Queue();peer.events=[];peer.error=None
            peer.lines.put(dict(event='scene_ready',received_monotonic=1))
            peer.lines.put(dict(event=milestone,received_monotonic=3))
            self.assertEqual(peer.wait_any(('sui','scene_ready'),after=2)['event'],milestone)
            self.assertEqual(len(peer.events),2)
        with self.assertRaises(ValueError):peer.wait_any([])
    def test_old_ready_does_not_complete_a_new_setup(self):
        import queue
        from protocol_driver import Session
        peer=object.__new__(Session);peer.lines=queue.Queue();peer.events=[];peer.error=None
        peer.lines.put(dict(event='action_ready',received_monotonic=1))
        peer.lines.put(dict(event='scene_started',received_monotonic=3))
        peer.lines.put(dict(event='action_ready',received_monotonic=4))
        self.assertEqual(peer.wait('action_ready',after=2)['received_monotonic'],4)
        self.assertEqual(len(peer.events),3)
    def test_unfenced_milestones_keep_existing_behavior(self):
        import queue
        from protocol_driver import Session
        peer=object.__new__(Session);peer.lines=queue.Queue();peer.events=[];peer.error=None
        event=dict(event='scene_ready',received_monotonic=1);peer.lines.put(event)
        self.assertEqual(peer.wait('scene_ready'),event)

class SnapshotIdentityTests(unittest.TestCase):
    def test_maintenance_rejects_a_retained_or_unrelated_actor(self):
        from protocol_fixture_restart import require_empty_fixture
        for count in (1,2,5):
            with patch('protocol_fixture_restart.native_snapshots',return_value=(None,None,None,None,'observed_players='+str(count)+' (includes retained authoritative players)')):
                with self.assertRaises(RuntimeError):require_empty_fixture(lambda command:None)
    def test_maintenance_accepts_a_coherent_empty_fixture(self):
        from protocol_fixture_restart import require_empty_fixture
        proof='observed_players=0 (includes retained authoritative players)'
        with patch('protocol_fixture_restart.native_snapshots',return_value=(None,None,None,None,proof)):
            self.assertEqual(require_empty_fixture(lambda command:None),proof)

    def test_fault_occupancy_uses_the_validated_snapshot(self):
        from inspect_client_fixture import native_snapshots
        content='schema=1 mode=observe_only state=collected nonce=7\nkey\tcontroller\nobserved_players=2 (includes retained authoritative players)\n'
        calls=[]
        def query(name):
            calls.append(name)
            if name=='capacityContent':return content if calls.count(name)<=2 else content.replace('players=2','players=3')
            return 'schema=1\nscene\tinstance\n'
        result=native_snapshots(query,include_text=True)
        self.assertEqual(len(result),5);self.assertEqual(result[4],content);self.assertEqual(calls.count('capacityContent'),2)
    def test_default_snapshot_api_keeps_four_fields(self):
        from inspect_client_fixture import native_snapshots
        content='schema=1 mode=observe_only state=collected nonce=7\nkey\tcontroller\n'
        self.assertEqual(len(native_snapshots(lambda name:content if name=='capacityContent' else 'schema=1\nscene\tinstance\n')),4)

class PrivateOwnedFixtureTests(unittest.TestCase):
    def test_original_exit_selection_is_explicit_and_stays_single(self):
        from inspect_client_fixture import fixture_scene_selection
        base=['tatooine','tutorial','dungeon1','space_npe_falcon','space_ord_mantell']
        for kashyyyk in (False,True):
            for private in (False,True):
                selected=base+(['kashyyyk_main','kashyyyk_rryatt_trail'] if kashyyyk else [])+(['corellia'] if private else [])
                report=dict(kashyyyk_entry_pilot=kashyyyk,private_mtp_pilot=private,selected=selected)
                self.assertEqual(fixture_scene_selection(report),selected)
        self.assertEqual(fixture_scene_selection(dict(selected=base)),base)

    def test_exit_cannot_be_omitted_substituted_or_enabled_by_a_string(self):
        from inspect_client_fixture import fixture_scene_selection
        base=['tatooine','tutorial','dungeon1','space_npe_falcon','space_ord_mantell']
        for report in (dict(private_mtp_pilot=True,selected=base),
                       dict(private_mtp_pilot=False,selected=base+['corellia']),
                       dict(private_mtp_pilot='true',selected=base+['corellia']),
                       dict(private_mtp_pilot=True,selected=base+['tatooine']),
                       dict(private_mtp_pilot=True,selected=base+['corellia_2'])):
            with self.assertRaises(ValueError):fixture_scene_selection(report)

    def test_saved_owner_scenario_keeps_an_independent_outside_witness(self):
        suite=json.loads((sets.SETS/'private_owned_lifecycle.json').read_text())
        sets.validate(suite)
        changed=copy.deepcopy(suite)
        changed['tests'][1]['options']['member']='actor'
        with self.assertRaises(ValueError):sets.validate(changed)
        changed=copy.deepcopy(suite)
        changed['tests'][1]['options']['zone']='corellia'
        with self.assertRaises(ValueError):sets.validate(changed)

    def test_owner_acceptance_requires_exact_native_room_and_lease(self):
        from private_owned_lifecycle import require_owned_room
        state=dict(inside='true',owned='true',owner='123',root='-999',session='5',sequence='5',limit='1',scene='dungeon1',instance='0')
        row=dict(building='-999',scene='dungeon1',instance='0',room='entryb',group='null',x=3.6,y=-12,z=29.7)
        require_owned_room(state,row,'123')
        for key,value in (('owned','false'),('owner','456'),('root','0'),('session','0'),('sequence','6'),('limit','2'),('instance','4')):
            changed=dict(state);changed[key]=value
            with self.assertRaises(ValueError):require_owned_room(changed,row,'123')
        for key,value in (('building','-998'),('room','hangarbay2'),('instance','4'),('group','123'),('x',0)):
            changed=dict(row);changed[key]=value
            with self.assertRaises(ValueError):require_owned_room(state,changed,'123')


if __name__ == '__main__':
    unittest.main()
