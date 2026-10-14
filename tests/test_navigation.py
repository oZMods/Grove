import unittest
from grove.bots.woodcutting import choose, menu_matches, acknowledged
from test_woodcutting import fixture

class NavigationTests(unittest.TestCase):
    def test_edge_bank_projection_does_not_override_return_path(self):
        state = self.full_state()
        state['dimensions'] = (1360,705)
        state['objects'][2]['point'] = (10,696)
        target = choose(state,1521,frozenset({(3161,3416)}))
        self.assertEqual(target['kind'],'walk')

    def full_state(self):
        s=fixture()
        s['player'].update(x=3166,y=3420)
        s['inventory'] += [{'slot':n,'id':1521,'quantity':1} for n in range(1,28)]
        s['objects'][2]['point']=None
        s['ground_points']=[{'x':3170,'y':3423,'point':(700,300)},
                            {'x':3162,'y':3416,'point':(400,400)}]
        return s

    def test_full_inventory_walks_toward_offscreen_bank(self):
        s=self.full_state()
        target=choose(s,1521,frozenset({(3161,3416),(3165,3411),(3167,3420)}))
        self.assertEqual((target['kind'],target['x'],target['y']),('walk',3170,3423))
        self.assertEqual(target['destination'],(3185,3436))

    def test_visible_bank_is_preferred_to_ground_step(self):
        s=self.full_state()
        s['objects'][2]['point']=(300,200)
        self.assertEqual(choose(s,1521,frozenset({(3161,3416)}))['kind'],'bank')

    def test_walk_requires_exact_native_tile_and_actual_movement(self):
        s=self.full_state()
        target={'kind':'walk','x':3170,'y':3423}
        s['default']={'action':'Walk here','world':0,'x':3170,'y':3423}
        self.assertTrue(menu_matches(target,s))
        s['default']['x']=3171
        self.assertFalse(menu_matches(target,s))
        self.assertFalse(acknowledged(target,s,s,True))
        after=dict(s,player=dict(s['player'],x=3167))
        self.assertTrue(acknowledged(target,s,after,None))
