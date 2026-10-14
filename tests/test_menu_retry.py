import unittest
from types import SimpleNamespace
from grove.api.contracts import ActionMismatchError
from grove.core.runtime import BotRuntime
from grove.core.config import RuntimeState

class MenuRetryTests(unittest.TestCase):
    def test_unconfirmed_bank_uses_camera_recovery(self):
        runtime = BotRuntime(SimpleNamespace(after=lambda *args: None),lambda *args: None)
        runtime.target = {'kind':'bank','point':(500,300)}
        runtime.policy = object()
        runtime.offsets = [(0,0)]
        runtime.offset_index = 1
        runtime.snapshot = {'player':{'x':3171,'y':3424},'default':{'action':'Switch tab'}}
        called = []
        runtime.begin_camera = lambda token: called.append(token)
        runtime.hover(runtime.generation)
        self.assertEqual(runtime.target['kind'], 'camera')
        self.assertEqual(runtime.target['destination'], (3185,3436))
        self.assertEqual(called, [runtime.generation])

    def runtime(self, error=None):
        callbacks=[]
        runtime=BotRuntime(SimpleNamespace(after=lambda delay,callback:callbacks.append(callback)),lambda *args:None)
        runtime.running=True
        runtime.target={'kind':'bank','id':10583,'x':3186,'y':3438}
        state={'default':{'action':'Walk here'},'xp':100}
        def click(predicate, scheduler=None):
            if error: raise error
            return state
        runtime.api=SimpleNamespace(click_verified=click,last_raw=state)
        return runtime,callbacks,state

    def test_menu_mismatch_retargets_without_stopping(self):
        runtime,callbacks,state=self.runtime(ActionMismatchError('changed'))
        runtime.submit_click(runtime.generation)
        self.assertTrue(runtime.running)
        self.assertEqual(runtime.state,RuntimeState.TARGETING)
        self.assertEqual(runtime.menu_retries,1)
        self.assertEqual(len(callbacks),2)
        self.assertEqual(runtime.records[-1]['actual'],state['default'])

    def test_retry_is_bounded(self):
        runtime,callbacks,state=self.runtime(ActionMismatchError('changed'))
        for _ in range(runtime.config.menu_retry_limit): runtime.submit_click(runtime.generation)
        with self.assertRaises(RuntimeError): runtime.submit_click(runtime.generation)

    def test_unknown_click_failure_is_never_retried(self):
        runtime,callbacks,state=self.runtime(RuntimeError('up event failed'))
        with self.assertRaises(RuntimeError): runtime.submit_click(runtime.generation)
        self.assertEqual(len(callbacks),1)
        self.assertEqual(runtime.menu_retries,0)

    def test_success_uses_actual_preclick_snapshot_for_acknowledgment(self):
        runtime,callbacks,state=self.runtime()
        runtime.menu_retries=2
        runtime.submit_click(runtime.generation)
        self.assertIs(runtime.before_click,state)
        self.assertEqual(runtime.state,RuntimeState.VERIFYING)
        self.assertEqual(runtime.menu_retries,0)

if __name__ == '__main__': unittest.main()
