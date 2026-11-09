"""Wait for authoritative quest activation without replaying a conversation."""
import unittest
from unittest.mock import Mock,patch
import rryatt_recovery as recovery
class RecoveryActionTests(unittest.TestCase):
 def test_quest_activation_is_observed_after_async_grant(self):
  case=Mock();case.row.side_effect=[{'mastery_active':'false'},{'mastery_active':'true'}]
  with patch.object(recovery.time,'sleep') as sleep:
   self.assertEqual(recovery.await_flag(case,'actor','mastery_active')['mastery_active'],'true')
  self.assertEqual(case.row.call_count,2);sleep.assert_called_once_with(.5)
  case.setup.assert_not_called()
 def test_missing_quest_state_fails_without_repeating_mutations(self):
  case=Mock();case.row.return_value={'mastery_active':'false'}
  with self.assertRaisesRegex(RuntimeError,'Quest state did not settle'):
   recovery.await_flag(case,'actor','mastery_active',timeout=0)
  case.setup.assert_not_called()

 def audit(self):
  from rryatt_linked import ROUTES
  rows=[]
  for anchor in range(0,24,4):
   for index,(row,route) in enumerate(zip((0,0,0,1,1,2,2,3),ROUTES)):
    rows.append([str(anchor+row),route,str(anchor*8+index+1),'1','188','2','1','188','2','true','-1','ep3_rryatt_trail_guide_f_01','true'])
  return rows
 def check_audit(self,rows):
  return recovery.assert_guide_audit({'count':'48','guides':','.join(':'.join(row) for row in rows)})
 def test_complete_authored_static_roster_passes(self):
  self.assertEqual(len(self.check_audit(self.audit())),48)
 def test_fallen_guide_is_rejected(self):
  rows=self.audit();rows[-1][4]='-10'
  with self.assertRaisesRegex(RuntimeError,'authored platform'):self.check_audit(rows)
 def test_shifted_guide_is_rejected(self):
  rows=self.audit();rows[0][3]='11'
  with self.assertRaisesRegex(RuntimeError,'authored platform'):self.check_audit(rows)
 def test_wrong_linked_row_is_rejected(self):
  rows=self.audit();rows[0][0]='23'
  with self.assertRaisesRegex(RuntimeError,'linked rows'):self.check_audit(rows)
 def test_nonstatic_guide_is_rejected(self):
  rows=self.audit();rows[0][9]='false'
  with self.assertRaisesRegex(RuntimeError,'authored platform'):self.check_audit(rows)
 def test_missing_or_duplicate_guide_is_rejected(self):
  rows=self.audit()
  with self.assertRaisesRegex(RuntimeError,'48 original'):self.check_audit(rows[:-1])
  rows[0]=rows[1]
  with self.assertRaisesRegex(RuntimeError,'identities'):self.check_audit(rows)
