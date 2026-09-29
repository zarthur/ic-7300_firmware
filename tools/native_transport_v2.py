#!/usr/bin/env python3
"""Offline v2 recorder carrier; recover full or explicitly aborted captures."""
from pathlib import Path
import struct

from emulate_platform import STACK, engine
from native_transport import TransportTrial as LegacyTransportTrial, checksum
from native_capture import build_core
from native_capture_v2 import decode_storage, STORAGE_SIZE

FRAME_SIZE=216
PAYLOAD_SIZE=192
FRAME_COUNT=(STORAGE_SIZE+PAYLOAD_SIZE-1)//PAYLOAD_SIZE
MAGIC=b'IC73RX02'
CODE=0x01000000
CAPTURE=0x02000010
CONTROL=0x03000010
ORIGINAL=0x04000010
DESTINATION=0x05000010
SOURCE=Path(__file__).resolve().parents[1]/'prototype/native_receive/transport_v2.S'


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
    if decoded['status'] not in (2,5,6):raise ValueError('Carrier does not contain a frozen capture')
    return result


class TransportTrial(LegacyTransportTrial):
    """Reuse the v1 calling convention checks; v2 has distinct code/storage bounds."""
    def __init__(self,capture,index=0,status=0):
        if not isinstance(capture,bytes) or len(capture)!=STORAGE_SIZE:raise ValueError('Invalid capture storage')
        self.code=build_core(SOURCE)
        self.uc,self.u,self.a=engine()
        for address,size in ((CODE,4096),(CAPTURE&~4095,0x1d000),(CONTROL&~4095,4096),
                             (ORIGINAL&~4095,4096),(DESTINATION&~4095,4096)):
            self.uc.mem_map(address,size)
        self.uc.mem_write(CODE,self.code)
        self.uc.mem_write(CAPTURE,capture)
        self.uc.mem_write(CONTROL,struct.pack('<2I',index,status))
        self.uc.hook_add(self.u.UC_HOOK_CODE,self._code)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ|self.u.UC_HOOK_MEM_WRITE,self._memory)
        self.instructions=0

    def _memory(self,uc,access,address,size,value,user):
        if STACK<=address and address+size<=STACK+0x10000:return
        write=access==self.u.UC_MEM_WRITE
        for lo,n,writable in ((CAPTURE,STORAGE_SIZE,False),(CONTROL,8,True),
                               (ORIGINAL,216,False),(DESTINATION,216,True)):
            if lo<=address and address+size<=lo+n and (not write or writable):return
        raise ValueError('Transport accessed memory outside its contract')

