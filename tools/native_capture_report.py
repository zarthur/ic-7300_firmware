#!/usr/bin/env python3
"""Read-only analysis of one complete native diagnostic recording."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct

from native_capture import decode_storage
from native_transport import recover, MAGIC
from reporting import atomic_json

BANKS = (0x203fb180, 0x203fb3c0)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wav_payload(data):
    """Require a complete mono PCM16/8k RIFF file; never rewrite a damaged input."""
    if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('Not a RIFF WAVE file')
    if struct.unpack_from('<I', data, 4)[0]+8 != len(data):
        raise ValueError('RIFF length does not match file')
    offset = 12
    chunks = []
    audio = None
    fmt = None
    while offset < len(data):
        if offset+8 > len(data):
            raise ValueError('Truncated chunk header')
        tag, size = struct.unpack_from('<4sI', data, offset)
        end = offset+8+size
        if end+(size&1) > len(data):
            raise ValueError('Truncated chunk or padding')
        body = data[offset+8:end]
        if tag == b'fmt ':
            if fmt is not None or len(body) < 16:
                raise ValueError('Invalid or duplicate format chunk')
            fmt = struct.unpack_from('<HHIIHH', body)
        if tag == b'data':
            if audio is not None or size%2:
                raise ValueError('Invalid or duplicate audio chunk')
            audio = body
        chunks.append({'tag': tag.decode('ascii', errors='replace'), 'offset': offset, 'bytes': size})
        offset = end+(size&1)
    if fmt != (1, 1, 8000, 16000, 2, 16) or audio is None:
        raise ValueError('Require mono PCM16 at 8000 Hz')
    return audio, chunks


def analyze(data):
    audio, chunks = wav_payload(data)
    storage = recover(audio)
    decoded = decode_storage(storage)
    records = decoded['records']
    observations = [row['observations'] for row in records]
    if any(o[6] not in BANKS for o in observations):
        raise ValueError('Unknown DMA bank identifier')
    streams = {}
    for name in ('stream_a', 'stream_b'):
        values = [v for row in records for v in row[name]]
        streams[name] = {'samples': len(values), 'min': min(values), 'max': max(values),
                         'mean': statistics.mean(values),
                         'rms': math.sqrt(statistics.mean(v*v for v in values)),
                         'zero_samples': values.count(0),
                         'rail_samples': sum(v in (-32768, 32767) for v in values)}
    clean = all(o[0] == o[3] and not ((o[2]|o[5])&64) and
                0 <= o[4] <= o[1] <= 32000 for o in observations)
    tick_deltas = [(b[0]-a[0])&0xffffffff for a, b in zip(observations, observations[1:])]
    cycles = [ticks*32001+a[1]-b[1] for ticks, a, b in zip(tick_deltas, observations, observations[1:])]
    # This projection explicitly assumes the recovered clock scale and serviced
    # timer epochs. Ambiguous snapshots or large epoch gaps suppress the estimate.
    project = clean and all(t in (0, 1) for t in tick_deltas) and min(cycles) > 0
    timing = {'clean_snapshot_fields': clean,
              'tick_delta_counts': dict(Counter(tick_deltas)),
              'pending_before': sum(bool(o[2]&64) for o in observations),
              'pending_after': sum(bool(o[5]&64) for o in observations),
              'tick_changes_during_snapshot': sum(o[0] != o[3] for o in observations),
              'nominal_projection_available': project}
    if project:
        timing.update(assumed_clock_hz=32000000, timer_period_cycles=32001,
                      interval_cycles_min=min(cycles), interval_cycles_max=max(cycles),
                      first_to_last_cycles=sum(cycles),
                      first_to_last_seconds=sum(cycles)/32000000,
                      mean_block_microseconds=statistics.mean(cycles)/32,
                      sample_rate_hz=(len(records)-1)*36*32000000/sum(cycles))
    # Search only ordinary audio preceding the diagnostic section. Require a
    # distinctive 60-sample prefix and report ALL matches, rather than choosing
    # a best correlation or interpreting silence as channel identity.
    prefix = audio[:audio.find(MAGIC)]
    matches = []
    for name in ('stream_a', 'stream_b'):
        values = [v for row in records for v in row[name]][::6]
        if len(set(values[:60])) < 8:
            continue
        for gain in ('unity', '181/256_toward_zero'):
            transformed = values if gain == 'unity' else [
                (abs(v)*181//256)*(1 if v >= 0 else -1) for v in values]
            raw = struct.pack('<'+'h'*len(transformed), *transformed)
            start = 0
            while True:
                at = prefix.find(raw[:120], start)
                if at < 0:
                    break
                start = at+1
                if at%2:
                    continue
                count = 60
                while count < len(values) and at+(count+1)*2 <= len(prefix) and prefix[at+count*2:at+(count+1)*2] == raw[count*2:(count+1)*2]:
                    count += 1
                matches.append({'stream': name, 'stride': 6, 'phase': 0, 'gain': gain,
                                'wav_sample_index': at//2, 'matching_samples': count})
    return {'schema_version': 1, 'recording_sha256': sha(data), 'recording_bytes': len(data),
            'wav': {'chunks': chunks, 'audio_bytes': len(audio), 'duration_seconds': len(audio)/16000},
            'capture_sha256': sha(storage), 'capture_bytes': len(storage), 'records': len(records),
            'diagnostic_frames': 470, 'first_frame_audio_byte': audio.find(MAGIC),
            'bank_counts': {hex(k): v for k, v in Counter(o[6] for o in observations).items()},
            'adjacent_same_bank': sum(a[6] == b[6] for a, b in zip(observations, observations[1:])),
            'streams': streams, 'timing': timing, 'recorder_matches': matches,
            'limits': ['Full transport/checksum/sequence validity does not prove acquisition continuity.',
                       'Alternating banks cannot exclude an even number of missed banks.',
                       'Time projection assumes 32 MHz and serviced timer epochs; it is not UTC or an independently calibrated sample rate.',
                       'Observations follow extraction, not acquisition; snapshot span excludes the final block duration.',
                       'A recorder match identifies the observed configuration only, not all DSP routes, AF/squelch/AGC settings or RF gain.',
                       'No physical runtime stack, interrupt margin or recovery guarantee follows from a successful capture.']}


def report(path):
    path = Path(path)
    def identity():
        st = path.stat()
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns
    sources = [Path(__file__).with_name(name) for name in
               ('native_capture_report.py', 'native_capture.py', 'native_transport.py', 'reporting.py')]
    hashes = {str(p): sha(p.read_bytes()) for p in sources}
    before = identity()
    data = path.read_bytes()
    result = analyze(data)
    if identity() != before or sha(path.read_bytes()) != sha(data):
        raise ValueError('Recording changed during inspection')
    result['input_unchanged'] = True
    result['input_path'] = str(path.resolve())
    if hashes != {str(p): sha(p.read_bytes()) for p in sources}:
        raise ValueError('Analysis source changed during inspection')
    result['tool_sha256'] = hashes
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite an existing report')
    atomic_json(args.output, report(args.recording))
    print(args.output)


if __name__ == '__main__':
    main()
