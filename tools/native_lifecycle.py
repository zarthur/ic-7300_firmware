#!/usr/bin/env python3
"""Exact-image DMA decision and receive-queue reset probes; no hardware access."""
import argparse
from pathlib import Path
import struct

from control_flow import walk
from emulate_platform import APP_BASE, RETURN, STACK, inputs
from firmware import digest, revision
from native_receive import Isolated, QUEUE, tool_hashes as receive_hashes
from recorder_interface import identity
from reporting import atomic_json

RESTART = 0x200605e4
HANDLERS = {
    # entry, ready boundary before acknowledgment, idle return block, CHSTAT, bank register
    'receive_ch3': (0x20060614, 0x2006064c, 0x200606e8, 0xe82000e4, 'R0'),
    'output_ch4': (0x20060778, 0x200607b0, 0x20060884, 0xe8200124, 'R4'),
    'input_ch5': (0x20060888, 0x200608c0, 0x20060944, 0xe8200164, 'R0'),
}


def decision_probe(app, channel, statuses):
    if channel not in HANDLERS or not isinstance(statuses, (list, tuple)) or not statuses or any(
            type(s) is not int or not 0 <= s <= 0xffffffff for s in statuses):
        raise ValueError('Require a known handler and uint32 status fixtures')
    entry, ready, idle, status_address, bank_reg = HANDLERS[channel]
    h = Isolated(app, [(entry, ready+4), (idle, idle+8), (RESTART, RESTART+4)], [(status_address, 4)])
    def stop(uc, address, size, unused):
        if address in (ready, RESTART):
            uc.emu_stop()
    h.uc.hook_add(h.u.UC_HOOK_CODE, stop)
    results = []
    for status in statuses:
        h.uc.mem_write(status_address, struct.pack('<I', status))
        h.uc.reg_write(h.a.UC_ARM_REG_SP, STACK+0xf000)
        h.uc.reg_write(h.a.UC_ARM_REG_LR, RETURN)
        before = h.count
        h.accesses.clear()
        h.uc.emu_start(entry, RETURN, timeout=1000000, count=100)
        pc = h.uc.reg_read(h.a.UC_ARM_REG_PC)
        if pc not in (RETURN, ready, RESTART):
            raise ValueError('Handler did not reach a reviewed boundary')
        if h.accesses != [(h.u.UC_MEM_READ, status_address, 4)]:
            raise ValueError('Unexpected handler register access')
        if pc in (RETURN, RESTART) and h.uc.reg_read(h.a.UC_ARM_REG_SP) != STACK+0xf000:
            raise ValueError('Idle/restart path did not restore the caller stack')
        results.append({'status': status, 'decision': 'ready' if pc == ready else 'restart' if pc == RESTART else 'idle',
                        'bank': h.uc.reg_read(getattr(h.a, 'UC_ARM_REG_'+bank_reg)) if pc == ready else None,
                        'instructions': h.count-before, 'boundary': hex(pc)})
    return results


def queue_reset_probe(app, operation, producer, consumer):
    if operation not in ('initialize', 'flush') or any(type(x) is not int or not 0 <= x < 8 for x in (producer, consumer)):
        raise ValueError('Require queue initialize/flush and indices 0..7')
    h = Isolated(app, [(0x2005fac4, 0x2005fae8)], [(QUEUE, 0x242)])
    payload = bytes((i*17+3)&255 for i in range(576))
    h.uc.mem_write(QUEUE, payload+bytes((producer, consumer)))
    result = h.run(0x2005fac4 if operation == 'initialize' else 0x2005fad8)
    after = bytes(h.uc.mem_read(QUEUE, 0x242))
    result.update(producer=after[576], consumer=after[577], payload_unchanged=after[:576] == payload,
                  writes=[{'offset': addr-QUEUE, 'size': size} for access, addr, size in h.accesses if access == h.u.UC_MEM_WRITE])
    return result


