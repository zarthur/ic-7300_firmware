#!/usr/bin/env python3
"""Exact-v1.42 diagnostic wrapper construction and offline original-call probes."""
from pathlib import Path
import struct

from emulate_platform import APP_BASE, STACK, RETURN
from firmware import digest
from native_capture import build_core, STORAGE_SIZE
from native_receive import Isolated, COPY, CLEAR, QUEUE, SPLIT, DMA, STATE, INDICES, SCRATCH, RING
from recorder_interface import APPLICATION_SHA256

ROOT=Path(__file__).resolve().parents[1]
CODE=0x20362000
CAPTURE=0x20364000
CONTROL=0x2037a020
TICK=0x20390a78
COUNTER=0xfcfec004
PENDING=0xe8201210
RECORD=0x20390444
SITES={'dma':(0x200606d8,0x2005fb28,False),
       'carrier':(0x20066f80,0x2017c710,True),
       'arm':(0x200497f0,0x2006a354,False)}


def arm_call(site,target,thumb=False):
    if type(site) is not int or type(target) is not int or not 0<=site<=0xfffffff7 or not 0<=target<=0xffffffff or site%4 or target%(2 if thumb else 4):
        raise ValueError('Misaligned ARM call')
    delta=target-site-8
    if not -(1<<25)<=delta<(1<<25):raise ValueError('ARM call outside branch range')
    word=(0xfa000000 if thumb else 0xeb000000)|((delta>>2)&0xffffff)
    if thumb:word|=(delta&2)<<23
    return struct.pack('<I',word)


def build_bundle():
    code=build_core(ROOT/'prototype/native_receive/wrappers.S')
    magic,version,dma,carrier,arm,capture,transport,end=struct.unpack_from('<8I',code)
    offsets=[dma,carrier,arm,capture,transport]
    if magic!=0x584e3733 or version!=1 or end!=len(code) or dma!=32 or offsets!=sorted(set(offsets)) or any(i%4 for i in offsets):
        raise ValueError('Invalid wrapper bundle header')
    for name,start,stop in [('capture',capture,transport),('transport',transport,None)]:
        core=build_core(ROOT/f'prototype/native_receive/{name}.S')
        if code[start:start+len(core)]!=core or (stop is not None and start+len(core)!=stop):
            raise ValueError('Bundled core differs from standalone tested core')
    if CODE+len(code)>CAPTURE or CAPTURE+STORAGE_SIZE>CONTROL or CONTROL+8>0x20390000:
        raise ValueError('Wrapper footprint outside proposed padding')
    return code,dict(zip(('dma','carrier','arm'),(CODE+dma,CODE+carrier,CODE+arm)))


def patches(app):
    if digest(app)!=APPLICATION_SHA256:raise ValueError('Requires exact pinned v1.42 application')
    code,entries=build_bundle()
    edits=[]
    for name,(site,target,thumb) in SITES.items():
        before=app[site-APP_BASE:site-APP_BASE+4]
        if before!=arm_call(site,target,thumb):raise ValueError('Original call-site mismatch')
        edits.append((site,arm_call(site,entries[name])))
    for address,data in ((CODE,code),(CAPTURE,bytes(STORAGE_SIZE)),(CONTROL,bytes(8))):
        before=app[address-APP_BASE:address-APP_BASE+len(data)]
        if len(before)!=len(data) or any(x!=255 for x in before):raise ValueError('Diagnostic padding is not all FF')
        edits.append((address,data))
    return edits


