#!/usr/bin/env python3
"""Host-side FT8 ingress for explicitly labeled native stream-A PCM blocks.

This path is deliberately separate from recorder WAVE audio. Callers must
provide the source rate and contiguous sample indices; this module assigns no
UTC or FT8 slot phase.
"""
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import wave

import numpy as np
from scipy.signal import resample_poly

from native_capture_v2 import CAPACITY, decode_storage

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'native_stream_a'
SAMPLE_FORMAT = 'pcm_s16le'
DECODER_RATE = 12000
SLOT_SAMPLES = 180000
WINDOW_HOP = 12000
SAMPLES_PER_V2_RECORD = 36
RATE_BASES = ('measured', 'nominal', 'synthetic')


@dataclass(frozen=True)
class NativeSampleBlock:
    """One source-labeled PCM block from a single continuity segment.

    `first_sample_index` is in the declared native-rate sample domain. The
    `stream_id` identifies one continuous segment; a new ID is required after
    any unproven gap, reset, overrun or source change.
    """
    source: str
    stream_id: str
    sequence: int
    first_sample_index: int
    sample_rate_hz: float
    sample_rate_basis: str
    pcm16le: bytes
    sample_format: str = SAMPLE_FORMAT
    sample_index_scope: str = 'stream-relative'
    quality_flags: int = 0


def _integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'Invalid {name}')
    return value


def _rate(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Require an explicit native sample rate')
    if not math.isfinite(value) or value <= 0 or value > 1000000:
        raise ValueError('Invalid native sample rate')
    return float(value)


def validate_blocks(blocks):
    """Validate one source, rate and continuous sample-indexed block run."""
    try:
        rows = list(blocks)
    except TypeError as exc:
        raise ValueError('Require an iterable of native sample blocks') from exc
    if not rows:
        raise ValueError('Require at least one native sample block')

    first = rows[0]
    if not isinstance(first, NativeSampleBlock):
        raise ValueError('Require NativeSampleBlock inputs')
    if first.source != SOURCE:
        raise ValueError('Require explicitly labeled native stream A')
    if not isinstance(first.stream_id, str) or not first.stream_id:
        raise ValueError('Require a stream ID for this continuity segment')
    rate = _rate(first.sample_rate_hz)
    if not isinstance(first.sample_rate_basis, str) or first.sample_rate_basis not in RATE_BASES:
        raise ValueError('Require an explicit sample-rate basis')
    if first.sample_index_scope not in ('stream-relative', 'capture-relative'):
        raise ValueError('Require an explicit sample-index scope')

    expected_sequence = None
    expected_sample = None
    count = 0
    byte_parts = []
    for block in rows:
        if not isinstance(block, NativeSampleBlock):
            raise ValueError('Require NativeSampleBlock inputs')
        if block.source != first.source:
            raise ValueError('Cannot mix native stream A with another audio source')
        if block.stream_id != first.stream_id:
            raise ValueError('Cannot join distinct stream continuity segments')
        if block.sample_format != SAMPLE_FORMAT:
            raise ValueError('Require signed little-endian PCM16 samples')
        if _rate(block.sample_rate_hz) != rate or block.sample_rate_basis != first.sample_rate_basis:
            raise ValueError('Native sample-rate metadata changed within the stream')
        if block.sample_index_scope != first.sample_index_scope:
            raise ValueError('Sample-index scope changed within the stream')
        sequence = _integer(block.sequence, 'block sequence')
        sample = _integer(block.first_sample_index, 'first sample index')
        flags = _integer(block.quality_flags, 'quality flags')
        if flags & ~0x1f:
            raise ValueError('Block contains unknown quality flags')
        if flags & 0x0f:
            raise ValueError('Block quality flags indicate an epoch, loss or nested-callback boundary')
        if expected_sequence is not None and sequence != expected_sequence:
            raise ValueError('Missing, duplicate or reordered native block sequence')
        if expected_sample is not None and sample != expected_sample:
            raise ValueError('Native stream has a sample-index gap or overlap')
        if not isinstance(block.pcm16le, bytes) or not block.pcm16le or len(block.pcm16le) % 2:
            raise ValueError('Require non-empty whole PCM16 samples')
        samples = len(block.pcm16le) // 2
        count += samples
        expected_sequence = sequence + 1
        expected_sample = sample + samples
        byte_parts.append(block.pcm16le)
    return rows, b''.join(byte_parts), count, rate


def _resampling_ratio(sample_rate_hz):
    ratio = Fraction(DECODER_RATE / sample_rate_hz).limit_denominator(100000)
    if ratio.numerator > 100000 or ratio.denominator > 100000:
        raise ValueError('Native sample rate cannot be represented by a bounded resampling ratio')
    return ratio.numerator, ratio.denominator


def _window_starts(count):
    if count < SLOT_SAMPLES:
        return []
    last = count - SLOT_SAMPLES
    starts = list(range(0, last + 1, WINDOW_HOP))
    if starts[-1] != last:
        starts.append(last)
    return starts


def _write_window(path, samples):
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, DECODER_RATE, 0, 'NONE', 'not compressed'))
        output.writeframes(samples.astype('<i2', copy=False).tobytes())


