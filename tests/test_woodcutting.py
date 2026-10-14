import copy
import unittest
from grove.bots.woodcutting import choose, menu_matches, acknowledged

def fixture():
    return {'inventory': [{'slot': 0, 'id': 1355, 'quantity': 1}],
            'player': {'x': 3185, 'y': 3436, 'world_id': 0, 'plane': 0, 'route': 0, 'animation': -1},
            'bank_open': False, 'bank_slots': [], 'bank_close': (800, 30),
            'objects': [{'id': 1276, 'x': 3184, 'y': 3450, 'point': (600, 200)},
                        {'id': 10820, 'x': 3185, 'y': 3437, 'point': (650, 250)},
                        {'id': 10583, 'x': 3186, 'y': 3438, 'point': (620, 230)}],
            'default': None}

class PolicyTests(unittest.TestCase):
    def test_scene_kind_does_not_override_tree_operation(self):
        s = fixture()
        for obj in s['objects']: obj['kind'] = 'game_object'
        target = choose(s)
        self.assertEqual(target['kind'], 'tree')
        self.assertEqual(target['object_kind'], 'game_object')
        s['default'] = {'action': 'Chop down', 'id': target['id'], 'x': target['x'], 'y': target['y'], 'world': 0}
        self.assertTrue(menu_matches(target, s))

    def test_scene_kind_does_not_override_bank_operation(self):
        s = fixture()
        for obj in s['objects']: obj['kind'] = 'game_object'
        s['inventory'] += [{'slot': n, 'id': 1511, 'quantity': 1} for n in range(1, 28)]
        target = choose(s)
        self.assertEqual(target['kind'], 'bank')
        s['default'] = {'action': 'Bank', 'id': target['id'], 'x': target['x'], 'y': target['y'], 'world': 0}
        self.assertTrue(menu_matches(target, s))

    def test_regular_tree_selected_over_closer_oak(self):
        self.assertEqual(choose(fixture())['id'], 1276)

    def test_full_inventory_routes_to_west_bank(self):
        s = fixture()
        s['inventory'] += [{'slot': n, 'id': 1511, 'quantity': 1} for n in range(1, 28)]
        self.assertEqual(choose(s)['kind'], 'bank')
        s['objects'][2]['x'], s['objects'][2]['y'] = 3167, 3490
        with self.assertRaises(RuntimeError):
            choose(s)  # Same booth definition in a different bank is rejected.

    def test_bank_deposits_logs_and_retains_axe_and_other_items(self):
        s = fixture()
        s['bank_open'] = True
        s['inventory'] += [{'slot': 1, 'id': 1511, 'quantity': 1}, {'slot': 2, 'id': 1521, 'quantity': 1}]
        s['bank_slots'] = [{'slot': n, 'id': item['id'], 'point': (n * 40, 100)} for n, item in enumerate(s['inventory'])]
        target = choose(s)
        self.assertEqual((target['kind'], target['slot'], target['id']), ('deposit', 1, 1511))
        s['inventory'].pop(1)
        self.assertEqual(choose(s)['kind'], 'close')

    def test_wrong_tree_or_world_cannot_authorize_click(self):
        s = fixture()
        target = choose(s)
        s['default'] = {'action': 'Chop down', 'id': 1276, 'x': target['x'], 'y': target['y'], 'world': 0}
        self.assertTrue(menu_matches(target, s))
        for key, wrong in [('id', 10820), ('x', target['x'] + 1), ('world', 1), ('action', 'Examine')]:
            changed = copy.deepcopy(s)
            changed['default'][key] = wrong
            self.assertFalse(menu_matches(target, changed))

    def test_axe_menu_and_deposit_x_are_rejected(self):
        s = fixture()
        s['bank_open'] = True
        s['inventory'].append({'slot': 1, 'id': 1511, 'quantity': 1})
        target = {'kind': 'deposit', 'slot': 1, 'id': 1511}
        s['default'] = {'id': 983043, 'slot': 0, 'action': 'Deposit-All'}
        self.assertFalse(menu_matches(target, s))
        s['default']['slot'] = 1
        self.assertTrue(menu_matches(target, s))
        s['default']['action'] = 'Deposit-X'
        self.assertFalse(menu_matches(target, s))

    def test_missing_axe_and_wrong_area_stop(self):
        s = fixture()
        s['inventory'] = []
        with self.assertRaises(RuntimeError): choose(s)
        s = fixture()
        s['player']['x'] = 3300
        with self.assertRaises(RuntimeError): choose(s)

    def test_animation_does_not_delay_full_inventory_banking(self):
        s = fixture()
        s['player']['animation'] = 873
        self.assertEqual(choose(s)['kind'], 'wait')
        s['inventory'] += [{'slot': n, 'id': 1511, 'quantity': 1} for n in range(1, 28)]
        self.assertEqual(choose(s)['kind'], 'bank')

    def test_state_gain_acknowledges_click_when_queue_record_expired(self):
        before = fixture()
        before['xp'] = 100
        after = copy.deepcopy(before)
        after['xp'] = 125
        self.assertTrue(acknowledged({'kind': 'tree'}, before, after, None))
        after['xp'] = 100
        after['player']['route'] = 1
        self.assertFalse(acknowledged({'kind': 'tree'}, before, after, None))

    def test_bank_acknowledgment_requires_the_expected_change(self):
        before = fixture()
        after = copy.deepcopy(before)
        self.assertFalse(acknowledged({'kind': 'bank'}, before, after, None))
        after['bank_open'] = True
        self.assertTrue(acknowledged({'kind': 'bank'}, before, after, None))

    def test_oak_deposit_does_not_acknowledge_regular_log_deposit(self):
        before = fixture()
        before['inventory'] += [{'slot': 1, 'id': 1511, 'quantity': 1}, {'slot': 2, 'id': 1521, 'quantity': 1}]
        after = copy.deepcopy(before)
        after['inventory'].pop(2)
        self.assertFalse(acknowledged({'kind': 'deposit'}, before, after, None))

if __name__ == '__main__':
    unittest.main()
