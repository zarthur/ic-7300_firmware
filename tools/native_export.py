#!/usr/bin/env python3
"""Exact-image file-worker ABI and task-ID probes; no filesystem or OS simulation."""
import argparse
from pathlib import Path
import struct

from emulate_platform import OUTPUT, SOURCE, STACK, execute, inputs
from firmware import digest, revision
from native_receive import Isolated, tool_hashes as receive_hashes
from recorder_interface import identity
from reporting import atomic_json

TASK_IDS=0x204201a4
WORKERS={'open':(0x200bb8d4,0x200bb90c,0x200bb8f0),
         'read':(0x200bb958,0x200bb98c,0x200bb970),
         'write':(0x200bb98c,0x200bb9c0,0x200bb9a4)}


def task_id_probe(app,occupied):
    if not isinstance(occupied,list) or len(occupied)!=11 or any(type(x) is not bool for x in occupied):
        raise ValueError('Require eleven synthetic occupied-slot flags')
    h=Isolated(app,[(0x2018763c,0x2018765c)],[(TASK_IDS,44)])
    before=struct.pack('<11I',*(0x02000000+64*i if used else 0 for i,used in enumerate(occupied)))
    h.uc.mem_write(TASK_IDS,before)
    result=h.run(0x2018763d)
    result.update(occupied=occupied,table_unchanged=bytes(h.uc.mem_read(TASK_IDS,44))==before)
    return result


def worker_probe(app,operation,underlying_result):
    if operation not in WORKERS or type(underlying_result) is not int or not -(1<<31)<=underlying_result<(1<<31):
        raise ValueError('Require a reviewed worker and signed 32-bit boundary result')
    start,end,call=WORKERS[operation]
    h=Isolated(app,[(start,end)],[(OUTPUT-4,12)])
    h.uc.mem_write(OUTPUT-4,b'\xa5'*12)
    # Worker receives the dequeued request, not the public wrapper signature.
    # r0=command, r1=ticket, r2=caller task, r3=filename or handle.
    command={'open':15,'read':17,'write':18}[operation]
    args=(command,0x100|command,0x02100000,SOURCE if operation=='open' else 7)
    stack_args=(0x8400,OUTPUT,0x02200000) if operation=='open' else (SOURCE,90128,OUTPUT)
    h.uc.mem_write(STACK+0xf000,struct.pack('<3I',*stack_args))
    h.run(start,args,stop=call)
    regs=(h.a.UC_ARM_REG_R0,h.a.UC_ARM_REG_R1,h.a.UC_ARM_REG_R2,h.a.UC_ARM_REG_R3)
    forwarded=[h.uc.reg_read(r) for r in regs]
    # Do not execute or invent a file operation. Inject its result at the ABI
    # boundary, then execute only the original worker's result translation.
    h.uc.reg_write(h.a.UC_ARM_REG_R0,underlying_result & 0xffffffff)
    execute(h.uc,call+4,budget=100)
    out=bytes(h.uc.mem_read(OUTPUT-4,12))
    completion=h.uc.reg_read(h.a.UC_ARM_REG_R0)
    return {'operation':operation,'forwarded_arguments':forwarded,
            'underlying_result_fixture':underlying_result,
            'completion_result':struct.unpack('<i',struct.pack('<I',completion))[0],
            'output_value':struct.unpack_from('<i',out,4)[0],
            'guards_preserved':out[:4]+out[-4:]==b'\xa5'*8,
            'instructions':h.count,'file_operation_executed':False}




def publication_gate_probe(app,distance,consumer,previous):
    """Execute the original ring watermark gate, not a UI recording trigger."""
    from native_receive import STATE, INDICES
    if type(distance) is not int or not 0<=distance<1914 or type(consumer) is not int or not 0<=consumer<1914 or previous not in (0,1):
        raise ValueError('Invalid synthetic ring occupancy')
    h=Isolated(app,[(0x20048afc,0x20048b50),(0x200686a4,0x200686b0)],[(STATE,16),(INDICES,0xdc)])
    h.uc.mem_write(INDICES+0xd8,struct.pack('<H',consumer))
    h.uc.mem_write(STATE+6,bytes([previous]))
    h.run(0x20048afc,((consumer+distance)%1914,))
    return {'distance':distance,'consumer':consumer,'previous':previous,
            'enabled':h.uc.mem_read(STATE+6,1)[0]}


