import ctypes as C
from ctypes import wintypes as W
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from grove.input.window_messages import WindowMouse

class BackgroundProbeTests(unittest.TestCase):
    def mouse(self):
        mouse=WindowMouse.__new__(WindowMouse)
        mouse.pid=42
        mouse.window=100
        mouse.child=101
        mouse.armed=True
        mouse.failure=None
        mouse.packed_point=(300<<16)|400
        mouse.background_movement_only=True
        return mouse

    def native(self,foreground=200):
        def owner(hwnd,pointer): C.cast(pointer,C.POINTER(W.DWORD)).contents.value=42
        posted=[]
        return SimpleNamespace(GetWindowThreadProcessId=owner,GetAncestor=lambda *args:100,
                               GetForegroundWindow=lambda:foreground,GetAsyncKeyState=lambda key:0,
                               PostMessageW=lambda *args:posted.append(args) or True),posted

    def test_background_movement_posts_to_owned_child_only(self):
        native,posted=self.native()
        with patch('grove.input.window_messages.U',native): self.mouse().post(0x200,0)
        self.assertEqual(posted,[(101,0x200,0,(300<<16)|400)])

    def test_background_mode_blocks_buttons_and_keyboard(self):
        native,posted=self.native()
        mouse=self.mouse()
        with patch('grove.input.window_messages.U',native):
            for action in (lambda:mouse.press(),lambda:mouse.post(0x201,1),lambda:mouse.key_down(37)):
                with self.assertRaises(RuntimeError): action()
        self.assertEqual(posted,[])

    def test_foreground_game_cannot_pass_background_probe(self):
        native,posted=self.native(100)
        with patch('grove.input.window_messages.U',native):
            with self.assertRaises(RuntimeError): self.mouse().post(0x200,0)
        self.assertEqual(posted,[])

    def test_focus_independent_run_accepts_foreground_and_background_clicks(self):
        for foreground in (100,200):
            native,posted=self.native(foreground)
            mouse=self.mouse()
            mouse.background_movement_only=False
            mouse.background_enabled=True
            mouse.button_down=False
            mouse.button_point=None
            with patch('grove.input.window_messages.U',native): mouse.click()
            self.assertEqual([p[0:3] for p in posted],[(101,0x201,1),(101,0x202,0)])

    def test_focus_independent_camera_keys_target_client_child(self):
        native,posted=self.native(200)
        native.MapVirtualKeyW=lambda key,mode:75
        mouse=self.mouse()
        mouse.background_movement_only=False
        mouse.background_enabled=True
        mouse.held_keys=set()
        with patch('grove.input.window_messages.U',native):
            mouse.key_down(37)
            mouse.key_up(37)
        self.assertEqual([p[0:3] for p in posted],[(101,0x100,37),(101,0x101,37)])
        self.assertFalse(mouse.held_keys)
