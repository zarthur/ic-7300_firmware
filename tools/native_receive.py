#!/usr/bin/env python3
"""Exact-v1.42 offline receive data-path probes. Never accesses a radio."""
import argparse
import importlib.metadata
from pathlib import Path
import struct

from control_flow import walk
from emulate_platform import APP_BASE, RETURN, STACK, SOURCE, OUTPUT, engine, inputs
from firmware import digest, revision
from recorder_interface import APPLICATION_SHA256, identity
from reporting import atomic_json

QUEUE = 0x203fbdc0
STATE = 0x2039041c
RING = 0x204a0600
INDICES = 0x20507200
SCRATCH = 0x203fc76c
DMA = 0x203faf40
SPLIT = 0x203fc48a
COPY = (0x2017c710, 0x2017c750)
CLEAR = (0x2017c758, 0x2017c76a)
ROUTINES = {
    'file_read_command': (0x2006bfd4, 0x2006c0a0),
    'file_read_wrapper': (0x2006bc84, 0x2006bcac),
    'record_submit': (0x2006a354, 0x2006a370),
    'queue_free': (0x2005fae8, 0x2005fb14),
    'queue_count': (0x2005fb14, 0x2005fb28),
    'queue_push': (0x2005fb28, 0x2005fb64),
    'queue_pop': (0x2005fb64, 0x2005fbb4),
    'dma_handler': (0x20060614, 0x200606ec),
    'select_samples': (0x20066fc4, 0x200670c4),
    'publish_record_block': (0x20066f18, 0x20066fc4),
    'record_consumer': (0x20067254, 0x20067458),
    'record_enable': (0x200686a4, 0x200686b0),
    'record_format_writer': (0x20069008, 0x2006908c),
    'dma_setup': (0x2005ff1c, 0x2006003c),
    'audio_restart': (0x200605e4, 0x200605fc),
    'audio_start': (0x200605fc, 0x20060614),
    'timer_service': (0x20005b98, 0x20005c08),
    'timer_setup': (0x20005c08, 0x20005cac),
}


class Isolated:
    """Original instructions, private synthetic RAM, exact access/flow bounds."""
    def __init__(self, app, code_ranges, regions):
        if digest(app) != APPLICATION_SHA256:
            raise ValueError('Requires exact pinned v1.42 application')
        self.uc, self.u, self.a = engine()
        self.app = app
        self.ranges = code_ranges
        self.regions = regions
        self.count = 0
        self.accesses = []
        self.uc.mem_map(APP_BASE, (len(app)+4095)&~4095,
                        self.u.UC_PROT_READ | self.u.UC_PROT_EXEC)
        self.uc.mem_write(APP_BASE, app)
        pages = set()
        for lo, size in regions:
            for page in range(lo & ~4095, (lo+size+4095)&~4095, 4096):
                if page in pages:
                    continue
                pages.add(page)
                if APP_BASE <= page < APP_BASE + ((len(app)+4095)&~4095):
                    self.uc.mem_protect(page, 4096, self.u.UC_PROT_READ | self.u.UC_PROT_WRITE)
                else:
                    self.uc.mem_map(page, 4096, self.u.UC_PROT_READ | self.u.UC_PROT_WRITE)
        self.uc.hook_add(self.u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ | self.u.UC_HOOK_MEM_WRITE, self._memory)

    def _code(self, uc, address, size, unused):
        if not any(lo <= address and address+size <= hi for lo, hi in self.ranges):
            raise ValueError(f'Unreviewed receive execution: {address:#x}')
        self.count += 1

    def _memory(self, uc, access, address, size, value, unused):
        if STACK <= address and address+size <= STACK+0x10000:
            return
        if any(lo <= address and address+size <= lo+n for lo, n in self.regions):
            self.accesses.append((access, address, size))
            return
        if access == self.u.UC_MEM_READ and APP_BASE <= address and address+size <= APP_BASE+len(self.app):
            return  # Pinned original literal pool, never writable unless declared above.
        raise ValueError(f'Receive access outside exact bounds: {address:#x}+{size}')

    def run(self, entry, args=(), stop=RETURN, budget=20000):
        for reg, value in zip((self.a.UC_ARM_REG_R0,self.a.UC_ARM_REG_R1,
                               self.a.UC_ARM_REG_R2,self.a.UC_ARM_REG_R3),args):
            self.uc.reg_write(reg,value)
        self.uc.reg_write(self.a.UC_ARM_REG_SP, STACK+0xf000)
        self.uc.reg_write(self.a.UC_ARM_REG_LR, RETURN)
        before = self.count
        try:
            self.uc.emu_start(entry, stop, timeout=1000000, count=budget)
        except self.u.UcError as exc:
            raise ValueError(f'Receive emulation stopped: {exc}') from exc
        if self.uc.reg_read(self.a.UC_ARM_REG_PC) != stop:
            raise ValueError('Receive execution did not reach boundary within limits')
        return {'instructions':self.count-before,
                'r0':self.uc.reg_read(self.a.UC_ARM_REG_R0)}


