#!/usr/bin/env python3
"""Decode only intact recorder audio around a validated native capture carrier.

This tool treats the diagnostic frames as binary transport, never as PCM audio.
It does not join audio on opposite sides of a diagnostic span or assign UTC.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import wave

import numpy as np
from scipy.signal import resample_poly

from native_capture import STORAGE_SIZE
from native_capture_report import wav_payload
from native_transport import FRAME_SIZE, MAGIC, recover
from reporting import atomic_json

ROOT = Path(__file__).resolve().parents[1]
SOURCE_RATE = 8000
DECODER_RATE = 12000
SLOT_SAMPLES = 180000
WINDOW_HOP_SAMPLES = DECODER_RATE


def sha(data):
    return hashlib.sha256(data).hexdigest()


def carrier_spans(audio):
    """Validate one complete carrier and return its byte ranges in WAV data."""
    recovered = recover(audio)
    if len(recovered) != STORAGE_SIZE:
        raise ValueError('Unexpected native capture storage size')
    positions = []
    offset = 0
    while True:
        start = audio.find(MAGIC, offset)
        if start < 0:
            break
        if start % 2:
            raise ValueError('Diagnostic carrier is not PCM sample aligned')
        if start + FRAME_SIZE > len(audio):
            raise ValueError('Truncated diagnostic frame')
        positions.append(start)
        offset = start + FRAME_SIZE

    if not positions:
        raise ValueError('No native diagnostic frames found')
    spans = []
    start = previous = positions[0]
    for position in positions[1:]:
        if position != previous + FRAME_SIZE:
            spans.append((start, previous + FRAME_SIZE))
            start = position
        previous = position
    spans.append((start, previous + FRAME_SIZE))
    return recovered, spans


def ordinary_audio_segments(audio, diagnostic_spans):
    """Keep normal PCM ranges separate so removed carrier time is never hidden."""
    cursor = 0
    segments = []
    for start, end in diagnostic_spans:
        if start < cursor or end > len(audio) or start > end:
            raise ValueError('Invalid diagnostic span inventory')
        if start % 2 or end % 2:
            raise ValueError('Diagnostic span is not PCM sample aligned')
        if start > cursor:
            segments.append((cursor // 2, audio[cursor:start]))
        cursor = end
    if cursor < len(audio):
        if cursor % 2 or len(audio) % 2:
            raise ValueError('Audio segment is not PCM sample aligned')
        segments.append((cursor // 2, audio[cursor:]))
    if not segments and not audio:
        raise ValueError('Recording contains no ordinary PCM audio')
    return [(start, data) for start, data in segments if data]


def resample_pcm16(pcm):
    """Convert one independent 8 kHz PCM16 span to 12 kHz without UTC claims."""
    if len(pcm) % 2:
        raise ValueError('PCM16 span has an odd byte count')
    values = np.frombuffer(pcm, dtype='<i2').astype(np.float64)
    if values.size == 0:
        return np.empty(0, dtype='<i2'), 0
    converted = resample_poly(values, 3, 2, window=('kaiser', 5.0), padtype='constant')
    rounded = np.rint(converted)
    clipped = int(np.count_nonzero((rounded < -32768) | (rounded > 32767)))
    return np.clip(rounded, -32768, 32767).astype('<i2'), clipped


def window_starts(sample_count):
    if sample_count < SLOT_SAMPLES:
        return []
    final = sample_count - SLOT_SAMPLES
    starts = list(range(0, final + 1, WINDOW_HOP_SAMPLES))
    if starts[-1] != final:
        starts.append(final)
    return starts


def write_window(path, samples):
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, DECODER_RATE, 0, 'NONE', 'not compressed'))
        output.writeframes(samples.astype('<i2', copy=False).tobytes())


def decode_window(exe, samples):
    with tempfile.TemporaryDirectory(prefix='native-ft8-window-') as directory:
        wav_path = Path(directory) / 'window.wav'
        write_window(wav_path, samples)
        result = subprocess.run([str(exe), 'inspect', str(wav_path)],
                                capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise ValueError('Offline decoder failed for a validated PCM window')
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        messages = []
        metrics = []
        for row in rows:
            if 'message' in row:
                messages.append({key: row[key] for key in
                                 ('message', 'frequency_hz', 'sync_score') if key in row})
            elif 'decoded_count' in row:
                metrics.append(row)
        if len(metrics) != 1:
            raise ValueError('Offline decoder did not return one completion record')
        return messages, metrics[0]


def source_hashes():
    paths = ('native_capture_decode.py', 'native_capture_report.py',
             'native_capture.py', 'native_transport.py', 'reporting.py')
    return {f'tools/{name}': sha((ROOT / 'tools' / name).read_bytes()) for name in paths}


def analyze_bytes(data, exe):
    if not isinstance(data, bytes):
        raise ValueError('Require immutable recording bytes')
    exe = Path(exe).resolve()
    if not exe.is_file():
        raise ValueError('Offline FT8 decoder executable is unavailable')
    before_exe = sha(exe.read_bytes())
    before_tools = source_hashes()
    audio, chunks = wav_payload(data)
    capture, diagnostic_spans = carrier_spans(audio)
    segments = ordinary_audio_segments(audio, diagnostic_spans)
    segment_reports = []
    for index, (source_sample_start, pcm) in enumerate(segments):
        converted, clipped = resample_pcm16(pcm)
        starts = window_starts(len(converted))
        windows = []
        for window_index, start in enumerate(starts):
            messages, metrics = decode_window(exe, converted[start:start + SLOT_SAMPLES])
            windows.append({'window_index': window_index,
                            'start_sample_12khz': start,
                            'messages': messages,
                            'decoded_count': metrics['decoded_count']})
        segment_reports.append({
            'segment_index': index,
            'source_wav_data_sample_start': source_sample_start,
            'source_sample_count_8khz': len(pcm) // 2,
            'decoder_sample_count_12khz': int(len(converted)),
            'resampling_clipped_samples': clipped,
            'window_count': len(windows),
            'windows': windows,
        })
    if sha(exe.read_bytes()) != before_exe or source_hashes() != before_tools:
        raise ValueError('Decoder or analysis source changed during replay')
    return {
        'schema_version': 1,
        'recording_sha256': sha(data),
        'recording_bytes': len(data),
        'recording_format': {'encoding': 'PCM16', 'channels': 1,
                             'sample_rate_hz': SOURCE_RATE},
        'native_capture_sha256': sha(capture),
        'native_capture_bytes': len(capture),
        'diagnostic_frame_count': sum((end - start) // FRAME_SIZE
                                      for start, end in diagnostic_spans),
        'diagnostic_spans_wav_data_samples': [
            {'start': start // 2, 'count': (end - start) // 2}
            for start, end in diagnostic_spans
        ],
        'resampling': {'from_hz': SOURCE_RATE, 'to_hz': DECODER_RATE,
                       'method': 'scipy.signal.resample_poly', 'up': 3, 'down': 2,
                       'window': 'kaiser 5.0'},
        'window_hop_samples_12khz': WINDOW_HOP_SAMPLES,
        'window_sample_origin': 'relative to each intact audio segment; no UTC mapping',
        'decoder_sha256': before_exe,
        'tool_sha256': before_tools,
        'wav_chunks': chunks,
        'segments': segment_reports,
        'limitations': [
            'Diagnostic carrier bytes are removed only after complete frame, checksum, sequence and padding validation.',
            'Audio on opposite sides of diagnostic spans remains in separate segments.',
            'Window indices are sample-relative; they do not establish UTC, FT8 slot phase or radio timing.',
            '8-to-12 kHz resampling follows the WAVE header and does not establish RF bandwidth, gain or source identity.',
            'An empty decode is not evidence that the native capture path failed.',
        ],
    }


def report(recording, exe):
    recording = Path(recording).resolve()
    before = recording.stat()
    data = recording.read_bytes()
    result = analyze_bytes(data, exe)
    after = recording.stat()
    stamp = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
    if stamp(before) != stamp(after) or sha(recording.read_bytes()) != result['recording_sha256']:
        raise ValueError('Recording changed during offline decode')
    result['input_unchanged'] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--exe', type=Path, default=ROOT / 'build/ft8_proto')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new private evidence path')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = report(args.recording, args.exe)
    atomic_json(args.output, result)
    print(f'Offline native-recording decode: {result["recording_sha256"][:12]} '
          f'({sum(x["window_count"] for x in result["segments"])} windows); {args.output}')


if __name__ == '__main__':
    main()
