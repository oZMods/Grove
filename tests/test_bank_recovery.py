import unittest
from unittest.mock import patch
from types import SimpleNamespace
from grove.core.runtime import BotRuntime

class BankRecoveryTests(unittest.TestCase):
    def test_close_hover_accounts_for_input_child_origin(self):
        runtime=self.runtime()
        runtime.target={'kind':'close','point':(779,19)}
        runtime.snapshot={'dimensions':(1360,705)}
        runtime.api=SimpleNamespace(last_hover_point=None)
        runtime.mouse.client_offset=lambda:(0,39)
        runtime.move_step=lambda token:None
        with patch('grove.core.runtime.random.randint',return_value=0):
            runtime.hover(0)
        endpoint=list(runtime.motion_steps)[-1][0]
        self.assertEqual(endpoint,(779,58))

    def runtime(self):
        runtime=BotRuntime(SimpleNamespace(after=lambda *args:None),lambda *args:None)
        runtime.running=True
        runtime.target={'kind':'close'}
        runtime.mouse=SimpleNamespace(release=lambda:None)
        runtime.later=lambda *args:None
        return runtime

    def state(self):
        return {'bank_open':True,'bank_close':(779,19),'inventory':[{'slot':0,'id':1357,'quantity':1}],
                'player':{'world_id':0,'plane':0,'route':0}}

    def test_close_retry_is_idempotent_fresh_and_bounded(self):
        runtime=self.runtime()
        state=self.state()
        self.assertTrue(runtime.recover_bank_close(state,state,0))
        self.assertTrue(runtime.recover_bank_close(state,state,0))
        self.assertFalse(runtime.recover_bank_close(state,state,0))

    def test_uncertain_deposit_is_not_replayed(self):
        runtime=self.runtime()
        runtime.target={'kind':'deposit'}
        state=self.state()
        self.assertFalse(runtime.recover_bank_close(state,state,0))

    def test_changed_inventory_or_world_blocks_close_retry(self):
        runtime=self.runtime()
        before=self.state()
        after=self.state()
        after['inventory']=[]
        self.assertFalse(runtime.recover_bank_close(before,after,0))
        after=self.state()
        after['player']['world_id']=1
        self.assertFalse(runtime.recover_bank_close(before,after,0))

    def test_closed_bank_never_gets_another_close_click(self):
        runtime=self.runtime()
        before=self.state()
        after=dict(before,bank_open=False)
        self.assertFalse(runtime.recover_bank_close(before,after,0))
