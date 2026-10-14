"""Offline PE recovery report. Candidates never authorize input or change offsets."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parent.parent


def load_scanner():
    spec = importlib.util.spec_from_file_location('grove_signature_scanner', ROOT/'archive/client_signatures.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def readable_section(pe, rva):
    return next((section for section in pe.sections if
                 section.VirtualAddress <= rva < section.VirtualAddress + max(section.Misc_VirtualSize,section.SizeOfRawData)
                 and section.Characteristics & 0x40000000), None)


def rtti_evidence(pe, limit=500):
    """Identify MSVC x64 type descriptors and structurally matching COL records."""
    descriptors = {}
    for section in pe.sections:
        if section.Characteristics & 0x20000000: continue
        data=section.get_data()
        for match in re.finditer(rb'\.\?A[UV][ -~]{1,240}?@@\x00',data):
            rva=section.VirtualAddress+match.start()-16
            if rva<0 or rva%8: continue
            header=pe.get_data(rva,16)
            if len(header)!=16: continue
            vtable,spare=struct.unpack('<QQ',header)
            if spare or readable_section(pe,vtable-pe.OPTIONAL_HEADER.ImageBase) is None: continue
            descriptors[rva]={'name':match.group()[:-1].decode('ascii'),'type_descriptor_rva':hex(rva),'locators':[]}
            if len(descriptors)>=limit: break
    for section in pe.sections:
        if section.Characteristics & 0x20000000: continue
        data=section.get_data()
        for offset in range(0,max(0,len(data)-23),4):
            signature,object_offset,constructor_offset,type_rva,hierarchy,self_rva=struct.unpack_from('<6I',data,offset)
            rva=section.VirtualAddress+offset
            if signature==1 and type_rva in descriptors and self_rva==rva and readable_section(pe,hierarchy):
                descriptors[type_rva]['locators'].append({'rva':hex(rva),'object_offset':object_offset,
                                                        'constructor_offset':constructor_offset,'hierarchy_rva':hex(hierarchy)})
    return list(descriptors.values())


def recover(binary, manifest_path=None):
    scanner=load_scanner()
    raw=Path(binary).read_bytes()
    pe=scanner.pefile.PE(data=raw)
    if pe.FILE_HEADER.Machine!=0x8664 or pe.OPTIONAL_HEADER.Magic!=0x20b:
        raise ValueError('Only x64 PE binaries are supported.')
    latest = ROOT/'recovery/client_166231c8_signatures.json'
    manifest_path=Path(manifest_path or (latest if latest.exists() else ROOT/'archive/client_signatures.json'))
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    report=scanner.scan(binary,manifest_path)
    by_name={entry['name']:entry for entry in manifest['signatures']}
    decoder=scanner.capstone.Cs(scanner.capstone.CS_ARCH_X86,scanner.capstone.CS_MODE_64)
    decoder.detail=True
    global_candidates={}
    for result in report['results']:
        signature=by_name[result['name']]
        valid=True
        evidence=[]
        if result['match_count']==1:
            function_rva=int(result['candidate_rvas'][0],16)
            for reference in signature.get('rip_references',()):
                rva=function_rva+reference['instruction_offset']
                instructions=list(decoder.disasm(pe.get_data(rva,15),rva,count=1))
                instruction=instructions[0] if instructions else None
                targets=[instruction.address+instruction.size+operand.mem.disp for operand in instruction.operands
                         if operand.type==scanner.capstone.x86.X86_OP_MEM and operand.mem.base==scanner.capstone.x86.X86_REG_RIP] if instruction else []
                matching=bool(instruction and instruction.size==reference['instruction_size'] and instruction.disp_offset==reference['displacement_offset'] and len(targets)==1 and readable_section(pe,targets[0]))
                valid &= matching
                evidence.append({'instruction_rva':hex(rva),'validated_encoding':matching,'resolved_rvas':list(map(hex,targets))})
                if matching:
                    key=hex(reference['target_rva'])
                    global_candidates.setdefault(key,[]).append({'source':result['name'],'candidate_rva':hex(targets[0])})
        result['reference_evidence']=evidence
        result['encoding_valid']=valid if result['match_count']==1 else False
    report.update(schema=1,binary=str(Path(binary).resolve()),sha256=hashlib.sha256(raw).hexdigest(),
                  baseline_sha256=manifest['baseline_sha256'],input_authorized=False,
                  globals=[{'baseline_rva':key,'candidates':sorted({e['candidate_rva'] for e in values}),
                            'sources':values,'consistent':len({e['candidate_rva'] for e in values})==1}
                           for key,values in global_candidates.items()],rtti=rtti_evidence(pe),
                  pending=['Structure-field offset recovery','Read-only runtime invariants on new build',
                           'Explicit reviewed build-profile promotion'],
                  policy='Offline candidates only. Unique matches and RTTI do not establish semantic compatibility.')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary')
    parser.add_argument('--manifest')
    parser.add_argument('--output',help='Report JSON path; omit to print to stdout.')
    args=parser.parse_args()
    encoded=json.dumps(recover(args.binary,args.manifest),indent=2)+'\n'
    if args.output: Path(args.output).write_text(encoded,encoding='utf-8')
    else: print(encoded,end='')
