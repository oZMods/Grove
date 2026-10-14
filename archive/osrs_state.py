"""Read-only state access for the single, verified official-client build."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import math
from pathlib import Path
import struct

BUILD = '3852dd48aa6a75cfb042489b5192b477a1b828cbc95af8b759c139095c8b6ea2'
K = C.WinDLL('kernel32', use_last_error=True)
P = C.WinDLL('psapi', use_last_error=True)

class ProcessEntry(C.Structure):
    _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('pid', W.DWORD),
                ('heap', C.c_size_t), ('module', W.DWORD), ('threads', W.DWORD),
                ('parent', W.DWORD), ('priority', W.LONG), ('flags', W.DWORD),
                ('name', W.WCHAR * 260)]

K.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
K.CreateToolhelp32Snapshot.restype = W.HANDLE
K.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(ProcessEntry)]
K.Process32FirstW.restype = W.BOOL
K.Process32NextW.argtypes = K.Process32FirstW.argtypes
K.Process32NextW.restype = W.BOOL
K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
K.OpenProcess.restype = W.HANDLE
K.CloseHandle.argtypes = [W.HANDLE]
K.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
K.ReadProcessMemory.restype = W.BOOL
P.EnumProcessModules.argtypes = [W.HANDLE, C.POINTER(W.HMODULE), W.DWORD, C.POINTER(W.DWORD)]
P.EnumProcessModules.restype = W.BOOL
P.GetModuleFileNameExW.argtypes = [W.HANDLE, W.HMODULE, W.LPWSTR, W.DWORD]
P.GetModuleFileNameExW.restype = W.DWORD

def client_pids():
    snapshot = K.CreateToolhelp32Snapshot(2, 0)
    if snapshot == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    result = []
    try:
        entry = ProcessEntry()
        entry.size = C.sizeof(entry)
        present = K.Process32FirstW(snapshot, C.byref(entry))
        while present:
            if entry.name.casefold() == 'osclient.exe':
                result.append(entry.pid)
            present = K.Process32NextW(snapshot, C.byref(entry))
        if C.get_last_error() != 18:
            raise C.WinError(C.get_last_error())
    finally:
        K.CloseHandle(snapshot)
    return result

class ClientState:
    def __init__(self, pid=None):
        if C.sizeof(C.c_void_p) != 8:
            raise RuntimeError('64-bit Python required.')
        pids = client_pids()
        if pid is None:
            if len(pids) != 1:
                raise RuntimeError('Exactly one osclient.exe must be running.')
            pid = pids[0]
        if pid not in pids:
            raise RuntimeError('PID is not osclient.exe.')
        self.pid = pid
        self.handle = K.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        try:
            modules = (W.HMODULE * 1024)()
            needed = W.DWORD()
            if not P.EnumProcessModules(self.handle, modules, C.sizeof(modules), C.byref(needed)):
                raise C.WinError(C.get_last_error())
            self.base = modules[0]
            path = C.create_unicode_buffer(32768)
            if not P.GetModuleFileNameExW(self.handle, modules[0], path, len(path)):
                raise C.WinError(C.get_last_error())
            if hashlib.sha256(Path(path.value).read_bytes()).hexdigest() != BUILD:
                raise RuntimeError('Unsupported client build; offsets require review.')
        except Exception:
            self.close()
            raise

    def close(self):
        if self.handle:
            K.CloseHandle(self.handle)
            self.handle = None

    def read(self, address, size):
        if not address or not 0 <= size <= 1024 * 1024:
            raise RuntimeError('Invalid bounded memory read.')
        data = C.create_string_buffer(size)
        count = C.c_size_t()
        if not K.ReadProcessMemory(self.handle, address, data, size, C.byref(count)) or count.value != size:
            raise C.WinError(C.get_last_error())
        return data.raw

    def q(self, address):
        return struct.unpack('<Q', self.read(address, 8))[0]

    def i(self, address):
        return struct.unpack('<i', self.read(address, 4))[0]

    def string(self, address):
        data = self.read(address, 24)
        if data[23] & 128:
            pointer, size = struct.unpack_from('<QQ', data)
            if size > 512:
                raise RuntimeError('Invalid string length.')
            data = self.read(pointer, size) if size else b''
        return data.split(b'\0', 1)[0].decode('utf-8', errors='replace')

    def chain_lookup(self, buckets, count, key, next_offset, key64=False):
        if not 1 <= count <= 65536:
            raise RuntimeError('Invalid hash bucket count.')
        sentinel = self.q(buckets + 8 * count)
        node = self.q(buckets + 8 * (key % count))
        seen = set()
        while node and node != sentinel and node not in seen and len(seen) < 256:
            seen.add(node)
            if (self.q(node) if key64 else self.i(node)) == key:
                return node
            node = self.q(node + next_offset)
        return 0

    def inventory(self):
        buckets, count = self.q(self.base + 0x154FAB8), self.i(self.base + 0x154FAC0)
        node = self.chain_lookup(buckets, count, 93, 56)
        if not node:
            return []
        begin, end = self.q(node + 8), self.q(node + 16)
        quantities, quantity_end = self.q(node + 32), self.q(node + 40)
        if (end - begin) % 4 or not 0 <= end - begin <= 8192 or quantity_end - quantities != end - begin:
            raise RuntimeError('Invalid inventory vectors.')
        size = (end - begin) // 4
        ids = struct.unpack('<' + 'i' * size, self.read(begin, size * 4)) if size else ()
        nums = struct.unpack('<' + 'i' * size, self.read(quantities, size * 4)) if size else ()
        return [{'slot': n, 'id': item, 'quantity': nums[n]} for n, item in enumerate(ids) if item >= 0]

    def player(self, state):
        index, current_world = self.i(state + 52316), self.i(state + 52320)
        world_node = self.chain_lookup(self.q(state + 51688), self.i(state + 51696), current_world, 24)
        if not world_node:
            raise RuntimeError('Current world is unavailable.')
        world = self.q(world_node + 16)
        player_node = self.chain_lookup(self.q(world + 104), self.i(world + 112), index, 24)
        if not player_node:
            raise RuntimeError('Local player is unavailable; log in first.')
        player = self.q(player_node + 16)
        return {'world_id': current_world, 'world': world, 'pointer': player,
                'scene': self.q(world + 16), 'plane': self.i(world + 24),
                'base_x': self.i(world + 36), 'base_y': self.i(world + 40),
                'local_x': self.i(player + 1008), 'local_y': self.i(player + 1048),
                'route': self.i(player + 1004), 'animation': self.i(player + 1240)}

    def projection(self, state, scene):
        renderer = self.q(state + 144)
        logical_w, logical_h = self.i(renderer + 48), self.i(renderer + 52)
        physical_w, physical_h = self.i(renderer + 108), self.i(renderer + 112)
        if min(logical_w, logical_h, physical_w, physical_h) <= 0:
            raise RuntimeError('Invalid viewport dimensions.')
        camera = [self.i(state + off) for off in (0x895D8, 0x895DC, 0x895E0)]
        sp, cp, sy, cy = struct.unpack('<ffff', self.read(scene + 1048, 16))
        viewport = self.q(renderer + 440)
        zoom = self.i(viewport + 16)
        ox, oy = self.i(viewport + 20) + self.i(viewport + 88), self.i(viewport + 24) + self.i(viewport + 80)
        def project(x, y, z):
            x, y, z = x - camera[0], y - camera[1], z - camera[2]
            yd, horizontal = cy * z - sy * x, cy * x + sy * z
            vertical, depth = cp * y - sp * yd, sp * y + cp * yd
            if depth <= 50:
                return None
            px = round((ox + math.trunc(zoom * horizontal / depth)) * physical_w / logical_w)
            py = round((oy + math.trunc(zoom * vertical / depth)) * physical_h / logical_h)
            return (px, py) if 0 <= px < physical_w and 0 <= py < physical_h else None
        return project, (physical_w, physical_h), (logical_w, logical_h)

    def objects(self, state, player, radius=25):
        scene, plane = player['scene'], player['plane']
        sx, sy = self.i(scene + 2376), self.i(scene + 2380)
        if not 1 <= sx <= 256 or not 1 <= sy <= 256 or not 0 <= plane < 4:
            raise RuntimeError('Invalid scene dimensions.')
        tiles, heights = self.q(scene + 2408), self.q(scene + 976)
        project, dimensions, logical = self.projection(state, scene)
        seen, result = set(), []
        for x in range(max(0, player['local_x'] - radius), min(sx, player['local_x'] + radius + 1)):
            for y in range(max(0, player['local_y'] - radius), min(sy, player['local_y'] + radius + 1)):
                tile = self.q(tiles + 16 * (y + sy * (x + sx * plane)) + 8)
                if not tile:
                    continue
                count, entries = self.i(tile + 52), self.q(tile + 56)
                if not 0 <= count <= 50:
                    continue
                pointers = self.read(entries, 16 * count) if count else b''
                for n in range(count):
                    obj = struct.unpack_from('<Q', pointers, n * 16 + 8)[0]
                    if not obj or obj in seen:
                        continue
                    seen.add(obj)
                    tag = self.q(obj + 496)
                    type_id = (tag >> 20) & 65535
                    if (tag >> 16) & 7 != 2 or type_id not in (1276, 1278, 10583):
                        continue
                    x0, x1, y0, y1 = struct.unpack('<iiii', self.read(obj + 528, 16))
                    if not (0 <= x0 <= x1 < sx and 0 <= y0 <= y1 < sy):
                        continue
                    height = self.i(heights + 4 * (y0 + (x0 + plane * (sx + 1)) * (sy + 1)))
                    result.append({'id': type_id, 'x': player['base_x'] + x0,
                                   'y': player['base_y'] + y0,
                                   'point': project(64 * (x0 + x1 + 1), height - 100, 64 * (y0 + y1 + 1))})
        return result, dimensions, logical

    def menu(self, state):
        root = self.q(state + 4273152)
        if not root:
            return [], None
        def entry(pointer):
            labels = []
            for offset in (80, 184):
                string, size = self.q(pointer + offset), self.q(pointer + offset + 8)
                if size > 512:
                    raise RuntimeError('Invalid menu string.')
                labels.append(self.read(string, size).decode('utf-8', errors='replace') if size else '')
            return {'target': labels[0], 'action': labels[1],
                    'id': self.i(pointer + 296), 'slot': self.i(pointer + 300),
                    'operation': self.i(pointer + 308), 'world': self.i(pointer + 312),
                    'x': self.i(pointer + 316), 'y': self.i(pointer + 320)}
        begin, end = self.q(root + 552), self.q(root + 560)
        if not 0 <= end - begin <= 336 * 500 or (end - begin) % 336:
            raise RuntimeError('Invalid menu vector.')
        entries = [entry(pointer) for pointer in range(begin, end, 336)]
        selected = None
        ordered, ordered_end = self.q(root + 640), self.q(root + 648)
        if 24 <= ordered_end - ordered <= 24 * 500 and (ordered_end - ordered) % 24 == 0:
            for _ in range(8):
                collection = self.q(ordered)
                if collection:
                    index = self.q(ordered + 8)
                    start, stop = self.q(collection + 24), self.q(collection + 32)
                    if 0 <= stop - start <= 336 * 500 and (stop - start) % 336 == 0 and index < (stop - start) // 336:
                        selected = entry(start + 336 * index)
                    break
                nested = self.q(ordered + 16)
                if not nested:
                    break
                start, stop = self.q(nested), self.q(nested + 8)
                if not 24 <= stop - start <= 24 * 500 or (stop - start) % 24:
                    break
                ordered = start
        return entries, selected

    def bank(self, state, inventory):
        manager = self.q(state + 4275176)
        group_count, groups = self.q(manager + 26760), self.q(manager + 26768)
        if not 16 <= group_count < 10000:
            return False, []
        def component(group, index):
            info = groups + 24 * group
            count, array = self.q(info + 8), self.q(info + 16)
            return self.q(array + index * 16 + 8) if index < count <= 2048 else 0
        root = component(12, 0)
        opened = bool(root and self.i(root + 56) > 0 and self.i(root + 100) > 0 and self.i(root + 104) > 0)
        if not opened:
            return False, []
        buckets, count = self.q(state + 4275408), self.i(state + 4275416)
        coordinates = self.chain_lookup(buckets, count, 15, 40)
        parent = component(15, 3)
        if not coordinates or not parent:
            return True, []
        origin_x, origin_y = self.i(coordinates + 4), self.i(coordinates + 8)
        count, array = self.q(parent + 2896), self.q(parent + 2904)
        if count > 2048:
            raise RuntimeError('Invalid bank child count.')
        items, slots = {item['slot']: item for item in inventory}, []
        for index in range(count):
            child = self.q(array + index * 16 + 8)
            if not child:
                continue
            slot, item_id = self.i(child + 8), self.i(child + 2872)
            if slot not in items or items[slot]['id'] != item_id:
                continue
            x, y, w, h = struct.unpack('<iiii', self.read(child + 92, 16))
            if w > 0 and h > 0:
                slots.append({'slot': slot, 'id': item_id, 'point': (origin_x + x + w // 2, origin_y + y + h // 2)})
        return True, slots

    def bank_close_point(self, state):
        manager = self.q(state + 4275176)
        groups = self.q(manager + 26768)
        info = groups + 24 * 12
        count, array = self.q(info + 8), self.q(info + 16)
        node = self.chain_lookup(self.q(state + 4275408), self.i(state + 4275416), 12, 40)
        if not node or not 1 <= count <= 2048:
            return None
        ox, oy = self.i(node + 4), self.i(node + 8)
        for index in range(count):
            component = self.q(array + index * 16 + 8)
            if not component or self.i(component + 56) <= 0:
                continue
            op_count, ops = self.q(component + 736), self.q(component + 744)
            if op_count <= 20 and any(self.string(ops + n * 24) == 'Close' for n in range(op_count)):
                x, y, width, height = struct.unpack('<iiii', self.read(component + 92, 16))
                if width > 0 and height > 0:
                    return (ox + x + width // 2, oy + y + height // 2)
        return None

    def snapshot(self):
        state = self.q(self.base + 0xE98C18)
        inventory = self.inventory()
        player = self.player(state)
        player['x'], player['y'] = player['base_x'] + player['local_x'], player['base_y'] + player['local_y']
        objects, dimensions, logical = self.objects(state, player)
        menu, default = self.menu(state)
        bank_open, bank_slots = self.bank(state, inventory)
        return {'pid': self.pid, 'player': player, 'inventory': inventory,
                'objects': objects, 'dimensions': dimensions, 'logical': logical,
                'menu': menu, 'default': default, 'bank_open': bank_open,
                'bank_slots': bank_slots, 'xp': self.i(state + 13352 + 32),
                'bank_close': self.bank_close_point(state) if bank_open else None,
                'level': self.i(state + 13252 + 32)}

    def input_backend(self):
        owner = self.q(self.base + 0x154F070)
        if self.q(self.q(owner) + 88) - self.base != 0x2A1D0:
            raise RuntimeError('Unverified hook owner layout.')
        window = self.q(owner + 100016)
        dispatcher = self.q(window + 248)
        if self.q(self.q(dispatcher) + 80) - self.base != 0x38EE0:
            raise RuntimeError('Unverified hook dispatcher layout.')
        fallback = self.q(dispatcher + 123260216 + 8)
        wrapper = self.q(self.q(fallback + 2192))
        callable_object = self.q(wrapper + 56)
        if self.q(self.q(callable_object) + 16) - self.base != 0x6D16D0:
            raise RuntimeError('Unverified movement callback.')
        backend = self.q(self.q(callable_object + 24))
        return backend

    def input_recorder(self):
        backend = self.input_backend()
        stack, seen = [self.q(backend + 8)], set()
        while stack and len(seen) < 128:
            node = stack.pop()
            if not node or node == backend + 8 or node in seen:
                continue
            seen.add(node)
            listener = self.q(node + 40)
            if listener and self.q(self.q(listener) + 112) - self.base == 0x30710:
                return listener
            stack.extend((self.q(node), self.q(node + 8)))
        raise RuntimeError('Verified input recorder is unavailable.')

    def input_events(self, kinds=(10, 11)):
        backend = self.input_backend()
        data = self.read(backend + 336, 6400)
        result = []
        for offset in range(0, len(data), 32):
            kind, message, flags, x, y, reserved, stamp = struct.unpack_from('<iiiiiiq', data, offset)
            if kind in kinds:
                result.append({'kind': kind, 'message': message, 'flags': flags,
                               'x': x, 'y': y, 'stamp': stamp})
        return result

    def hook_events(self):
        return self.input_events()

    def window_handles(self):
        owner = self.q(self.base + 0x154F070)
        if self.q(self.q(owner) + 88) - self.base != 0x2A1D0:
            raise RuntimeError('Unverified window-owner layout.')
        window = self.q(owner + 100016)
        child_object = self.q(window + 224)
        if not child_object:
            raise RuntimeError('Client input child window is unavailable.')
        return self.q(window + 576), self.q(child_object + 32)

    def recorded_input(self):
        recorder = self.input_recorder()
        owner = self.q(self.base + 0x154F070)
        window = self.q(owner + 100016)
        return {'message': self.i(recorder + 1992), 'flags': self.i(recorder + 1996),
                'movement_count': self.i(recorder + 10040),
                'hook_handle': self.q(self.base + 0x1348FB8),
                'hook_config': self.read(window + 642, 1)[0]}

if __name__ == '__main__':
    import json
    reader = ClientState()
    try:
        print(json.dumps(reader.snapshot(), indent=2))
    finally:
        reader.close()