def _decode_window(exe, samples):
    with tempfile.TemporaryDirectory(prefix='native-stream-a-ft8-') as directory:
        wav_path = Path(directory) / 'window.wav'
        _write_window(wav_path, samples)
        result = subprocess.run([str(exe), 'inspect', str(wav_path)],
                                capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise ValueError('FT8 decoder failed on a validated stream-A window')
        rows = [json.loads(line) for line in result.stdout.splitlines()
                if line.startswith('{')]
        messages = [{key: row[key] for key in ('message', 'frequency_hz', 'sync_score')
                     if key in row} for row in rows if 'message' in row]
        metrics = [row for row in rows if 'decoded_count' in row]
        if len(metrics) != 1:
            raise ValueError('FT8 decoder did not return one completion record')
        return messages, metrics[0]['decoded_count']


def analyze_blocks(blocks, exe=None):
    """Resample and decode only complete 15-second windows from stream A.

    Short but valid captures return `insufficient_samples` without invoking the
    decoder. Discontinuities fail before samples are concatenated.
    """
    rows, raw, input_count, rate = validate_blocks(blocks)
    up, down = _resampling_ratio(rate)
    source = np.frombuffer(raw, dtype='<i2').astype(np.float64)
    converted = resample_poly(source, up, down, window=('kaiser', 5.0),
                              padtype='constant')
    rounded = np.rint(converted)
    clipped = int(np.count_nonzero((rounded < -32768) | (rounded > 32767)))
    converted = np.clip(rounded, -32768, 32767).astype('<i2')
    starts = _window_starts(len(converted))

    result = {
        'schema_version': 1,
        'source': SOURCE,
        'sample_format': SAMPLE_FORMAT,
        'stream_id': rows[0].stream_id,
        'sample_index_scope': rows[0].sample_index_scope,
        'first_sample_index': rows[0].first_sample_index,
        'last_sample_index_exclusive': rows[-1].first_sample_index + len(rows[-1].pcm16le) // 2,
        'block_count': len(rows),
        'source_sample_count': input_count,
        'source_sample_rate_hz': rate,
        'sample_rate_basis': rows[0].sample_rate_basis,
        'quality_flag_counts': {
            'ssi_observations_unavailable': sum(bool(row.quality_flags & 16) for row in rows),
        },
        'decoder_rate_hz': DECODER_RATE,
        'resampling_ratio': {'up': up, 'down': down},
        'resampling_clipped_samples': clipped,
        'decoder_sample_count': int(len(converted)),
        'minimum_decoder_window_samples': SLOT_SAMPLES,
        'window_hop_samples_12khz': WINDOW_HOP,
        'window_origin': 'relative to the first supplied stream-A sample; no UTC mapping',
        'windows': [],
        'decoded_count': 0,
        'limitations': [
            'The supplied sample rate and continuity metadata are inputs; this tool does not qualify them.',
            'Native sample indices are not UTC or FT8 slot phase.',
            'Decoded messages come only from the explicitly labeled native_stream_a input blocks.',
        ],
    }
    if not starts:
        result['status'] = 'insufficient_samples'
        result['minimum_source_samples_at_declared_rate'] = math.ceil(rate * SLOT_SAMPLES / DECODER_RATE)
        return result

    decoder = Path(exe or ROOT / 'build/ft8_proto').resolve()
    if not decoder.is_file():
        raise ValueError('Offline FT8 decoder executable is unavailable')
    for index, start in enumerate(starts):
        messages, count = _decode_window(decoder, converted[start:start + SLOT_SAMPLES])
        result['windows'].append({'window_index': index,
                                  'start_sample_12khz': start,
                                  'messages': messages,
                                  'decoded_count': count})
        result['decoded_count'] += count
    result['status'] = 'decoded'
    return result


def blocks_from_v2_storage(storage, sample_rate_hz, sample_rate_basis):
    """Extract only validated stream A from one complete fixed v2 export.

    The sequence-derived sample origin is capture-relative. This does not
    extend the firmware's fixed 512-record storage or join separate exports.
    """
    decoded = decode_storage(storage)
    if decoded['status'] != 2 or decoded['count'] != CAPACITY:
        raise ValueError('Require one complete frozen v2 capture')
    records = decoded['records']
    if any(row['flags'] & 0x0f for row in records):
        raise ValueError('Capture flags indicate an epoch, loss or nested-callback boundary')
    stream_id = hashlib.sha256(storage).hexdigest()
    blocks = []
    for row in records:
        sequence = row['sequence']
        samples = row['stream_a']
        if len(samples) != SAMPLES_PER_V2_RECORD:
            raise ValueError('Unexpected native stream-A record length')
        blocks.append(NativeSampleBlock(
            source=SOURCE,
            stream_id=stream_id,
            sequence=sequence,
            first_sample_index=sequence * SAMPLES_PER_V2_RECORD,
            sample_rate_hz=sample_rate_hz,
            sample_rate_basis=sample_rate_basis,
            sample_index_scope='capture-relative',
            quality_flags=row['flags'],
            pcm16le=struct.pack('<36h', *samples),
        ))
    return blocks


def analyze_v2_storage(storage, sample_rate_hz, sample_rate_basis, exe=None):
    """Convenience path from exact v2 storage into the stream-A decoder."""
    blocks = blocks_from_v2_storage(storage, sample_rate_hz, sample_rate_basis)
    result = analyze_blocks(blocks, exe)
    result['capture_storage_sha256'] = hashlib.sha256(storage).hexdigest()
    result['capture_status'] = 'full'
    result['capture_records'] = CAPACITY
    return result
