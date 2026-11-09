"""Strict observation of an original occupied-evacuation capacity charge."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import protocol_test_sets as sets
from retirement_interrupted_arrival import descriptor


class InterruptedEvacuationTests(unittest.TestCase):
    def setUp(self):
        self.bot = {'player': '1234'}
        self.scene = 'space_ord_mantell'
        self.record = '\t'.join(['1', '123', 'x', 'x', 'x', 'x', '1',
                                 self.scene, '47', '-', '1', '1', '1234', 'aa'])

    def test_exact_charge_is_read_only_and_repeatable(self):
        with patch('retirement_interrupted_arrival.run', return_value=self.record) as run:
            first = descriptor('swg-cold-test-1234abcd', self.bot, '123', self.scene, '47')
            self.assertEqual(first, descriptor('swg-cold-test-1234abcd', self.bot, '123', self.scene, '47'))
        self.assertEqual(first['record'], self.record)
        self.assertEqual(run.call_args.args[0], ['docker', 'exec', 'swg-cold-test-1234abcd-central-1',
                         'cat', '/capacity-journal/admission/records/123'])

    def test_linked_world_and_content_charges_must_both_match(self):
        scene = 'kashyyyk_rryatt_trail'
        fields = ['1', '123', 'x', 'x', 'x', 'x', '2', scene, '47', '-', '1',
                  scene, '47', '-42', '1', '1', '1234', 'aa']
        with patch('retirement_interrupted_arrival.run', return_value='\t'.join(fields)):
            self.assertEqual(descriptor('swg-cold-test-1234abcd', self.bot, '123', scene, '47')['grant'], '123')
        fields[12] = '48'
        with patch('retirement_interrupted_arrival.run', return_value='\t'.join(fields)):
            with self.assertRaises(RuntimeError):
                descriptor('swg-cold-test-1234abcd', self.bot, '123', scene, '47')

    def test_missing_payload_or_extra_members_are_refused(self):
        for raw in (self.record.rsplit('\t', 1)[0], self.record+'\t999', self.record[:-2]+'xx'):
            with patch('retirement_interrupted_arrival.run', return_value=raw):
                with self.assertRaises(RuntimeError):
                    descriptor('swg-cold-test-1234abcd', self.bot, '123', self.scene, '47')

    def test_scope_refusals_do_not_access_docker(self):
        for project, grant, scene, world in [('starwarsgalaxies', '123', self.scene, '47'),
                ('swg-cold-test-1234abcd', '../123', self.scene, '47'),
                ('swg-cold-test-1234abcd', '123', 'tatooine', '47'),
                ('swg-cold-test-1234abcd', '123', self.scene, '0'),
                ('swg-cold-test-1234abcd', '123', self.scene, '047')]:
            with self.subTest(project=project, grant=grant, scene=scene, world=world):
                with patch('retirement_interrupted_arrival.run') as run:
                    with self.assertRaises(ValueError):
                        descriptor(project, self.bot, grant, scene, world)
                    run.assert_not_called()

    def test_wrong_actor_world_and_partial_charge_are_refused(self):
        fields = self.record.split('\t')
        for index, value in [(0, '2'), (1, '124'), (6, '0'), (8, '48'), (12, '999')]:
            bad = list(fields)
            bad[index] = value
            with self.subTest(index=index), patch('retirement_interrupted_arrival.run', return_value='\t'.join(bad)):
                with self.assertRaises(RuntimeError):
                    descriptor('swg-cold-test-1234abcd', self.bot, '123', self.scene, '47')

    def test_saved_suite_requires_three_distinct_bound_roles(self):
        data = json.loads((sets.SETS/'stage7_occupied_interrupted.json').read_text())
        sets.validate(data)
        self.assertEqual({c['kind'] for c in data['tests']},
                         {'retirement_occupied_interrupted_rryatt', 'retirement_occupied_interrupted_ord'})
        bad = copy.deepcopy(data)
        bad['tests'][0]['options']['filler'] = 'leader'
        with self.assertRaises(ValueError):
            sets.validate(bad)


if __name__ == '__main__':
    unittest.main()
