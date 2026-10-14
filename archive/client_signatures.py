"""Build/scan candidate signatures. Requires pefile and capstone; never writes to the client."""
import argparse
import hashlib
import json
from pathlib import Path
import capstone
import pefile

TARGETS = {
    'ClientState_getStatEffectiveLevel': (0xF5890, 0x21),
    'ClientState_getStatXP': (0xF58C0, 0x21),
    'ClientState_getStatBaseLevel': (0xF58F0, 0x21),
    'Inventory_GetItemId': (0x30D70, 0x5D),
    'Inventory_GetQuantity': (0x30DD0, 0x5D),
    'Player_SetActionAnimation': (0x714B0, 0x120),
    'LocType_GetOrLoadById': (0x5ED140, 0x100),
    'SceneTile_FindLocType': (0x6A2D90, 0x160),
    'Lua_RegisterLocTypeBindings': (0xF4940, 0x120),
    'Menu_BuildLocEntries': (0x383790, 0x120),
    'Scene_ProjectWorldPoint': (0x6AA8A0, 0xED),
    'LuaIfType_retrieveIfGroup': (0x228370, 0x160),
    'MenuInput_ActivateOrderedFirstAction': (0x380B00, 0x120),
}
EXPECTED_HASH = '3852dd48aa6a75cfb042489b5192b477a1b828cbc95af8b759c139095c8b6ea2'

def executable_sections(pe):
    return [(s.VirtualAddress, s.get_data()) for s in pe.sections if s.Characteristics & 0x20000000]

def pattern_matches(pe, pattern):
    tokens = pattern.split()
    values = [None if token == '??' else int(token, 16) for token in tokens]
    runs = []
    run_start = 0
    for index in range(len(values) + 1):
        if index == len(values) or values[index] is None:
            if index > run_start:
                runs.append((run_start, bytes(values[run_start:index])))
            run_start = index + 1
    if not runs:
        raise ValueError('A signature needs fixed bytes')
    anchor_offset, anchor = max(runs, key=lambda run: len(run[1]))
    matches = []
    for base, data in executable_sections(pe):
        search_offset = 0
        while True:
            found = data.find(anchor, search_offset)
            if found < 0:
                break
            start = found - anchor_offset
            if 0 <= start <= len(data) - len(values) and all(value is None or data[start+i] == value for i, value in enumerate(values)):
                matches.append(base + start)
            search_offset = found + 1
    return matches

def build(binary, manifest_path):
    raw = Path(binary).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_HASH:
        raise ValueError('Build requires the already analyzed binary hash; analyze new builds first.')
    pe = pefile.PE(data=raw)
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    relocations = {e.rva: (8 if e.type == 10 else 4) for block in getattr(pe, 'DIRECTORY_ENTRY_BASERELOC', [])
                   for e in block.entries if e.type in (3, 10)}
    entries = []
    for name, (rva, size) in TARGETS.items():
        code = pe.get_data(rva, size)
        masked = list(code)
        instructions = list(decoder.disasm(code, rva))
        boundaries = []
        references = []
        for ins in instructions:
            start = ins.address - rva
            for op in ins.operands:
                if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                    for k in range(ins.disp_offset, ins.disp_offset + ins.disp_size):
                        masked[start + k] = None
                    references.append({'instruction_offset': start, 'displacement_offset': ins.disp_offset,
                                       'instruction_size': ins.size, 'target_rva': ins.address + ins.size + op.mem.disp})
            if ins.group(capstone.CS_GRP_JUMP) or ins.group(capstone.CS_GRP_CALL):
                for op in ins.operands:
                    if op.type == capstone.x86.X86_OP_IMM:
                        for k in range(ins.imm_offset, ins.imm_offset + ins.imm_size):
                            masked[start + k] = None
            for rel_rva, width in relocations.items():
                if ins.address <= rel_rva < ins.address + ins.size:
                    for k in range(rel_rva-rva, min(rel_rva-rva+width, len(masked))):
                        masked[k] = None
            boundaries.append(start + ins.size)
        candidate = None
        for length in boundaries:
            if length < 20:
                continue
            pattern = ' '.join('??' if v is None else f'{v:02X}' for v in masked[:length])
            matches = pattern_matches(pe, pattern)
            if matches == [rva]:
                candidate = {'name': name, 'pattern': pattern, 'baseline_rva': rva,
                             'baseline_match_count': 1, 'rip_references': [x for x in references if x['instruction_offset'] < length]}
                break
        if candidate is None:
            raise ValueError(f'No unique in-function signature for {name}')
        entries.append(candidate)
    manifest = {'schema': 1, 'baseline_sha256': digest, 'architecture': 'x86_64',
                'policy': 'Unique signature matches are candidates only. Structure displacements remain literal. New hashes require semantic/layout validation before memory access or actions.',
                'signatures': entries}
    if manifest_path == '-':
        return manifest
    Path(manifest_path).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return {'manifest': str(manifest_path), 'signatures': len(entries), 'unique': True}

def scan(binary, manifest_path):
    raw = Path(binary).read_bytes()
    pe = pefile.PE(data=raw)
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    known = hashlib.sha256(raw).hexdigest() == manifest['baseline_sha256']
    results = []
    for signature in manifest['signatures']:
        matches = pattern_matches(pe, signature['pattern'])
        resolved = []
        if len(matches) == 1:
            for ref in signature.get('rip_references', []):
                instruction_rva = matches[0] + ref['instruction_offset']
                displacement = int.from_bytes(pe.get_data(instruction_rva + ref['displacement_offset'], 4), 'little', signed=True)
                resolved.append(hex(instruction_rva + ref['instruction_size'] + displacement))
        results.append({'name': signature['name'], 'match_count': len(matches),
                        'candidate_rvas': [hex(x) for x in matches],
                        'resolved_reference_rvas': resolved,
                        'status': 'baseline_verified' if known and matches == [signature['baseline_rva']]
                        else 'needs_analysis' if len(matches) == 1 else 'unresolved'})
    return {'same_build': known, 'results': results}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['build', 'scan'])
    parser.add_argument('binary')
    parser.add_argument('--manifest', default=str(Path(__file__).with_name('client_signatures.json')))
    args = parser.parse_args()
    print(json.dumps(build(args.binary, args.manifest) if args.mode == 'build' else scan(args.binary, args.manifest), indent=2))
