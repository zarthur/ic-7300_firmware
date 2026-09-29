#!/usr/bin/env python3
"""Read-only v2 WAV analysis with explicit aborts and segmented nominal timing."""
import argparse
from collections import Counter
import math
from pathlib import Path
import statistics
import struct

from native_capture_report import BANKS, sha, wav_payload
from native_capture_v2 import decode_storage
from native_transport_v2 import FRAME_COUNT, MAGIC, recover
from reporting import atomic_json

FLAG_NAMES = {1: 'epoch_changed', 2: 'epoch_unknown', 4: 'epoch_exhausted',
              8: 'nested_callback', 16: 'ssi_unavailable'}
STATUS_NAMES = {2: 'full', 5: 'aborted_with_record', 6: 'aborted_without_record'}
OBSERVATION_FIELDS = ['tick_before', 'counter_before', 'pending_before',
                      'tick_after', 'counter_after', 'pending_after', 'source_end',
                      'ssicr', 'ssifcr', 'ssisr', 'ssifsr', 'ssitdmr']


def record_exclusions(row):
    reasons = [name for bit,name in FLAG_NAMES.items() if bit != 16 and row['flags'] & bit]
    before,after = row['epoch_before'],row['epoch_after']
    if before != after and 'epoch_changed' not in reasons: reasons.append('epoch_state_changed')
    if any(not e[0] or e[1] not in (1,2,3,4) or e[2] for e in (before,after)):
        reasons.append('unqualified_epoch')
    o = row['observations']
    if not (o[0] == o[3] and not ((o[2]|o[5]) & 64) and 0 <= o[4] <= o[1] <= 32000):
        reasons.append('ambiguous_timer_snapshot')
    return reasons


def timing_segments(records):
    """Never project across an excluded record, epoch boundary or bad interval."""
    groups,excluded,boundaries = [],[],[]
    current = []
    for row in records:
        reasons = record_exclusions(row)
        if reasons:
            excluded.append({'sequence': row['sequence'], 'reasons': reasons})
            if current: groups.append(current); current = []
            continue
        if current:
            previous = current[-1]
            a,b = previous['observations'],row['observations']
            ticks = (b[0]-a[0]) & 0xffffffff
            cycles = ticks*32001+a[1]-b[1]
            reasons = []
            if previous['epoch_after'] != row['epoch_before']: reasons.append('between_record_epoch_change')
            if a[6] == b[6]: reasons.append('repeated_dma_bank')
            if ticks not in (0,1) or cycles <= 0: reasons.append('ambiguous_timer_interval')
            if reasons:
                boundaries.append({'before_sequence': row['sequence'], 'reasons': reasons})
                groups.append(current); current = []
        current.append(row)
    if current: groups.append(current)
    segments = []
    for group in groups:
        result = {'first_sequence': group[0]['sequence'], 'last_sequence': group[-1]['sequence'],
                  'records': len(group), 'epoch': group[0]['epoch_before'],
                  'nominal_projection_available': len(group) >= 2}
        if len(group) >= 2:
            observations = [r['observations'] for r in group]
            cycles = [((b[0]-a[0])&0xffffffff)*32001+a[1]-b[1] for a,b in zip(observations,observations[1:])]
            result.update(assumed_clock_hz=32000000, timer_period_cycles=32001,
                          interval_cycles_min=min(cycles), interval_cycles_max=max(cycles),
                          first_to_last_cycles=sum(cycles), first_to_last_seconds=sum(cycles)/32000000,
                          mean_block_microseconds=statistics.mean(cycles)/32,
                          sample_rate_hz=(len(group)-1)*36*32000000/sum(cycles))
        segments.append(result)
    return segments,excluded,boundaries


def stream_statistics(records):
    result = {}
    for name in ('stream_a','stream_b'):
        values = [v for row in records for v in row[name]]
        result[name] = {'samples': len(values), 'min': min(values) if values else None,
                        'max': max(values) if values else None,
                        'mean': statistics.mean(values) if values else None,
                        'rms': math.sqrt(statistics.mean(v*v for v in values)) if values else None,
                        'zero_samples': values.count(0),
                        'rail_samples': sum(v in (-32768,32767) for v in values)}
    return result


