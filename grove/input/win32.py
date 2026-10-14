"""Read-only client-window geometry and foreground checks."""
import ctypes as C
from ctypes import wintypes as W
from grove.input.types import user32 as U, POINT, validate_layout

class RECT(C.Structure):
    _fields_ = [('left', W.LONG), ('top', W.LONG), ('right', W.LONG), ('bottom', W.LONG)]

ENUMPROC = C.WINFUNCTYPE(W.BOOL, W.HWND, C.c_ssize_t)
U.EnumWindows.argtypes = [ENUMPROC, C.c_ssize_t]
U.EnumWindows.restype = W.BOOL
U.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
U.GetWindowThreadProcessId.restype = W.DWORD
U.IsWindowVisible.argtypes = [W.HWND]
U.IsWindowVisible.restype = W.BOOL
U.IsIconic.argtypes = [W.HWND]
U.IsIconic.restype = W.BOOL
U.GetClientRect.argtypes = [W.HWND, C.POINTER(RECT)]
U.GetClientRect.restype = W.BOOL
U.WindowFromPoint.argtypes = [POINT]
U.WindowFromPoint.restype = W.HWND
U.GetAsyncKeyState.argtypes = [C.c_int]
U.GetAsyncKeyState.restype = C.c_short

class ClientWindow:
    def __init__(self, pid):
        validate_layout()
        self.pid = pid
        self.failure = None
        self.target = None
        windows = []
        def collect(hwnd, unused):
            owner = W.DWORD()
            U.GetWindowThreadProcessId(hwnd, C.byref(owner))
            if owner.value == pid and U.IsWindowVisible(hwnd):
                windows.append(hwnd)
            return True
        callback = ENUMPROC(collect)
        if not U.EnumWindows(callback, 0):
            raise C.WinError(C.get_last_error())
        if len(windows) != 1:
            raise RuntimeError('Expected one visible client window on this desktop.')
        self.window = windows[0]

    def geometry(self):
        if U.IsIconic(self.window):
            raise RuntimeError('Client is minimized.')
        rect, origin = RECT(), POINT()
        if not U.GetClientRect(self.window, C.byref(rect)) or not U.ClientToScreen(self.window, C.byref(origin)):
            raise C.WinError(C.get_last_error())
        return origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top

    def foreground(self):
        owner = W.DWORD()
        U.GetWindowThreadProcessId(self.window, C.byref(owner))
        if owner.value != self.pid:
            raise RuntimeError('Client window identity changed.')
        foreground = U.GetForegroundWindow()
        if foreground != self.window:
            foreground_pid = W.DWORD()
            U.GetWindowThreadProcessId(foreground, C.byref(foreground_pid))
            raise RuntimeError(f'Client lost foreground: expected HWND {self.window}, actual HWND {foreground}, foreground PID {foreground_pid.value}.')
        if U.GetAsyncKeyState(0x77) & 0x8000:  # F8; no synthesized key events.
            raise RuntimeError('F8 stop requested.')

    def allowed_point(self, x, y):
        hit = U.WindowFromPoint(POINT(x, y))
        return bool(hit and U.GetAncestor(hit, 2) == self.window)
