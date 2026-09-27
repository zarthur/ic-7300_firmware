#!/usr/bin/env python3
"""Bounded, input-only USB capture. Never opens serial or audio output devices."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import wave

from firmware import revision

RATE = 48000
OUT_RATE = 12000
BLOCK = 4800
ROOT = Path(__file__).resolve().parents[1]


def select_input(devices, name):
    matches = [(i, d) for i, d in enumerate(devices)
               if d['name'] == name and d['max_input_channels'] >= 2]
    if len(matches) != 1:
        raise ValueError('Require exactly one matching stereo input; found %d' % len(matches))
    return matches[0]


def slot_ranges(start_utc, frames, rate=OUT_RATE):
    """Full UTC slots only; rounding error is at most half an output sample."""
    slot = math.ceil(start_utc / 15) * 15
    while True:
        offset = round((slot - start_utc) * rate)
        if offset + 15 * rate > frames:
            return
        yield slot, offset, offset + 15 * rate
        slot += 15


def timing_report(blocks, rate=RATE):
    # Rows: first sample index, ADC timestamp, callback timestamp, status flag.
    valid = all(math.isfinite(row[1]) and row[1] > 0 for row in blocks)
    residuals = [b[1] - a[1] - (b[0] - a[0]) / rate
                 for a, b in zip(blocks, blocks[1:])]
    maximum = max((abs(x) for x in residuals), default=0.0)
    flagged = sum(bool(row[3]) for row in blocks)
    return dict(adc_timestamps_valid=valid, flagged_blocks=flagged,
                max_timestamp_residual_seconds=maximum,
                continuity_ok=bool(blocks) and valid and not flagged and maximum <= 0.001,
                limitation='Host ADC timestamps/status cannot prove absence of upstream radio gaps.')


def convert(samples, channel):
    import numpy as np
    from scipy.signal import resample_poly
    if samples.ndim != 2 or channel not in range(samples.shape[1]):
        raise ValueError('Invalid channel or sample layout')
    # Whole-record zero-phase FIR; SciPy compensates the filter group delay.
    # Boundary extension is zero; exclude the first/last 10 ms from slot export.
    values = resample_poly(samples[:, channel].astype(np.float64), 1, 4,
                           window=('kaiser', 5.0), padtype='constant')
    clipped = int(np.count_nonzero((values < -32768) | (values > 32767)))
    return np.clip(np.rint(values), -32768, 32767).astype('<i2'), clipped


def write_wav(path, samples, rate, channels):
    with path.open('xb') as handle:
        with wave.open(handle, 'wb') as wav:
            wav.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
            wav.writeframes(samples.astype('<i2', copy=False).tobytes())


def compare_slots(directory, jt9):
    results = []
    for path in sorted(directory.glob('slots/*.wav')):
        sandbox = directory / ('decode-' + path.stem)
        sandbox.mkdir()
        record = dict(file=str(path.relative_to(directory)),
                      sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for name, command in (
            ('prototype', [ROOT / 'build/ft8_proto', 'decode', path]),
            ('wsjtx', [jt9, '-8', '-p', '15', '-d', '3', '-a', sandbox, '-t', sandbox, path])):
            result = subprocess.run(list(map(str, command)), cwd=sandbox,
                                    capture_output=True, text=True, timeout=90)
            (sandbox / (name + '.stdout.txt')).write_text(result.stdout)
            (sandbox / (name + '.stderr.txt')).write_text(result.stderr)
            record[name] = dict(returncode=result.returncode)
            if name == 'prototype':
                rows = [json.loads(x) for x in result.stdout.splitlines() if x.startswith('{')]
                messages = [x['message'] for x in rows if 'message' in x]
            else:
                messages = [x.split('~', 1)[1].strip().split('   ')[0].strip()
                            for x in result.stdout.splitlines() if '~' in x]
            record[name]['messages'] = messages
        results.append(record)
    report = dict(slots=results, decoder_errors=sum(
                      item[name]['returncode'] != 0 for item in results for name in ('prototype', 'wsjtx')),
                  reference_sha256=hashlib.sha256(jt9.read_bytes()).hexdigest(),
                  prototype_sha256=hashlib.sha256((ROOT / 'build/ft8_proto').read_bytes()).hexdigest(),
                  limitation='UTC derived from host clock; absolute UTC accuracy not verified.')
    (directory / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def capture(args):
    import numpy as np
    import sounddevice as sd
    index, device = select_input(sd.query_devices(), args.device_name)
    sd.check_input_settings(device=index, channels=2, dtype='int16', samplerate=RATE)
    total = round(args.seconds * RATE)
    samples = np.empty((total, 2), dtype=np.int16)
    timing = np.zeros((math.ceil(total / BLOCK) + 2, 4), dtype=np.float64)
    position = 0
    count = 0

    def callback(data, frames, times, status):
        nonlocal position, count
        if count >= len(timing):
            raise sd.CallbackAbort
        take = min(frames, total - position)
        samples[position:position + take] = data[:take]
        timing[count] = position, times.inputBufferAdcTime, times.currentTime, bool(status)
        position += take
        count += 1
        if position == total:
            raise sd.CallbackStop

    args.output.mkdir(parents=True, exist_ok=False)
    began_wall, began_mono = time.time(), time.monotonic()
    with sd.InputStream(device=index, samplerate=RATE, channels=2, dtype='int16',
                        blocksize=BLOCK, callback=callback, latency='high') as stream:
        before = time.time()
        stream_clock = stream.time
        after = time.time()
        utc_offset = (before + after) / 2 - stream_clock
        latency = stream.latency
        actual_rate = stream.samplerate
        while stream.active and time.monotonic() - began_mono < args.seconds + 10:
            time.sleep(0.1)
    elapsed = time.monotonic() - began_mono
    wall_drift = time.time() - began_wall - elapsed
    blocks = timing[:count].tolist()
    report = timing_report(blocks)
    report.update(requested_frames=total, captured_frames=position,
                  complete=position == total, wall_elapsed_seconds=elapsed,
                  host_wall_vs_monotonic_drift_seconds=wall_drift,
                  clock_mapping_bracket_seconds=after - before,
                  input_latency_seconds=latency, device=dict(device), device_index=index,
                  actual_stream_rate=actual_rate, source_revision=revision(),
                  tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  portaudio_version=sd.get_portaudio_version(),
                  source_association='USB device selected; operator source verification pending',
                  input_rate=RATE, input_channels=2, selected_channel=args.channel,
                  versions={p: importlib.metadata.version(p) for p in ('sounddevice', 'numpy', 'scipy')},
                  resampling='48 to 12 kHz, Kaiser 5.0 polyphase FIR, group delay compensated; zero extension',
                  utc_accuracy='Unverified host clock; not radio RTC or a TX timing qualification')
    report['alignment_usable'] = (report['complete'] and report['continuity_ok']
                                  and actual_rate == RATE
                                  and abs(wall_drift) <= 0.1 and after - before <= 0.01)
    raw = samples[:position]
    report['channel_statistics'] = [dict(
        rms_pcm=float(np.sqrt(np.mean(raw[:, c].astype(np.float64) ** 2))) if position else None,
        peak_pcm=int(np.max(np.abs(raw[:, c].astype(np.int32)))) if position else None,
        clipped_samples=int(np.count_nonzero((raw[:, c] == -32768) | (raw[:, c] == 32767))))
        for c in range(2)]
    write_wav(args.output / 'raw-stereo.wav', raw, RATE, 2)
    if position:
        mono, clipped = convert(raw, args.channel)
        report['resampling_clipped_samples'] = clipped
        write_wav(args.output / 'mono-12k.wav', mono, OUT_RATE, 1)
        report['first_sample_host_utc'] = blocks[0][1] + utc_offset
        if report['alignment_usable']:
            (args.output / 'slots').mkdir()
            for slot, start, end in slot_ranges(report['first_sample_host_utc'], len(mono)):
                if start < 120 or end > len(mono) - 120:
                    continue
                filename = datetime.fromtimestamp(slot, timezone.utc).strftime('%y%m%d_%H%M%S.wav')
                write_wav(args.output / 'slots' / filename, mono[start:end], OUT_RATE, 1)
    report['wav_sha256'] = {str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in args.output.rglob('*.wav')}
    (args.output / 'timestamps.json').write_text(json.dumps(blocks) + '\n')
    (args.output / 'capture.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--device-name', help='Exact input device name; no default device fallback')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--channel', type=int, choices=(0, 1), default=0)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--jt9', type=Path, help='Optional independent decoder for exported full slots')
    parser.add_argument('--capture-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.list:
        import sounddevice as sd
        print(sd.query_devices())
        return
    if not args.device_name or not args.output or not 1 <= args.seconds <= 600:
        parser.error('Require --device-name, new --output directory and --seconds between 1 and 600')
    args.output = args.output.resolve()
    if args.jt9:
        args.jt9 = args.jt9.resolve()
        if not args.jt9.is_file() or not (ROOT / 'build/ft8_proto').is_file():
            parser.error('Both decoder binaries must exist')
    if args.capture_worker:
        capture(args)
        return
    if args.output.exists():
        parser.error('Output directory already exists; select a new directory')
    # Core Audio can block during permission negotiation even before stream open.
    # A separate process bounds initialization as well as capture/stream shutdown.
    command = [sys.executable, str(Path(__file__).resolve()), '--capture-worker',
               '--device-name', args.device_name, '--seconds', str(args.seconds),
               '--channel', str(args.channel), '--output', str(args.output)]
    try:
        result = subprocess.run(command, timeout=args.seconds + 20)
    except subprocess.TimeoutExpired:
        args.output.mkdir(parents=True, exist_ok=True)
        failure = dict(outcome='TIMEOUT', requested_seconds=args.seconds,
                       recorded_at_utc=datetime.now(timezone.utc).isoformat(),
                       reason='Audio initialization, capture or shutdown stalled; permission/backend cause unconfirmed',
                       next_step='Check macOS Microphone permission for the capture process, then retry into a new directory')
        (args.output / 'failure.json').write_text(json.dumps(failure, indent=2) + '\n')
        raise SystemExit(failure['reason'])
    if result.returncode:
        raise SystemExit(result.returncode)
    report = json.loads((args.output / 'capture.json').read_text())
    if args.jt9 and report['alignment_usable']:
        comparison = compare_slots(args.output, args.jt9)
        if comparison['decoder_errors']:
            raise SystemExit('Decoder failure; inspect comparison.json and decoder logs')
    if not report['alignment_usable']:
        raise SystemExit('Capture retained for diagnosis; continuity/alignment checks did not pass')


if __name__ == '__main__':
    main()
