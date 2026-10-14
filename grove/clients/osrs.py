"""Read-only state access for the single, verified official-client build."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import math
from pathlib import Path
import struct

BASELINE_BUILD = '3852dd48aa6a75cfb042489b5192b477a1b828cbc95af8b759c139095c8b6ea2'
BUILD = '166231c8f6bd05c7542b8f0d35eb64b0aad701a87ba6ba41f60c4706de946944'
PROFILES = {
    BASELINE_BUILD: {'state_offsets':{},'fingerprints':{},'input_validated':True},
    BUILD: {'state_offsets':{offset:offset-16 for offset in
            (12712,13096,13152,13252,13352,51688,51696,52316,52320,
             4273152,4275176,4275408,4275416,0x895D8,0x895DC,0x895E0)},
            'fingerprints':{0x38EE0:0x38EF0,0x6D16D0:0x6D15E0},
            'input_owner_rva':0x154F078,'dispatcher_member':123260200,'input_validated':True},
}
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
            digest = hashlib.sha256(Path(path.value).read_bytes()).hexdigest()
            if digest not in PROFILES:
                raise RuntimeError(f'Client build changed: installed SHA-256 {digest}, expected {BUILD}. '
                                   'Attachment disabled pending offset review. Run tools/recover_offsets.py against the installed executable.')
            self.build_sha256 = digest
            self.profile = PROFILES[digest]
        except Exception:
            self.close()
            raise

    def s(self,state,offset):
        return state + getattr(self,'profile',{}).get('state_offsets',{}).get(offset,offset)

    def fingerprint(self,baseline_rva):
        return getattr(self,'profile',{}).get('fingerprints',{}).get(baseline_rva,baseline_rva)

    def input_owner(self):
        return self.q(self.base + getattr(self,'profile',{}).get('input_owner_rva',0x154F070))

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

    def varbit(self, varbit_id):
        """Read a cached varbit definition; never load definitions into the client."""
        if not isinstance(varbit_id, int) or not 0 <= varbit_id <= 65535:
            raise ValueError('Invalid varbit id.')
        buckets = self.q(self.base + 0xDFE9E0)
        count = self.i(self.base + 0xDFE9E8)
        node = self.chain_lookup(buckets, count, varbit_id, 64, key64=True)
        if not node:
            return None
        definition = self.q(node + 16)
        base, low, high = struct.unpack('<iii', self.read(definition, 12))
        if not 0 <= base < 65536 or not 0 <= low <= high < 32:
            raise RuntimeError('Invalid cached varbit definition.')
        values = self.q(self.base + 0x155E540)
        value = struct.unpack('<I', self.read(values + base * 4, 4))[0]
        return (value >> low) & ((1 << (high - low + 1)) - 1)

    def inventory(self,container_id=93):
        buckets, count = self.q(self.base + 0x154FAB8), self.i(self.base + 0x154FAC0)
        node = self.chain_lookup(buckets, count, container_id, 56)
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

    def hash_entries(self,buckets,count,next_offset=24,limit=4096):
        if not 1<=count<=65536: raise RuntimeError('Invalid entity hash size.')
        pointers=struct.unpack('<'+'Q'*(count+1),self.read(buckets,8*(count+1)))
        sentinel=pointers[-1]
        seen=set()
        for node in pointers[:-1]:
            while node and node!=sentinel and node not in seen:
                if len(seen)>=limit: raise RuntimeError('Entity traversal exceeded bound.')
                seen.add(node)
                yield node
                node=self.q(node+next_offset)

    def operations(self,address):
        begin,end=self.q(address),self.q(address+8)
        if not 0<=end-begin<=64*20 or (end-begin)%64: raise RuntimeError('Invalid operations vector.')
        return tuple(self.string(begin+64*i) for i in range((end-begin)//64))

    def item_definition(self,item_id):
        node=self.chain_lookup(self.q(self.base+0xDE1330),self.i(self.base+0xDE1338),item_id,64,key64=True)
        if not node: return None
        definition=self.q(node+16)
        if not definition or self.i(definition)!=item_id: raise RuntimeError('Item definition identity mismatch.')
        begin, end = self.q(definition+264), self.q(definition+272)
        if not 0 <= end-begin <= 24*20 or (end-begin)%24:
            raise RuntimeError('Invalid inventory operations vector.')
        return {'id':item_id,'name':self.string(definition+8),'description':self.string(definition+32),
                'ground_operations':self.operations(definition+240),
                'operations':tuple(self.string(begin+24*i) for i in range((end-begin)//24)),'stackable':self.i(definition+212)==1,
                'value':self.i(definition+216),'note_id':self.i(definition+688),'placeholder_id':self.i(definition+788)}

    def actors(self,state,player):
        world=player['world']
        result=[]
        project,_,_=self.projection(state,player['scene'])
        heights=self.q(player['scene']+976)
        sx,sy=self.i(player['scene']+2376),self.i(player['scene']+2380)
        for kind,bucket_offset,count_offset in (('player',104,112),('npc',152,160)):
            for node in self.hash_entries(self.q(world+bucket_offset),self.i(world+count_offset)):
                entity=self.q(node+16)
                if not entity: continue
                x,y=self.i(entity+1008),self.i(entity+1048)
                if not 0<=x<sx or not 0<=y<sy: continue
                height=self.i(heights+4*(y+(x+player['plane']*(sx+1))*(sy+1)))
                index=self.i(node)
                if kind=='npc':
                    definition=self.q(entity+1840)
                    if not definition: continue
                    name=self.string(entity+1808) or self.string(definition+8)
                    type_id=self.i(definition)
                    ops=self.operations(definition+256)
                else:
                    name_pointer=self.q(entity+1816)
                    name=self.string(name_pointer) if name_pointer else ''
                    type_id=index
                    ops=()
                result.append({'kind':kind,'index':index,'id':type_id,'name':name,'ops':ops,
                               'x':player['base_x']+x,'y':player['base_y']+y,'plane':player['plane'],
                               'world_instance_id':player['world_id'],'animation':self.i(entity+1240),
                               'route':self.i(entity+1004),'point':project(128*x+64,height-100,128*y+64)})
        return result

    def camera(self,state,player):
        sp,cp,sy,cy=struct.unpack('<ffff',self.read(player['scene']+1048,16))
        renderer=self.q(self.s(state,144))
        viewport=self.q(renderer+440)
        return {'yaw':math.atan2(sy,cy),'pitch':math.atan2(sp,cp),'zoom':self.i(viewport+16),
                'position':tuple(self.i(self.s(state,offset)) for offset in (0x895D8,0x895DC,0x895E0))}

    def skills(self,state):
        effective=struct.unpack('<25i',self.read(self.s(state,13152),100))
        base=struct.unpack('<25i',self.read(self.s(state,13252),100))
        xp=struct.unpack('<25i',self.read(self.s(state,13352),100))
        return [{'id':i,'effective_level':effective[i],'base_level':base[i],'xp':xp[i]} for i in range(25)]

    def interfaces(self,state,group_ids=None,max_components=10000):
        manager=self.q(self.s(state,4275176))
        group_count,groups=self.q(manager+26760),self.q(manager+26768)
        if not 0<group_count<10000: raise RuntimeError('Invalid interface group count.')
        origins={self.i(node):(self.i(node+4),self.i(node+8)) for node in
                 self.hash_entries(self.q(self.s(state,4275408)),self.i(self.s(state,4275416)),40)}
        selected=origins.keys() if group_ids is None else group_ids
        result=[]
        def intersection(a,b):
            if a is None: return b
            x,y=max(a[0],b[0]),max(a[1],b[1])
            right,bottom=min(a[0]+a[2],b[0]+b[2]),min(a[1]+a[3],b[1]+b[3])
            return x,y,max(0,right-x),max(0,bottom-y)
        for group in selected:
            if group not in origins or not 0<=group<group_count: continue
            info=groups+24*group
            count,array=self.q(info+8),self.q(info+16)
            if not 0<=count<=2048: raise RuntimeError('Invalid interface component count.')
            roots=[self.q(array+16*i+8) for i in range(count)]
            def origin(pointer):
                x,y=origins[group]
                ancestor_hidden=False
                parents=[]
                parent=self.i(pointer+116)
                seen=set()
                while parent!=-1:
                    if parent in seen or parent>>16!=group or not 0<=parent&65535<count:
                        raise RuntimeError('Invalid interface ancestor chain.')
                    seen.add(parent)
                    ptr=roots[parent&65535]
                    if not ptr: raise RuntimeError('Interface parent is absent.')
                    parents.append(ptr)
                    parent=self.i(ptr+116)
                clip=None
                for ptr in reversed(parents):
                    px,py,width,height=struct.unpack('<iiii',self.read(ptr+92,16))
                    px,py=x+px,y+py
                    if width>0 and height>0: clip=intersection(clip,(px,py,width,height))
                    x,y=px-self.i(ptr+132),py-self.i(ptr+136)
                    ancestor_hidden |= bool(self.read(ptr+120,1)[0])
                return x,y,ancestor_hidden,clip
            pending=[(pointer,None) for pointer in roots if pointer]
            seen=set()
            while pending:
                pointer,inherited=pending.pop()
                if pointer in seen: continue
                seen.add(pointer)
                if len(result)>=max_components: raise RuntimeError('Interface scan exceeded bound; restrict groups.')
                ox,oy,ancestor_hidden,clip=inherited if inherited is not None else origin(pointer)
                x,y,width,height=struct.unpack('<iiii',self.read(pointer+92,16))
                op_count,ops=self.q(pointer+736),self.q(pointer+744)
                if not 0<=op_count<=100: raise RuntimeError('Invalid interface operation count.')
                identity,child=self.i(pointer+4),self.i(pointer+8)
                processed=self.i(pointer+56)
                hidden=ancestor_hidden or bool(self.read(pointer+120,1)[0])
                scroll_x,scroll_y=struct.unpack('<ii',self.read(pointer+132,8))
                bounds=(ox+x,oy+y,width,height)
                clipped=intersection(clip,bounds)
                result.append({'id':identity,'sub_id':child,'group':group,'parent_id':self.i(pointer+116),
                               'bounds':bounds,'clipped_bounds':clipped,'processed_frame':processed,
                               'text':self.string(pointer+344),'ops':tuple(self.string(ops+24*i) for i in range(op_count)),
                               'item_id':self.i(pointer+2872),'quantity':self.i(pointer+2876),
                               'hidden':hidden,'scroll':(scroll_x,scroll_y),
                               'visible_candidate':not hidden and processed>0 and clipped[2]>0 and clipped[3]>0})
                children,vector=self.q(pointer+2896),self.q(pointer+2904)
                if not 0<=children<=2048: raise RuntimeError('Invalid interface child count.')
                child_clip=clipped if width>0 and height>0 else clip
                pending.extend((ptr,(ox+x-scroll_x,oy+y-scroll_y,hidden,child_clip)) for i in range(children)
                               for ptr in [self.q(vector+16*i+8)] if ptr)
        return result

    def player(self, state):
        index, current_world = self.i(self.s(state,52316)), self.i(self.s(state,52320))
        world_node = self.chain_lookup(self.q(self.s(state,51688)), self.i(self.s(state,51696)), current_world, 24)
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
        renderer = self.q(self.s(state,144))
        logical_w, logical_h = self.i(renderer + 48), self.i(renderer + 52)
        physical_w, physical_h = self.i(renderer + 108), self.i(renderer + 112)
        if min(logical_w, logical_h, physical_w, physical_h) <= 0:
            raise RuntimeError('Invalid viewport dimensions.')
        camera = [self.i(self.s(state,off)) for off in (0x895D8, 0x895DC, 0x895E0)]
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

    def objects(self, state, player, radius=40):
        scene, plane = player['scene'], player['plane']
        sx, sy = self.i(scene + 2376), self.i(scene + 2380)
        if not 1 <= sx <= 256 or not 1 <= sy <= 256 or not 0 <= plane < 4:
            raise RuntimeError('Invalid scene dimensions.')
        tiles, heights = self.q(scene + 2408), self.q(scene + 976)
        project, dimensions, logical = self.projection(state, scene)
        seen, result, definitions = set(), [], {}
        for x in range(max(0, player['local_x'] - radius), min(sx, player['local_x'] + radius + 1)):
            for y in range(max(0, player['local_y'] - radius), min(sy, player['local_y'] + radius + 1)):
                tile = self.q(tiles + 16 * (y + sy * (x + sx * plane)) + 8)
                if not tile:
                    continue
                height=self.i(heights+4*(y+(x+plane*(sx+1))*(sy+1)))
                for offset,kind in ((264,'wall'),(272,'wall_decoration'),(280,'floor_decoration')):
                    obj=self.q(tile+offset)
                    if not obj or obj in seen: continue
                    seen.add(obj)
                    type_id=(self.q(obj+56)>>20)&65535
                    if type_id not in definitions: definitions[type_id]=self.loc_definition(type_id)
                    name,ops=definitions[type_id]
                    result.append({'id':type_id,'name':name,'ops':ops,'kind':kind,
                                   'x':player['base_x']+x,'y':player['base_y']+y,
                                   'point':project(128*x+64,height-70,128*y+64)})
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
                    if (tag >> 16) & 7 != 2:
                        continue
                    x0, x1, y0, y1 = struct.unpack('<iiii', self.read(obj + 528, 16))
                    if not (0 <= x0 <= x1 < sx and 0 <= y0 <= y1 < sy):
                        continue
                    height = self.i(heights + 4 * (y0 + (x0 + plane * (sx + 1)) * (sy + 1)))
                    if type_id not in definitions:
                        definitions[type_id] = self.loc_definition(type_id)
                    name, ops = definitions[type_id]
                    result.append({'id': type_id, 'name': name, 'ops': ops,'kind':'game_object', 'x': player['base_x'] + x0,
                                   'y': player['base_y'] + y0,
                                   'world_point':(128*player['base_x']+64*(x0+x1+1),height-100,128*player['base_y']+64*(y0+y1+1)),
                                   'point': project(64 * (x0 + x1 + 1), height - 100, 64 * (y0 + y1 + 1))})
        return result, dimensions, logical

    def loc_definition(self, type_id):
        node = self.chain_lookup(self.q(self.base + 0xD22A30), self.i(self.base + 0xD22A38), type_id, 64, key64=True)
        if not node: return f'Object {type_id}', ()
        definition = self.q(node + 16)
        if not definition: return f'Object {type_id}', ()
        begin, end = self.q(definition + 232), self.q(definition + 240)
        if not 0 <= end - begin <= 64 * 20 or (end - begin) % 64:
            raise RuntimeError('Invalid object operations vector.')
        return self.string(definition + 64), tuple(self.string(begin + n * 64) for n in range((end - begin) // 64))

    def menu(self, state):
        root = self.q(self.s(state,4273152))
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
        manager = self.q(self.s(state,4275176))
        group_count, groups = self.q(manager + 26760), self.q(manager + 26768)
        if not 16 <= group_count < 10000:
            return False, []
        def component(group, index):
            info = groups + 24 * group
            count, array = self.q(info + 8), self.q(info + 16)
            return self.q(array + index * 16 + 8) if index < count <= 2048 else 0
        root = component(12, 0)
        opened = bool(root and self.i(root + 56) > 0 and self.i(root + 100) > 0 and self.i(root + 104) > 0
                      and not self.read(root+120,1)[0])
        if not opened:
            return False, []
        buckets, count = self.q(self.s(state,4275408)), self.i(self.s(state,4275416))
        if not self.chain_lookup(buckets,count,12,40):
            return False, []
        coordinates = self.chain_lookup(buckets, count, 15, 40)
        parent = component(15, 3)
        if not coordinates or not parent:
            return True, []
        items, slots = {item['slot']: item for item in inventory}, []
        for child in self.interfaces(state,(15,)):
            if child['id'] != 983043 or not child['visible_candidate']:
                continue
            slot, item_id = child['sub_id'], child['item_id']
            if slot not in items or items[slot]['id'] != item_id:
                continue
            x, y, w, h = child['clipped_bounds']
            if w > 0 and h > 0:
                slots.append({'slot': slot, 'id': item_id, 'point': (x + w // 2, y + h // 2)})
        return True, slots

    def bank_close_point(self, state):
        self.bank_close_identity = None
        manager = self.q(self.s(state,4275176))
        groups = self.q(manager + 26768)
        info = groups + 24 * 12
        count, array = self.q(info + 8), self.q(info + 16)
        node = self.chain_lookup(self.q(self.s(state,4275408)), self.i(self.s(state,4275416)), 12, 40)
        if not node or not 1 <= count <= 2048:
            return None
        ox, oy = self.i(node + 4), self.i(node + 8)
        roots = [self.q(array + index * 16 + 8) for index in range(count)]
        def parent_origin(component):
            x,y,seen = ox,oy,set()
            hidden=False
            parent = self.i(component + 116)
            while parent != -1:
                if parent in seen or parent >> 16 != 12 or not 0 <= (parent & 65535) < count:
                    raise RuntimeError('Invalid bank component parent chain.')
                seen.add(parent)
                pointer = roots[parent & 65535]
                if not pointer: raise RuntimeError('Bank component parent is missing.')
                x += self.i(pointer + 92)-self.i(pointer+132)
                y += self.i(pointer + 96)-self.i(pointer+136)
                hidden |= bool(self.read(pointer+120,1)[0])
                parent = self.i(pointer + 116)
            return x,y,hidden
        pending = [(component,None) for component in roots if component]
        if len(roots)>2 and roots[2]:
            pending=[entry for entry in pending if entry[0]!=roots[2]]+[(roots[2],None)]
        seen = set()
        while pending:
            component, dynamic_origin = pending.pop()
            if component in seen: continue
            seen.add(component)
            if len(seen) > 4096: raise RuntimeError('Bank component tree exceeds bounds.')
            if not component or self.i(component + 56) <= 0:
                continue
            origin = dynamic_origin if dynamic_origin is not None else parent_origin(component)
            hidden=origin[2] or bool(self.read(component+120,1)[0])
            if hidden: continue
            x,y,width,height = struct.unpack('<iiii',self.read(component + 92,16))
            children, child_array = self.q(component + 2896), self.q(component + 2904)
            if children > 2048: raise RuntimeError('Invalid bank component child count.')
            pending.extend((child,(origin[0]+x-self.i(component+132),origin[1]+y-self.i(component+136),hidden)) for n in range(children)
                           for child in [self.q(child_array+n*16+8)] if child)
            op_count, ops = self.q(component + 736), self.q(component + 744)
            if op_count <= 20 and any(self.string(ops + n * 24) == 'Close' for n in range(op_count)):
                if width > 0 and height > 0:
                    self.bank_close_identity = {'id':self.i(component+4),'slot':self.i(component+8)}
                    return (origin[0] + x + width // 2, origin[1] + y + height // 2)
        return None

    def ground_points(self,state,player,radius=6):
        scene,plane=player['scene'],player['plane']
        sx,sy=self.i(scene+2376),self.i(scene+2380)
        project,dimensions,logical=self.projection(state,scene)
        heights=self.q(scene+976)
        result=[]
        for x in range(max(0,player['local_x']-radius),min(sx,player['local_x']+radius+1)):
            for y in range(max(0,player['local_y']-radius),min(sy,player['local_y']+radius+1)):
                height=sum(self.i(heights+4*(yy+(xx+plane*(sx+1))*(sy+1)))
                           for xx,yy in ((x,y),(x+1,y),(x,y+1),(x+1,y+1)))//4
                point=project(x*128+64,height,y*128+64)
                if point: result.append({'x':player['base_x']+x,'y':player['base_y']+y,'point':point})
        return result

    def ground_items(self,state,player,radius=40):
        planes=self.q(player['world']+320)
        plane=planes+24*player['plane']
        width,columns=self.q(plane+8),self.q(plane+16)
        if not 1<=width<=256: raise RuntimeError('Invalid ground-item map width.')
        project,_,_=self.projection(state,player['scene'])
        heights=self.q(player['scene']+976)
        sx,sy=self.i(player['scene']+2376),self.i(player['scene']+2380)
        result=[]
        definitions={}
        for x in range(max(0,player['local_x']-radius),min(width,player['local_x']+radius+1)):
            column=columns+24*x
            height,cells=self.q(column+8),self.q(column+16)
            if not 1<=height<=256: raise RuntimeError('Invalid ground-item map height.')
            first,last=max(0,player['local_y']-radius),min(height,player['local_y']+radius+1)
            data=self.read(cells+24*first,24*(last-first))
            for y in range(first,last):
                node,previous,count=struct.unpack_from('<QQQ',data,24*(y-first))
                if count==0:continue
                if count>128:raise RuntimeError('Ground-item pile exceeds traversal bound.')
                sentinel=cells+24*y
                seen=set()
                while node and node!=sentinel and node not in seen:
                    if len(seen)>=128:raise RuntimeError('Ground-item list exceeded bound.')
                    seen.add(node)
                    item=self.q(node+24)
                    if item:
                        item_id,quantity=self.i(item+32),self.i(item+36)
                        if not 0<=item_id<=65535 or quantity<=0:raise RuntimeError('Invalid ground item identity/quantity.')
                        if item_id not in definitions:definitions[item_id]=self.item_definition(item_id)
                        definition=definitions[item_id] or {}
                        elevation=self.i(heights+4*(y+(x+player['plane']*(sx+1))*(sy+1)))
                        result.append({'id':item_id,'quantity':quantity,'x':player['base_x']+x,'y':player['base_y']+y,
                                       'plane':player['plane'],'name':definition.get('name',''),
                                       'ops':definition.get('ground_operations',()),'point':project(128*x+64,elevation-20,128*y+64)})
                    node=self.q(node)
        return result

    def collision(self,player):
        maps=self.q(player['scene']+760)
        entry=maps+40*player['plane']
        ox,oy,width,height=struct.unpack('<iiii',self.read(entry,16))
        if not 1<=width<=256 or not 1<=height<=256: raise RuntimeError('Invalid collision map dimensions.')
        rows=self.q(entry+32)
        if self.q(entry+24)!=width: raise RuntimeError('Collision column count mismatch.')
        flags=[]
        for x in range(width):
            column=rows+24*x
            if self.q(column+8)!=height: raise RuntimeError('Collision row count mismatch.')
            flags.extend(struct.unpack('<'+'I'*height,self.read(self.q(column+16),height*4)))
        return {'origin_x':player['base_x']+ox,'origin_y':player['base_y']+oy,'width':width,'height':height,
                'plane':player['plane'],'flags':flags}

    def snapshot(self,details=True,interface_groups=None):
        state = self.q(self.base + 0xE98C18)
        inventory = self.inventory()
        player = self.player(state)
        player['x'], player['y'] = player['base_x'] + player['local_x'], player['base_y'] + player['local_y']
        if details: objects, dimensions, logical = self.objects(state, player)
        else:
            objects=[]
            _,dimensions,logical=self.projection(state,player['scene'])
        menu, default = self.menu(state)
        bank_open, bank_slots = self.bank(state, inventory)
        close_point = self.bank_close_point(state) if bank_open else None
        result = {'pid': self.pid, 'build_sha256':getattr(self,'build_sha256',BUILD), 'player': player, 'inventory': inventory,
                'objects': objects, 'dimensions': dimensions, 'logical': logical,
                'menu': menu, 'default': default, 'bank_open': bank_open,
                'bank_slots': bank_slots, 'xp': self.i(self.s(state,13352) + 32),
                'bank_close': close_point,
                'bank_close_identity': self.bank_close_identity if bank_open else None,
                'ground_points': self.ground_points(state,player) if details else [],
                'collision': self.collision(player) if details else None,
                'actors':self.actors(state,player) if details else [],'camera':self.camera(state,player),'skills':self.skills(state),
                'ground_items':self.ground_items(state,player) if details else [],
                'equipment':self.inventory(94),'bank_items':self.inventory(95),
                'game_state':self.i(self.s(state,8544)),'tick':self.i(self.s(state,12712)),
                'logged_in':self.q(self.s(state,13096))!=0xffffffffffffffff and self.i(self.s(state,8544))==30,
                'item_definitions':[definition for item_id in ({item['id'] for item in inventory} if details else set())
                                    for definition in [self.item_definition(item_id)] if definition],
                'interfaces':self.interfaces(state,interface_groups) if interface_groups is not None else [],
                'level': self.i(self.s(state,13252) + 32)}
        # Reject a map/instance transition during the non-atomic collection.
        if self.q(self.base+0xE98C18) != state:
            raise RuntimeError('Client state changed during snapshot; refresh before input.')
        fresh = self.player(state)
        identity = ('world','scene','plane','base_x','base_y')
        if any(fresh[key] != player[key] for key in identity):
            raise RuntimeError('Scene changed during snapshot; refresh before input.')
        return result

    def action_snapshot(self): return self.snapshot(details=False)

    def input_backend(self):
        owner = self.input_owner()
        if self.q(self.q(owner) + 88) - self.base != 0x2A1D0:
            raise RuntimeError('Unverified hook owner layout.')
        window = self.q(owner + 100016)
        dispatcher = self.q(window + 248)
        if self.q(self.q(dispatcher) + 80) - self.base != self.fingerprint(0x38EE0):
            raise RuntimeError('Unverified hook dispatcher layout.')
        fallback = self.q(dispatcher + getattr(self,'profile',{}).get('dispatcher_member',123260216) + 8)
        wrapper = self.q(self.q(fallback + 2192))
        callable_object = self.q(wrapper + 56)
        if self.q(self.q(callable_object) + 16) - self.base != self.fingerprint(0x6D16D0):
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
        owner = self.input_owner()
        if self.q(self.q(owner) + 88) - self.base != 0x2A1D0:
            raise RuntimeError('Unverified window-owner layout.')
        window = self.q(owner + 100016)
        child_object = self.q(window + 224)
        if not child_object:
            raise RuntimeError('Client input child window is unavailable.')
        return self.q(window + 576), self.q(child_object + 32)

    def recorded_input(self):
        recorder = self.input_recorder()
        owner = self.input_owner()
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