class WrapperTrial:
    """Original code plus actual patched calls; no cache, DMA or OS emulation."""
    def __init__(self,app,kind,patched=True):
        if kind not in SITES:raise ValueError('Unknown wrapper fixture')
        code,self.entries=build_bundle()
        common=[(CAPTURE,STORAGE_SIZE),(CONTROL,8)]
        if kind=='dma':
            ranges=[(0x20060690,0x200606ec),(0x2005fb28,0x2005fb64),(0x2005fc24,0x2005fc60),COPY]
            regions=[(DMA,1152),(SPLIT,144),(QUEUE,0x242),(0x203fc002,0x243),
                     (TICK,4),(COUNTER,4),(PENDING,4)]
        elif kind=='carrier':
            ranges=[(0x20066f18,0x20066fc4),COPY,CLEAR]
            regions=[(STATE,16),(INDICES,0xdc),(SCRATCH,216),(RING,1914*220)]
        else:
            ranges=[(0x200497f0,0x200497f4),(0x2006a354,0x2006a370)]
            regions=[(RECORD,0x58)]
        self.h=Isolated(app,ranges+[(CODE+32,CODE+len(code))],common+regions)
        self.uc,self.u,self.a=self.h.uc,self.h.u,self.h.a
        # Isolated gates the exact original before these declared substitutions.
        for address,data in patches(app):
            if patched or address>=CODE:self.uc.mem_write(address,data)
        self.reads=[];self.snapshots=[];self.next_snapshot=0;self.minimum_sp=STACK+0xf000
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ|self.u.UC_HOOK_MEM_WRITE,self._observe)
        self.uc.hook_add(self.u.UC_HOOK_CODE,self._stack)

    def _stack(self,uc,address,size,user):
        self.minimum_sp=min(self.minimum_sp,uc.reg_read(self.a.UC_ARM_REG_SP))

    def _observe(self,uc,access,address,size,value,user):
        registers=(TICK,COUNTER,PENDING)
        if not any(address<base+4 and base<address+size for base in registers):return
        if access==self.u.UC_MEM_WRITE:raise ValueError('Diagnostic wrote timer or pending/tick state')
        if address not in registers or size!=4:raise ValueError('Unexpected observation width')
        sequence=(TICK,COUNTER,PENDING,TICK,COUNTER,PENDING)
        if not self.snapshots or self.next_snapshot>=6 or address!=sequence[self.next_snapshot]:
            raise ValueError('Unexpected snapshot read order')
        supplied=self.snapshots[self.next_snapshot]
        uc.mem_write(address,struct.pack('<I',supplied))
        self.reads.append((address,supplied));self.next_snapshot+=1

    def configure(self,status=0,count=0,index=0,transport_status=0):
        self.uc.mem_write(CAPTURE,struct.pack('<4I',status,count,0,0))
        self.uc.mem_write(CONTROL,struct.pack('<2I',index,transport_status))

    def dma(self,words,bank=0,snapshots=(1,32000,0,1,31990,0)):
        if len(words)!=576 or bank not in (0,1) or len(snapshots)!=6:raise ValueError('Invalid DMA fixture')
        self.snapshots=list(snapshots);self.next_snapshot=0;self.reads=[]
        self.uc.mem_write(DMA+576*bank,words)
        # Enter after original acknowledgment/cache maintenance with the original
        # handler's saved stack frame explicitly supplied. Neither is simulated.
        self.uc.mem_write(STACK+0xf000,struct.pack('<4I',0x44444444,0x55555555,0x66666666,RETURN))
        self.uc.reg_write(self.a.UC_ARM_REG_R2,DMA+576*bank)
        result=self.h.run(0x20060690,budget=10000)
        result.update(queue_a=bytes(self.uc.mem_read(QUEUE,0x242)),
                      queue_b=bytes(self.uc.mem_read(0x203fc002,0x243)),
                      split=bytes(self.uc.mem_read(SPLIT,144)),
                      observations=list(self.reads),
                      stack_extra_bytes=STACK+0xf000-self.minimum_sp)
        return result

    def publish(self,index,payload=bytes(range(216)),enabled=1):
        if type(index) is not int or not 0<=index<1914 or len(payload)!=216 or enabled not in (0,1):raise ValueError('Invalid publisher fixture')
        self.uc.mem_write(STATE+3,b'\x5a');self.uc.mem_write(STATE+6,bytes([enabled]))
        self.uc.mem_write(STATE+8,struct.pack('<H',216))
        self.uc.mem_write(INDICES+0xda,struct.pack('<H',index));self.uc.mem_write(SCRATCH,payload)
        self.uc.mem_write(RING,b'\xa5'*(1914*220))
        result=self.h.run(0x20066f18,(1,),budget=10000)
        ring=bytes(self.uc.mem_read(RING,1914*220))
        result.update(ring=ring,index_after=struct.unpack('<H',self.uc.mem_read(INDICES+0xda,2))[0],
                      fill_after=struct.unpack('<H',self.uc.mem_read(STATE+8,2))[0],
                      stack_extra_bytes=STACK+0xf000-self.minimum_sp)
        return result

    def arm(self,length=216):
        if type(length) is not int or not 0<=length<=0xffffffff:raise ValueError('Invalid write length')
        self.uc.mem_write(RECORD+0x24,struct.pack('<I',0x01234560))
        result=self.h.run(0x200497f0,(0x205072e0,length,0x12345678,0x87654321),stop=0x20186f00,budget=1000)
        result.update(record_state=bytes(self.uc.mem_read(RECORD,0x58)),
                      arguments=[self.uc.reg_read(r) for r in (self.a.UC_ARM_REG_R0,self.a.UC_ARM_REG_R1,
                                  self.a.UC_ARM_REG_R2,self.a.UC_ARM_REG_R3,self.a.UC_ARM_REG_LR)],
                      stack_extra_bytes=STACK+0xf000-self.minimum_sp)
        return result

    def storage(self):return bytes(self.uc.mem_read(CAPTURE,STORAGE_SIZE))
    def control(self):return struct.unpack('<2I',self.uc.mem_read(CONTROL,8))


