"""A dead Central cannot substitute a stale or foreign empty-fixture receipt."""
import contextlib,copy,hashlib,io,json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from central_loss_recovery import CentralLossReceipt, dead_central, same_services, disabled_restart
from configure import NODES

class CentralLossTests(unittest.TestCase):
    def test_fixture_debugger_option_is_explicit_preserved_and_removable(self):
        from prepare_stage5_client_fixture64 import central_debugger
        data=dict(name=self.project,services=dict(central={}))
        self.assertFalse(central_debugger(data,None,True))
        self.assertTrue(central_debugger(data,True,True))
        self.assertEqual(data['services']['central']['cap_add'],['SYS_PTRACE'])
        self.assertTrue(central_debugger(data,None,True))
        self.assertFalse(central_debugger(data,False,True))
        self.assertNotIn('cap_add',data['services']['central'])
        for change in ('canonical','other_cap','privileged','no_shutdown','string'):
            bad=copy.deepcopy(data)
            if change=='canonical':bad['name']='starwarsgalaxies'
            if change=='other_cap':bad['services']['central']['cap_add']=['SYS_ADMIN']
            if change=='privileged':bad['services']['central']['privileged']=True
            before=copy.deepcopy(bad)
            with self.subTest(change=change),self.assertRaises(ValueError):central_debugger(bad,'true' if change=='string' else True,change!='no_shutdown')
            self.assertEqual(bad,before)

    def test_debugger_capability_normalization_and_scope_refusal(self):
        from retirement_central_loss import debugger_container
        row=copy.deepcopy(self.service);row['HostConfig']=dict(Privileged=False,CapAdd=['CAP_SYS_PTRACE'])
        debugger_container(row,self.target,self.project)
        row['HostConfig']['CapAdd']=['SYS_PTRACE'];debugger_container(row,self.target,self.project)
        for change in ('missing','extra','privileged','image','identity','project','fixture','role'):
            bad=copy.deepcopy(row)
            if change=='missing':bad['HostConfig']['CapAdd']=[]
            elif change=='extra':bad['HostConfig']['CapAdd'].append('SYS_ADMIN')
            elif change=='privileged':bad['HostConfig']['Privileged']=True
            elif change=='image':bad['Image']='different'
            elif change=='identity':bad['Id']='different'
            elif change=='project':bad['Config']['Labels']['com.docker.compose.project']='starwarsgalaxies'
            elif change=='fixture':bad['Config']['Labels']['whitengold.test.client']=''
            elif change=='role':bad['Config']['Labels']['com.docker.compose.service']='game'
            with self.subTest(change=change),self.assertRaises(ValueError):debugger_container(bad,self.target,self.project)

    def test_debugger_scopes_and_exact_native_hit(self):
        from retirement_central_loss import freeze_breakpoint_script,FreezeBreakpoint
        target=dict(role='central',container='swg-cold-test-d9d6e6af-central-1',pid='20',start_ticks='123')
        expected=dict(definition='kashyyyk_rryatt_trail',instance='8',generation='3',operation='4')
        text=freeze_breakpoint_script(target,expected,'/tmp/central-loss-test',200)
        self.assertIn('tbreak CentralServer_WorldShutdown.cpp:200',text)
        self.assertEqual(text.count("/proc/20/exe"),2)
        self.assertIn('timeout 10',text)
        for change in ({'container':'starwarsgalaxies-central-1'},{'pid':'20;quit'},{'start_ticks':'0'},{'role':'game'}):
            with self.subTest(change=change),self.assertRaises(ValueError):freeze_breakpoint_script(dict(target,**change),expected,'/tmp/central-loss-test',200)
        for remote in ('/tmp','/tmp/central-loss-../other','/tmp/central-loss-test;quit'):
            with self.subTest(remote=remote),self.assertRaises(ValueError):freeze_breakpoint_script(target,expected,remote,200)
        with tempfile.TemporaryDirectory() as name:
            gate=object.__new__(FreezeBreakpoint);gate.log=Path(name)/'log';gate.wait=lambda *a:None
            token='FIXTURE_FREEZE_HIT world=8 generation=3 operation=4 phase=3'
            gate.log.write_text(token+'\n');gate.hit(expected)
            for wrong in (token.replace('world=8','world=9'),token.replace('phase=3','phase=4'),token.replace('operation=4','operation=5')):
                gate.log.write_text(wrong+'\n')
                with self.subTest(wrong=wrong),self.assertRaises(RuntimeError):gate.hit(expected)

    def setUp(self):
        self.project='swg-cold-test-d9d6e6af';self.schema='WGC_AE80ACB41011'
        self.service={'Id':'a'*64,'Image':'sha256:'+'b'*64,'Mounts':[], 'State':{'Running':True},
            'Config':{'Labels':{'com.docker.compose.project':self.project,'com.docker.compose.service':'central','whitengold.test.client':self.schema}}}
        self.target=dict(pid='20',start_ticks='123',executable='/opt/whitengold/bin/CentralServer',sha256='c'*64,
            container=self.project+'-central-1',container_id='a'*64,image_id='sha256:'+'b'*64,role='central')

    def test_restart_wakes_only_proven_stopped_managed_families(self):
        from protocol_fixture_restart import stopped_warm_wakes
        scenes=[dict(scene=name,instance='0',preload='finished',heartbeat_fresh='1')
                for name in ('tatooine','tutorial','dungeon1','kashyyyk_main')]
        instances=[dict(definition=name,state='stopped') for name in
                   ('space_npe_falcon','space_ord_mantell','kashyyyk_rryatt_trail')]
        self.assertEqual(stopped_warm_wakes(scenes,instances,True),
                         ['space_npe_falcon','space_ord_mantell','kashyyyk_rryatt_trail'])
        instances[0]['state']='uncertain'
        self.assertEqual(stopped_warm_wakes(scenes,instances,True),
                         ['space_ord_mantell','kashyyyk_rryatt_trail'])
        scenes[0]['heartbeat_fresh']='0'
        self.assertEqual(stopped_warm_wakes(scenes,instances,True),[])
    def test_saved_suite_has_only_typed_reviewed_family_inputs(self):
        import protocol_test_sets as sets
        data=json.loads((sets.SETS/'stage7_central_fencing.json').read_text());sets.validate(data)
        for key,value in [('family','space_npe_falcon_2'),('pid','20'),('phase','stopping_games'),('member','leader')]:
            bad=copy.deepcopy(data);bad['tests'][1]['options'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):sets.validate(bad)
        argv=sets.command(data['tests'][1],{'leader':'beta','member':'gamma'},Path('/tmp/folder'),Path('/tmp/peer'),
            {'overlay':Path('/tmp/overlay'),'jdk':Path('/tmp/jdk')},Path('/tmp/console'),Path('/tmp/retirement'))
        self.assertTrue(argv[1].endswith('retirement_central_loss.py'));self.assertNotIn('--pid',argv)

    def test_authorizing_suite_is_fixed_to_database_hold_for_all_families(self):
        import protocol_test_sets as sets
        data=json.loads((sets.SETS/'stage7_central_authorizing.json').read_text());sets.validate(data)
        self.assertEqual({c['options']['family'] for c in data['tests'][1:]},{'rryatt','ord','falcon'})
        for case in data['tests'][1:]:
            argv=sets.command(case,{'leader':'beta','member':'gamma'},Path('/tmp/folder'),Path('/tmp/peer'),
                {'overlay':Path('/tmp/overlay'),'jdk':Path('/tmp/jdk')},Path('/tmp/console'),Path('/tmp/retirement'))
            self.assertEqual(argv[-2:],['--boundary','authorizing'])
        for change in ({'phase':'freezing'},{'role':'oracle'},{'pid':'1'}):
            bad=copy.deepcopy(data);bad['tests'][1]['options'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):sets.validate(bad)

    def test_database_loss_suite_has_fixed_boundary_and_reviewed_families(self):
        import protocol_test_sets as sets
        data=json.loads((sets.SETS/'stage7_database_authorizing.json').read_text());sets.validate(data)
        self.assertEqual({c['options']['family'] for c in data['tests'][2:]},{'rryatt','falcon','ord'})
        for case in data['tests'][2:]:
            argv=sets.command(case,{'leader':'beta','member':'gamma'},Path('/tmp/folder'),Path('/tmp/peer'),
                {'overlay':Path('/tmp/overlay'),'jdk':Path('/tmp/jdk')},Path('/tmp/console'),Path('/tmp/retirement'))
            self.assertEqual(argv[-4:],['--boundary','authorizing','--fault-service','database'])
        bad=copy.deepcopy(data);bad['tests'][2]['options']['role']='oracle'
        with self.assertRaises(ValueError):sets.validate(bad)

    def test_coordinator_loss_suite_has_fixed_fencing_boundary(self):
        import protocol_test_sets as sets
        data=json.loads((sets.SETS/'stage7_coordinator_fencing.json').read_text());sets.validate(data)
        self.assertEqual({c['options']['family'] for c in data['tests'][2:]},{'rryatt','falcon','ord'})
        for case in data['tests'][2:]:
            argv=sets.command(case,{'leader':'beta','member':'gamma'},Path('/tmp/folder'),Path('/tmp/peer'),
                {'overlay':Path('/tmp/overlay'),'jdk':Path('/tmp/jdk')},Path('/tmp/console'),Path('/tmp/retirement'))
            self.assertEqual(argv[-4:],['--boundary','fencing','--fault-service','coordinator'])
        bad=copy.deepcopy(data);bad['tests'][2]['options']['role']='oracle'
        with self.assertRaises(ValueError):sets.validate(bad)

    def test_signal_allowlist_scopes_supervisor_kills_and_refuses_worker_kills(self):
        from retirement_central_loss import signal
        with patch('retirement_central_loss.run',return_value='verified') as command:
            for role in ('database','taskmanager','game','planet'):
                target=dict(self.target,role=role,container=self.project+'-'+role+'-1')
                for mode in ('--stop','--continue','--check'):
                    self.assertEqual(signal(self.project,target,'/tmp/signal',mode),'verified')
                    self.assertEqual(command.call_args.args[0][-2:],[{'database':'database','taskmanager':'coordinator','game':'game-supervisor','planet':'planet-supervisor'}[role],mode])
                command.reset_mock()
                self.assertEqual(signal(self.project,target,'/tmp/signal','--kill'),'verified')
                self.assertEqual(command.call_args.args[0][-2:],
                                 [{'database':'database','taskmanager':'coordinator',
                                   'game':'game-supervisor','planet':'planet-supervisor'}[role],'--kill'])
                command.reset_mock()
            worker=dict(self.target,role='game',container=self.project+'-game-1',kind='worker',
                        scene='space_ord_mantell',world='57',generation='3')
            with self.assertRaises(ValueError):signal(self.project,worker,'/tmp/signal','--kill')
            command.assert_not_called()
            with self.assertRaises(ValueError):signal(self.project,self.target,'/tmp/signal','--stop')
            command.assert_not_called()

    def test_supervisor_loss_suites_fix_boundary_and_family(self):
        import protocol_test_sets as sets
        for role,phase in [('game','stopping_games'),('planet','stopping_planet')]:
            data=json.loads((sets.SETS/('stage7_'+role+'_supervisor_stop.json')).read_text())
            sets.validate(data)
            self.assertEqual({case['options']['family'] for case in data['tests'][2:]},
                             {'rryatt','falcon','ord'})
            for case in data['tests'][2:]:
                argv=sets.command(case,{'leader':'beta','member':'gamma'},Path('/tmp/folder'),
                                  Path('/tmp/peer'),{'overlay':Path('/tmp/overlay'),'jdk':Path('/tmp/jdk')},
                                  Path('/tmp/console'),Path('/tmp/retirement'))
                self.assertEqual(argv[-4:],['--boundary',phase,'--fault-service',role+'-supervisor'])
            bad=copy.deepcopy(data);bad['tests'][2]['options']['pid']='1'
            with self.assertRaises(ValueError):sets.validate(bad)

    def test_hold_requires_stopped_original_process_before_injection(self):
        from retirement_central_loss import held_service
        target=dict(self.target,role='database',container=self.project+'-database-1')
        def stat(state='T',ticks='123',pid='20'):
            return pid+' (SwgDatabaseServer) '+' '.join([state]+['0']*18+[ticks])
        held_service(target,lambda argv:stat())
        for value in (stat('S'),stat('Z'),stat(ticks='124'),stat(pid='21'),'truncated'):
            with self.subTest(stat=value),self.assertRaises(RuntimeError):held_service(target,lambda argv:value)
        with self.assertRaises(ValueError):held_service(dict(target,container='starwarsgalaxies-database-1'),lambda argv:self.fail('Foreign IO'))

    def test_authorization_wait_requires_full_fence_then_exact_unadvanced_boundary(self):
        from retirement_central_loss import await_boundary,HOLDS
        self.assertEqual(HOLDS,{'fencing':'taskmanager','authorizing':'database','freezing':'database','committing':'database','stopping_games':'database','stopping_planet':'database'})
        expected=dict(definition='space_ord_mantell',instance='8',generation='3',operation='4',workers='1')
        initial=dict(expected,state='fencing',nodes='10',fenced_nodes='5',frozen='0',saved='0',game_reaps='0',reaped_launches='0',failed_at='idle',failure_reason='none')
        authorized=dict(initial,state='authorizing',fenced_nodes='10');observations=[];pause=[]
        def text(row):return 'shutdown\n'+'\t'.join(row)+'\n'+'\t'.join(row.values())+'\n'
        values=iter([text(initial),text(authorized)]);matched=[]
        self.assertEqual(await_boundary(lambda command:next(values),expected,'authorizing',10,observations,lambda:10.,pause.append,matched.append),authorized)
        self.assertEqual(observations,[initial,authorized]);self.assertEqual(pause,[.1]);self.assertEqual(matched,[authorized])
        for change in ({'fenced_nodes':'9'},{'state':'freezing'},{'state':'quarantined'},{'generation':'4'},{'frozen':'1'}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):
                await_boundary(lambda command:text(dict(authorized,**change)),expected,'authorizing',10,[],lambda:10.,lambda seconds:None)
        with self.assertRaises(RuntimeError):
            await_boundary(lambda command:text(initial),expected,'fencing',10,[],lambda:10.,lambda seconds:None)

    def test_boundary_wait_deadline_clock_rollback_and_unimplemented_phase_refuse(self):
        from retirement_central_loss import await_boundary
        query=lambda command:self.fail('No query after invalid deadline or phase')
        for times in ([100.,99.],[100.,126.],[100.,float('nan')],[100.,float('inf')]):
            ticks=iter(times)
            with self.subTest(times=times),self.assertRaises(TimeoutError):
                await_boundary(query,{},'authorizing',10,[],lambda:next(ticks))
        with self.assertRaises(ValueError):await_boundary(query,{},'retired',10,[])

    def test_all_old_generation_launch_markers_must_survive_recovery(self):
        from retirement_central_loss import launch_markers
        expected=dict(definition='space_ord_mantell',instance='8',generation='3',operation='4')
        calls=[]
        def query(argv):calls.append(argv);return '4'
        self.assertEqual(launch_markers(self.project,NODES,expected,query),{role:'4' for role in NODES})
        self.assertEqual(len(calls),10)
        self.assertTrue(all(c[-1]=='/world-launch-fences/space_ord_mantell-8-3.fence' for c in calls))
        with self.assertRaises(RuntimeError):launch_markers(self.project,NODES,expected,lambda argv:'5')
        for project,roles,row in [('starwarsgalaxies',NODES,expected),(self.project,NODES[:-1],expected),
                (self.project,NODES,dict(expected,generation='03')),(self.project,NODES,dict(expected,definition='dungeon1'))]:
            with self.subTest(project=project,row=row),self.assertRaises(ValueError):
                launch_markers(project,roles,row,lambda argv:self.fail('Invalid marker query'))

    def test_reap_suites_fix_each_phase_and_cover_all_reviewed_families(self):
        import protocol_test_sets as sets
        from retirement_central_loss import SECONDARY_HOLDS
        self.assertEqual(SECONDARY_HOLDS,{'freezing':'game','committing':'game','stopping_games':'game','stopping_planet':'planet'})
        for phase in SECONDARY_HOLDS:
            data=json.loads((sets.SETS/('stage7_central_'+phase+'.json')).read_text());sets.validate(data)
            self.assertEqual({c['options']['family'] for c in data['tests'][1:]},{'rryatt','falcon','ord'})
            for case in data['tests'][1:]:
                argv=sets.command(case,{'leader':'beta','member':'gamma'},Path('/tmp/folder'),Path('/tmp/peer'),
                    {'overlay':Path('/tmp/overlay'),'jdk':Path('/tmp/jdk')},Path('/tmp/console'),Path('/tmp/retirement'))
                self.assertEqual(argv[-2:],['--boundary',phase])
                bad=copy.deepcopy(data);bad['tests'][1]['options']['pid']='1'
                with self.assertRaises(ValueError):sets.validate(bad)

    def test_reap_wait_requires_real_freeze_commit_and_ordered_game_receipts(self):
        from retirement_central_loss import await_boundary
        expected=dict(definition='space_npe_falcon',instance='8',generation='3',operation='4',workers='1')
        authorizing=dict(expected,state='authorizing',nodes='10',fenced_nodes='10',frozen='0',saved='0',game_reaps='0',reaped_launches='0',failed_at='idle',failure_reason='none')
        freezing=dict(authorizing,state='freezing');committing=dict(authorizing,state='committing',frozen='1')
        games=dict(committing,state='stopping_games',saved='1');planet=dict(games,state='stopping_planet',game_reaps='1',reaped_launches='1')
        def text(row):return 'shutdown\n'+'\t'.join(row)+'\n'+'\t'.join(row.values())+'\n'
        for phase,sequence in [('stopping_games',[authorizing,freezing,committing,games]),('stopping_planet',[authorizing,freezing,committing,games,planet])]:
            values=iter(map(text,sequence));seen=[]
            self.assertEqual(await_boundary(lambda command:next(values),expected,phase,10,seen,lambda:10.,lambda seconds:None),sequence[-1])
            self.assertEqual(seen,sequence)
        for phase,row in [('stopping_games',dict(games,saved='0')),('stopping_games',planet),
                          ('stopping_planet',dict(planet,game_reaps='0')),('stopping_planet',dict(planet,reaped_launches='2')),
                          ('stopping_planet',dict(authorizing,fenced_nodes='9'))]:
            with self.subTest(phase=phase,row=row),self.assertRaises(RuntimeError):
                await_boundary(lambda command:text(row),expected,phase,10,[],lambda:10.,lambda seconds:None)

    def test_worker_hold_keeps_generation_package_and_captured_container_scope(self):
        from retirement_central_loss import observe_worker,signal
        meta=copy.deepcopy(self.service);meta['Config']['Labels']['com.docker.compose.service']='game'
        manifest={'files':{'bin/SwgGameServer':{'sha256':'c'*64}}}
        expected=dict(definition='space_ord_mantell',instance='8',generation='3')
        found=dict(pid='20',start_ticks='123',scene='space_ord_mantell',world='8',generation='3',role='game',sha256='c'*64,container_id=meta['Id'],image_id=meta['Image'])
        with patch('retirement_central_loss.worker_target',return_value=found) as target:
            observed=observe_worker(self.project,self.schema,{'game':meta},manifest,expected)
            target.assert_called_once_with(self.project,'space_ord_mantell','8','3','game','c'*64)
            self.assertEqual(observed['kind'],'worker')
            target.return_value=dict(found,container_id='d'*64)
            with self.assertRaises(RuntimeError):observe_worker(self.project,self.schema,{'game':meta},manifest,expected)
        with patch('retirement_central_loss.run',return_value='verified') as run:
            for mode in ('--stop','--continue','--check'):
                signal(self.project,observed,'/tmp/signal',mode)
                self.assertEqual(run.call_args.args[0][-4:],['space_ord_mantell','8','game',mode])
            run.reset_mock()
            for change,mode in [({},'--kill'),({'generation':'0'},'--stop'),({'kind':'untrusted'},'--stop'),({'scene':'dungeon1'},'--stop')]:
                with self.subTest(change=change,mode=mode),self.assertRaises(ValueError):signal(self.project,dict(observed,**change),'/tmp/signal',mode)
            run.assert_not_called()

    def test_freeze_and_commit_waits_refuse_missing_or_unearned_worker_proof(self):
        from retirement_central_loss import await_boundary
        expected=dict(definition='kashyyyk_rryatt_trail',instance='8',generation='3',operation='4',workers='1')
        freezing=dict(expected,state='freezing',nodes='10',fenced_nodes='10',frozen='0',saved='0',game_reaps='0',reaped_launches='0',failed_at='idle',failure_reason='none')
        committing=dict(freezing,state='committing',frozen='1')
        def text(row):return 'shutdown\n'+'\t'.join(row)+'\n'+'\t'.join(row.values())+'\n'
        self.assertEqual(await_boundary(lambda command:text(freezing),expected,'freezing',10,[],lambda:10.),freezing)
        values=iter(map(text,[freezing,committing]));seen=[]
        self.assertEqual(await_boundary(lambda command:next(values),expected,'committing',10,seen,lambda:10.,lambda s:None),committing)
        for phase,row in [('freezing',committing),('freezing',dict(freezing,frozen='1')),('committing',dict(committing,frozen='0')),('committing',dict(committing,saved='1'))]:
            with self.subTest(phase=phase,row=row),self.assertRaises(RuntimeError):await_boundary(lambda command:text(row),expected,phase,10,[],lambda:10.)

    def test_full_saved_matrix_covers_each_family_at_each_boundary_once(self):
        import protocol_test_sets as sets
        data=json.loads((sets.SETS/'stage7_central_fault_matrix.json').read_text());sets.validate(data)
        self.assertEqual(len(data['tests']),20)
        self.assertEqual(data['tests'][1]['options'],{'gate':'retirement_fault_services'})
        expected={(phase,family) for phase in ('fencing','authorizing','freezing','committing','stopping_games','stopping_planet') for family in ('rryatt','falcon','ord')}
        actual={(c['kind'][len('retirement_central_'):],c['options']['family']) for c in data['tests'][2:]}
        self.assertEqual(actual,expected)

    def test_fault_signal_refuses_foreign_container_before_docker(self):
        from retirement_central_loss import signal
        with patch('retirement_central_loss.run') as command:
            for change in ({'container':'starwarsgalaxies-central-1'},{'role':'oracle'}):
                with self.subTest(change=change),self.assertRaises(ValueError):
                    signal(self.project,dict(self.target,**change),'/tmp/signal','--kill')
            command.assert_not_called()

    def test_unchanged_scoped_services_are_required(self):
        before={'central':self.service}
        self.assertEqual(same_services(before,copy.deepcopy(before),self.project),None)
        for change in ('Id','Image','Mounts','project','role','state','extra'):
            after=copy.deepcopy(before)
            if change in ('Id','Image','Mounts'):after['central'][change]='changed'
            elif change=='project':after['central']['Config']['Labels']['com.docker.compose.project']='starwarsgalaxies'
            elif change=='role':after['central']['Config']['Labels']['com.docker.compose.service']='game'
            elif change=='state':after['central']['State']['Running']=False
            else:after['other']=self.service
            with self.subTest(change=change),self.assertRaises(RuntimeError):same_services(before,after,self.project)

    def test_only_exact_killed_coordinator_may_be_stopped_for_recovery(self):
        before={'taskmanager':copy.deepcopy(self.service),'central':copy.deepcopy(self.service)}
        before['taskmanager']['Config']['Labels']['com.docker.compose.service']='taskmanager'
        after=copy.deepcopy(before)
        after['taskmanager']['State']={'Running':False,'Status':'exited','ExitCode':137}
        same_services(before,after,self.project,'taskmanager')
        with self.assertRaises(RuntimeError):same_services(before,after,self.project)
        after['taskmanager']['State']['ExitCode']=0
        with self.assertRaises(RuntimeError):same_services(before,after,self.project,'taskmanager')
        after['taskmanager']['State']['ExitCode']=137
        after['central']['State']={'Running':False,'Status':'exited','ExitCode':137}
        with self.assertRaises(RuntimeError):same_services(before,after,self.project,'taskmanager')

    def test_coordinator_receipt_requires_exact_pidfd_kill(self):
        receipt=object.__new__(CentralLossReceipt)
        receipt.project=self.project
        receipt.services={'taskmanager':self.service}
        target=dict(self.target,role='taskmanager',container=self.project+'-taskmanager-1')
        proof='verified_pid=20 start_ticks=123 signal=9 role=coordinator'
        receipt.record_coordinator_loss(target,proof)
        self.assertEqual(receipt.coordinator_loss,target)
        for wrong in (proof.replace('signal=9','signal=19'),proof.replace('role=coordinator','role=database')):
            with self.assertRaises(RuntimeError):receipt.record_coordinator_loss(target,wrong)
    def test_complete_swg_roster_includes_its_existing_local_chat_backend(self):
        from configure import ROLES
        before={role:copy.deepcopy(self.service) for role in set(ROLES)|{'oracle','local_chat'}}
        for role,row in before.items():row['Config']['Labels']['com.docker.compose.service']=role
        same_services(before,copy.deepcopy(before),self.project)
        after=copy.deepcopy(before);after['local_chat']['Image']='sha256:'+'d'*64
        with self.assertRaises(RuntimeError):same_services(before,after,self.project)

    def test_dead_original_and_matching_package_without_replacement(self):
        calls=[]
        def query(argv):
            calls.append(argv)
            if argv[3]=='ps':return 'PID COMMAND\n1 /opt/whitengold/bin/TaskManager\n'
            if argv[3]=='sha256sum':return 'c'*64+'  /opt/whitengold/bin/CentralServer'
            self.fail(str(argv))
        dead_central(self.target,query)
        self.assertEqual(len(calls),2)
    def test_original_replacement_or_changed_package_refuse(self):
        for ps,digest in [('20 /opt/whitengold/bin/CentralServer','c'*64),
                ('21 /opt/whitengold/bin/CentralServer','c'*64),('20 [CentralServer] <defunct>','c'*64),
                ('20 /different/program','c'*64),('1 /opt/whitengold/bin/TaskManager','d'*64)]:
            def query(argv):return ps if argv[3]=='ps' else digest+'  /opt/whitengold/bin/CentralServer'
            with self.subTest(ps=ps,digest=digest),self.assertRaises(RuntimeError):dead_central(self.target,query)
    def test_receipt_expiry_clock_rollback_and_scope_drift_refuse_before_io(self):
        r=object.__new__(CentralLossReceipt)
        r.created=100.;r.clock=lambda:101.;r.project=self.project;r.schema=self.schema
        r.overlay=Path('/tmp/accepted');r.players=['7','8']
        for now,project,schema,overlay,players in [(99.,self.project,self.schema,r.overlay,['7','8']),
                (281.,self.project,self.schema,r.overlay,['7','8']),
                (101.,'starwarsgalaxies',self.schema,r.overlay,['7','8']),
                (101.,self.project,'WGC_000000000000',r.overlay,['7','8']),
                (101.,self.project,self.schema,Path('/tmp/other'),['7','8']),
                (101.,self.project,self.schema,r.overlay,['7','9'])]:
            r.clock=lambda:now
            with self.subTest(now=now,project=project,schema=schema,players=players),self.assertRaises(RuntimeError):
                r.scope(project,schema,overlay,[{'player':p} for p in players])
    def test_restart_has_no_cli_receipt_bypass(self):
        import protocol_fixture_restart as restart
        err=io.StringIO()
        with contextlib.redirect_stderr(err),self.assertRaises(SystemExit):
            restart.main(['--folder','/tmp/fixture','--overlay','/tmp/overlay','--jdk','/tmp/jdk',
                          '--console','/tmp/console','--bots','beta','gamma','--central-loss-receipt','forged.json'])
        self.assertIn('unrecognized arguments: --central-loss-receipt',err.getvalue())

    def test_authorization_rechecks_dead_process_package_scope_and_saved_data(self):
        with tempfile.TemporaryDirectory(prefix='swg-loss-proof-') as name:
            root=Path(name);(root/'manifest.json').write_text('{}')
            r=object.__new__(CentralLossReceipt);r.created=100.;r.clock=lambda:101.
            r.project=self.project;r.schema=self.schema;r.overlay=root;r.folder=root;r.players=['7','8']
            r.services={'central':self.service};r.configs={'config':'sha'};r.target=self.target
            r.bots=[{'player':'7'},{'player':'8'}];r.saved_players=[{'id':'7'},{'id':'8'}]
            r.restart_policy={};r.manifest_sha256=hashlib.sha256(b'{}').hexdigest();r.original={'sha256':'saved'};r.empty_proof='fresh zero proof'
            with patch('central_loss_recovery.config_hashes',return_value=r.configs),\
                 patch('central_loss_recovery.dead_central') as dead,\
                 patch('central_loss_recovery.disabled_restart',return_value=r.restart_policy),\
                 patch('central_loss_recovery.unloaded',side_effect=AssertionError('Dead Central cannot answer unload queries')) as unload,\
                 patch('central_loss_recovery.saved',side_effect=lambda p,s,b:{'id':b}),\
                 patch('central_loss_recovery.snapshot',return_value=r.original) as saved:
                self.assertEqual(r.authorize(self.project,self.schema,r.services,[{'player':'7'},{'player':'8'}],root),r.empty_proof)
                dead.assert_called_once_with(self.target);unload.assert_not_called()
                saved.return_value={'sha256':'changed'}
                with self.assertRaises(RuntimeError):r.authorize(self.project,self.schema,r.services,[{'player':'7'},{'player':'8'}],root)
                saved.return_value=r.original
                (root/'manifest.json').write_text('changed')
                with self.assertRaises(RuntimeError):r.authorize(self.project,self.schema,r.services,[{'player':'7'},{'player':'8'}],root)

    def test_dead_restart_preflight_never_queries_bot_census_or_live_empty_console(self):
        import protocol_fixture_restart as restart
        with tempfile.TemporaryDirectory(prefix='swg-loss-restart-') as name:
            root=Path(name);(root/'runtime').mkdir();(root/'protocol-driver').mkdir()
            policy=dict(rryatt_demand_instances=True,policy=dict(rryatt_maximum_instances=2,rryatt_capacity=2,ord_capacity=2))
            (root/'runtime/stage5-report.json').write_text(json.dumps(policy))
            for key,player in [('alpha','7'),('beta','8')]:
                (root/'protocol-driver'/(key+'.json')).write_text(json.dumps({'player':player}))
            receipt=object.__new__(CentralLossReceipt)
            with patch.object(restart,'fixture',return_value=(self.project,self.schema,{'oracle':{'Id':'oracle'}})),\
                 patch.object(restart,'identity',side_effect=lambda v:v),\
                 patch.object(restart,'unloaded',side_effect=AssertionError('Central is dead')) as unload,\
                 patch.object(restart,'require_empty_fixture',side_effect=AssertionError('Central is dead')) as empty,\
                 patch.object(CentralLossReceipt,'authorize',return_value='fresh captured proof') as authorize,\
                 patch.object(restart,'snapshot',side_effect=RuntimeError('stop after preflight')):
                with self.assertRaisesRegex(RuntimeError,'stop after preflight'):
                    restart.main(['--folder',str(root),'--overlay',str(root),'--jdk',str(root),'--console',str(root),'--rryatt','--bots','alpha','beta'],recovery=receipt)
                authorize.assert_called_once();unload.assert_not_called();empty.assert_not_called()

    def test_running_supervisors_must_load_the_explicit_false_configuration(self):
        with tempfile.TemporaryDirectory(prefix='swg-loss-config-') as name:
            folder=Path(name);config=folder/'runtime/config';config.mkdir(parents=True)
            runtime=folder/'runtime/runtime.cfg';runtime.write_text('[TaskManager]\nmaximumLoad=3\n')
            expected='[TaskManager]\nrestartCentral=false\n'
            for role in NODES:(config/(role+'.cfg')).write_text(expected)
            def query(argv):
                self.assertTrue(argv[2].startswith(self.project+'-'))
                if argv[3]=='cat':return '[SharedFile]\nuseTreeFiles=true'
                if argv[3]=='ps':return '1 /opt/whitengold/bin/TaskManager -- @/run/whitengold/runtime.cfg @/run/whitengold/container.cfg'
                path=runtime if argv[-1].endswith('/runtime.cfg') else config/'central.cfg'
                return hashlib.sha256(path.read_bytes()).hexdigest()+'  '+argv[-1]
            self.assertEqual(set(disabled_restart(folder,self.project,query)),set(NODES))
            runtime.write_text('.include "/opt/whitengold/exe/shared/servercommon.cfg"\n[TaskManager]\nmaximumLoad=3\n')
            self.assertTrue(all('shared_text_sha256' in v for v in disabled_restart(folder,self.project,query).values()))
            for text in ('[TaskManager]\nrestartCentral=true\n','[TaskManager]\nrestartCentral=false\nrestartCentral=false\n','@other.cfg\n'):
                (config/(NODES[0]+'.cfg')).write_text(text)
                with self.subTest(text=text),self.assertRaises(RuntimeError):disabled_restart(folder,self.project,query)
            (config/(NODES[0]+'.cfg')).write_text(expected)
            def overridden(argv):
                value=query(argv)
                return value+' restartCentral=true' if argv[3]=='ps' else value
            with self.assertRaises(RuntimeError):disabled_restart(folder,self.project,overridden)

if __name__=='__main__':unittest.main()