def configuration_probe(app, mode_values):
    """Execute separate original store slices in synthetic register memory.

    Deliberately retain supplied SSITDMR values, including non-default modes.
    No peripheral effects, waits, pin setup or DMA enable are simulated.
    """
    if not isinstance(mode_values, (list, tuple)) or not mode_values or any(
            type(v) is not int or not 0 <= v <= 0xffffffff for v in mode_values):
        raise ValueError('Require nonempty uint32 mode fixtures')
    base = 0xe820b000
    h = Isolated(app, [(0x2005fe54, 0x2005fe68), (0x2005fefc, 0x2005ff18),
                      (0x20060044, 0x20060060), (0x2006050c, 0x20060528)],
                 [(base, 0x24), (base+0x800, 0x24)])
    boundaries = [
        ('setup', 0x2005fe54, 0x2005fe68, [(base, 0x2b0030), (base+0x10, 0xc3)]),
        ('clear_status', 0x2005fefc, 0x2005ff18,
         [(base+4, 0), (base+0x804, 0), (base+0x14, 0), (base+0x814, 0)]),
        ('start_prefix', 0x20060044, 0x20060060,
         [(base+0x10, 0xcc), (base, 0x3c2b0033), (base+0x18, 0)]),
        ('stop_prefix', 0x2006050c, 0x20060528,
         [(base+0x10, 0xc0), (base, 0x22b0030)])]
    rows = []
    for mode in mode_values:
        for region in (base, base+0x800):
            h.uc.mem_write(region, b'\xa5'*32+struct.pack('<I', mode))
        stages = []
        for name, entry, stop, expected_writes in boundaries:
            before = {r: bytearray(h.uc.mem_read(r, 0x24)) for r in (base, base+0x800)}
            if name == 'clear_status':
                h.uc.reg_write(h.a.UC_ARM_REG_R11, base)
                h.uc.reg_write(h.a.UC_ARM_REG_R1, base+0x810)
            h.accesses.clear()
            h.run(entry, stop=stop)
            writes = [(a, n) for k, a, n in h.accesses if k == h.u.UC_MEM_WRITE]
            if writes != [(a, 4) for a, _ in expected_writes] or any(
                    k == h.u.UC_MEM_READ for k, _, _ in h.accesses):
                raise ValueError('Unexpected SSIF configuration access')
            for region, expected in before.items():
                for a, value in expected_writes:
                    if region <= a < region+len(expected):
                        struct.pack_into('<I', expected, a-region, value)
                if bytes(h.uc.mem_read(region, len(expected))) != bytes(expected):
                    raise ValueError('Unexpected SSIF register or guard change')
            stages.append({'name': name,
                           'writes': [{'address': a, 'value': v} for a, v in expected_writes],
                           'ssicr': struct.unpack('<I', h.uc.mem_read(base, 4))[0],
                           'ssifcr': struct.unpack('<I', h.uc.mem_read(base+0x10, 4))[0],
                           'ssitdmr': struct.unpack('<I', h.uc.mem_read(base+0x20, 4))[0],
                           'other_ssitdmr': struct.unpack('<I', h.uc.mem_read(base+0x820, 4))[0]})
        rows.append({'input_mode': mode, 'stages': stages})
    return rows



