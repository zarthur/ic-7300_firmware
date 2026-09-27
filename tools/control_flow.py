"""Reachability walk within reviewed routine bounds, with explicit unresolved exits."""
import struct


def walk(data, base, start, end, mode='ARM'):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, CS_GRP_JUMP, CS_GRP_CALL
    from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC, ARM_REG_LR, ARM_CC_AL, ARM_CC_INVALID
    if not base <= start < end <= base+len(data) or mode not in ('ARM','Thumb'):
        raise ValueError('Invalid routine bounds/mode')
    cs=Cs(CS_ARCH_ARM,CS_MODE_ARM if mode=='ARM' else CS_MODE_THUMB);cs.detail=True
    pending=[start];visited=set();edges=[];literals=[];stops=[]
    while pending:
        address=pending.pop()
        if address in visited: continue
        if not start <= address < end:
            stops.append({'address':hex(address),'reason':'outside reviewed bounds'});continue
        visited.add(address)
        ins=next(cs.disasm(data[address-base:min(address-base+4,end-base)],address,count=1),None)
        if ins is None:
            stops.append({'address':hex(address),'reason':'undecodable'});continue
        conditional=ins.cc not in (ARM_CC_AL,ARM_CC_INVALID) or ins.mnemonic in ('cbz','cbnz')
        is_call=ins.group(CS_GRP_CALL);is_jump=ins.group(CS_GRP_JUMP)
        writes_pc=(ins.mnemonic.startswith(('pop','ldm')) and any(o.type==ARM_OP_REG and o.reg==ARM_REG_PC for o in ins.operands))
        writes_pc |= bool(ins.operands and ins.operands[0].type==ARM_OP_REG and ins.operands[0].reg==ARM_REG_PC and ins.mnemonic.startswith(('ldr','mov','sub')))
        if ins.mnemonic.startswith('ldr') and len(ins.operands)==2:
            src=ins.operands[1]
            if src.type==ARM_OP_MEM and src.mem.base==ARM_REG_PC:
                pc=address+8 if mode=='ARM' else (address+4)&~3
                pool=pc+src.mem.disp
                if base<=pool<=base+len(data)-4:
                    literals.append({'address':hex(address),'pool':hex(pool),'value':hex(struct.unpack_from('<I',data,pool-base)[0])})
        if is_jump or is_call or writes_pc:
            op=ins.operands[-1] if ins.operands else None
            target=op.imm if op and op.type==ARM_OP_IMM and (is_jump or is_call) else None
            edge={'address':hex(address),'kind':'call' if is_call else 'branch',
                  'conditional':conditional,'target':None if target is None else hex(target & ~1),
                  'target_mode':None if target is None else (('Thumb' if mode=='ARM' else 'ARM') if ins.mnemonic=='blx' else mode)}
            if target is None:
                stack_return=ins.mnemonic.startswith('pop') or (ins.mnemonic.startswith('ldm') and ins.operands and ins.operands[0].type==ARM_OP_REG and cs.reg_name(ins.operands[0].reg)=='sp')
                edge['kind']='return' if stack_return or (ins.mnemonic=='bx' and op.type==ARM_OP_REG and op.reg==ARM_REG_LR) else 'unresolved indirect'
            edges.append(edge)
            if target is not None and not is_call:
                pending.append(target & ~1)
            if not is_call and not conditional: continue
        pending.append(address+ins.size)
    return {'entry':hex(start),'end':hex(end),'mode':mode,'reachable_instructions':len(visited),
            'edges':sorted(edges,key=lambda x:int(x['address'],16)),
            'literal_loads':sorted(literals,key=lambda x:int(x['address'],16)),
            'unresolved_exits':sorted(stops,key=lambda x:int(x['address'],16)),
            'limitations':['calls recorded but callee effects not inferred',
                           'conditional branches explore both paths',
                           'indirect control flow requires separate resolution']}
