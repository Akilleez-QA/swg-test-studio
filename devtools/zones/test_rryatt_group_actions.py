import unittest
from rryatt_group import anchor,assert_translation,assert_stationary
class PublicGroupActionTests(unittest.TestCase):
    def fixtures(self):
        origin={'scene':'kashyyyk_rryatt_trail','instance':'0','buildout_row':'4','instance_controller':'-2','x':'500','y':'5','z':'100','on_floor':'true'}
        destination=dict(origin,buildout_row='0',instance_controller='-1',x='0',z='0')
        before=dict(origin,buildout_row='7',x='510',z='120')
        after=dict(destination,buildout_row='3',x='10',z='20')
        return before,after,origin,destination
    def test_independent_level_guard(self):
        before=self.fixtures()[0]
        assert_stationary(before,dict(before))
        for change in ({'buildout_row':'6'},{'instance_controller':'-1'},{'x':'511'},{'z':'130'},{'y':'50'},{'pending':'true'},{'outstanding':'true'},{'x':'nan'}):
            with self.subTest(change=change),self.assertRaises(RuntimeError):assert_stationary(before,dict(before,**change))
    def test_matching_position_and_child_level(self):assert_translation(*self.fixtures())
    def test_wrong_controller_child_coordinates_floor_and_world_are_rejected(self):
        for change in ({'instance_controller':'-2'},{'buildout_row':'2'},{'x':'0'},{'z':'21'},{'y':'-200'},{'on_floor':'false'},{'instance':'1'}):
            before,after,origin,destination=self.fixtures();after.update(change)
            with self.subTest(change=change),self.assertRaises(RuntimeError):assert_translation(before,after,origin,destination)
    def test_terrain_standing_does_not_require_a_mesh_floor(self):
        before,after,origin,destination=self.fixtures();before['on_floor']=after['on_floor']='false'
        assert_translation(before,after,origin,destination)
    def test_all_24_rows_resolve_to_their_original_set(self):
        for row in range(24):
            before=self.fixtures()[0];before['buildout_row']=str(row);self.assertEqual(anchor(before),row//4*4)
    def test_fault_hold_follows_fixture_approach_before_real_gate_action(self):
        from types import SimpleNamespace
        from rryatt_group import PublicGroup
        for hold in (False,True):
            events=[]
            class Peer:
                def send(self,text):events.append(text.split()[0])
                def wait(self,kind,timeout):
                    events.append(kind)
                    return dict(name='Script.listBox',page=7,properties=[dict(property='Text',value='@travel/zone_transition:kachirho_rryatt '+str(n)) for n in range(6)])
            p=object.__new__(PublicGroup);p.s=SimpleNamespace(sessions={'beta':Peer()})
            p.approach=lambda key:events.append('approach') or '123'
            p.use=lambda key,target:events.append('use')
            p.request_entry('beta',0,hold=hold)
            self.assertEqual(events[0],'approach')
            if hold:self.assertLess(events.index('holdArrival'),events.index('use'))
            else:self.assertNotIn('holdArrival',events)
            self.assertEqual(events[-2:],['answer','sui_answered'])
if __name__=='__main__':unittest.main()
