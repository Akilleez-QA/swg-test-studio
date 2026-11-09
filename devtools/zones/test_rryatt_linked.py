"""Negative acceptance checks for linked guide travel evidence."""
import unittest
from rryatt_linked import assert_arrival


class LinkedRouteTests(unittest.TestCase):
    def setUp(self):
        self.before = dict(scene='kashyyyk_rryatt_trail',instance='0',instance_controller='-91',
                           buildout_row='9',x='0',y='0',z='0')
        self.setup = dict(anchor='8',route='rryattThree_rryattFour',target='123',
                          x='10',y='20',z='30',ground_y='20',return_x='1',return_y='2',return_z='3',return_ground_y='2')
        self.after = dict(self.before,buildout_row='10',x='10',y='20',z='30',
                          last_rryatt_guide='123',outstanding='false',connected='true')

    def test_matching_point_in_other_copy_or_controller_is_rejected(self):
        for change in (dict(instance='1'),dict(instance_controller='-92'),dict(buildout_row='14'),
                       dict(scene='kashyyyk_main'),dict(last_rryatt_guide='124')):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                assert_arrival(self.before,dict(self.after,**change),self.setup,4,False)

    def test_invalid_or_unsettled_positions_are_rejected(self):
        for change in (dict(x='nan'),dict(y='inf'),dict(z='31'),dict(outstanding='true'),
                       dict(connected='false')):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                assert_arrival(self.before,dict(self.after,**change),self.setup,4,False)

    def test_guide_return_requires_root_row_and_authored_return_point(self):
        returned = dict(self.after,buildout_row='8',x='1',y='2',z='3')
        assert_arrival(self.before,returned,self.setup,4,True)
        with self.assertRaises(RuntimeError):
            assert_arrival(self.before,self.after,self.setup,4,True)

    def test_foreign_anchor_or_route_is_rejected_before_acceptance(self):
        for change in (dict(anchor='12'),dict(anchor='9'),dict(route='rryattFour_rryattFive')):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                assert_arrival(self.before,self.after,dict(self.setup,**change),4,False)

    def test_terrain_settling_retains_exact_horizontal_destination(self):
        setup=dict(self.setup,ground_y='21')
        assert_arrival(self.before,dict(self.after,y='21'),setup,4,False)
        with self.assertRaises(RuntimeError):
            assert_arrival(self.before,dict(self.after,y='21.5'),setup,4,False)

    def test_collision_platform_above_terrain_is_verified_independently(self):
        setup=dict(self.setup,ground_y='-200',floor_y='20.8')
        assert_arrival(self.before,dict(self.after,y='20.8'),setup,4,False)
        for y in ('-200','20','21'):
            with self.assertRaises(RuntimeError):
                assert_arrival(self.before,dict(self.after,y=y),setup,4,False)

    def test_floor_seam_uses_geometry_and_rejects_large_background_drop(self):
        setup=dict(self.setup,ground_y='-10',floor_y='nan')
        after=dict(self.after,on_floor='true',standing_floor_y='20.33',y='20.33')
        assert_arrival(self.before,after,setup,4,False)
        with self.assertRaises(RuntimeError):
            assert_arrival(self.before,dict(after,y='-10',standing_floor_y='-10'),setup,4,False)

    def test_actual_linked_arrival_is_accepted(self):
        assert_arrival(self.before,self.after,self.setup,4,False)


if __name__ == '__main__':
    unittest.main()
