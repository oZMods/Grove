"""Foreground-checked child-window messages; no SendInput or hook modification."""
import ctypes as C
from ctypes import wintypes as W
import time
from osrs_mouse import Mouse, U, RECT, POINT

U.PostMessageW.argtypes = [W.HWND, W.UINT, C.c_size_t, C.c_ssize_t]
U.PostMessageW.restype = W.BOOL

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

    def install(self):
        self.armed = True  # No hooks installed.

    def close(self):
        self.armed = False

    def audit_ok(self):
        return self.armed and not self.failure and self.packed_point is not None

    def post(self, message, keys):
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
        if not self.allowed_point(root_x + x, root_y + y):
            raise RuntimeError('Target is covered by another window.')
        origin, bounds = POINT(), RECT()
        if not U.ClientToScreen(self.child, C.byref(origin)) or not U.GetClientRect(self.child, C.byref(bounds)):
            raise C.WinError(C.get_last_error())
        child_x, child_y = root_x + x - origin.x, root_y + y - origin.y
        if not 0 <= child_x < min(bounds.right, 32768) or not 0 <= child_y < min(bounds.bottom, 32768):
            raise RuntimeError('Target lies outside the input child.')
        self.packed_point = (child_y << 16) | child_x
        self.target = (child_x, child_y)
        self.sent_at = time.perf_counter_ns() // 1000000
        self.post(0x200, 0)

    def click(self):
        if not self.audit_ok():
            raise RuntimeError('Movement has not been confirmed.')
        self.sent_at = time.perf_counter_ns() // 1000000
        self.post(0x201, 1)
        try:
            self.post(0x202, 0)
        except Exception:
            # Attempt release only to the already validated input child.
            U.PostMessageW(self.child, 0x202, 0, self.packed_point)
            raise
