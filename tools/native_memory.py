#!/usr/bin/env python3
"""Exact-image offline allocator and startup-range evidence; no target access."""
import argparse
import importlib.metadata
from pathlib import Path
import struct

from control_flow import walk
from emulate_platform import APP_BASE, inputs
from firmware import digest, revision
from native_receive import Isolated, COPY, tool_hashes as receive_hashes
from recorder_interface import identity
from reporting import atomic_json

HEAP = 0x20587b64
LIMIT = 0x205dcb60
SPAN = (LIMIT-HEAP) & ~7
STATE = 0x20390b00
ALLOC = 0x20186230
FREE = 0x20184b5c


class HeapTrial:
    """Sequential original allocator calls on an initially unused synthetic heap."""
    def __init__(self, app):
        self.h = Isolated(app, [(ALLOC,0x20186270), (0x20186bc8,0x20186c14),
                               (FREE,0x20184bb4), COPY], [(HEAP,SPAN),(STATE,8)])
        self.h.uc.mem_write(STATE,bytes(8))
        self.live = {}

    def chain(self):
        head, initialized = struct.unpack('<II',self.h.uc.mem_read(STATE,8))
        blocks = []
        seen = set()
        while head:
            if head in seen or not HEAP <= head <= HEAP+SPAN-8:
                raise ValueError('Invalid synthetic free-list pointer')
            seen.add(head)
            size, following = struct.unpack('<II',self.h.uc.mem_read(head,8))
            if size < 8 or size%8 or head+size > HEAP+SPAN:
                raise ValueError('Invalid synthetic free-list span')
            if following and following < head+size:
                raise ValueError('Overlapping or unsorted synthetic free list')
            blocks.append({'offset':head-HEAP,'size':size})
            head = following
        return {'initialized':initialized,'free_blocks':blocks,
                'free_bytes':sum(b['size'] for b in blocks)}

    def allocate(self, name, size):
        # These are diagnostic stimuli, not validation added to the original API.
        if not isinstance(name,str) or not name or name in self.live or type(size) is not int or not 1 <= size <= 1024*1024:
            raise ValueError('Invalid or duplicate synthetic allocation')
        result = self.h.run(ALLOC|1,(size,))
        pointer = result['r0']
        if pointer:
            if pointer%8 or not HEAP+4 <= pointer or pointer+size > HEAP+SPAN:
                raise ValueError('Original allocator returned an out-of-bounds block')
            for old, payload in self.live.values():
                if pointer < old+len(payload) and old < pointer+size:
                    raise ValueError('Original allocator returned overlapping live blocks')
            payload = bytes([len(self.live)+1])*size
            self.h.uc.mem_write(pointer,payload)
            self.live[name] = (pointer,payload)
        self.check_payloads()
        return dict(result,requested=size,pointer=hex(pointer),state=self.chain())

    def release(self, name):
        if name not in self.live:
            raise ValueError('Only a live synthetic allocation can be released')
        pointer, _ = self.live.pop(name)
        result = self.h.run(FREE|1,(pointer,))
        self.check_payloads()
        return dict(result,released=hex(pointer),state=self.chain())

    def check_payloads(self):
        for pointer,payload in self.live.values():
            if bytes(self.h.uc.mem_read(pointer,len(payload))) != payload:
                raise ValueError('Live allocation contents changed')


def sequence_probe(app):
    trial = HeapTrial(app)
    results = []
    for name,size in [('a',4096),('b',4096),('c',72)]:
        results.append(trial.allocate(name,size))
    results.append(trial.release('b'))
    results.append(trial.allocate('replacement',4096))
    results.append(trial.allocate('codec_reservation',393216))
    for name in ('a','c','replacement'):
        results.append(trial.release(name))
    results.append(trial.allocate('entire_payload',SPAN-4))
    results.append(trial.allocate('exhausted',1))
    results.append(trial.release('entire_payload'))
    return results


def startup_ranges(app):
    table = 0x20360aac
    entries = []
    for i in range(3):
        source,destination,size,entry = struct.unpack_from('<4I',app,table-APP_BASE+i*16)
        entries.append(dict(source=hex(source),destination=hex(destination),size=size,entry=hex(entry)))
    padding_start,padding_end = 0x2036166c,0x20390000
    padding = app[padding_start-APP_BASE:padding_end-APP_BASE]
    return {'initialization_entries':entries,'decoded_end':hex(APP_BASE+len(app)),
            'padding_candidate':{'start':hex(padding_start),'end':hex(padding_end),
                                 'bytes':len(padding),'all_ff':all(b==255 for b in padding),
                                 'runtime_ownership_established':False},
            'limitation':'Padding content and scatter ranges alone do not prove absence of runtime aliases or safe executable placement.'}


def tool_hashes():
    return dict(receive_hashes(), **{'native_memory.py':digest(Path(__file__).read_bytes())})


def _report(image):
    data,_,app,_ = inputs(image)
    return {'schema_version':1,'image_sha256':digest(data),'application_sha256':digest(app),
            'dependencies':{n:importlib.metadata.version(n) for n in ('capstone','unicorn')},
            'heap':{'base':hex(HEAP),'limit':hex(LIMIT),'managed_bytes':SPAN,
                    'maximum_single_payload_in_unused_fixture':SPAN-4,
                    'available_on_radio':None},
            'sequence':sequence_probe(app),'startup':startup_ranges(app),
            'static_flows':{name:walk(app,APP_BASE,start,end,mode='Thumb') for name,start,end in
                            [('allocate',ALLOC,0x20186270),('allocate_core',0x20186bc8,0x20186c14),('free',FREE,0x20184bb4)]},
            'limitations':['Heap is initially unused synthetic RAM, not a target memory measurement.',
                           'Calls are sequential; locking, interrupt safety and concurrent callers are not proven.',
                           'No capture allocation or executable insertion has been installed on the radio.']}


def report(image):
    image = Path(image)
    initial,hashes,source = identity(image),tool_hashes(),revision()
    result = _report(image)
    if identity(image)!=initial or result['image_sha256']!=initial[0] or hashes!=tool_hashes() or source!=revision():
        raise ValueError('Image/source changed during native memory analysis')
    return dict(result,source_revision=source,tool_sha256=hashes,source_unchanged=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new evidence path')
    result=report(args.image)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    atomic_json(args.output,result)
    print(f'Native memory evidence: {args.output}')


if __name__ == '__main__':
    main()
