"""Fault suites accept a healthy warm baseline and reject uncertain worlds."""
import unittest
from retirement_fault_recovery import needs_baseline_restart

class RetirementFaultBaselineTests(unittest.TestCase):
    def row(self, world, **changes):
        row=dict(definition='kashyyyk_rryatt_trail',instance=str(world),generation='3',state='running',ready='1')
        row.update(changes)
        return row

    def test_one_ready_copy_keeps_current_baseline(self):
        self.assertFalse(needs_baseline_restart([self.row(14)], 'kashyyyk_rryatt_trail'))

    def test_two_ready_copies_from_previous_regressions_need_guarded_restart(self):
        self.assertTrue(needs_baseline_restart([self.row(58),self.row(62)], 'kashyyyk_rryatt_trail'))

    def test_retired_history_and_other_families_do_not_count_as_warm(self):
        rows=[self.row(14),self.row(12,state='retired',ready='0'),self.row(3,definition='space_ord_mantell')]
        self.assertFalse(needs_baseline_restart(rows, 'kashyyyk_rryatt_trail'))

    def test_missing_uncertain_unready_or_oversubscribed_baselines_refuse_restart(self):
        cases=[[],[self.row(14,state='uncertain')],[self.row(14,ready='0')],
               [self.row(14),self.row(16),self.row(18)],[self.row(14),self.row(14)],
               [self.row('014')],[self.row(0)],[self.row(14,generation='0')]]
        for rows in cases:
            with self.subTest(rows=rows),self.assertRaises(RuntimeError):
                needs_baseline_restart(rows,'kashyyyk_rryatt_trail')

    def test_unreviewed_family_is_refused(self):
        with self.assertRaises(ValueError):
            needs_baseline_restart([self.row(14)], 'tatooine')

if __name__ == '__main__':
    unittest.main()