def recorder_matches(prefix, records, segments):
    matches = []
    for segment in segments:
        first,last = segment['first_sequence'],segment['last_sequence']
        for name in ('stream_a','stream_b'):
            values = [v for row in records[first:last+1] for v in row[name]][::6]
            if len(values) < 60 or len(set(values[:60])) < 8: continue
            for gain in ('unity','181/256_toward_zero'):
                transformed = values if gain == 'unity' else [(abs(v)*181//256)*(1 if v>=0 else -1) for v in values]
                raw = struct.pack('<'+'h'*len(transformed),*transformed)
                start = 0
                while True:
                    at = prefix.find(raw[:120],start)
                    if at < 0: break
                    start = at+1
                    if at%2: continue
                    count = 60
                    while count < len(values) and at+(count+1)*2 <= len(prefix) and prefix[at+count*2:at+(count+1)*2] == raw[count*2:(count+1)*2]:
                        count += 1
                    matches.append({'stream': name, 'stride': 6, 'phase': 0, 'gain': gain,
                                    'first_capture_sequence': first, 'last_capture_sequence': last,
                                    'wav_sample_index': at//2, 'matching_samples': count})
    return matches


def analyze(data):
    audio,chunks = wav_payload(data)
    storage = recover(audio)
    decoded = decode_storage(storage)
    records = decoded['records']
    observations = [row['observations'] for row in records]
    if any(o[6] not in BANKS for o in observations): raise ValueError('Unknown DMA bank identifier')
    segments,excluded,boundaries = timing_segments(records)
    complete = decoded['status'] == 2
    project = complete and len(segments) == 1 and segments[0]['records'] == len(records) and segments[0]['nominal_projection_available']
    timing = {'full_capture_projection_available': project, 'segments': segments,
              'excluded_records': excluded, 'boundaries': boundaries}
    if project: timing['sample_rate_hz'] = segments[0]['sample_rate_hz']
    first_frame = audio.find(MAGIC)
    return {'schema_version': 2, 'recording_sha256': sha(data), 'recording_bytes': len(data),
            'wav': {'chunks': chunks, 'audio_bytes': len(audio), 'duration_seconds': len(audio)/16000},
            'capture_sha256': sha(storage), 'capture_bytes': len(storage),
            'export_complete': True, 'capture_status': decoded['status'],
            'capture_outcome': STATUS_NAMES[decoded['status']], 'capture_full': complete,
            'records': len(records), 'diagnostic_frames': FRAME_COUNT, 'first_frame_audio_byte': first_frame,
            'flag_counts': {name: sum(bool(row['flags']&bit) for row in records) for bit,name in FLAG_NAMES.items()},
            'bank_counts': {hex(k):v for k,v in Counter(o[6] for o in observations).items()},
            'adjacent_same_bank': sum(a[6]==b[6] for a,b in zip(observations,observations[1:])),
            'raw_streams': stream_statistics(records), 'timing': timing,
            'recorder_matches': recorder_matches(audio[:first_frame],records,segments),
            'observation_fields': OBSERVATION_FIELDS, 'epoch_fields': ['number','reason','exhausted'],
            'record_details': records,
            'limits': ['Complete export is not a full capture; full capture is not proof of continuous acquisition.',
                       'Raw stream statistics include flagged records; nested-callback samples may be mixed.',
                       'Segments exclude observed faults and ambiguous timing, but cannot rule out unobserved losses or an even number of missed banks.',
                       'Nominal projections assume a 32 MHz clock and serviced timer epochs. They are not UTC or calibrated acquisition timestamps.',
                       'Clock observations follow extraction; SSI words are non-atomic raw register snapshots, not completed-bank frame phase.',
                       'SSI-unavailable flag 16 does not by itself invalidate independent timer observations.',
                       'Recorder matches apply only within the reported segment and observed configuration; no all-mode or calibrated gain claim follows.',
                       'No runtime memory ownership, stack headroom or interrupt margin is established by this report.']}


def report(path):
    path = Path(path)
    def identity():
        st = path.stat()
        return st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns
    sources = [Path(__file__).with_name(name) for name in (
        'native_capture_v2_report.py','native_capture_report.py','native_capture_v2.py',
        'native_capture.py','native_transport_v2.py','native_transport.py','reporting.py')]
    hashes = {str(p):sha(p.read_bytes()) for p in sources}
    before = identity(); data = path.read_bytes()
    result = analyze(data)
    if identity() != before or sha(path.read_bytes()) != sha(data): raise ValueError('Recording changed during inspection')
    if hashes != {str(p):sha(p.read_bytes()) for p in sources}: raise ValueError('Analysis source changed during inspection')
    result.update(input_unchanged=True,input_path=str(path.resolve()),tool_sha256=hashes)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists(): raise SystemExit('Refusing to overwrite an existing report')
    atomic_json(args.output,report(args.recording))
    print(args.output)


if __name__ == '__main__': main()