def publication_probe(app,index):
    """Original publisher around the copy boundary; explicit synthetic ABI bridge."""
    from native_receive import STATE, INDICES, SCRATCH, RING, CLEAR
    import native_transport as carrier
    if type(index) is not int or index not in (0,1913):raise ValueError('Require a reviewed ring boundary')
    code=carrier.build_core(carrier.SOURCE)
    h=Isolated(app,[(0x20066f18,0x20066fc4),CLEAR,(carrier.CODE,carrier.CODE+len(code))],
               [(STATE,16),(INDICES,0xdc),(SCRATCH,216),(RING,1914*220),
                (carrier.CAPTURE,carrier.STORAGE_SIZE),(carrier.CONTROL,8)])
    h.uc.mem_map(carrier.CODE,4096,h.u.UC_PROT_READ|h.u.UC_PROT_EXEC)
    h.uc.mem_write(carrier.CODE,code)
    capture=struct.pack('<4I',2,512,0,0)+bytes(carrier.STORAGE_SIZE-16)
    h.uc.mem_write(carrier.CAPTURE,capture)
    h.uc.mem_write(carrier.CONTROL,bytes(8))
    h.uc.mem_write(STATE+3,b'\x5a');h.uc.mem_write(STATE+6,b'\x01')
    h.uc.mem_write(STATE+8,struct.pack('<H',216))
    h.uc.mem_write(INDICES+0xda,struct.pack('<H',index))
    h.uc.mem_write(SCRATCH,bytes(range(216)))
    h.uc.mem_write(RING,b'\xa5'*(1914*220))
    h.run(0x20066f18,(1,),stop=0x20066f80)
    forwarded=[h.uc.reg_read(r) for r in (h.a.UC_ARM_REG_R0,h.a.UC_ARM_REG_R1,h.a.UC_ARM_REG_R2)]
    # Model only the future wrapper's argument/return bridge. No firmware hook
    # is patched or claimed verified by this experiment.
    h.uc.reg_write(h.a.UC_ARM_REG_R2,carrier.CAPTURE)
    h.uc.reg_write(h.a.UC_ARM_REG_R3,carrier.CONTROL)
    h.uc.reg_write(h.a.UC_ARM_REG_LR,0x20066f84)
    execute(h.uc,carrier.CODE,budget=3000)
    ring=bytes(h.uc.mem_read(RING,1914*220))
    return {'index_before':index,'copy_arguments':forwarded,
            'index_after':struct.unpack('<H',h.uc.mem_read(INDICES+0xda,2))[0],
            'fill_after':struct.unpack('<H',h.uc.mem_read(STATE+8,2))[0],
            'published_hex':ring[index*220:(index+1)*220].hex(),
            'next_slot_hex':ring[((index+1)%1914)*220:((index+1)%1914+1)*220].hex(),
            'changed_slots':[i for i in range(1914) if ring[i*220:(i+1)*220]!=b'\xa5'*220],
            'scratch_unchanged':bytes(h.uc.mem_read(SCRATCH,216))==bytes(range(216)),
            'capture_unchanged':bytes(h.uc.mem_read(carrier.CAPTURE,carrier.STORAGE_SIZE))==capture,
            'wrapper_bridge_modeled':True,'firmware_hook_installed':False}


def tool_hashes():
    paths=('tools/native_export.py','tools/native_capture.py','tools/native_transport.py',
           'prototype/native_receive/transport.S')
    root=Path(__file__).resolve().parents[1]
    return dict(receive_hashes(),**{p:digest((root/p).read_bytes()) for p in paths})


def _report(image):
    data,_,app,_=inputs(image)
    import native_transport as carrier
    ids=[task_id_probe(app,[i<n for i in range(11)]) for n in range(12)]
    holes=[task_id_probe(app,[i!=free for i in range(11)]) for free in range(11)]
    workers=[worker_probe(app,op,result) for op in WORKERS for result in (-17921,-1,0,7,90128)]
    return {'schema_version':1,'image_sha256':digest(data),'application_sha256':digest(app),
            'publication_gate':[publication_gate_probe(app,d,c,p) for d in (0,1879,1880,1908,1909,1913)
                                for c in (0,1913) for p in (0,1)],
            'carrier_code_sha256':digest(carrier.build_core(carrier.SOURCE)),
            'publication':[publication_probe(app,i) for i in (0,1913)],
            'task_id_prefixes':ids,'task_id_holes':holes,'file_workers':workers,
            'limitations':['Task-ID availability is synthetic; no live free slot or stack allocation is established.',
                           'No thread is created and no scheduler, semaphore or SVC operation is simulated.',
                           'File operation results are explicit injected stimuli, not successful native I/O.',
                           'Open flags, task lifecycle, hook, trigger and target export remain unqualified.']}


def report(image):
    image=Path(image)
    initial,hashes,source=identity(image),tool_hashes(),revision()
    result=_report(image)
    if identity(image)!=initial or result['image_sha256']!=initial[0] or tool_hashes()!=hashes or revision()!=source:
        raise ValueError('Image/source changed during native export analysis')
    return dict(result,source_revision=source,tool_sha256=hashes,source_unchanged=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Output exists; choose a new evidence path')
    result=report(args.image)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(args.output,result)
    print(f'Native export ABI evidence: {args.output}')


if __name__=='__main__':main()
