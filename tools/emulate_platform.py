#!/usr/bin/env python3
"""Offline execution of pinned firmware routines; no device or serial access."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
from firmware import checked_image, digest, lzss, parse, revision

APP_BASE = 0x20005000
RETURN = 0x08000000
STACK = 0x07000000
SOURCE = 0x01000000
OUTPUT = 0x04000000


def engine():
    import unicorn as u
    from unicorn import arm_const as a
    if u.__version__ != '2.1.4':
        raise ValueError('Requires pinned unicorn==2.1.4')
    uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_ARM)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(RETURN, 0x1000, u.UC_PROT_READ | u.UC_PROT_EXEC)
    uc.reg_write(a.UC_ARM_REG_SP, STACK+0xf000)
    uc.reg_write(a.UC_ARM_REG_LR, RETURN)
    return uc, u, a


def execute(uc, start, budget=1000000):
    from unicorn import arm_const as a
    from unicorn import UcError
    try:
        uc.emu_start(start, RETURN, timeout=30000000, count=budget)
    except UcError as exc:
        raise ValueError(f'Emulation stopped at {uc.reg_read(a.UC_ARM_REG_PC):#x}: {exc}') from exc
    if uc.reg_read(a.UC_ARM_REG_PC) != RETURN:
        raise ValueError('Execution did not return: instruction/time limit or modeled interruption')


def inputs(path):
    data = checked_image(path, 'trace')
    part = parse(data)[0]
    main = data[part['offset']:part['offset']+part['size']]
    size = struct.unpack_from('<I', main, 0x10000)[0]
    app, consumed = lzss(main[0x10004:], size)
    return data, main, app, consumed


def decode_loader(loader, compressed, size, *, budget=150000000):
    """Run original loader. Caller supplies lookahead bytes actually available.

    Unlike the host decoder the device routine may read another token after
    producing size bytes. Source ends at a page boundary to detect overread.
    """
    if not 0 < size <= 16*1024*1024 or not compressed:
        raise ValueError('Invalid decode input')
    uc, u, a = engine()
    uc.mem_map(0x20004000, 0x1000)
    uc.mem_write(0x20004000, loader)
    uc.mem_protect(0x20004000, 0x1000, u.UC_PROT_READ | u.UC_PROT_EXEC)
    span = (len(compressed)+4095) & ~4095
    uc.mem_map(SOURCE, span, u.UC_PROT_READ)
    source = SOURCE+span-len(compressed)
    uc.mem_write(source, compressed)
    uc.mem_map(OUTPUT, (size+4095) & ~4095, u.UC_PROT_READ | u.UC_PROT_WRITE)
    for reg, value in [(a.UC_ARM_REG_R0,OUTPUT),(a.UC_ARM_REG_R1,source),(a.UC_ARM_REG_R2,size)]:
        uc.reg_write(reg,value)
    violations = []
    accesses = {'source_read_end': 0, 'output_write_end': 0, 'output_read_end': 0}

    def bounds(machine, access, address, width, value, unused):
        if SOURCE <= address < SOURCE + span:
            valid = source <= address and address + width <= source + len(compressed)
            accesses['source_read_end'] = max(accesses['source_read_end'], address + width - source)
        else:
            valid = OUTPUT <= address and address + width <= OUTPUT + size
            key = 'output_write_end' if access == u.UC_MEM_WRITE else 'output_read_end'
            accesses[key] = max(accesses[key], address + width - OUTPUT)
        if not valid:
            violations.append((address, width))
            machine.emu_stop()

    uc.hook_add(u.UC_HOOK_MEM_READ, bounds, begin=SOURCE, end=SOURCE + span - 1)
    uc.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, bounds, begin=OUTPUT,
                end=OUTPUT + ((size + 4095) & ~4095) - 1)
    try:
        execute(uc, 0x2000425c, budget)
    except ValueError:
        if violations:
            raise ValueError(f'Loader access outside exact byte bounds: {violations}') from None
        raise
    if violations:
        raise ValueError(f'Loader access outside exact byte bounds: {violations}')
    written = uc.reg_read(a.UC_ARM_REG_R0)
    if written != size:
        raise ValueError(f'Unexpected loader output length {written}')
    return bytes(uc.mem_read(OUTPUT,size)), {'bytes_written':written,
            'source_bytes_advanced':uc.reg_read(a.UC_ARM_REG_R1)-source,
            'access_bounds': accesses, 'exact_byte_bounds_checked': True,
            'executed':'original ARM loader at 0x2000425c',
            'modeled':['private RAM and stack', 'return sentinel'],
            'limits':{'instructions':budget,'wall_seconds':30}}


def validate_envelope(app, header, trailer=None):
    """Execute original magic/trailer checker; only byte comparison is modeled."""
    if len(header)!=4 or (trailer is not None and len(trailer)!=2):
        raise ValueError('Expected four magic bytes and optional two trailer bytes')
    uc,u,a=engine();uc.mem_map(0x20000000,0x400000);uc.mem_write(APP_BASE,app)
    uc.mem_map(SOURCE,0x1000);uc.mem_write(SOURCE,header)
    if trailer is not None: uc.mem_write(SOURCE+16,trailer)
    def hook(machine,address,size,user):
        if address==0x2017c81e:
            r0=uc.reg_read(a.UC_ARM_REG_R0);r1=uc.reg_read(a.UC_ARM_REG_R1);n=uc.reg_read(a.UC_ARM_REG_R2)
            if n not in (2,4): raise ValueError('Unexpected comparison length')
            result=int(bytes(uc.mem_read(r0,n))!=bytes(uc.mem_read(r1,n)))
            uc.reg_write(a.UC_ARM_REG_R0,result)
            uc.reg_write(a.UC_ARM_REG_PC,uc.reg_read(a.UC_ARM_REG_LR))
        elif not 0x200247e4<=address<0x20024850:
            raise ValueError(f'Unmodeled envelope execution {address:#x}')
    uc.hook_add(u.UC_HOOK_CODE,hook)
    uc.reg_write(a.UC_ARM_REG_R0,SOURCE)
    uc.reg_write(a.UC_ARM_REG_R1,0 if trailer is None else SOURCE+16)
    execute(uc,0x200247e4)
    return {'accepted':uc.reg_read(a.UC_ARM_REG_R0)==0,
            'executed':'original 0x200247e4 magic/trailer checker',
            'modeled':['memcmp equality'], 'limitation':'not complete updater validation'}


def select_bank(loader, marker):
    """Execute original selector/comparator, intercept only decompressor entry."""
    if len(marker)!=16: raise ValueError('Marker must be 16 bytes')
    uc,u,a=engine()
    uc.mem_map(0x20004000,0x1000)
    uc.mem_write(0x20004000,loader)
    uc.mem_protect(0x20004000,0x1000,u.UC_PROT_READ | u.UC_PROT_EXEC)
    marker_address=struct.unpack_from('<I',loader,0x560)[0]
    if marker_address!=0x187f0000: raise ValueError('Unexpected marker location')
    for address in (0x18010000,0x18400000,marker_address):
        uc.mem_map(address,0x1000,u.UC_PROT_READ)
    uc.mem_write(marker_address,marker)
    uc.mem_write(0x18010000,struct.pack('<I',1234))
    uc.mem_write(0x18400000,struct.pack('<I',5678))
    selected={}
    def hook(machine,address,size,user):
        if address==0x2000425c:
            selected.update(source=hex(uc.reg_read(a.UC_ARM_REG_R1)),
                            destination=hex(uc.reg_read(a.UC_ARM_REG_R0)),
                            decoded_length=uc.reg_read(a.UC_ARM_REG_R2))
            uc.reg_write(a.UC_ARM_REG_PC,RETURN)
        elif not 0x20004334<=address<0x200043c4:
            raise ValueError(f'Unmodeled bank-selector execution {address:#x}')
    uc.hook_add(u.UC_HOOK_CODE,hook)
    execute(uc,0x20004374)
    return dict(selected, marker_sha256=digest(marker),
                executed='original loader selector and 16-byte comparator',
                modeled=['persistent marker bytes','bank length words','decompressor interception'])


def transfer(app, payload, *, destination=0x10000, initial_equal=False, initial_content=None,
             short_read=False, read_error=False, cancel=False, interrupt=None, program_error=False,
             controller_scenario=None):
    """Execute transfer control flow with explicit file/flash/callee models.

    Flash size here is a model bound, not hardware qualification. Interrupt is
    before_erase, after_erase or after_program; no physical writes occur.
    """
    capacity = 0x10000 if destination == 0 else 0x3f0000
    if destination not in (0,0x10000,0x400000) or not 0 < len(payload) <= capacity:
        raise ValueError('Unsupported modeled transfer range')
    unit_span = (len(payload) + 0xffff) & ~0xffff
    if initial_content is not None:
        if initial_equal or not isinstance(initial_content, bytes) or len(initial_content) != unit_span:
            raise ValueError('Initial content must cover exact erase-unit span without initial_equal')
    if interrupt not in (None,'before_erase','after_erase','after_program'):
        raise ValueError('Unknown interruption stage')
    controller_results = None
    if controller_scenario is not None:
        from controller import prepare_call_results
        blocks=[(destination+i,payload[i:i+0x10000].ljust(0x10000,b'\xff')) for i in range(0,len(payload),0x10000)]
        controller_results=prepare_call_results(app,controller_scenario,blocks)
    uc,u,a = engine()
    uc.mem_map(0x20000000,0x600000)
    uc.mem_write(APP_BASE,app)
    changed = 0x20500100
    uc.mem_write(STACK+0xf000,struct.pack('<I',changed))
    uc.mem_write(0x20390317, bytes([bool(cancel)]))
    flash = bytearray(b'\xff'*0x800000)
    if initial_content is not None:
        flash[destination:destination+unit_span] = initial_content
    elif initial_equal:
        flash[destination:destination+len(payload)] = payload
    events=[]; offset=0; md5=hashlib.md5(); stopped=None
    regs=(a.UC_ARM_REG_R0,a.UC_ARM_REG_R1,a.UC_ARM_REG_R2,a.UC_ARM_REG_R3)
    def readreg(): return [uc.reg_read(r) for r in regs]
    def stop(stage):
        nonlocal stopped
        if interrupt == stage:
            stopped=stage; uc.emu_stop(); return True
        return False
    def bounds(address,length):
        if address < 0 or length < 0 or address+length > len(flash):
            raise ValueError('Modeled flash bounds exceeded')
    def hook(machine,address,size,user):
        nonlocal offset, stopped
        if address in hooks:
            r0,r1,r2,r3=readreg(); result=0
            if controller_scenario is not None and address in (0x20024cd0,0x20024bb8,0x20024a60,0x20024850):
                name={0x20024cd0:'enter_command',0x20024bb8:'erase',0x20024a60:'program',0x20024850:'restore_mapping'}[address]
                evidence=controller_results[(name,r0 if name in ('erase','program') else None)]
                if name=='program' and digest(bytes(uc.mem_read(r1,r2)))!=evidence['input_sha256']:
                    raise ValueError('Controller evidence does not match caller payload')
                if name=='erase' and r1!=r0: raise ValueError('Controller evidence does not match erase range')
                events.append({'operation':'original_controller','routine':name,'outcome':evidence['outcome'],
                               'pc':evidence['pc'],'event_sha256':evidence['event_sha256'],
                               'modeled_helpers':evidence['modeled_helpers'],'limits':evidence['limits']})
                if evidence['outcome']!='RETURNED':
                    stopped='controller_'+evidence['outcome'];uc.emu_stop();return
            if address==0x2017c758:  # observed memset-style ABI: ptr, length, byte
                uc.mem_write(r0,bytes([r2 & 255])*r1); result=r0
            elif address==0x200bc6a4:
                count=min(r2,len(payload)-offset)
                if short_read: count=max(0,count-1)
                uc.mem_write(r1,payload[offset:offset+count]); offset+=count
                uc.mem_write(r3,struct.pack('<I',count))
                result=1 if read_error else 0
                events.append({'operation':'read','requested':r2,'actual':count,'status':result})
            elif address==0x200214b0: result=r0  # explicit assumed status mapping
            elif address==0x2003d38c: md5.update(bytes(uc.mem_read(r1,r2)))
            elif address==0x2017c81e:
                at=r1-0x18000000; bounds(at,r2)
                result=int(bytes(uc.mem_read(r0,r2)) != bytes(flash[at:at+r2]))
                events.append({'operation':'compare','offset':at,'length':r2,'different':bool(result)})
            elif address==0x20024bb8:
                if r0 != r1 or r0 % 0x10000: raise ValueError('Unexpected erase call')
                bounds(r0,0x10000)
                if stop('before_erase'): return
                flash[r0:r0+0x10000]=b'\xff'*0x10000
                events.append({'operation':'erase','offset':r0,'length':0x10000})
                if stop('after_erase'): return
            elif address==0x20024a60:
                bounds(r0,r2)
                data=bytes(uc.mem_read(r1,r2))
                if not program_error:
                    flash[r0:r0+r2]=bytes(x & y for x,y in zip(flash[r0:r0+r2],data))
                result=1 if program_error else 0
                events.append({'operation':'program','offset':r0,'length':r2,'modeled_error':program_error})
                if stop('after_program'): return
            elif address==0x2017c618:
                if not r1: raise ValueError('Division by zero')
                result=r0//r1
            else: events.append({'operation':'modeled_controller_transition','address':hex(address)})
            uc.reg_write(a.UC_ARM_REG_R0,result)
            uc.reg_write(a.UC_ARM_REG_PC,uc.reg_read(a.UC_ARM_REG_LR))
        elif not 0x20024db8 <= address < 0x20024ef8:
            raise ValueError(f'Unmodeled execution at {address:#x}')
    hooks={0x2017c758,0x200bc6a4,0x200214b0,0x2003d38c,0x2017c81e,
           0x20024cd0,0x20024bb8,0x20024a60,0x20024850,0x2017c618}
    uc.hook_add(u.UC_HOOK_CODE,hook)
    for reg,value in zip(regs,(1,destination,len(payload),0x20500200)): uc.reg_write(reg,value)
    try:
        execute(uc,0x20024db8)
    except ValueError:
        if stopped is None: raise
    return {'initial_state': 'supplied erase units' if initial_content is not None else 'equal payload with FF padding' if initial_equal else 'erased FF',
            'initial_content_sha256':digest(initial_content) if initial_content is not None else None,
            'return_code':None if stopped else uc.reg_read(a.UC_ARM_REG_R0),
            'interrupted':stopped,'changed_flag':uc.mem_read(changed,1)[0],
            'file_bytes_read':offset,'hashed_bytes_md5':md5.hexdigest(),
            'flash_payload_equal':None if stopped and stopped.startswith('controller_') else bytes(flash[destination:destination+len(payload)])==payload,
            'flash_sha256':None if stopped and stopped.startswith('controller_') else digest(flash),'events':events,
            'controller_scenario':controller_scenario,
            'executed':'original 0x20024db8..0x20024ef4 ARM control flow',
            'modeled':['file read/status mapping','MD5 update','memcmp/memset/divide',
                       '8 MiB flash bound, 64 KiB erase and programming', 'controller transitions'],
            'not_established':['physical geometry','flash controller completion/errors',
                               'whole updater acceptance','bank activation','recoverability']}


def report(path):
    data, main, app, consumed=inputs(path)
    loader=main[0x4000:0x4650]
    decoded, detail=decode_loader(loader,main[0x10004:],len(app))
    if decoded!=app: raise ValueError('Original loader disagrees with host decoder')
    result={'schema_version':1,'source_revision':revision(),'image_sha256':digest(data),
            'tool_sha256':{name:digest(Path(__file__).with_name(name).read_bytes())
                           for name in ('emulate_platform.py','firmware.py')},'unicorn':'2.1.4',
            'original_decode':dict(detail, matches_host=True, host_consumed=consumed)}
    result['envelope']={name:validate_envelope(app,header,trailer) for name,header,trailer in [
        ('official',data[:4],data[-2:]),('bad_magic',b'BAD!',data[-2:]),
        ('bad_trailer',data[:4],b'xx'),('header_only',data[:4],None)]}
    marker=loader[0x564:0x574]
    result['bank_selection']={name:select_bank(loader,value) for name,value in [
        ('matching',marker),('erased',b'\xff'*16),('zero',bytes(16)),
        ('one_bit_changed',bytes([marker[0]^1])+marker[1:])]}
    result['persistent_record_matches_loader_marker'] = app[0x20025024-APP_BASE:0x20025034-APP_BASE] == marker
    synthetic=b'ABCD'*20000
    scenarios={'changed':{},'unchanged':{'initial_equal':True},'short_read':{'short_read':True},
               'read_error':{'read_error':True},'cancel':{'cancel':True},'program_error':{'program_error':True}}
    scenarios.update({stage:{'interrupt':stage} for stage in ('before_erase','after_erase','after_program')})
    result['transfers']={name:transfer(app,synthetic,**options) for name,options in scenarios.items()}
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    try:
        result=report(args.image)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n')
    except (ValueError,OSError,KeyError,struct.error) as exc:
        print(f'error: {exc}',file=sys.stderr);return 1
    return 0


if __name__=='__main__':sys.exit(main())
