#!/usr/bin/env python3
"""Offline startup mapping and padding evidence for a bounded receive diagnostic."""
import argparse
from pathlib import Path
import struct

from emulate_platform import APP_BASE, OUTPUT, inputs
from firmware import digest, revision
from native_memory import startup_ranges
from native_receive import Isolated, tool_hashes as receive_hashes
from recorder_interface import identity
from reporting import atomic_json

PADDING = (0x2036166c, 0x20390000)
TABLE = 0x20000000


def section_fields(descriptor):
    if type(descriptor) is not int or not 0 <= descriptor <= 0xffffffff:
        raise ValueError('Require an unsigned 32-bit descriptor')
    if descriptor & 3 != 2 or descriptor & (1 << 18):
        raise ValueError('Require a regular short-descriptor section')
    return {'physical_base':hex(descriptor & 0xfff00000),
            'execute_never':bool(descriptor & 16),
            'access_permissions':((descriptor >> 10)&3) | ((descriptor >> 13)&4),
            'domain':(descriptor >> 5)&15,
            'tex':(descriptor >> 12)&7,'cacheable_bit':bool(descriptor & 8),
            'bufferable_bit':bool(descriptor & 4)}


def mapping_probe(app):
    # Stop before TTBR0/DACR writes. Actual MMU/cache behavior is not emulated.
    h=Isolated(app,[(0x200b8d2c,0x200b8fe8),(0x200b86d4,0x200b8d2c),
                    (0x200b9120,0x200b9214)],
                   [(TABLE,0x4000),(0x20390788,0x38),(0x2080c400,0x400)])
    result=h.run(0x200b8d2c,stop=0x200b8fe8,budget=100000)
    table=bytes(h.uc.mem_read(TABLE,0x4000))
    descriptors=struct.unpack('<4096I',table)
    index=PADDING[0] >> 20
    target=descriptors[index]
    fields=section_fields(target)
    aliases=[]
    for i,value in enumerate(descriptors):
        if value & 3 == 2 and not value & (1 << 18) and value & 0xfff00000 == target & 0xfff00000:
            aliases.append(hex(i << 20))
    result.update(table_sha256=digest(table),padding_section=hex(target),
                  application_section=hex(descriptors[APP_BASE >> 20]),
                  same_attributes_as_application=(target & 0xfffff)==(descriptors[APP_BASE >> 20]&0xfffff),
                  fields=fields,regular_section_aliases=aliases,
                  hardware_mapping_executed=False)
    return result


def zero_helper_probe(app, size):
    if type(size) is not int or size not in (4,16,72,4096):
        raise ValueError('Require a reviewed nonzero word-aligned fixture size')
    h=Isolated(app,[(0x20186488,0x20186496)],[(OUTPUT-4,size+8)])
    h.uc.mem_write(OUTPUT-4,b'\xa5'*(size+8))
    # The original scatter table has a padding address as this unused source.
    reads=[]
    h.uc.hook_add(h.u.UC_HOOK_MEM_READ,lambda uc,access,addr,n,value,user: reads.append(hex(addr)),
                  begin=PADDING[0],end=PADDING[1]-1)
    result=h.run(0x20186489,(PADDING[0],OUTPUT,size))
    memory=bytes(h.uc.mem_read(OUTPUT-4,size+8))
    result.update(size=size,all_zero=memory[4:-4]==bytes(size),
                  guards_preserved=memory[:4]+memory[-4:]==b'\xa5'*8,
                  source_reads=reads)
    return result


def tool_hashes():
    return dict(receive_hashes(),**{name:digest(Path(__file__).with_name(name).read_bytes())
                                  for name in ('native_memory.py','native_placement.py')})


def _report(image):
    data,_,app,_=inputs(image)
    mapping=mapping_probe(app)  # Exact application gate precedes all interpretation.
    startup=startup_ranges(app)
    overlaps=[]
    for entry in startup['initialization_entries']:
        lo=int(entry['destination'],16); hi=lo+entry['size']
        if lo<PADDING[1] and PADDING[0]<hi:overlaps.append(entry)
    return {'schema_version':1,'image_sha256':digest(data),'application_sha256':digest(app),
            'mapping':mapping,'startup':startup,'scatter_destination_overlaps':overlaps,
            'zero_helper':[zero_helper_probe(app,n) for n in (4,16,72,4096)],
            'placement_ready_for_installation':False,
            'limitations':['Only original RAM table construction is executed; no CP15/MMU/cache effects are simulated.',
                           'Section alias scan does not exclude later table changes, small-page aliases or computed runtime references.',
                           'SCTLR enable sequence preserves inherited WXN/UWXN; descriptor XN alone does not prove executable permission.',
                           'Zero helper uses bounded synthetic lengths; full startup and runtime ownership are not simulated.',
                           'No payload, capture trigger, file exporter or installation is approved by these results.']}


def report(image):
    image=Path(image)
    initial,hashes,source=identity(image),tool_hashes(),revision()
    result=_report(image)
    if identity(image)!=initial or result['image_sha256']!=initial[0] or tool_hashes()!=hashes or revision()!=source:
        raise ValueError('Image/source changed during native placement analysis')
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
    print(f'Native placement evidence: {args.output}')


if __name__=='__main__':main()
