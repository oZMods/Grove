"""Foreground-checked child-window messages; no SendInput or hook modification."""
import ctypes as C
from ctypes import wintypes as W
import time
from grove.input.win32 import ClientWindow as Mouse, U, RECT, POINT

U.PostMessageW.argtypes = [W.HWND, W.UINT, C.c_size_t, C.c_ssize_t]
U.PostMessageW.restype = W.BOOL
U.MapVirtualKeyW.argtypes=[W.UINT,W.UINT]
U.MapVirtualKeyW.restype=W.UINT

class WindowMouse(Mouse):
    def __init__(self, pid, reader):
        super().__init__(pid)
        root, child = reader.window_handles()
        if root != self.window or not child or U.GetAncestor(child, 2) != self.window:
            raise RuntimeError('Input child does not belong to the selected client window.')
        owner = W.DWORD()
        U.GetWindowThreadProcessId(child, C.byref(owner))
        if owner.value != pid:
            raise RuntimeError('Input child has a different process owner.')
        self.child = child
        self.armed = False
        self.packed_point = None
        self.held_keys=set()
        self.button_down = False
        self.button_point = None
        self.background_movement_only = False
        self.background_enabled = False

    def foreground(self):
        if not (getattr(self,'background_movement_only',False) or getattr(self,'background_enabled',False)):
            return super().foreground()
        owner = W.DWORD()
        U.GetWindowThreadProcessId(self.window,C.byref(owner))
        if owner.value != self.pid or U.GetAncestor(self.child,2) != self.window:
            raise RuntimeError('Background probe client window identity changed.')
        child_owner = W.DWORD()
        U.GetWindowThreadProcessId(self.child,C.byref(child_owner))
        if child_owner.value != self.pid:
            raise RuntimeError('Background probe child ownership changed.')
        if getattr(self,'background_movement_only',False) and U.GetForegroundWindow() == self.window:
            raise RuntimeError('Background probe requires another application in the foreground.')
        if U.GetAsyncKeyState(0x77) & 0x8000:
            raise RuntimeError('F8 stop requested.')

    def install(self):
        self.armed = True  # No hooks installed.

    def close(self):
        self.release()
        for key in tuple(self.held_keys): self.key_up(key)
        self.armed = False
        self.background_movement_only = False
        self.background_enabled = False

    def key_down(self,key):
        if getattr(self,'background_movement_only',False):
            raise RuntimeError('Background probe permits movement only; keyboard input is disabled.')
        if key not in (0x25,0x26,0x27,0x28): raise RuntimeError('Only camera arrow keys are allowed here.')
        self.foreground()
        if not self.armed: raise RuntimeError('Input is not armed.')
        code=U.MapVirtualKeyW(key,0)
        lparam=1|(code<<16)|(1<<24)
        if not U.PostMessageW(self.child,0x100,key,lparam): raise C.WinError(C.get_last_error())
        self.held_keys.add(key)

    def key_up(self,key):
        if key not in self.held_keys: return
        code=U.MapVirtualKeyW(key,0)
        lparam=1|(code<<16)|(1<<24)|(1<<30)|(1<<31)
        if not U.PostMessageW(self.child,0x101,key,lparam): raise C.WinError(C.get_last_error())
        self.held_keys.remove(key)

    def audit_ok(self):
        return self.armed and not self.failure and self.packed_point is not None

    def client_offset(self):
        root_x,root_y,_,_=self.geometry()
        child_origin=POINT()
        if not U.ClientToScreen(self.child,C.byref(child_origin)):
            raise C.WinError(C.get_last_error())
        return child_origin.x-root_x,child_origin.y-root_y

    def post(self, message, keys):
        if getattr(self,'background_movement_only',False) and message != 0x200:
            raise RuntimeError('Background probe permits movement messages only.')
        self.foreground()
        if not self.armed or self.failure or self.packed_point is None:
            raise RuntimeError('Window-message backend is not armed.')
        if not U.PostMessageW(self.child, message, keys, self.packed_point):
            raise C.WinError(C.get_last_error())

    def move(self, point, dimensions):
        self.foreground()
        root_x, root_y, width, height = self.geometry()
        if (width, height) != tuple(dimensions):
            raise RuntimeError('Client geometry and renderer dimensions disagree.')
        x, y = map(int, point)
        if not 0 <= x < width or not 0 <= y < height:
            raise RuntimeError('Target lies outside the client.')
        if not (getattr(self,'background_movement_only',False) or getattr(self,'background_enabled',False)) and not self.allowed_point(root_x + x, root_y + y):
            raise RuntimeError('Target is covered by another window.')
        origin, bounds = POINT(), RECT()
        if not U.ClientToScreen(self.child, C.byref(origin)) or not U.GetClientRect(self.child, C.byref(bounds)):
            raise C.WinError(C.get_last_error())
        child_x, child_y = root_x + x - origin.x, root_y + y - origin.y
        if not 0 <= child_x < min(bounds.right, 32768) or not 0 <= child_y < min(bounds.bottom, 32768):
            raise RuntimeError('Target lies outside the input child.')
        packed=(child_y << 16) | child_x
        if packed==self.packed_point and time.perf_counter_ns()//1000000-self.sent_at<1000:
            return False
        self.packed_point = packed
        self.target = (child_x, child_y)
        self.sent_at = time.perf_counter_ns() // 1000000
        self.post(0x200, 0)
        return True

    def press(self):
        if getattr(self,'background_movement_only',False):
            raise RuntimeError('Background movement probe cannot submit clicks.')
        if not self.audit_ok():
            raise RuntimeError('Movement has not been confirmed.')
        if self.button_down:
            raise RuntimeError('A button press is already outstanding.')
        self.sent_at = time.perf_counter_ns() // 1000000
        self.post(0x201, 1)
        self.button_point = self.packed_point
        self.button_down = True

    def release(self):
        if not self.button_down:
            return
        # Release the original press even when focus changes or Stop is requested.
        if not U.PostMessageW(self.child, 0x202, 0, self.button_point):
            raise C.WinError(C.get_last_error())
        self.button_down = False
        self.button_point = None

    def click(self, scheduler=None):
        self.press()
        try:
            if scheduler is None:
                self.release()
            else:
                scheduler.after(75, self.release)
        except Exception:
            self.release()
            raise
