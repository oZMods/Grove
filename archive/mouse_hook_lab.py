"""Isolated Windows hook-chain experiment. Never integrates with a game client.

Run on a separate desktop/VM, or with osclient.exe closed. Only tagged mouse
movement is generated; no button clicks. Hooks are removed after each trial.
"""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import secrets
import sys
import tkinter as tk
from tkinter import messagebox

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

def require_client_closed():
    class PROCESSENTRY32(C.Structure):
        _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD),
                    ('th32ProcessID', W.DWORD), ('th32DefaultHeapID', ULONG_PTR),
                    ('th32ModuleID', W.DWORD), ('cntThreads', W.DWORD),
                    ('th32ParentProcessID', W.DWORD), ('pcPriClassBase', W.LONG),
                    ('dwFlags', W.DWORD), ('szExeFile', W.WCHAR * 260)]
    kernel32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = W.HANDLE
    kernel32.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(PROCESSENTRY32)]
    kernel32.Process32FirstW.restype = W.BOOL
    kernel32.Process32NextW.argtypes = [W.HANDLE, C.POINTER(PROCESSENTRY32)]
    kernel32.Process32NextW.restype = W.BOOL
    kernel32.CloseHandle.argtypes = [W.HANDLE]
    kernel32.CloseHandle.restype = W.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(2, 0)
    if snapshot == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = C.sizeof(entry)
        found = kernel32.Process32FirstW(snapshot, C.byref(entry))
        while found:
            if entry.szExeFile.casefold() == 'osclient.exe':
                raise RuntimeError('Close osclient.exe before testing. No input was sent.')
            found = kernel32.Process32NextW(snapshot, C.byref(entry))
        if C.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise C.WinError(C.get_last_error())
    finally:
        kernel32.CloseHandle(snapshot)

