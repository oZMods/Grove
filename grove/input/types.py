import ctypes as C
from ctypes import wintypes as W
import sys

if sys.platform != 'win32':
    raise SystemExit('Windows is required.')

ULONG_PTR = C.c_size_t
LRESULT = C.c_ssize_t
HOOKPROC = C.WINFUNCTYPE(LRESULT, C.c_int, ULONG_PTR, C.c_ssize_t)
user32 = C.WinDLL('user32', use_last_error=True)
kernel32 = C.WinDLL('kernel32', use_last_error=True)

class POINT(C.Structure):
    _fields_ = [('x', W.LONG), ('y', W.LONG)]

class MSLLHOOKSTRUCT(C.Structure):
    _fields_ = [('pt', POINT), ('mouseData', W.DWORD), ('flags', W.DWORD),
                ('time', W.DWORD), ('dwExtraInfo', ULONG_PTR)]

class MOUSEINPUT(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD),
                ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', ULONG_PTR)]

class INPUTUNION(C.Union):
    _fields_ = [('mi', MOUSEINPUT)]

class INPUT(C.Structure):
    _fields_ = [('type', W.DWORD), ('u', INPUTUNION)]

user32.SetWindowsHookExW.argtypes = [C.c_int, HOOKPROC, W.HINSTANCE, W.DWORD]
user32.SetWindowsHookExW.restype = W.HHOOK
user32.CallNextHookEx.argtypes = [W.HHOOK, C.c_int, ULONG_PTR, C.c_ssize_t]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [W.HHOOK]
user32.UnhookWindowsHookEx.restype = W.BOOL
user32.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
user32.SendInput.restype = W.UINT
user32.GetForegroundWindow.restype = W.HWND
user32.GetAncestor.argtypes = [W.HWND, W.UINT]
user32.GetAncestor.restype = W.HWND
user32.GetSystemMetrics.argtypes = [C.c_int]
user32.GetSystemMetrics.restype = C.c_int
user32.ClientToScreen.argtypes = [W.HWND, C.POINTER(POINT)]
user32.ClientToScreen.restype = W.BOOL
kernel32.GetModuleHandleW.argtypes = [W.LPCWSTR]
kernel32.GetModuleHandleW.restype = W.HMODULE

def validate_layout():
    expected_input_size = 40 if C.sizeof(C.c_void_p) == 8 else 28
    expected_hook_size = 32 if C.sizeof(C.c_void_p) == 8 else 24
    assert C.sizeof(INPUT) == expected_input_size
    assert C.sizeof(MSLLHOOKSTRUCT) == expected_hook_size
    assert MSLLHOOKSTRUCT.flags.offset == 12
