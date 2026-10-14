import unittest
from grove.core.recovery import RecoveryBudget, MovementProgress


class RecoveryTests(unittest.TestCase):
    def test_visibility_budget_requires_real_progress_to_reset(self):
        state = {'player':{'world_id':0,'plane':0,'x':1,'y':1},'xp':1,'bank_open':False,'inventory':[]}
        budget=RecoveryBudget(2)
        budget.observe(state)
        budget.consume()
        budget.observe(state)
        budget.consume()
        with self.assertRaises(RuntimeError): budget.consume()
        state['player']['x']=2
        budget.observe(state)
        budget.consume()
        self.assertEqual(budget.attempts,1)

    def test_stall_uses_position_not_animation_or_route_length(self):
        clock=[0]
        tracker=MovementProgress(12,lambda:clock[0])
        player={'world_id':0,'plane':0,'x':1,'y':1,'route':3}
        self.assertFalse(tracker.observe(player))
        clock[0]=12
        self.assertTrue(tracker.observe(dict(player,route=1)))
        player['x']=2
        self.assertFalse(tracker.observe(player))
        clock[0]=30
        self.assertFalse(tracker.observe(dict(player,route=0)))