class Lab:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Isolated mouse hook lab')
        self.root.geometry('640x360')
        self.tag = secrets.randbits(31) | 0x40000000
        self.handles = []
        self.callbacks = []  # Keep native callback references alive.
        self.records = []
        self.phase = ''
        self.modify = False
        self.running = False
        self.callback_error = None
        tk.Label(self.root, text='Close OSRS first. Test generates movement only.\n'
                 'Only this trial\'s tagged events are recorded or modified.').pack(pady=12)
        self.button = tk.Button(self.root, text='Run baseline / modified / baseline trial',
                                command=self.start)
        self.button.pack()
        self.status = tk.Label(self.root, text='Ready. Keep this window foreground during trial.')
        self.status.pack(pady=10)
        self.output = tk.Text(self.root, height=11, width=75)
        self.output.pack()
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    def install(self, role):
        def callback(code, message, address):
            try:
                if code >= 0 and address:
                    event = C.cast(address, C.POINTER(MSLLHOOKSTRUCT)).contents
                    if event.dwExtraInfo == self.tag:
                        before = int(event.flags)
                        if role == 'modifier' and self.modify:
                            event.flags = before & ~3
                        self.records.append({'phase': self.phase, 'role': role,
                                             'message': int(message), 'before': before,
                                             'after': int(event.flags), 'x': event.pt.x,
                                             'y': event.pt.y, 'time': int(event.time)})
            except Exception as error:
                self.callback_error = repr(error)
            return user32.CallNextHookEx(None, code, message, address)
        native = HOOKPROC(callback)
        handle = user32.SetWindowsHookExW(14, native, kernel32.GetModuleHandleW(None), 0)
        if not handle:
            raise C.WinError(C.get_last_error())
        self.callbacks.append(native)
        self.handles.append(handle)

    def uninstall(self):
        failures = []
        remaining = []
        for handle in reversed(self.handles):
            if not user32.UnhookWindowsHookEx(handle):
                failures.append(C.get_last_error())
                remaining.append(handle)
        self.handles = remaining
        if not remaining:
            self.callbacks.clear()
        if failures:
            raise RuntimeError(f'Hook cleanup failed: {failures}. Close this process.')

    def start(self):
        if self.running:
            return
        try:
            require_client_closed()
            self.records.clear()
            self.callback_error = None
            self.install('observer')
            self.install('modifier')  # Newly installed hook runs first.
            self.running = True
            self.button.config(state='disabled')
            self.root.after(250, lambda: self.step(0))
        except Exception as error:
            self.finish(error)

    def step(self, index):
        if not self.running:
            return
        try:
            require_client_closed()  # Check again before every generated event.
            if self.callback_error:
                raise RuntimeError(self.callback_error)
            window = user32.GetAncestor(self.root.winfo_id(), 2)
            if user32.GetForegroundWindow() != window:
                raise RuntimeError('Test window lost foreground. Trial stopped.')
            phases = [('baseline_before', False), ('modified', True), ('baseline_after', False)]
            self.phase, self.modify = phases[index]
            point = POINT(250 + index * 12, 170)
            if not user32.ClientToScreen(self.root.winfo_id(), C.byref(point)):
                raise C.WinError(C.get_last_error())
            # Normalized virtual-desktop coordinates, including negative origins.
            left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
            width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
            if width <= 1 or height <= 1:
                raise RuntimeError('Desktop geometry unavailable.')
            dx = round((point.x - left) * 65535 / (width - 1))
            dy = round((point.y - top) * 65535 / (height - 1))
            if not (0 <= dx <= 65535 and 0 <= dy <= 65535):
                raise RuntimeError('Target is outside the virtual desktop.')
            event = INPUT(0, INPUTUNION(mi=MOUSEINPUT(dx, dy, 0, 0xC001, 0, self.tag)))
            if user32.SendInput(1, C.byref(event), C.sizeof(INPUT)) != 1:
                raise C.WinError(C.get_last_error())
            self.status.config(text=f'Sent movement: {self.phase}')
            self.root.after(350, lambda: self.step(index + 1) if index < 2 else self.finish())
        except Exception as error:
            self.finish(error)

    def finish(self, error=None):
        self.running = False
        self.modify = False
        try:
            self.uninstall()
        except Exception as cleanup_error:
            error = cleanup_error
        phases = {}
        for phase in ('baseline_before', 'modified', 'baseline_after'):
            samples = [r for r in self.records if r['phase'] == phase]
            phases[phase] = {
                'callback_order': [r['role'] for r in samples],
                'modifier_before': [r['before'] for r in samples if r['role'] == 'modifier'],
                'observer_flags': [r['before'] for r in samples if r['role'] == 'observer']}
        phase_order_valid = all(p['callback_order'] == ['modifier', 'observer'] for p in phases.values())
        baseline_valid = all(phases[p]['observer_flags'] and phases[p]['observer_flags'][0] & 1
                             for p in ('baseline_before', 'baseline_after'))
        modified_valid = (phases['modified']['modifier_before'] and
                          phases['modified']['modifier_before'][0] & 1 and
                          phases['modified']['observer_flags'] == [0])
        assessment = ('Downstream observer saw cleared flags for this tagged event.'
                      if phase_order_valid and baseline_valid and modified_valid and not error and not self.callback_error
                      else 'Inconclusive: inspect records and errors.')
        report = {'architecture_bits': C.sizeof(C.c_void_p) * 8,
                  'error': str(error) if error else self.callback_error,
                  'assessment': assessment, 'phases': phases,
                  'lower_integrity_bit_observed': any(r['before'] & 2 for r in self.records),
                  'records': self.records,
                  'scope': 'One process, one desktop, tagged movement only; no OSRS integration.'}
        text = json.dumps(report, indent=2)
        self.output.delete('1.0', 'end')
        self.output.insert('end', text)
        self.status.config(text='Trial stopped with error.' if report['error'] else 'Trial finished; hooks removed.')
        self.button.config(state='normal' if not self.handles else 'disabled')
        try:
            Path(__file__).with_name('mouse_hook_lab_results.json').write_text(text, encoding='utf-8')
        except OSError as save_error:
            self.output.insert('end', f'\nCould not save report: {save_error}')

    def close(self):
        self.running = False
        try:
            self.uninstall()
        finally:
            self.root.destroy()

if __name__ == '__main__':
    validate_layout()
    if '--check' in sys.argv:
        require_client_closed()
        print('ABI layouts valid; client absent. No hooks installed or input sent.')
    else:
        Lab().root.mainloop()
