import unittest
from dataclasses import FrozenInstanceError
from grove.api.models import Bank, Inventory, Item, MenuAction, Player, Point, Snapshot, WorldObject

class APITests(unittest.TestCase):
    def test_inventory_quantities_and_slots(self):
        inventory = Inventory((Item(0, 1355, 1), Item(1, 1511, 1), Item(2, 1511, 5)))
        self.assertEqual(inventory.count(1511), 6)
        self.assertEqual(inventory.slots_for(1511), (1, 2))
        self.assertFalse(inventory.full)
        self.assertFalse(inventory.contains(9999))
        with self.assertRaises(FrozenInstanceError): inventory.capacity = 1

    def test_object_filters_and_nearest_use_actual_world_coordinates(self):
        player = Player(0, 3185, 3436, 0, 0, -1)
        objects = (WorldObject(1276, 3184, 3435, Point(500, 300), 'Tree', ('Chop down',)),
                   WorldObject(1278, 3188, 3439, None, 'Tree', ('Chop down',)),
                   WorldObject(10583, 3186, 3438, Point(550, 250), 'Bank booth', ('Bank',)))
        snapshot = Snapshot(1, 0, player, Inventory(()), objects, Bank(False, (), None), (), None, 1, 0, (1360, 705))
        trees = snapshot.find_objects(name='tree', operation='Chop down')
        self.assertEqual(len(trees), 2)
        self.assertEqual(snapshot.nearest(trees).id, 1276)
        self.assertIsNone(snapshot.nearest(()))
        self.assertEqual(snapshot.find_objects(ids={10583})[0].name, 'Bank booth')

    def fake_api(self):
        from types import SimpleNamespace
        from grove.api.client import ClientAPI
        raw = {'pid': 1, 'player': {'world_id': 0, 'x': 3185, 'y': 3436, 'plane': 0, 'route': 0, 'animation': -1},
               'inventory': [], 'objects': [], 'bank_open': False, 'bank_slots': [], 'bank_close': None,
               'menu': [], 'default': {'action': 'Chop down', 'id': 1276, 'slot': -1, 'world': 0, 'x': 3184, 'y': 3435, 'target': 'Tree'},
               'level': 1, 'xp': 0, 'dimensions': (1360, 705)}
        class Reader:
            def snapshot(self): return raw
            def input_events(self, kinds): return [{'kind': 0, 'stamp': 1001, 'x': 10, 'y': 20}]
        class Adapter:
            target, sent_at, clicks = (10, 20), 1000, 0
            def audit_ok(self): return True
            def click(self): self.clicks += 1
        adapter = Adapter()
        return ClientAPI(SimpleNamespace(reader=Reader(), input=adapter)), raw, adapter

    def test_verified_click_uses_fresh_menu_not_cached_menu(self):
        api, raw, adapter = self.fake_api()
        api.snapshot()
        raw['default']['id'] = 10820
        with self.assertRaises(RuntimeError):
            api.click_verified(lambda snapshot: snapshot.default_action.target_id == 1276)
        self.assertEqual(adapter.clicks, 0)

    def test_verified_click_posts_only_after_menu_and_movement_agree(self):
        api, raw, adapter = self.fake_api()
        result = api.click_verified(lambda snapshot: snapshot.default_action.target_id == 1276)
        self.assertEqual(adapter.clicks, 1)
        self.assertEqual(result.default_action.target_id, 1276)
        api.session.reader.input_events = lambda kinds: []
        with self.assertRaises(RuntimeError): api.click_verified(lambda snapshot: True)
        self.assertEqual(adapter.clicks, 1)

if __name__ == '__main__': unittest.main()
