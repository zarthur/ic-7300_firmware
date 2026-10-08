"""Source-labeled stream-A ingress stays separate from recorder PCM."""
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import native_capture_v2 as capture
import native_stream_decode as decoder

EXE = Path(os.environ.get('FT8_PROTO', ROOT / 'build/ft8_proto')).resolve()


def v2_storage(flags=0, sample=0, status=2, count=capture.CAPACITY):
    before = (1, 100, 0)
    after = (1, 100, 0)
    if flags & 4:
        before = (1, 100, 1)
        after = before
    observations = (1, 100, 0, 1, 100, 0, 0x203fb180, 0, 0, 0, 0, 0)
    if flags & 16:
        observations = observations[:7] + (0xffffffff,) * 5
    row = []
    for sequence in range(count):
        stream_a = [sample] * decoder.SAMPLES_PER_V2_RECORD
        stream_b = [0] * decoder.SAMPLES_PER_V2_RECORD
        row.append(struct.pack('<20I72h', sequence, flags, *before, *after,
                               *observations, *stream_a, *stream_b))
    empty = struct.pack('<20I72h', *([0] * 92))
    row.extend([empty] * (capture.CAPACITY - count))
    return (struct.pack('<4I', status, count, capture.MAGIC, capture.VERSION)
            + b''.join(row))


def blocks_from_samples(samples, block_samples=36, source=decoder.SOURCE,
                        stream_id='synthetic-slot', rate=48000.0):
    samples = np.asarray(samples, dtype='<i2')
    if len(samples) % block_samples:
        raise ValueError('fixture sample count must fit whole blocks')
    result = []
    for sequence, start in enumerate(range(0, len(samples), block_samples)):
        values = samples[start:start + block_samples]
        result.append(decoder.NativeSampleBlock(
            source=source,
            stream_id=stream_id,
            sequence=sequence,
            first_sample_index=start,
            sample_rate_hz=rate,
            sample_rate_basis='synthetic',
            pcm16le=values.tobytes(),
        ))
    return result


class NativeStreamDecodeTests(unittest.TestCase):
    def test_existing_v2_export_is_source_labeled_and_too_short_for_a_slot(self):
        result = decoder.analyze_v2_storage(v2_storage(sample=123), 48000, 'nominal')
        self.assertEqual(result['source'], 'native_stream_a')
        self.assertEqual(result['sample_index_scope'], 'capture-relative')
        self.assertEqual(result['source_sample_count'], 512 * 36)
        self.assertEqual(result['decoder_sample_count'], 4608)
        self.assertEqual(result['minimum_source_samples_at_declared_rate'], 720000)
        self.assertEqual(result['status'], 'insufficient_samples')
        self.assertEqual(result['windows'], [])
        self.assertNotIn('slot_utc_ms', result)
        self.assertNotIn('utc_ms', result)

    def test_v2_export_rejects_incomplete_or_faulted_record_sequence(self):
        with self.assertRaisesRegex(ValueError, 'complete frozen'):
            decoder.blocks_from_v2_storage(v2_storage(flags=8, status=5, count=1),
                                           48000, 'nominal')
        with self.assertRaisesRegex(ValueError, 'epoch, loss or nested'):
            decoder.blocks_from_v2_storage(v2_storage(flags=4), 48000, 'nominal')

    def test_explicit_ssi_unavailable_flag_does_not_mix_stream_sources(self):
        blocks = decoder.blocks_from_v2_storage(v2_storage(flags=16), 48000, 'nominal')
        self.assertEqual(len(blocks), capture.CAPACITY)
        self.assertTrue(all(block.source == 'native_stream_a' for block in blocks))
        result = decoder.analyze_blocks(blocks)
        self.assertEqual(result['quality_flag_counts']['ssi_observations_unavailable'],
                         capture.CAPACITY)

    def test_requires_explicit_source_rate_and_sample_index_contract(self):
        good = blocks_from_samples(np.zeros(72, dtype='<i2'))
        for bad in (blocks_from_samples(np.zeros(72, dtype='<i2'), source='recorder_audio_pcm'),
                    [good[0], decoder.NativeSampleBlock(**{**good[1].__dict__, 'stream_id': 'other'})],
                    [good[0], decoder.NativeSampleBlock(**{**good[1].__dict__, 'sequence': 3})],
                    [good[0], decoder.NativeSampleBlock(**{**good[1].__dict__, 'first_sample_index': 40})],
                    [good[0], decoder.NativeSampleBlock(**{**good[1].__dict__, 'sample_rate_hz': 44100})]):
            with self.subTest(blocks=bad[0] if isinstance(bad, list) else bad):
                with self.assertRaises(ValueError):
                    decoder.analyze_blocks(bad)
        bad_basis = [decoder.NativeSampleBlock(**{**good[0].__dict__, 'sample_rate_basis': 'unknown'})]
        with self.assertRaisesRegex(ValueError, 'sample-rate basis'):
            decoder.analyze_blocks(bad_basis)
        unknown_flags = [decoder.NativeSampleBlock(**{**good[0].__dict__, 'quality_flags': 32})]
        with self.assertRaisesRegex(ValueError, 'unknown quality flags'):
            decoder.analyze_blocks(unknown_flags)

    @unittest.skipUnless(EXE.is_file(), 'build the FT8 prototype first')
    def test_synthetic_full_native_rate_slot_reaches_decoder(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.wav'
            subprocess.run([str(EXE), 'generate', 'CQ K1ABC FN42', str(source)],
                           check=True, capture_output=True, text=True)
            with wave.open(str(source), 'rb') as wav:
                samples_12k = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
            samples_48k = resample_poly(samples_12k.astype(np.float64), 4, 1,
                                        window=('kaiser', 5.0), padtype='constant')
            samples_48k = np.clip(np.rint(samples_48k), -32768, 32767).astype('<i2')
            blocks = blocks_from_samples(samples_48k, block_samples=36)
            result = decoder.analyze_blocks(blocks, EXE)

        self.assertEqual(result['status'], 'decoded')
        self.assertEqual(result['source'], 'native_stream_a')
        self.assertEqual(result['source_sample_count'], 720000)
        self.assertEqual(result['decoder_sample_count'], decoder.SLOT_SAMPLES)
        self.assertEqual(len(result['windows']), 1)
        messages = [row['message'] for window in result['windows']
                    for row in window['messages']]
        self.assertIn('CQ K1ABC FN42', messages)
        self.assertNotIn('slot_utc_ms', result['windows'][0]['messages'][0])


if __name__ == '__main__':
    unittest.main()
