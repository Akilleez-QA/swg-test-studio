import contextlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from swg_test_studio import recording


class RecordingStartTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.folder=Path(self.temporary.name)/'fixture';self.folder.mkdir()
        (self.folder/'fixture/teststudio').mkdir(parents=True)
        (self.folder/'runtime/config').mkdir(parents=True)
        (self.folder/'runtime/config/game.cfg').write_text('[GameServer]\ntestStudioRecorder=true\n')
        (self.folder/'runtime/stage5-report.json').write_text(json.dumps(dict(test_studio_recording=True)))
        (self.folder/'protocol-driver').mkdir()
        bot=dict(schema_version=1,account='capbot_123abcd',character='Capabcdefghijkl',player='123',station='42')
        (self.folder/'protocol-driver/beta.json').write_text(json.dumps(bot))
        self.env=dict(folder=str(self.folder),bindings=dict(actor='beta'))
        self.mounts=[dict(Destination='/fixture',Source=str(self.folder/'fixture'),RW=False),
                     dict(Destination='/teststudio-capture',Source=str(self.folder/'fixture/teststudio'),RW=True)]
        self.driver=SimpleNamespace(REPO=self.folder,fixture=Mock(return_value=(
            'swg-cold-test-0123abcd','WGC_012345ABCDEF',dict(game=dict(Mounts=self.mounts)))),
            identity=lambda value:value,operation_lock=lambda _:contextlib.nullcontext())
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(recording,'driver_modules',return_value=(self.driver,None)))
        self.stack.enter_context(patch.object(recording,'studio_lock',side_effect=lambda _:contextlib.nullcontext()))

    def test_readonly_tools_and_exact_capture_mount_are_supported(self):
        result=recording.start(self.env,Path(self.temporary.name)/'workspace','actor',60)
        self.assertEqual(result['account'],'capbot_123abcd')
        self.assertEqual(result['state'],'armed_waiting_for_server_events')
        self.assertTrue((self.folder/'fixture/teststudio/123.control').is_file())
        self.assertEqual((self.folder/'fixture/teststudio'/result['id']/'events.jsonl').read_text(),'')
        self.assertFalse(self.mounts[0]['RW'])

    def test_missing_wrong_or_readonly_capture_mount_refuses_before_control(self):
        for change in ({'RW':False},{'Source':str(self.folder/'elsewhere')},{'Destination':'/other'}):
            original=self.mounts[1].copy();self.mounts[1].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                recording.start(self.env,Path(self.temporary.name)/'workspace','actor',60)
            self.assertFalse((self.folder/'fixture/teststudio/123.control').exists())
            self.mounts[1].clear();self.mounts[1].update(original)

    def test_profile_or_game_role_flag_must_be_explicit(self):
        profile=self.folder/'runtime/stage5-report.json';profile.write_text('{}')
        with self.assertRaises(ValueError):recording.start(self.env,Path(self.temporary.name)/'workspace','actor',60)
        profile.write_text(json.dumps(dict(test_studio_recording=True)))
        (self.folder/'runtime/config/game.cfg').write_text('[GameServer]\ntestStudioRecorder=false\n')
        with self.assertRaises(ValueError):recording.start(self.env,Path(self.temporary.name)/'workspace','actor',60)
        self.assertFalse((self.folder/'fixture/teststudio/123.control').exists())


if __name__=='__main__':unittest.main()
