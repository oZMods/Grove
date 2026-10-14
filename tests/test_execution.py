import unittest
from grove.core.execution import ConditionTask


class Scheduler:
    def __init__(self): self.callbacks = {}; self.next = 0
    def after(self, delay, callback):
        self.next += 1
        self.callbacks[self.next] = callback
        return self.next
    def after_cancel(self, token): self.callbacks.pop(token, None)


class ExecutionTests(unittest.TestCase):
    def test_cancel_removes_callback_and_prevents_work(self):
        scheduler = Scheduler()
        calls = []
        task = ConditionTask(scheduler, lambda: calls.append(1), 1).start()
        task.cancel()
        task.poll()
        self.assertEqual(calls, [1])
        self.assertFalse(scheduler.callbacks)
        self.assertEqual(task.status, 'cancelled')

    def test_deadline_and_condition_failure_are_distinct(self):
        now = [0]
        task = ConditionTask(Scheduler(), lambda: False, 1, clock=lambda: now[0]).start()
        now[0] = 1
        task.poll()
        self.assertEqual(task.status, 'timed_out')
        def fail(): raise ValueError('bad read')
        failed = ConditionTask(Scheduler(), fail, 1).start()
        self.assertEqual(failed.status, 'failed')
        self.assertIsInstance(failed.error, ValueError)
