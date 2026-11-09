"""ELF64 checks of the actual generated fixture console argument validator."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class BotConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_login_recovery
        captured = []
        def capture(source, **_):
            captured.append(Path(source).read_text())
        with patch.object(test_login_recovery, 'main', side_effect=capture):
            runpy.run_path(str(Path(__file__).with_name('build_protocol_bot_console.py')),run_name='__main__')
        source = captured[0]
        # Execute the generated validator and formatter, stopping before the
        # socket boundary. Keep its actual number/name/command checks intact.
        number = source[source.index('static bool number'):source.index('static bool transfer')]
        main = source[source.index('int main('):source.index('    for(int i=3;')]
        scope=(test_login_recovery.REPO/'src/engine/server/library/serverUtility/src/shared/ZoneInstanceScope.h').read_text()
        probe = '#include <string>\n#include <cstring>\n#include <iostream>\n'+scope+number+main
        probe += 'for(int i=3;i<argc;++i) {command+=" "+std::string(argv[i]);}\nstd::cout<<command;return 0;}\n'
        cls.folder = tempfile.TemporaryDirectory(prefix='swg-bot-console-guards-')
        root = Path(cls.folder.name)
        path = root/'validator.cpp';path.write_text(probe)
        cls.binary = root/'validator'
        subprocess.run(['g++','-m64','-std=gnu++03','-Wall','-Wextra','-Werror',str(path),'-o',str(cls.binary)],check=True)
        if cls.binary.read_bytes()[:6] != b'\x7fELF\x02\x01':
            raise RuntimeError('ELF64 console validator required')

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def invoke(self, command, player='2562923411',station='903905304',name='Capabcdefghijkl'):
        return subprocess.run([str(self.binary),'127.0.0.1',command,'12',player,station,name],
                              capture_output=True,text=True)

    def test_shutdown_console_is_exactly_scoped(self):
        for args,code in ((['capacityRetireEmpty','kashyyyk_rryatt_trail','6'],0),
                          (['capacityRetireEmpty','space_ord_mantell','6'],0),
                          (['capacityRetireEmpty','space_npe_falcon','6'],0),
                          (['capacityRetireEmpty','dungeon1','6'],2),
                          (['capacityRetireEmpty','space_ord_mantell_2','6'],2),
                          (['capacityRetireEmpty','kashyyyk_rryatt_trail','6;quit'],2),
                          (['capacityRetireEmpty','kashyyyk_rryatt_trail','-1'],2),
                          (['capacityRetireStatus'],0)):
            result=subprocess.run([str(self.binary),'127.0.0.1',*args],capture_output=True,text=True)
            self.assertEqual(result.returncode,code,result.stderr)

    def test_all_canonical_player_worlds_have_only_empty_retirement_and_save(self):
        from instance_scope import load
        for row in load()['definitions']:
            allowed=row['mode'] in ('dynamic_area','piloted_space') or row['definition']=='space_npe_falcon'
            for command in ('capacityRetireEmpty','capacitySaveProbe'):
                result=subprocess.run([str(self.binary),'127.0.0.1',command,row['definition'],'6'],capture_output=True,text=True)
                self.assertEqual(result.returncode,0 if allowed else 2,(row,command,result.stderr))
        for scene in ('space_ord_mantell_2','kashyyyk_pob_dungeons','dungeon1','tatooine','unknown','kashyyyk_main;quit'):
            result=subprocess.run([str(self.binary),'127.0.0.1','capacityRetireEmpty',scene,'6'],capture_output=True)
            self.assertEqual(result.returncode,2,scene)

    def test_ground_cell_commands_are_exact_actor_scoped_setup(self):
        for command,method in (('botGroundCellApproach','approach'),('botGroundCellEnter','enter'),('botGroundCellInspect','inspectCell')):
            result=self.invoke(command)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'game 12 runScript fixture.ground_cell_entry '+method+' 2562923411:903905304:Capabcdefghijkl')
            for change in (dict(name='Schlawe Fiahi'),dict(player='-1'),dict(station='1;quit')):
                self.assertEqual(self.invoke(command,**change).returncode,2)
        for command in ('botGroundCellEnter0','botGroundCellApproach;quit','botGroundCellEnterExtra'):
            self.assertEqual(self.invoke(command).returncode,2)

    def test_temporary_pob_commands_require_the_exact_dedicated_actor(self):
        for suffix,method in (('Prepare','prepare'),('Inspect','inspect'),('Remove','remove')):
            command='botCrewShip'+suffix
            result=self.invoke(command)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'game 12 runScript fixture.private_ship_crew '+method+' 2562923411:903905304:Capabcdefghijkl')
            for change in (dict(name='Schlawe Fiahi'),dict(player='-1'),dict(station='1;quit')):
                self.assertEqual(self.invoke(command,**change).returncode,2)
            self.assertEqual(self.invoke(command+';quit').returncode,2)

    def test_heroic_fixture_has_fixed_actions_and_reviewed_family_indices(self):
        actions=[('botHeroicPrepare'+str(i),'prepare'+str(i)) for i in range(6)]
        actions += [('botHeroic'+suffix,method) for suffix,method in
                    [('Inspect','inspectHeroic'),('Enter','enter'),('Capture','capture'),
                      ('AnchorLeft','anchorLeft'),('AnchorRight','anchorRight'),('Close','close'),('Home','home'),
                      ('ExitSetup','exitSetup'),('Finish','finish')]]
        for command,method in actions:
            result=self.invoke(command)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'game 12 runScript fixture.heroic_entry '+method+' 2562923411:903905304:Capabcdefghijkl')
            for change in (dict(name='Ordinary Player'),dict(player='-1'),dict(station='1;quit')):
                self.assertEqual(self.invoke(command,**change).returncode,2)
        for command in ('botHeroicPrepare6','botHeroicPrepare00','botHeroicPrepare-1','botHeroicEnter;quit','botHeroicSetGroup'):
            self.assertEqual(self.invoke(command).returncode,2)

    def test_occupied_ground_retirement_keeps_exact_scene_scope(self):
        from instance_scope import load
        allowed={'kashyyyk_rryatt_trail','space_ord_mantell','kashyyyk_hunting','kashyyyk_dead_forest'}
        for row in load()['definitions']:
            result=subprocess.run([str(self.binary),'127.0.0.1','capacityRetireOccupied',row['definition'],'6'],capture_output=True)
            self.assertEqual(result.returncode,0 if row['definition'] in allowed else 2,row['definition'])
        for scene in ('kashyyyk_main_2','kashyyyk_pob_dungeons','space_npe_falcon','tatooine','unknown','kashyyyk_main;quit'):
            result=subprocess.run([str(self.binary),'127.0.0.1','capacityRetireOccupied',scene,'6'],capture_output=True)
            self.assertEqual(result.returncode,2,scene)

    def test_recovery_commands_are_typed_and_identity_guarded(self):
        for method in ['originProbe', 'privateMtpPrepare', 'privateMtpEnter', 'privateMtpInspect', 'privateMtpClose', 'privateMtpLeave', 'privateMtpHome','hostedSelection','privateSoloEligibility','privateSoloMtp','privateSoloObiwan','falconEnter','falconInspect','falconArm','falconExit','worldSaveStamp','worldSaveClear','rryattCombatSetup','rryattEnemySetup','rryattEnemyCleanup','rryattQuestReset','rryattMaster','rryattDeath','rryattResurrect','rryattLegacy','rryattStale','rryattForeignGuide']:
            command='bot'+method[0].upper()+method[1:]
            result=self.invoke(command)
            self.assertEqual(result.returncode,0)
            self.assertEqual(result.stdout,'game 12 runScript fixture.protocol_bot '+method+' 2562923411:903905304:Capabcdefghijkl')
            self.assertEqual(self.invoke(command,name='Ordinary Player').returncode,2)
            self.assertEqual(self.invoke(command+';quit').returncode,2)

    def test_saved_object_actions_keep_exact_actor_and_command_guards(self):
        for method in ('encounterLoadSpawn','encounterLoadUnload','encounterLoadInspect','encounterReleaseSpawn','encounterReleaseInspect','encounterReleaseRemove'):
            command='bot'+method[0].upper()+method[1:]
            result=self.invoke(command)
            self.assertEqual(result.returncode,0)
            self.assertEqual(result.stdout,'game 12 runScript fixture.protocol_bot '+method+' 2562923411:903905304:Capabcdefghijkl')
            self.assertEqual(self.invoke(command,name='Ordinary Player').returncode,2)
            self.assertEqual(self.invoke(command,player='2562923411;quit').returncode,2)
            self.assertEqual(self.invoke(command+';quit').returncode,2)

    def test_give_requires_two_exact_dedicated_actor_identities(self):
        args=['127.0.0.1','botEncounterReleaseGive','12','2562923411','903905304','Capabcdefghijkl','2559922180','903905305','Capmnopqrstuvwx']
        result=subprocess.run([str(self.binary),*args],capture_output=True,text=True)
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout,'game 12 runScript fixture.protocol_bot encounterReleaseGive 2562923411:903905304:Capabcdefghijkl,2559922180:903905305:Capmnopqrstuvwx')
        for index,value in ((6,'2559922180;quit'),(7,'0'),(8,'Schlawe Fiahi'),(8,'Capmnopqrstuvwx;quit')):
            bad=list(args);bad[index]=value
            self.assertEqual(subprocess.run([str(self.binary),*bad],capture_output=True).returncode,2)

    def test_all_eight_guide_commands_dispatch_the_matching_typed_method(self):
        for index in range(8):
            result=self.invoke('botRryattGuide'+str(index))
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'game 12 runScript fixture.protocol_bot rryattGuide'+str(index)+
                             ' 2562923411:903905304:Capabcdefghijkl')

    def test_all_world_actions_are_exact_and_do_not_accept_arbitrary_scenes(self):
        for index in range(18):
            result=self.invoke('botWorldEnter'+str(index))
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'game 12 runScript fixture.world_entry worldEnter'+str(index)+
                             ' 2562923411:903905304:Capabcdefghijkl')
        for action in ('Home','Clear'):
            result=self.invoke('botWorld'+action)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('fixture.world_entry world'+action,result.stdout)
        for command in ('botWorldEnter18','botWorldEnter19','botWorldEnter-1','botWorldEnter00','botWorldEnter01',
                        'botWorldEnter','botWorldEnter0;quit','botWorldEnterspace_corellia'):
            self.assertEqual(self.invoke(command).returncode,2,command)
        for change in (dict(name='Schlawe Fiahi'),dict(player='-1'),dict(station='1;quit')):
            self.assertEqual(self.invoke('botWorldEnter0',**change).returncode,2)

    def test_public_routes_are_exact_and_actor_scoped(self):
        for command,method in [('botPublicEnter0','enter0'),('botPublicEnter1','enter1'),
                               ('botPublicExitMyyydril','exitMyyydril'),('botPublicExitNova','exitNova')]:
            result=self.invoke(command)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout,'game 12 runScript fixture.hosted_public_entry '+method+
                             ' 2562923411:903905304:Capabcdefghijkl')
            for change in (dict(name='Schlawe Fiahi'),dict(player='-1'),dict(station='1;quit')):
                self.assertEqual(self.invoke(command,**change).returncode,2)
        for command in ('botPublicEnter2','botPublicEnter01','botPublicEnter-1','botPublicExitNovaExtra',
                        'botPublicEnter0;quit','botPublicEnter','botPublicExitMyyydrilExtra'):
            self.assertEqual(self.invoke(command).returncode,2,command)

    def test_malformed_or_out_of_range_guide_commands_never_dispatch(self):
        for command in ('botRryattGuide8','botRryattGuide00','botRryattGuide-1','botRryattGuide0extra',
                        'botRryattGuide','botRryattGuide0;quit'):
            with self.subTest(command=command):
                self.assertEqual(self.invoke(command).returncode,2)

    def test_guide_commands_cannot_carry_other_names_or_injected_arguments(self):
        for change in (dict(name='Eaka Ized'),dict(player='-1'),dict(station='1;quit'),
                       dict(name='Capabcdefghijk;')):
            with self.subTest(change=change):
                self.assertEqual(self.invoke('botRryattGuide0',**change).returncode,2)


if __name__=='__main__':
    unittest.main()
