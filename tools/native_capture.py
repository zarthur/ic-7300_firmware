#!/usr/bin/env python3
"""Build and exercise the original receive capture core offline; no firmware output."""
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from emulate_platform import RETURN, STACK, engine

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'prototype/native_receive/capture.S'
CAPACITY=512
RECORD_SIZE=176
CONTROL_SIZE=16
STORAGE_SIZE=CONTROL_SIZE+CAPACITY*RECORD_SIZE
CODE=0x01000000
STATE=0x02000010
SAMPLES=0x03000002  # Native extracted arrays are halfword, not word, aligned.
OBSERVATIONS=0x04000000


def text_section(data):
    """Accept little-endian ARM ELF32 relocatable objects with standalone .text."""
    if len(data)<52 or data[:7]!=b'\x7fELF\x01\x01\x01':raise ValueError('Require ELF32 little-endian object')
    header=struct.unpack_from('<HHIIIIIHHHHHH',data,16)
    kind,machine,version,entry,phoff,shoff,flags,ehsize,phsize,phnum,shsize,shnum,shstr=header
    if (kind,machine,version,ehsize,phnum,shsize)!=(1,40,1,52,0,40) or not 0<shstr<shnum:
        raise ValueError('Unexpected ARM relocatable object layout')
    if shoff+shnum*40>len(data):raise ValueError('Truncated section table')
    sections=[struct.unpack_from('<10I',data,shoff+i*40) for i in range(shnum)]
    def contents(section):
        offset,size=section[4:6]
        if offset+size>len(data):raise ValueError('Truncated section')
        return data[offset:offset+size]
    names=contents(sections[shstr])
    matches=[]
    for i,section in enumerate(sections):
        name=section[0]
        if name>=len(names):raise ValueError('Invalid section name')
        end=names.find(b'\0',name)
        if end<0:raise ValueError('Unterminated section name')
        if names[name:end]==b'.text':matches.append((i,section))
    if len(matches)!=1:raise ValueError('Require one text section')
    index,section=matches[0]
    if section[1]!=1 or section[2]!=6 or section[8]!=4:raise ValueError('Unexpected text section attributes')
    for i,other in enumerate(sections):
        if other[1] in (4,9) and other[5]:raise ValueError('Relocations are not permitted')
        if i!=index and other[2]&2 and other[5]:raise ValueError('Extra allocated section')
    code=contents(section)
    if not code or len(code)>8192 or len(code)%4:raise ValueError('Invalid capture code length')
    return code


def build_core(source=None):
    compiler=shutil.which('clang')
    if not compiler:raise ValueError('clang is required to assemble the ARM capture core')
    with tempfile.TemporaryDirectory() as directory:
        obj=Path(directory)/'capture.o'
        subprocess.run([compiler,'--target=armv7-none-eabi','-c',str(SOURCE if source is None else source),'-o',str(obj)],
                       check=True,capture_output=True,timeout=30)
        return text_section(obj.read_bytes())