def tool_hashes():
    from native_receive import tool_hashes as receive_hashes
    paths=('tools/native_wrappers.py','tools/native_capture.py','tools/native_transport.py',
           'prototype/native_receive/wrappers.S','prototype/native_receive/capture.S',
           'prototype/native_receive/transport.S')
    return dict(receive_hashes(),**{p:digest((ROOT/p).read_bytes()) for p in paths})


def _report(image):
    from emulate_platform import inputs
    data,_,app,_=inputs(image)
    code,entries=build_bundle()
    edits=patches(app)
    dma_rows=[]
    words=b''.join(struct.pack('<4I',((i*97)&65535)<<16|0xabcd,((65535-i*113)&65535)<<16|0x1234,
                               0xdeadbeef,0xcafefeed) for i in range(36))
    for bank in (0,1):
        baseline=WrapperTrial(app,'dma',False).dma(words,bank)
        trial=WrapperTrial(app,'dma');trial.configure(status=1)
        result=trial.dma(words,bank,(0xffffffff,1,0,0,32000,0x40))
        dma_rows.append({'bank':bank,'native_queues_unchanged':all(result[k]==baseline[k] for k in ('queue_a','queue_b','split')),
                         'baseline_instructions':baseline['instructions'],'patched_instructions':result['instructions'],
                         'snapshot_reads':result['observations'],'stack_below_fixture_sp':result['stack_extra_bytes'],
                         'first_record_hex':trial.storage()[16:192].hex()})
    carrier_rows=[]
    for index in (0,1913):
        trial=WrapperTrial(app,'carrier');trial.configure(status=2,count=512)
        result=trial.publish(index)
        carrier_rows.append({'index':index,'index_after':result['index_after'],'fill_after':result['fill_after'],
                             'instructions':result['instructions'],'stack_below_fixture_sp':result['stack_extra_bytes'],
                             'published_hex':result['ring'][index*220:(index+1)*220].hex(),
                             'transport_control':trial.control()})
    trial=WrapperTrial(app,'arm');arm=trial.arm()
    return {'schema_version':1,'image_sha256':digest(data),'application_sha256':digest(app),'bundle_sha256':digest(code),
            'bundle_bytes':len(code),'entries':{k:hex(v) for k,v in entries.items()},
            'edits':[{'address':hex(address),'bytes':len(data),'sha256':digest(data)} for address,data in edits],
            'dma':dma_rows,'carrier':carrier_rows,
            'arm':{'instructions':arm['instructions'],'native_submit_arguments':arm['arguments'],
                   'capture_status':struct.unpack_from('<I',trial.storage())[0],
                   'stopped_before_kernel_semaphore':True},
            'limitations':['DMA entry starts after acknowledgment/cache maintenance with a supplied original stack frame.',
                           'Timer/pending values are explicit read fixtures; no hardware clock or interrupt controller is modeled.',
                           'Recording submission stops before the native kernel semaphore call; no OS or file operation is executed.',
                           'Instruction counts and fixture stack depth are not hardware latency or available-stack measurements.',
                           'Native ring-to-file routing, initial/final partial buffers, and target capture remain to be qualified.',
                           'No firmware container or card image is emitted and no radio is accessed.']}


def report(image):
    from firmware import revision
    from recorder_interface import identity
    image=Path(image)
    initial,hashes,source=identity(image),tool_hashes(),revision()
    result=_report(image)
    if identity(image)!=initial or result['image_sha256']!=initial[0] or tool_hashes()!=hashes or revision()!=source:
        raise ValueError('Image/source changed during native wrapper analysis')
    return dict(result,image_sha256=initial[0],source_revision=source,tool_sha256=hashes,source_unchanged=True)


def main():
    import argparse
    from reporting import atomic_json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Output exists; choose a new evidence path')
    result=report(args.image)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(args.output,result)
    print(f'Native wrapper evidence: {args.output}')


if __name__=='__main__':main()