def start_probe(app, cases):
    """Run the complete original start routine with scripted input observations.

    Cases are (timeout_phase, retries_per_phase, old_gate, timer_count, irq_mask).
    Phase -1 never expires; 0..19 expire at a pin wait; 20 at the final check.
    Private MMIO values model reads only, not peripheral effects or elapsed time.
    All callees execute original instructions, including the timer setup/clear.
    """
    if not isinstance(cases, (list, tuple)) or not cases:
        raise ValueError('Require nonempty start fixtures')
    for case in cases:
        if (not isinstance(case, (list, tuple)) or len(case) != 5 or
                any(type(v) is not int for v in case) or
                not -1 <= case[0] <= 20 or not 0 <= case[1] <= 4 or
                not 0 <= case[2] <= 255 or not 0 <= case[3] <= 65535 or
                case[4] not in (0, 1)):
            raise ValueError('Invalid start fixture')
    gate, timer_flag, timer = 0x2039038c, 0x203903ac, 0xfcff0305
    pins = (0xfcfe3208, 0xfcfe320c)
    regions = [(0xe820b000, 0x24), (0xe820b800, 0x24),
               (0xe82000e8, 4), (0xe8200128, 4), (0xe8200168, 4),
               (pins[0], 2), (pins[1], 2), (timer_flag, 1), (gate, 1), (timer, 5)]
    h = Isolated(app, [(0x2006003c, 0x200604c4), (0x20063448, 0x200634a8),
                      (0x20360adc, 0x20360af4), (0x20360b0c, 0x20360b34)], regions)
    phases = list(range(0x20060074, 0x20060254, 0x30))+list(range(0x20060294, 0x20060474, 0x30))
    state = {}
    stack = STACK+0xf000

    def stimulus(uc, address, size, unused):
        if address in phases:
            phase = phases.index(address)
            state['phase'] = phase
            count = state['polls'][phase]
            expired = state['timeout'] >= 0 and phase >= state['timeout']
            matched = not expired and count >= state['retries']
            bit = 0x200 if phase < 10 else 0x20
            high = bool(phase % 2) if matched else not bool(phase % 2)
            value = (0xa5a5 & ~bit) | (bit if high else 0)
            ptr = pins[phase // 10]
            uc.mem_write(ptr, struct.pack('<H', value))
            state['external'][ptr] = struct.pack('<H', value)
            state['polls'][phase] += 1
        elif address == 0x20060488:
            state['phase'] = 20
        elif address == 0x20360b24:
            expired = state['timeout'] >= 0 and state['phase'] >= state['timeout']
            value = 0xa4 | int(expired)
            uc.mem_write(timer, bytes([value]))
            state['external'][timer] = bytes([value])
            state['timeout_reads'].append(state['phase'])

    def writes(uc, kind, address, size, value, unused):
        if STACK <= address < STACK+0x10000:
            if not stack-32 <= address or address+size > stack:
                raise ValueError('Unexpected original start stack footprint')
            return
        state['writes'].append((address, size, value & ((1 << (8*size))-1)))

    h.uc.hook_add(h.u.UC_HOOK_CODE, stimulus)
    h.uc.hook_add(h.u.UC_HOOK_MEM_WRITE, writes)
    rows = []
    for timeout, retries, old_gate, timer_count, masked in cases:
        state.clear()
        state.update(timeout=timeout, retries=retries, phase=-1, polls=[0]*20,
                     external={}, writes=[], timeout_reads=[])
        for lo, size in regions:
            h.uc.mem_write(lo, b'\xa4'*size)
        # CHCTRL command bits read as zero (RZ/A1H manual, section 9.4.8).
        for ptr in (0xe82000e8, 0xe8200128, 0xe8200168):
            h.uc.mem_write(ptr, bytes(4))
        h.uc.mem_write(gate, bytes([old_gate]))
        h.uc.mem_write(timer+1, struct.pack('<H', timer_count))
        before = {lo: bytearray(h.uc.mem_read(lo, size)) for lo, size in regions}
        h.uc.mem_write(stack-96, b'\xa5'*128)
        preserved = {getattr(h.a, 'UC_ARM_REG_R'+str(n)): 0x11223300+n for n in range(4, 12)}
        h.uc.reg_write(h.a.UC_ARM_REG_CPSR, 0xa0000053 | (masked << 7))
        for reg, value in preserved.items():
            h.uc.reg_write(reg, value)
        h.accesses.clear()
        result = h.run(0x2006003c)
        expected = [(0xe820b010, 4, 0xcc), (0xe820b000, 4, 0x3c2b0033),
                    (0xe820b018, 4, 0), (timer_flag, 1, 1),
                    (timer+3, 2, (timer_count+32000) & 65535), (timer, 1, 0xa4),
                    (0xe8200128, 4, 1), (0xe82000e8, 4, 1),
                    (0xe820b810, 4, 0xc4), (0xe820b800, 4, 0x0c2b0031),
                    (0xe8200168, 4, 1)]
        if timeout == -1:
            expected.append((gate, 1, 1))
        expected.append((timer_flag, 1, 0))
        expected_polls = [1 if timeout >= 0 and i >= timeout else retries+1 for i in range(20)]
        expected_reads = [i for i in range(20) for _ in range(
            1 if timeout >= 0 and i >= timeout else retries)]+[20]
        if (state['writes'] != expected or state['polls'] != expected_polls or
                state['timeout_reads'] != expected_reads):
            raise ValueError('Unexpected original start writes or polling flow')
        for lo, data in before.items():
            for address, size, value in expected:
                if lo <= address and address+size <= lo+len(data):
                    data[address-lo:address-lo+size] = value.to_bytes(size, 'little')
            for address, value in state['external'].items():
                if lo <= address and address+len(value) <= lo+len(data):
                    data[address-lo:address-lo+len(value)] = value
            if bytes(h.uc.mem_read(lo, len(data))) != bytes(data):
                raise ValueError('Unexpected start input or register change')
        if (h.uc.reg_read(h.a.UC_ARM_REG_SP) != stack or
                any(h.uc.reg_read(reg) != value for reg, value in preserved.items()) or
                h.uc.reg_read(h.a.UC_ARM_REG_CPSR) & 0x80 or
                bytes(h.uc.mem_read(stack-96, 64))+bytes(h.uc.mem_read(stack, 32)) != b'\xa5'*96):
            raise ValueError('Unexpected original start return ABI')
        rows.append({'timeout_phase': timeout, 'retries_per_phase': retries,
                     'previous_gate': old_gate, 'timer_count': timer_count,
                     'initial_irq_mask': masked, 'gate': 1 if timeout == -1 else old_gate,
                     'polls': state['polls'], 'timeout_reads': state['timeout_reads'],
                     'writes': [{'address': a, 'size': n, 'value': v} for a, n, v in expected],
                     'return_irq_mask': 0, 'instructions': result['instructions']})
    return rows

def stop_probe(app, cases):
    """Execute complete original stop with supplied SSI-idle/expiry observations.

    Cases use the start probe shape, with timeout phases -1 (none), 0 or 1.
    CHCTRL reads are zero per the hardware manual, not retained command words.
    Peripheral side effects, request withdrawal and DMA completion are unmodeled.
    """
    if not isinstance(cases, (list, tuple)) or not cases:
        raise ValueError('Require nonempty stop fixtures')
    for case in cases:
        if (not isinstance(case, (list, tuple)) or len(case) != 5 or
                any(type(v) is not int for v in case) or
                case[0] not in (-1, 0, 1) or not 0 <= case[1] <= 4 or
                not 0 <= case[2] <= 255 or not 0 <= case[3] <= 65535 or
                case[4] not in (0, 1)):
            raise ValueError('Invalid stop fixture')
    gate, flag, timer = 0x2039038c, 0x203903ac, 0xfcff0305
    controls = (0xe82000e8, 0xe8200128, 0xe8200168)
    regions = [(0xe820b000, 0x24), (0xe820b800, 0x24),
               *((p, 4) for p in controls), (0xfcfe0440, 1),
               (flag, 1), (gate, 1), (timer, 5)]
    h = Isolated(app, [(0x200604c4, 0x200605e4), (0x20063448, 0x200634a8),
                      (0x20360adc, 0x20360af4), (0x20360b0c, 0x20360b34)], regions)
    state = {}
    stack = STACK+0xf000

    def stimulus(uc, address, size, unused):
        if address in (0x20060528, 0x20060574):
            phase = int(address == 0x20060574)
            state['phase'] = phase
            expired = state['timeout'] >= 0 and phase >= state['timeout']
            ready = not expired and state['polls'][phase] >= state['retries']
            value = (0xa4a4a4a4 & ~(1 << 25)) | ((1 << 25) if ready else 0)
            uc.mem_write(0xe820b004+phase*0x800, struct.pack('<I', value))
            state['polls'][phase] += 1
        elif address == 0x20360b24:
            expired = state['timeout'] >= 0 and state['phase'] >= state['timeout']
            uc.mem_write(timer, bytes([0xa4 | int(expired)]))
            state['timeout_reads'].append(state['phase'])

    def writes(uc, kind, address, size, value, unused):
        if STACK <= address < STACK+0x10000:
            if not stack-48 <= address or address+size > stack:
                raise ValueError('Unexpected original stop stack footprint')
        else:
            state['writes'].append((address, size, value & ((1 << (8*size))-1)))

    h.uc.hook_add(h.u.UC_HOOK_CODE, stimulus)
    h.uc.hook_add(h.u.UC_HOOK_MEM_WRITE, writes)
    rows = []
    for timeout, retries, old_gate, count, masked in cases:
        state.clear()
        state.update(timeout=timeout, retries=retries, phase=-1, polls=[0, 0],
                     timeout_reads=[], writes=[])
        for lo, size in regions:
            h.uc.mem_write(lo, b'\xa4'*size)
        for ptr in controls:
            h.uc.mem_write(ptr, bytes(4))
        h.uc.mem_write(gate, bytes([old_gate]))
        h.uc.mem_write(timer+1, struct.pack('<H', count))
        before = {lo: bytearray(h.uc.mem_read(lo, size)) for lo, size in regions}
        h.uc.reg_write(h.a.UC_ARM_REG_CPSR, 0xa0000053 | (masked << 7))
        saved = {getattr(h.a, 'UC_ARM_REG_R'+str(n)): 0x11223300+n for n in range(4, 12)}
        for reg, value in saved.items():
            h.uc.reg_write(reg, value)
        h.uc.mem_write(stack-96, b'\xa5'*128)
        h.accesses.clear()
        result = h.run(0x200604c4)
        expected = [(flag, 1, 1), (timer+3, 2, (count+32000) & 65535), (timer, 1, 0xa4),
                    *((ptr, 4, 0) for ptr in controls),
                    (0xe820b010, 4, 0xc0), (0xe820b000, 4, 0x022b0030), (0xe820b004, 4, 0),
                    (0xe820b810, 4, 0xc0), (0xe820b800, 4, 0x022b0030), (0xe820b804, 4, 0),
                    (0xfcfe0440, 1, 0xb4), (0xfcfe0440, 1, 0xb4), (gate, 1, 0), (flag, 1, 0)]
        if (state['writes'] != expected or
                state['polls'] != [1 if timeout >= 0 and i >= timeout else retries+1 for i in range(2)] or
                state['timeout_reads'] != [i for i in range(2) for _ in range(
                    1 if timeout >= 0 and i >= timeout else retries)]):
            raise ValueError('Unexpected original stop writes or polling flow')
        for lo, data in before.items():
            for address, size, value in expected:
                if lo <= address and address+size <= lo+len(data):
                    data[address-lo:address-lo+size] = value.to_bytes(size, 'little')
            if lo == timer and state['timeout_reads']:
                data[0] = 0xa4 | int(timeout >= 0)
            if bytes(h.uc.mem_read(lo, len(data))) != bytes(data):
                raise ValueError('Unexpected stop input or register change')
        if (h.uc.reg_read(h.a.UC_ARM_REG_SP) != stack or
                any(h.uc.reg_read(reg) != value for reg, value in saved.items()) or
                (h.uc.reg_read(h.a.UC_ARM_REG_CPSR) >> 7) & 1 != masked or
                bytes(h.uc.mem_read(stack-96, 48))+bytes(h.uc.mem_read(stack, 32)) != b'\xa5'*80):
            raise ValueError('Unexpected original stop return ABI')
        rows.append({'timeout_phase': timeout, 'retries_per_phase': retries,
                     'previous_gate': old_gate, 'timer_count': count, 'initial_irq_mask': masked,
                     'gate': 0, 'polls': state['polls'], 'timeout_reads': state['timeout_reads'],
                     'writes': [{'address': a, 'size': n, 'value': v} for a, n, v in expected],
                     'return_irq_mask': masked, 'instructions': result['instructions']})
    return rows


def tool_hashes():
    return dict(receive_hashes(), native_lifecycle=digest(Path(__file__).read_bytes()))


def _report(image):
    data, _, app, _ = inputs(image)
    statuses = list(range(256))+[0x80000000|s for s in (0, 1, 0x40, 0x41, 0x80, 0x81, 0xc0, 0xc1)]
    return {'image_sha256': digest(data), 'application_sha256': digest(app),
            'handler_decisions': {name: decision_probe(app, name, statuses) for name in HANDLERS},
            'queue_resets': {f'{op}_{w}_{r}': queue_reset_probe(app, op, w, r)
                             for op in ('initialize','flush') for w in range(8) for r in range(8)},
            'configuration': configuration_probe(app, [0, 1, 0x100, 0x101, 0xffffffff]),
            'start': start_probe(app, [(phase, retries, gate, count, mask)
                for phase in range(-1, 21) for retries in (0, 2) for gate in (0, 1)
                for count in (0, 65535) for mask in (0, 1)]),
            'stop': stop_probe(app, [(phase, retries, gate, count, mask)
                for phase in (-1, 0, 1) for retries in (0, 2) for gate in (0, 1, 255)
                for count in (0, 65535) for mask in (0, 1)]),
            'original_flow': {name: walk(app, APP_BASE, lo, hi) for name, lo, hi in (
                ('cold_start',0x200605fc,0x20060614), ('shared_restart',RESTART,0x200605fc),
                ('service_gate_and_dispatch',0x20005bd4,0x20005bf0))},
            'limits': ['Status words are supplied fixtures, not progressing DMA hardware.',
                       'Handler execution stops before acknowledgment/cache/data processing or at shared restart entry.',
                       'The shared restart body is statically walked; its complete callee chain and physical completion are not executed.',
                       'Queue reset tests execute original stores only in private synthetic RAM.',
                       'Configuration slices execute separately against synthetic register memory; waits, reset effects and DMA startup are not simulated.',
                       'Start and stop execute their full original routines and callees with scripted pin/SSI status and timeout observations; DMA completion, clock duration and physical framing are not simulated.',
                       'Aligned direct callers are evidence, not an exhaustive indirect-call inventory.']}


def report(image):
    image = Path(image)
    initial, hashes, source = identity(image), tool_hashes(), revision()
    result = _report(image)
    if identity(image) != initial or result['image_sha256'] != initial[0] or hashes != tool_hashes() or source != revision():
        raise ValueError('Image/source changed during lifecycle analysis')
    return dict(result, source_revision=source, tool_sha256=hashes, source_unchanged=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Output already exists')
    result=report(args.image);args.output.parent.mkdir(parents=True,exist_ok=True);atomic_json(args.output,result)
    print(args.output)


if __name__ == '__main__':main()
