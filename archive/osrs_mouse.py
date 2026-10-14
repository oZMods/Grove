"""Experimental desktop mouse backend. No client-memory writes or native calls.

Only this process's tagged events are modified. The guard hook blocks them if
flags remain set, the client isn't foreground, or the point is obstructed.
Cross-process effects are not established by the isolated lab result.
"""
import ctypes as C
from ctypes import wintypes as W
import secrets
import time
from mouse_hook_lab import user32 as U, kernel32 as K, HOOKPROC, MSLLHOOKSTRUCT, INPUT, INPUTUNION, MOUSEINPUT, POINT, validate_layout

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

class Mouse:
    def __init__(self, pid):
        validate_layout()
        self.pid = pid
        self.tag = secrets.randbits(31) | 0x40000000
        self.handles, self.callbacks = [], []
        self.audit, self.failure = [], None
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
        if owner.value != self.pid or U.GetForegroundWindow() != self.window:
            raise RuntimeError('Client lost foreground or window identity changed.')
        if U.GetAsyncKeyState(0x77) & 0x8000:  # F8; no synthesized key events.
            raise RuntimeError('F8 stop requested.')

    def allowed_point(self, x, y):
        hit = U.WindowFromPoint(POINT(x, y))
        return bool(hit and U.GetAncestor(hit, 2) == self.window)

    def install(self):
        if self.handles:
            return
        try:
            for role in ('guard', 'modifier'):
                def callback(code, message, address, role=role):
                    if code >= 0 and address:
                        event = C.cast(address, C.POINTER(MSLLHOOKSTRUCT)).contents
                        if event.dwExtraInfo == self.tag:
                            before = int(event.flags)
                            if role == 'modifier':
                                event.flags = before & ~3
                            else:
                                if event.flags & 3 or U.GetForegroundWindow() != self.window or not self.allowed_point(event.pt.x, event.pt.y):
                                    self.failure = 'Tagged event blocked by input guard.'
                                    return 1
                            self.audit.append((role, int(message), before, int(event.flags)))
                            self.audit[:] = self.audit[-32:]
                    return U.CallNextHookEx(None, code, message, address)
                native = HOOKPROC(callback)
                handle = U.SetWindowsHookExW(14, native, K.GetModuleHandleW(None), 0)
                if not handle:
                    raise C.WinError(C.get_last_error())
                self.callbacks.append(native)
                self.handles.append(handle)
        except Exception:
            self.close()
            raise

    def close(self):
        remaining = []
        for handle in reversed(self.handles):
            if not U.UnhookWindowsHookEx(handle):
                remaining.append(handle)
        self.handles = remaining
        if not remaining:
            self.callbacks.clear()
        else:
            raise RuntimeError('Hook cleanup failed; close the controller process.')

    def send(self, flags, x=0, y=0):
        self.foreground()
        if not self.handles or self.failure:
            raise RuntimeError(self.failure or 'Input hooks are not armed.')
        event = INPUT(0, INPUTUNION(mi=MOUSEINPUT(x, y, 0, flags, 0, self.tag)))
        previous = len(self.audit)
        if U.SendInput(1, C.byref(event), C.sizeof(INPUT)) != 1:
            raise C.WinError(C.get_last_error())
        if self.failure:
            raise RuntimeError(self.failure)
        # Audit delivery is asynchronous; controller checks it after a delay.

    def move(self, point, dimensions):
        self.foreground()
        ox, oy, width, height = self.geometry()
        if (width, height) != tuple(dimensions):
            raise RuntimeError('Client geometry and renderer dimensions disagree.')
        x, y = map(int, point)
        if not 0 <= x < width or not 0 <= y < height:
            raise RuntimeError('Target point is outside client area.')
        x, y = x + ox, y + oy
        if not self.allowed_point(x, y):
            raise RuntimeError('Target is covered by another window.')
        left, top, dw, dh = (U.GetSystemMetrics(n) for n in (76, 77, 78, 79))
        if min(dw, dh) <= 1:
            raise RuntimeError('Invalid desktop geometry.')
        self.audit.clear()
        self.sent_at = time.perf_counter_ns() // 1000000
        self.send(0xC001, round((x - left) * 65535 / (dw - 1)), round((y - top) * 65535 / (dh - 1)))
        self.target = point

    def audit_ok(self):
        return (not self.failure and len(self.audit) >= 2 and
                self.audit[-2][0] == 'modifier' and self.audit[-1][0] == 'guard' and
                self.audit[-1][3] & 3 == 0)

    def down(self):
        self.send(2)

    def up(self):
        self.send(4)

    def click(self):
        self.foreground()
        if not self.audit_ok() or self.failure:
            raise RuntimeError('Movement audit has not passed.')
        events = (INPUT * 2)(INPUT(0, INPUTUNION(mi=MOUSEINPUT(0, 0, 0, 2, 0, self.tag))),
                             INPUT(0, INPUTUNION(mi=MOUSEINPUT(0, 0, 0, 4, 0, self.tag))))
        self.audit.clear()
        self.sent_at = time.perf_counter_ns() // 1000000
        inserted = U.SendInput(2, events, C.sizeof(INPUT))
        if inserted != 2:
            if inserted == 1:
                # Release the same tagged button immediately; never retry the click.
                U.SendInput(1, C.byref(events[1]), C.sizeof(INPUT))
            raise RuntimeError(f'Click insertion incomplete ({inserted}/2); outcome uncertain.')
