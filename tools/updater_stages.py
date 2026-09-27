#!/usr/bin/env python3
"""Execute recovered header precheck and persistent-record writer offline."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
from emulate_platform import APP_BASE, SOURCE, engine, execute, inputs, select_bank
from firmware import digest, revision, parse


def _file_check(app, container, *, installed_ids=None, read_failure=None, seek_failure=False, payload_flags=None, main_selector=None,
                boot_changed=False, corrupt_transfer=False, transfer_failure=None):
    """Execute recovered header, payload-validation or main-update caller stages.

    File API and status translation are models. installed_ids describes three
    four-byte component identifiers in RAM, not the public firmware version.
    """
    if installed_ids is None:
        installed_ids=[container[4+i*4:8+i*4] for i in range(3)]
    if len(installed_ids)!=3 or any(len(v)!=4 for v in installed_ids):
        raise ValueError('Three four-byte installed component identifiers required')
    if read_failure is not None and read_failure not in range(1,1001):
        raise ValueError('Invalid read failure index')
    uc,u,a=engine();uc.mem_map(0x20000000,0x600000);uc.mem_write(APP_BASE,app)
    for index,value in enumerate(installed_ids):
        uc.mem_write(0x203def00+index*13,value)
    if payload_flags is not None and (len(payload_flags)!=3 or any(v not in (0,1) for v in payload_flags)):
        raise ValueError('Three boolean component flags required')
    uc.mem_write(0x2039013a,bytes(payload_flags) if payload_flags is not None else b'\xa5'*3)
    if main_selector is not None and main_selector not in (0,1):
        raise ValueError('Invalid main-update selector')
    if transfer_failure not in (None,1,2): raise ValueError('Invalid transfer failure index')
    if main_selector is not None: uc.mem_write(0x20390398,bytes([main_selector]))
    contexts={};finalized=[];transfers=0
    events=[];position=0;reads=0
    regs=(a.UC_ARM_REG_R0,a.UC_ARM_REG_R1,a.UC_ARM_REG_R2,a.UC_ARM_REG_R3)
    hooks={0x200bc5f4,0x200bc6a4,0x200bc754,0x200bc64c,0x200214b0,0x2017c81e}
    if payload_flags is not None or main_selector is not None:
        hooks.update((0x2003c860,0x2003d38c,0x2003d458,0x2017c618))
    if main_selector is not None:
        hooks.update((0x20037604,0x20024db8,0x20024d60,0x20021ff0))
    def hook(machine,address,size,user):
        nonlocal position,reads,transfers
        if address in hooks:
            r0,r1,r2,r3=[uc.reg_read(reg) for reg in regs];result=0
            if address==0x200bc5f4:
                position=0;uc.mem_write(r2,struct.pack('<I',1));events.append({'operation':'open'})
            elif address==0x200bc6a4:
                if r2>0x10000: raise ValueError('File read exceeds modeled buffer bound')
                reads+=1;count=min(r2,max(0,len(container)-position))
                if reads==read_failure: count=max(0,count-1)
                if count: uc.mem_write(r1,container[position:position+count])
                uc.mem_write(r3,struct.pack('<I',count))
                events.append({'operation':'read','offset':position,'requested':r2,'actual':count})
                position+=count
            elif address==0x200bc754:
                offset=r1 if r1<0x80000000 else r1-0x100000000
                if r2 not in (0,1,2): raise ValueError('Unknown seek origin')
                target=(0 if r2==0 else position if r2==1 else len(container))+offset
                result=1 if seek_failure or target<0 else 0
                if not result: position=target
                uc.mem_write(r3,struct.pack('<I',position))
                events.append({'operation':'seek','origin':r2,'offset':offset,'status':result})
            elif address==0x200bc64c: events.append({'operation':'close'})
            elif address==0x200214b0: result=r0
            elif address==0x20037604: events.append({'operation':'modeled_update_setup'})
            elif address==0x20021ff0: result=0  # explicit model: other component updates disabled
            elif address==0x20024db8:
                transfers+=1
                if transfers==transfer_failure or position+r2>len(container):
                    result=0xffffffed
                else:
                    content=container[position:position+r2]
                    if corrupt_transfer and transfers==2 and content:
                        content=content[:-1]+bytes([content[-1]^1])
                    contexts[r3].update(content);position+=r2
                    changed_at=struct.unpack('<I',uc.mem_read(uc.reg_read(a.UC_ARM_REG_SP),4))[0]
                    uc.mem_write(changed_at,bytes([int(boot_changed if transfers==1 else True)]))
                events.append({'operation':'modeled_main_transfer','destination':hex(r1),
                               'length':r2,'index':transfers,'status':result})
            elif address==0x20024d60:
                events.append({'operation':'activation_call','selector':r0,
                               'source_marker_sha256':digest(bytes(uc.mem_read(r1,16)))})
            elif address==0x2003c860: contexts[r0]=hashlib.md5()
            elif address==0x2003d38c: contexts[r0].update(bytes(uc.mem_read(r1,r2)))
            elif address==0x2003d458:
                checksum=contexts[r0].digest();uc.mem_write(r0+0x58,checksum)
                finalized.append(checksum.hex())
                events.append({'operation':'modeled_md5_finalize'})
            elif address==0x2017c618:
                if not r1: raise ValueError('Progress divisor zero in original routine')
                result=r0//r1
            elif address==0x2017c81e:
                if not 0<r2<=16: raise ValueError('Unexpected comparison length')
                result=int(bytes(uc.mem_read(r0,r2))!=bytes(uc.mem_read(r1,r2)))
            uc.reg_write(a.UC_ARM_REG_R0,result)
            uc.reg_write(a.UC_ARM_REG_PC,uc.reg_read(a.UC_ARM_REG_LR))
        elif not any(lo<=address<hi for lo,hi in ([(0x20025ae4,0x20026130)] if main_selector is not None else [(0x20025650,0x20025ae4)] if payload_flags is not None else
                 [(0x200253f4,0x20025604),(0x200247e4,0x20024850),(0x20006028,0x20006050),(0x200060d4,0x20006108)])):
            raise ValueError(f'Unmodeled updater-stage execution {address:#x}')
    uc.hook_add(u.UC_HOOK_CODE,hook);execute(uc,0x20025ae4 if main_selector is not None else 0x20025650 if payload_flags is not None else 0x200253f4)
    code=uc.reg_read(a.UC_ARM_REG_R0)
    return {'accepted':code==0,'return_code':code,'component_change_flags':list(uc.mem_read(0x2039013a,3)) if code==0 and main_selector is None else None,
            'finalized_md5':finalized,
            'events':events,'executed':(['main-update caller control flow'] if main_selector is not None else ['payload read/hash/compare control flow'] if payload_flags is not None else
            ['header precheck','character bitmap predicate','magic/trailer checker']),
            'modeled':['file open/read/seek/close','identity status translation','memcmp equality',
                       'installed component identifiers in RAM']+(['MD5 context/update/finalize','unsigned progress division'] if payload_flags is not None or main_selector is not None else [])+(['main transfers and changed flags','update setup','other components disabled','activation routine call boundary'] if main_selector is not None else []),
            'not_established':['whole updater acceptance','installed radio RAM state','flash programming or activation']}


def header_precheck(app, container, *, installed_ids=None, read_failure=None, seek_failure=False):
    return _file_check(app, container, installed_ids=installed_ids,
                       read_failure=read_failure, seek_failure=seek_failure)


def payload_precheck(app, container, *, flags=(1,1,1), read_failure=None, seek_failure=False):
    return _file_check(app, container, payload_flags=flags,
                       read_failure=read_failure, seek_failure=seek_failure)


def main_update(app, container, *, selector=1, boot_changed=False,
                corrupt_transfer=False, transfer_failure=None):
    return _file_check(app, container, main_selector=selector, boot_changed=boot_changed,
                       corrupt_transfer=corrupt_transfer, transfer_failure=transfer_failure)


def activation_record(app, main, *, current_selector, program_bytes=16, before_erase=False,
                      controller_scenario=None):
    """Execute original writer and inspect resulting original-loader selection.

    Erase/program operations are atomic models except for an explicitly bounded
    programmed prefix. No arbitrary interruption point is claimed to match real
    controller power-loss behavior.
    """
    if current_selector not in (0,1) or not 0<=program_bytes<=16:
        raise ValueError('Invalid selector or programmed prefix length')
    loader=main[0x4000:0x4650];matching=loader[0x564:0x574]
    source_marker=main[0x4f00:0x4f10]
    if source_marker!=matching: raise ValueError('Source marker differs from loader marker')
    alternate=app[0x20025024-APP_BASE:0x20025034-APP_BASE]
    controller_results=None
    if controller_scenario is not None:
        from controller import prepare_call_results
        controller_results=prepare_call_results(app,controller_scenario,[(0x7f0000,source_marker if current_selector else alternate)])
    uc,u,a=engine();uc.mem_map(0x20000000,0x600000);uc.mem_write(APP_BASE,app)
    uc.mem_map(SOURCE,0x1000);uc.mem_write(SOURCE,source_marker)
    record=bytearray(matching if current_selector==0 else alternate)
    initial=bytes(record);events=[];interrupted=False;seen_erase=False;controller_stop=None
    hooks={0x2017c710,0x20024cd0,0x20024bb8,0x20024a60,0x20024850}
    regs=(a.UC_ARM_REG_R0,a.UC_ARM_REG_R1,a.UC_ARM_REG_R2)
    def hook(machine,address,size,user):
        nonlocal interrupted,seen_erase,controller_stop
        if address in hooks:
            r0,r1,r2=[uc.reg_read(reg) for reg in regs]
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
                    controller_stop=evidence['outcome'];interrupted=True;uc.emu_stop();return
            if address==0x2017c710:
                if r2!=16: raise ValueError('Unexpected marker copy')
                uc.mem_write(r0,bytes(uc.mem_read(r1,r2)))
            elif address==0x20024bb8:
                if r0!=0x7f0000 or r1!=r0: raise ValueError('Unexpected activation erase')
                if before_erase: interrupted=True;uc.emu_stop();return
                record[:]=b'\xff'*16;seen_erase=True
                events.append({'operation':'modeled_block_erase','offset':r0,'length':0x10000})
            elif address==0x20024a60:
                if r0!=0x7f0000 or r2!=16 or not seen_erase: raise ValueError('Unexpected activation program')
                record[:program_bytes]=bytes(uc.mem_read(r1,program_bytes)) if program_bytes else b''
                events.append({'operation':'modeled_record_program','offset':r0,'requested':r2,'written':program_bytes})
                if program_bytes<16: interrupted=True;uc.emu_stop();return
            else: events.append({'operation':'modeled_controller_transition','address':hex(address)})
            uc.reg_write(a.UC_ARM_REG_PC,uc.reg_read(a.UC_ARM_REG_LR))
        elif not 0x20024d60<=address<0x20024db8:
            raise ValueError(f'Unmodeled activation execution {address:#x}')
    uc.hook_add(u.UC_HOOK_CODE,hook)
    uc.reg_write(a.UC_ARM_REG_R0,current_selector);uc.reg_write(a.UC_ARM_REG_R1,SOURCE)
    try: execute(uc,0x20024d60)
    except ValueError:
        if not interrupted: raise
    selected=select_bank(loader,bytes(record))
    return {'current_selector':current_selector,'program_bytes':program_bytes,
            'interrupted':interrupted,'initial_marker_sha256':digest(initial),
            'final_marker_sha256':None if controller_stop else digest(record),'selected_source':None if controller_stop else selected['source'],
            'controller_stop':controller_stop,'controller_scenario':controller_scenario,
            'events':events,'source_marker_matches_loader':True,
            'executed':['original persistent-record writer','original loader selector'],
            'modeled':['copy helper','controller transitions','64 KiB erase','prefix-only programming'],
            'not_established':['physical recovery','actual interrupted page-program effects',
                               'bank image validity','rest of erased block ownership']}


def report(path):
    data,main,app,_=inputs(path)
    scenarios={'official':data,'bad_magic':b'BAD!'+data[4:],
               'bad_trailer':data[:-2]+b'xx','invalid_component':data[:4]+b'ABCD'+data[8:],
               'different_numeric_component':data[:4]+b'9.99'+data[8:],
               'truncated_header':data[:3], 'truncated_trailer':data[:-1]}
    installed=[data[4+i*4:8+i*4] for i in range(3)]
    checks={name:header_precheck(app,value,installed_ids=installed) for name,value in scenarios.items()}
    checks.update({f'short_read_{i}':header_precheck(app,data,read_failure=i) for i in range(1,6)})
    checks['seek_failure']=header_precheck(app,data,seek_failure=True)
    payloads={'official':payload_precheck(app,data)}
    for part in parse(data):
        mutated=bytearray(data);mutated[part['offset']]^=1
        payloads['corrupt_'+part['name']]=payload_precheck(app,bytes(mutated))
    payloads['truncated_digest']=payload_precheck(app,data[:-8])
    payloads['unselected_components']=payload_precheck(app,data,flags=(0,0,0))
    main_updates={f'selector_{selector}_boot_{int(changed)}_corrupt_{int(corrupt)}':
        main_update(app,data,selector=selector,boot_changed=changed,corrupt_transfer=corrupt)
        for selector in (0,1) for changed in (False,True) for corrupt in (False,True)}
    return {'schema_version':1,'main_update':main_updates,'payload_precheck':payloads,'source_revision':revision(),'image_sha256':digest(data),
            'tool_sha256':{name:digest(Path(__file__).with_name(name).read_bytes())
                           for name in ('updater_stages.py','emulate_platform.py','firmware.py')},
            'unicorn':'2.1.4','precheck':checks,
            'activation':[activation_record(app,main,current_selector=selector,program_bytes=n)
                          for selector in (0,1) for n in range(17)],
            'before_erase':[activation_record(app,main,current_selector=s,before_erase=True) for s in (0,1)]}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image',type=Path)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    try:
        result=report(args.image);args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n')
    except (ValueError,OSError,KeyError,struct.error) as exc:
        print(f'error: {exc}',file=sys.stderr);return 1
    return 0


if __name__=='__main__':sys.exit(main())
