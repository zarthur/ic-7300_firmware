#!/usr/bin/env python3
"""Offline recorder-carrier core and strict recovery of one complete capture."""
from pathlib import Path
import struct

from emulate_platform import RETURN, STACK, engine, execute
from native_capture import build_core, decode_storage, STORAGE_SIZE

FRAME_SIZE=216
PAYLOAD_SIZE=192
FRAME_COUNT=(STORAGE_SIZE+PAYLOAD_SIZE-1)//PAYLOAD_SIZE
MAGIC=b'IC73RX01'
CODE=0x01000000
CAPTURE=0x02000010
CONTROL=0x03000010
ORIGINAL=0x04000010
DESTINATION=0x05000010
SOURCE=Path(__file__).resolve().parents[1]/'prototype/native_receive/transport.S'


def checksum(data):
    value=0x811c9dc5
    for byte in data:value=((value^byte)*0x01000193)&0xffffffff
    return value


def recover(data):
    """Require all frames in order in ONE file; never merge separate captures."""
    if not isinstance(data,bytes):raise ValueError('Require immutable carrier bytes')
    chunks=[];position=0
    while True:
        found=data.find(MAGIC,position)
        if found<0:break
        if found+FRAME_SIZE>len(data):raise ValueError('Truncated diagnostic frame')
        total,offset,length,expected=struct.unpack_from('<4I',data,found+8)
        wanted=len(chunks)*PAYLOAD_SIZE
        if total!=STORAGE_SIZE or offset!=wanted or wanted>=STORAGE_SIZE or length!=min(PAYLOAD_SIZE,total-offset):
            raise ValueError('Invalid, duplicate or missing diagnostic frame')
        payload=data[found+24:found+24+length]
        if checksum(payload)!=expected:raise ValueError('Diagnostic frame checksum mismatch')
        if any(data[found+24+length:found+FRAME_SIZE]):raise ValueError('Nonzero diagnostic frame padding')
        chunks.append(payload);position=found+FRAME_SIZE
    if len(chunks)!=FRAME_COUNT:raise ValueError('Incomplete diagnostic capture')
    result=b''.join(chunks)
    decoded=decode_storage(result)
    if decoded['status']!=2:raise ValueError('Carrier does not contain a full capture')
    return result


class TransportTrial:
    def __init__(self,capture,index=0,status=0):
        if not isinstance(capture,bytes) or len(capture)!=STORAGE_SIZE:raise ValueError('Invalid capture storage')
        self.code=build_core(SOURCE)
        self.uc,self.u,self.a=engine()
        for address,size in ((CODE,4096),(CAPTURE&~4095,0x17000),(CONTROL&~4095,4096),
                             (ORIGINAL&~4095,4096),(DESTINATION&~4095,4096)):
            self.uc.mem_map(address,size)
        self.uc.mem_write(CODE,self.code)
        self.uc.mem_write(CAPTURE,capture)
        self.uc.mem_write(CONTROL,struct.pack('<2I',index,status))
        self.uc.hook_add(self.u.UC_HOOK_CODE,self._code)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ|self.u.UC_HOOK_MEM_WRITE,self._memory)
        self.instructions=0

    def _code(self,uc,address,size,user):
        if not CODE<=address or address+size>CODE+len(self.code):raise ValueError('Transport escaped core')
        self.instructions+=1

    def _memory(self,uc,access,address,size,value,user):
        if STACK<=address and address+size<=STACK+0x10000:return
        write=access==self.u.UC_MEM_WRITE
        for lo,n,writable in ((CAPTURE,STORAGE_SIZE,False),(CONTROL,8,True),
                               (ORIGINAL,216,False),(DESTINATION,216,True)):
            if lo<=address and address+size<=lo+n and (not write or writable):return
        raise ValueError('Transport accessed memory outside its contract')

    def run(self,original):
        if not isinstance(original,bytes) or len(original)!=216:raise ValueError('Require original 216-byte payload')
        a=self.a
        self.uc.mem_write(ORIGINAL,original)
        self.uc.mem_write(DESTINATION-4,b'\xa5'*224)
        preserved=[a.UC_ARM_REG_R4,a.UC_ARM_REG_R5,a.UC_ARM_REG_R6,a.UC_ARM_REG_R7,
                   a.UC_ARM_REG_R8,a.UC_ARM_REG_R9,a.UC_ARM_REG_R10,a.UC_ARM_REG_R11]
        values=list(range(0x12345670,0x12345678))
        for reg,value in zip(preserved,values):self.uc.reg_write(reg,value)
        for reg,value in ((a.UC_ARM_REG_R0,DESTINATION),(a.UC_ARM_REG_R1,ORIGINAL),
                          (a.UC_ARM_REG_R2,CAPTURE),(a.UC_ARM_REG_R3,CONTROL),
                          (a.UC_ARM_REG_SP,STACK+0xf000),(a.UC_ARM_REG_LR,RETURN)):
            self.uc.reg_write(reg,value)
        self.instructions=0
        execute(self.uc,CODE,budget=2000)
        if self.uc.reg_read(a.UC_ARM_REG_R0)!=DESTINATION or self.uc.reg_read(a.UC_ARM_REG_SP)!=STACK+0xf000:
            raise ValueError('Transport violated return/stack contract')
        if [self.uc.reg_read(r) for r in preserved]!=values:raise ValueError('Transport damaged preserved registers')
        output=bytes(self.uc.mem_read(DESTINATION-4,224))
        if output[:4]+output[-4:]!=b'\xa5'*8:raise ValueError('Transport damaged output guards')
        return output[4:-4]

    def control(self):return struct.unpack('<2I',self.uc.mem_read(CONTROL,8))
