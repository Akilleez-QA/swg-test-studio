"""Refuse stale, missing, ambiguous and invalid original clone choices."""
import unittest
from protocol_clone import choose


class CloneChoiceTests(unittest.TestCase):
    def test_current_original_choice_is_selected_without_fabricating_a_location(self):
        row=dict(dead='true',clone_page='7',clone_targets='kashyyyk_hunting:1:2:3:0,kashyyyk_main:4:5:6:0')
        self.assertEqual(choose(row,dict(name='Script.listBox',page=7),'kashyyyk_main'),(1,dict(x=4.,y=5.,z=6.)))

    def test_stale_live_empty_duplicate_nonfinite_and_out_of_bounds_refuse(self):
        row=dict(dead='true',clone_page='7',clone_targets='kashyyyk_main:4:5:6:0');page=dict(name='Script.listBox',page=7)
        for change in ({'dead':'false'},{'dead':None},{'clone_page':'8'},{'clone_targets':'none'},
                       {'clone_targets':row['clone_targets']+','+row['clone_targets']},
                       {'clone_targets':'kashyyyk_main:NaN:0:0:0'},{'clone_targets':'kashyyyk_main:20000:0:0:0'}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):choose(dict(row,**change),page,'kashyyyk_main')
        for changed in (dict(page,page=8),dict(page,name='Script.messageBox')):
            with self.assertRaises(RuntimeError):choose(row,changed,'kashyyyk_main')


if __name__=='__main__':unittest.main()
