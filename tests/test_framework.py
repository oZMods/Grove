import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from grove.api import Coordinate, Area, ObjectQuery, ActionExpectation, Capabilities, UnsupportedCapabilityError
from grove.api.models import Player, WorldObject, Point, Inventory, Item, Snapshot, Bank, MenuAction
from grove.core.config import RuntimeConfig, RuntimeState
from grove.core.runtime import BotRuntime
from grove.bots.registry import WOODCUTTING, instantiate

def snapshot():
    return Snapshot(1,0,Player(7,3164,3418,0,0,-1),Inventory((Item(0,1357,1),Item(1,1521,1))),
                    (WorldObject(10820,3161,3416,Point(100,100),'Oak tree',('Chop down',)),
                     WorldObject(10820,3167,3420,None,'Oak tree',('Chop down',))),
                    Bank(False,(),None),(),None,32,1000,(1360,705))

class FrameworkTests(unittest.TestCase):
    def test_reusable_query_does_not_mutate_base(self):
        base = ObjectQuery().names('OAK TREE').actions('Chop down')
        visible = base.projected()
        s = snapshot()
        self.assertEqual(len(base.results(s)),2)
        self.assertEqual(len(visible.results(s)),1)
        self.assertEqual(len(visible.results(replace(s,objects=()))),0)
        self.assertEqual(base.within(4).nearest(s).x,3161)

    def test_area_plane_and_order(self):
        area = Area(Coordinate(3160,3410),Coordinate(3170,3425))
        self.assertTrue(area.contains(Coordinate(3164,3418)))
        self.assertFalse(area.contains(Coordinate(3164,3418,1)))
        with self.assertRaises(ValueError): Area(Coordinate(2,2),Coordinate(1,1))
        self.assertEqual(len(ObjectQuery().in_area(area).results(snapshot())),2)

    def test_contract_rejects_changed_slot_item_and_world(self):
        s = replace(snapshot(),default_action=MenuAction('Deposit-All',983043,1,7,0,0,'Oak logs'))
        expectation = ActionExpectation('Deposit-All',983043,7,slot=1,inventory_item_id=1521)
        self.assertTrue(expectation.matches(s))
        self.assertFalse(expectation.matches(replace(s,inventory=Inventory((Item(1,1357,1),)))))
        self.assertFalse(expectation.matches(replace(s,player=replace(s.player,world_instance_id=8))))

    def test_unsupported_capability_fails_explicitly(self):
        Capabilities().require('inventory')
        with self.assertRaises(UnsupportedCapabilityError): Capabilities().require('web_navigation')

    def test_policy_instances_are_isolated(self):
        a,pa = instantiate(WOODCUTTING)
        b,pb = instantiate(WOODCUTTING)
        pa.anchor = (3164,3418)
        self.assertIsNone(pb.anchor)
        self.assertIsNot(a.choose.__self__,b.choose.__self__)

    def test_config_rejects_nan_and_invalid_scheduler_values(self):
        for kwargs in ({'hover_ms':0},{'countdown_ms':1.5},{'idle_timeout_seconds':float('nan')},{'event_limit':True}):
            with self.assertRaises(ValueError): RuntimeConfig(**kwargs)

    def test_failed_attach_closes_partial_session(self):
        scheduler = SimpleNamespace(after=lambda *args: None)
        runtime = BotRuntime(scheduler,lambda *args: None)
        class FakeAPI:
            closed = False
            session = SimpleNamespace(reader=SimpleNamespace(pid=1),input=SimpleNamespace(close=lambda:None))
            def raw_snapshot(self): raise RuntimeError('Reader failed during attach')
            def close(self): self.closed = True
        api = FakeAPI()
        with patch('grove.core.runtime.ClientAPI.attach',return_value=api): runtime.attach()
        self.assertTrue(api.closed)
        self.assertIsNone(runtime.reader)
        self.assertIsNone(runtime.api)
        self.assertEqual(runtime.state,RuntimeState.DETACHED)

    def test_attachment_does_not_initialize_bot_anchor(self):
        scheduler=SimpleNamespace(after=lambda *args:None)
        runtime=BotRuntime(scheduler,lambda *args:None)
        api=SimpleNamespace(session=SimpleNamespace(reader=SimpleNamespace(pid=1),input=SimpleNamespace(close=lambda:None)),
                            raw_snapshot=lambda:{'pid':1,'player':{'x':3185,'y':3436},'dimensions':(1360,705)})
        with patch('grove.core.runtime.ClientAPI.attach',return_value=api): runtime.attach()
        self.assertEqual(runtime.state,RuntimeState.READY)
        self.assertIsNone(runtime.policy.anchor)

    def test_stopped_runtime_cancels_scheduled_work(self):
        callbacks=[]
        scheduler=SimpleNamespace(after=lambda delay,callback: callbacks.append(callback))
        runtime=BotRuntime(scheduler,lambda *args:None)
        runtime.running=True
        ran=[]
        runtime.later(1,lambda token: ran.append(token),runtime.generation)
        pending=callbacks[-1]
        runtime.stop()
        pending()
        self.assertEqual(ran,[])

    def test_stale_hover_never_reaches_adapter(self):
        from grove.api.client import ClientAPI
        from grove.api import StaleStateError, DetachedError
        moved=[]
        api=ClientAPI(SimpleNamespace(input=SimpleNamespace(move=lambda *args:moved.append(args))))
        api.last_snapshot=snapshot()
        with self.assertRaises(StaleStateError): api.hover(Point(100,100))
        api.closed=True
        with self.assertRaises(DetachedError): api.hover(Point(100,100))
        self.assertEqual(moved,[])

    def test_disappeared_object_cannot_be_hovered(self):
        from grove.api.client import ClientAPI
        from grove.api import ActionMismatchError
        api=ClientAPI(SimpleNamespace(input=None))
        api.snapshot=lambda:replace(snapshot(),objects=())
        with self.assertRaises(ActionMismatchError): api.hover_object(snapshot().objects[0],'Chop down')

    def test_read_only_session_rejects_input(self):
        from grove.api.client import ClientAPI
        api=ClientAPI(SimpleNamespace(input=None))
        with self.assertRaises(UnsupportedCapabilityError): api.arm_input()
        with self.assertRaises(UnsupportedCapabilityError): api.click_verified(lambda state:True)
        api.disarm_input()

    def test_interface_menu_world_is_distinct_from_player_instance(self):
        state=replace(snapshot(),default_action=MenuAction('Close',786434,11,-1,-1,-1,''))
        expected=ActionExpectation('Close',786434,7,slot=11,menu_world_instance_id=-1)
        self.assertTrue(expected.matches(state))
        self.assertFalse(expected.matches(replace(state,player=replace(state.player,world_instance_id=8))))

    def test_profile_preserves_anchor_when_attaching_at_bank(self):
        from grove.bots.profiles import VARROCK_WEST_OAKS
        from grove.bots.woodcutting import AnchoredOaks
        state={'player':{'plane':0,'x':3185,'y':3436},'bank_open':True,
               'objects':[{'x':x,'y':y,'name':'Oak tree','ops':['Chop down']} for x,y in VARROCK_WEST_OAKS.trees]}
        policy=AnchoredOaks()
        policy.load_profile(VARROCK_WEST_OAKS,state)
        self.assertEqual(policy.anchor,(3164,3418))
        state['objects'].pop()
        with self.assertRaises(RuntimeError): policy.load_profile(VARROCK_WEST_OAKS,state)

if __name__ == '__main__': unittest.main()
