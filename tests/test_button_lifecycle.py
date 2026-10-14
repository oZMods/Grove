import unittest
from unittest.mock import patch
from types import SimpleNamespace
from grove.input.window_messages import WindowMouse


class ButtonLifecycleTests(unittest.TestCase):
    def mouse(self):
        mouse = WindowMouse.__new__(WindowMouse)
        mouse.child = 42
        mouse.armed = True
        mouse.failure = None
        mouse.packed_point = (425 << 16) | 1197
        mouse.button_down = False
        mouse.button_point = None
        mouse.held_keys = set()
        mouse.foreground = lambda: None
        return mouse

    def test_scheduled_click_keeps_press_until_release(self):
        posted, scheduled = [], []
        mouse = self.mouse()
        native = SimpleNamespace(PostMessageW=lambda *args: posted.append(args) or True)
        scheduler = SimpleNamespace(after=lambda delay, callback: scheduled.append((delay, callback)))
        with patch('grove.input.window_messages.U', native):
            mouse.click(scheduler)
            self.assertEqual([entry[1] for entry in posted], [0x201])
            self.assertTrue(mouse.button_down)
            self.assertEqual(scheduled[0][0], 75)
            scheduled[0][1]()
            self.assertEqual([entry[1] for entry in posted], [0x201, 0x202])
            self.assertFalse(mouse.button_down)

    def test_stop_releases_original_point_once(self):
        posted, scheduled = [], []
        mouse = self.mouse()
        native = SimpleNamespace(PostMessageW=lambda *args: posted.append(args) or True)
        scheduler = SimpleNamespace(after=lambda delay, callback: scheduled.append(callback))
        original = mouse.packed_point
        with patch('grove.input.window_messages.U', native):
            mouse.click(scheduler)
            mouse.packed_point = 99
            mouse.close()
            scheduled[0]()
        self.assertEqual(len(posted), 2)
        self.assertEqual(posted[-1][-1], original)
        self.assertFalse(mouse.armed)

    def test_scheduler_failure_releases_without_replaying_press(self):
        posted = []
        mouse = self.mouse()
        native = SimpleNamespace(PostMessageW=lambda *args: posted.append(args) or True)
        def fail(*args): raise RuntimeError('scheduler closed')
        with patch('grove.input.window_messages.U', native):
            with self.assertRaises(RuntimeError): mouse.click(SimpleNamespace(after=fail))
        self.assertEqual([entry[1] for entry in posted], [0x201, 0x202])
        self.assertFalse(mouse.button_down)