def queue_probe(app, write_index, read_index, operation, payload=None):
    if type(write_index) is not int or type(read_index) is not int or not 0 <= write_index < 8 or not 0 <= read_index < 8:
        raise ValueError('Queue indices must be in 0..7')
    if operation not in ('count', 'push', 'pop'):
        raise ValueError('Unknown queue operation')
    if payload is None:
        payload = bytes(range(72))
    if not isinstance(payload, bytes) or len(payload) != 72:
        raise ValueError('Require 72-byte synthetic payload')
    h = Isolated(app, [(0x2005fae8,0x2005fbb4), COPY, CLEAR,
                       (0x2017c750,0x2017c758)], [(QUEUE,0x242),(SOURCE,72),(OUTPUT,72)])
    before = bytes((i*17+3)&255 for i in range(0x240)) + bytes((write_index,read_index))
    h.uc.mem_write(QUEUE,before)
    h.uc.mem_write(SOURCE,payload)
    h.uc.mem_write(OUTPUT,b'\xa5'*72)
    entry,args = {'count':(0x2005fb14,()), 'push':(0x2005fb28,(SOURCE,)),
                  'pop':(0x2005fb64,(OUTPUT,))}[operation]
    result = h.run(entry,args)
    after = bytes(h.uc.mem_read(QUEUE,0x242))
    result.update(write_index=after[0x240],read_index=after[0x241],
                  output_hex=bytes(h.uc.mem_read(OUTPUT,72)).hex(),
                  changed_queue_offsets=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b],
                  slot_hex=after[write_index*72:(write_index+1)*72].hex())
    return result


