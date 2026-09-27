#!/usr/bin/env python3
"""Export reproducible ARM evidence and candidate string cross-references.

Linear ARM literal scanning is a candidate finder, not function recovery.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from firmware import revision, trace_inputs

BASE=0x20005000
TOKENS=['Firmware Update','Updating MAIN CPU firmware.','Updating DSP/FPGA firmware.',
        'C:\\IC-7300\\VoiceTx\\voicetx1.wav','IC-7300 Voice Recorder Data',
        'IC-7300 Voice TX Data','Time Set','Date','CI-V','PTT Port Function',
        'USB SEND','REF Adjust','DSP TX TotalGain HF']


def evidence(app):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    from capstone.arm import ARM_OP_MEM, ARM_OP_IMM, ARM_REG_PC
    cs=Cs(CS_ARCH_ARM,CS_MODE_ARM);cs.detail=True;cs.skipdata=True
    references={}; md5_callers=[]
    for ins in cs.disasm(app[:0x185000],BASE):
        if ins.id and ins.mnemonic in ('bl','blx') and ins.operands[0].type==ARM_OP_IMM and ins.operands[0].imm==0x2003c860:
            md5_callers.append(hex(ins.address))
        if ins.id and ins.mnemonic=='ldr' and len(ins.operands)==2:
            op=ins.operands[1]
            if op.type==ARM_OP_MEM and op.mem.base==ARM_REG_PC:
                pool=ins.address+8+op.mem.disp-BASE
                if 0<=pool<=len(app)-4:
                    value=struct.unpack_from('<I',app,pool)[0]
                    references.setdefault(value,[]).append({'instruction':hex(ins.address),'pool':hex(BASE+pool)})
    tokens=[]
    for token in TOKENS:
        matches=[]
        for m in re.finditer(re.escape(token.encode()),app):
            address=BASE+m.start()
            pointers=[BASE+x.start() for x in re.finditer(re.escape(struct.pack('<I',address)),app)]
            matches.append({'address':hex(address),'literal_loads':references.get(address,[]),
                            'pointer_locations':[hex(x) for x in pointers],
                            'pointer_loads':[r for x in pointers for r in references.get(x,[])]})
        tokens.append({'token':token,'matches':matches})
    md5=[]
    for name,val in [('MD5_T0',0xd76aa478),('MD5_IV0',0x67452301),('MD5_IV1',0xefcdab89)]:
        offsets=[BASE+m.start() for m in re.finditer(re.escape(struct.pack('<I',val)),app)]
        md5.append({'name':name,'locations':[hex(x) for x in offsets],'literal_loads':references.get(val,[])})
    return {'source_revision':revision(),'image_sha256':hashlib.sha256(app).hexdigest(),
            'base':hex(BASE),'confidence':'Validated reset vectors and loader destination; xrefs are candidates',
            'strings':tokens,'md5_constants':md5,'md5_init_callers':md5_callers}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('extracted',type=Path);p.add_argument('output',type=Path);args=p.parse_args()
    try:
        app,boot=trace_inputs(args.extracted)
    except (ValueError, OSError, KeyError, struct.error) as e:
        print(f'error: {e}',file=sys.stderr)
        return 1
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    result=evidence(app);args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    cs=Cs(CS_ARCH_ARM,CS_MODE_ARM);cs.skipdata=True
    blocks=[('boot',boot[:0x138],0x18000000),('loader',boot[0x4000:0x4650],0x20004000),('application_reset',app[:0x200],BASE)]
    out=args.extracted/'assembly';out.mkdir(exist_ok=True)
    for name,data,address in blocks:
        (out/(name+'.txt')).write_text('\n'.join(f'{i.address:08x} {i.bytes.hex():12} {i.mnemonic} {i.op_str}' for i in cs.disasm(data,address))+'\n')


if __name__=='__main__':sys.exit(main())