class CaptureTrial:
    """Strict synthetic execution; caller-controlled snapshots are not timer models."""
    def __init__(self,code,status=1,count=0):
        self.uc,self.u,self.a=engine()
        self.code=code
        self.uc.mem_map(CODE,0x2000,self.u.UC_PROT_READ|self.u.UC_PROT_EXEC)
        self.uc.mem_write(CODE,code)
        self.uc.mem_map(STATE & ~4095,0x17000)
        self.uc.mem_map(SAMPLES & ~4095,4096)
        self.uc.mem_map(OBSERVATIONS,4096)
        self.uc.mem_write(STATE-4,b'\xa5'*(STORAGE_SIZE+8))
        self.uc.mem_write(STATE,struct.pack('<4I',status,count,0,0))
        self.instructions=0
        self.writes=[]
        self.uc.hook_add(self.u.UC_HOOK_CODE,self._code)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ|self.u.UC_HOOK_MEM_WRITE,self._memory)

    def _code(self,uc,address,size,user):
        if not CODE<=address or address+size>CODE+len(self.code):raise ValueError('Capture escaped core')
        self.instructions+=1

    def _memory(self,uc,access,address,size,value,user):
        write=access==self.u.UC_MEM_WRITE
        if STACK<=address and address+size<=STACK+0x10000:return
        if STATE<=address and address+size<=STATE+STORAGE_SIZE:
            if write:self.writes.append((address,size))
            return
        if not write and ((SAMPLES<=address and address+size<=SAMPLES+144) or
                          (OBSERVATIONS<=address and address+size<=OBSERVATIONS+28)):return
        raise ValueError(f'Capture access outside contract: {address:#x}+{size}, write={write}')

    def run(self,samples,observations):
        if not isinstance(samples,bytes) or len(samples)!=144 or len(observations)!=7:
            raise ValueError('Require 144 sample bytes and seven observation words')
        raw=struct.pack('<7I',*observations)
        self.uc.mem_write(SAMPLES,samples)
        self.uc.mem_write(OBSERVATIONS,raw)
        a=self.a
        preserved=[a.UC_ARM_REG_R4,a.UC_ARM_REG_R5,a.UC_ARM_REG_R6,a.UC_ARM_REG_R7,
                   a.UC_ARM_REG_R8,a.UC_ARM_REG_R9,a.UC_ARM_REG_R10,a.UC_ARM_REG_R11]
        before=[0x12345670+i for i in range(len(preserved))]
        for reg,value in zip(preserved,before):self.uc.reg_write(reg,value)
        for reg,value in ((a.UC_ARM_REG_R0,STATE),(a.UC_ARM_REG_R1,SAMPLES),
                          (a.UC_ARM_REG_R2,OBSERVATIONS),(a.UC_ARM_REG_SP,STACK+0xf000),
                          (a.UC_ARM_REG_LR,RETURN)):
            self.uc.reg_write(reg,value)
        self.instructions=0;self.writes=[]
        self.uc.emu_start(CODE,RETURN,count=1000,timeout=1000000)
        if self.uc.reg_read(a.UC_ARM_REG_PC)!=RETURN:raise ValueError('Capture did not return within budget')
        if [self.uc.reg_read(r) for r in preserved]!=before or self.uc.reg_read(a.UC_ARM_REG_SP)!=STACK+0xf000:
            raise ValueError('Capture violated preserved register/stack contract')
        if bytes(self.uc.mem_read(STATE-4,4))+bytes(self.uc.mem_read(STATE+STORAGE_SIZE,4))!=b'\xa5'*8:
            raise ValueError('Capture damaged storage guards')
        if bytes(self.uc.mem_read(SAMPLES,144))!=samples or bytes(self.uc.mem_read(OBSERVATIONS,28))!=raw:
            raise ValueError('Capture changed its inputs')
        return self.uc.reg_read(a.UC_ARM_REG_R0)

    def storage(self):return bytes(self.uc.mem_read(STATE,STORAGE_SIZE))


def decode_storage(data):
    """Decode stable core storage, retaining raw observations without clock claims."""
    if not isinstance(data,bytes) or len(data)!=STORAGE_SIZE:
        raise ValueError('Require an exact capture storage image')
    status,count,reserved0,reserved1=struct.unpack_from('<4I',data)
    if status not in (0,1,2) or count>CAPACITY or reserved0 or reserved1:
        raise ValueError('Invalid or unstable capture control')
    if (status==2)!=(count==CAPACITY) or (status==0 and count):
        raise ValueError('Inconsistent capture status and count')
    records=[]
    for i in range(count):
        words=struct.unpack_from('<8I72h',data,CONTROL_SIZE+i*RECORD_SIZE)
        if words[0]!=i:raise ValueError('Non-contiguous capture sequence')
        records.append({'sequence':i,'observations':list(words[1:8]),
                        'stream_a':list(words[8:44]),'stream_b':list(words[44:80])})
    return {'status':status,'count':count,'records':records}