def select_probe(app, mode, samples):
    if type(mode) is not int or not 0 <= mode <= 4 or not isinstance(samples,bytes) or not samples or len(samples)%2 or len(samples)>4096:
        raise ValueError('Require mode 0..4 and 1..2048 synthetic 16-bit samples')
    h=Isolated(app,[(0x20066fc4,0x200670c4)],[(SOURCE,len(samples)),(OUTPUT,len(samples))])
    h.uc.mem_write(SOURCE,samples);h.uc.mem_write(OUTPUT,b'\xa5'*len(samples))
    r=h.run(0x20066fc4,(OUTPUT,SOURCE,len(samples)//2,mode))
    writes=[(address,size) for access,address,size in h.accesses if access==h.u.UC_MEM_WRITE and OUTPUT<=address<OUTPUT+len(samples)]
    length=max((address+size-OUTPUT for address,size in writes),default=0)
    r.update(output_hex=bytes(h.uc.mem_read(OUTPUT,length)).hex(),output_bytes=length)
    return r


def split_probe(app, bank, words):
    if bank not in (0,1) or not isinstance(words,bytes) or len(words)!=576:
        raise ValueError('Require bank 0/1 and 576-byte DMA fixture')
    # Starts AFTER status acknowledgment/cache maintenance, stops BEFORE queue calls.
    h=Isolated(app,[(0x20060690,0x200606d4)],[(DMA,1152),(SPLIT,144)])
    h.uc.mem_write(DMA+576*bank,words)
    h.uc.reg_write(h.a.UC_ARM_REG_R2,DMA+576*bank)
    r=h.run(0x20060690,stop=0x200606d4)
    r.update(stream_a_hex=bytes(h.uc.mem_read(SPLIT,72)).hex(),
             stream_b_hex=bytes(h.uc.mem_read(SPLIT+72,72)).hex(),
             modeled_prestate='selected DMA bank after cache maintenance; no DMA/cache/MMIO execution')
    return r


def publish_probe(app,index,enabled,tag,payload):
    if type(index) is not int or not 0 <= index < 1914 or enabled not in (0,1) or type(tag) is not int or not 0 <= tag <= 255 or not isinstance(payload,bytes) or len(payload)!=216:
        raise ValueError('Invalid synthetic publication fixture')
    h=Isolated(app,[(0x20066f18,0x20066fc4),COPY,CLEAR],
               [(STATE,0x10),(INDICES,0xdc),(SCRATCH,216),(RING,1914*220)])
    h.uc.mem_write(STATE+3,b'\x5a');h.uc.mem_write(STATE+6,bytes([enabled]));h.uc.mem_write(STATE+8,struct.pack('<H',216))
    h.uc.mem_write(INDICES+0xda,struct.pack('<H',index));h.uc.mem_write(SCRATCH,payload)
    h.uc.mem_write(RING,b'\xa5'*(1914*220))
    r=h.run(0x20066f18,(tag,))
    ring=bytes(h.uc.mem_read(RING,1914*220))
    r.update(index_after=struct.unpack('<H',h.uc.mem_read(INDICES+0xda,2))[0],
             fill_after=struct.unpack('<H',h.uc.mem_read(STATE+8,2))[0],
             published_hex=ring[index*220:(index+1)*220].hex(),
             next_slot_hex=ring[((index+1)%1914)*220:((index+1)%1914+1)*220].hex(),
             changed_slots=[i for i in range(1914) if ring[i*220:(i+1)*220]!=b'\xa5'*220])
    return r


def meter_probe(app, samples, previous_peak=0, empty=False):
    if not isinstance(samples,bytes) or len(samples)!=72 or type(previous_peak) is not int or not 0 <= previous_peak <= 32767 or type(empty) is not bool:
        raise ValueError('Require 36 synthetic PCM16 samples and a valid previous peak')
    queue, peak = 0x203fc002, 0x2039024e
    h = Isolated(app, [(0x2004536c,0x20045424),(0x2005fbe0,0x2005fc24),
                       (0x2005fc60,0x2005fcb4),COPY,CLEAR,(0x2017c750,0x2017c758)],
                 [(queue,0x243),(peak,2)])
    h.uc.mem_write(queue,samples)
    h.uc.mem_write(queue+0x240,bytes((0 if empty else 1,7,0)))
    h.uc.mem_write(peak,struct.pack('<H',previous_peak))
    result = h.run(0x2004536c)
    result.update(peak=struct.unpack('<H',h.uc.mem_read(peak,2))[0],
                  cursors=list(h.uc.mem_read(queue+0x240,3)),
                  limitation='Peak-meter consumer proves cursor use, not physical channel identity')
    return result


def format_writer_probe(app):
    h = Isolated(app, [(0x20068fe8, 0x2006908c), (0x2017c860, 0x2017c872)],
                 [(OUTPUT, 24)])
    h.uc.mem_write(OUTPUT, b'\xa5' * 24)
    result = h.run(0x20069008, (OUTPUT,))
    chunk = bytes(h.uc.mem_read(OUTPUT, 24))
    size, encoding, channels, rate, byte_rate, align, bits = struct.unpack('<IHHIIHH', chunk[4:])
    result.update(chunk_hex=chunk.hex(), size=size, encoding=encoding, channels=channels,
                  rate=rate, byte_rate=byte_rate, block_align=align, bits=bits,
                  limitation='Stored recording header; not a measurement of the external sample clock')
    return result


def tool_hashes():
    names=('native_receive.py','recorder_interface.py','control_flow.py','emulate_platform.py','firmware.py','reporting.py')
    out={name:digest(Path(__file__).with_name(name).read_bytes()) for name in names}
    out['research/targets.json']=digest((Path(__file__).resolve().parents[1]/'research/targets.json').read_bytes())
    return out


def _report(image):
    data,_,app,_=inputs(image)
    samples=struct.pack('<36h',*[-32768+i*1800 for i in range(36)])
    words=b''.join(struct.pack('<4I',((i*1700)&65535)<<16|0xabcd,((65535-i*1300)&65535)<<16|0x1234,0xdeadbeef,0xcafefeed) for i in range(36))
    result={'schema_version':1,'image_sha256':digest(data),'application_sha256':digest(app),
            'dependencies':{n:importlib.metadata.version(n) for n in ('capstone','unicorn')},
            'record_format_writer':format_writer_probe(app),
            'second_queue_meter':{name:meter_probe(app,struct.pack('<36h',*values),prior,empty) for name,values,prior,empty in [
                ('negative_full_scale',[-32768]+[0]*35,0,False),('hold_peak',[12]*36,100,False),
                ('silence',[0]*36,0,False),('empty',[-32768]*36,123,True)]},
            'static_flows':{n:walk(app,APP_BASE,*bounds) for n,bounds in ROUTINES.items()},
            'queue_cases':{f'{op}_{w}_{r}':queue_probe(app,w,r,op) for op in ('count','pop','push') for w in range(8) for r in range(8)},
            'sample_selection':{str(mode):select_probe(app,mode,samples) for mode in range(5)},
            'dma_split':{str(bank):split_probe(app,bank,words) for bank in (0,1)},
            'record_publication':{f'{index}_{enabled}':publish_probe(app,index,enabled,1,bytes(range(216))) for index in (0,1913) for enabled in (0,1)},
            'limitations':['Original queue/copy/clear/sample-selection/publication instructions execute with private synthetic RAM.',
                           'DMA split executes only the bounded extraction block with supplied post-cache register state.',
                           'No physical DMA, timing, cache coherency, interrupt concurrency or live channel identity is proven.',
                           'Native adapter readiness remains unproven until remaining interface properties are resolved.']}
    return result


def report(image):
    image = Path(image)
    initial, hashes, source = identity(image), tool_hashes(), revision()
    result = _report(image)
    if identity(image)!=initial or result['image_sha256']!=initial[0] or hashes!=tool_hashes() or source!=revision():
        raise ValueError('Image/source changed during native receive analysis')
    return dict(result,source_revision=source,tool_sha256=hashes,source_unchanged=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('image',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Output exists; choose a new evidence path')
    result=report(args.image);args.output.parent.mkdir(parents=True,exist_ok=True);atomic_json(args.output,result)
    print(f'Native receive evidence: {args.output}')

if __name__=='__main__':main()
