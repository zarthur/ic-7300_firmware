"""The validated native carrier stays separate from audio sent to FT8."""
import io
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
import native_capture as capture
import native_capture_decode as decoder
import native_transport as transport

EXE = Path(os.environ.get('FT8_PROTO', ROOT / 'build/ft8_proto')).resolve()


def full_carrier():
    records = b''.join(struct.pack('<8I72h', i, *([0] * 7), *([0] * 72))
                       for i in range(capture.CAPACITY))
    storage = struct.pack('<4I', 2, capture.CAPACITY, 0, 0) + records
    frames = []
    for offset in range(0, len(storage), transport.PAYLOAD_SIZE):
        payload = storage[offset:offset + transport.PAYLOAD_SIZE]
        header = struct.pack('<4I', len(storage), offset, len(payload),
                             transport.checksum(payload))
        frames.append(transport.MAGIC + header + payload.ljust(transport.PAYLOAD_SIZE, b'\0'))
    return b''.join(frames)


def pcm_wav(audio):
    handle = io.BytesIO()
    with wave.open(handle, 'wb') as output:
        output.setparams((1, 2, decoder.SOURCE_RATE, 0, 'NONE', 'not compressed'))
        output.writeframes(audio)
    return handle.getvalue()


@unittest.skipUnless(EXE.is_file(), 'build the FT8 prototype first')
class NativeCaptureDecodeTests(unittest.TestCase):
    def test_carrier_is_removed_without_joining_its_audio_gap(self):
        prefix = bytes(1600)
        suffix = bytes(range(256)) * 20
        data = pcm_wav(prefix + full_carrier() + suffix)
        audio, _ = decoder.wav_payload(data)
        _, spans = decoder.carrier_spans(audio)
        segments = decoder.ordinary_audio_segments(audio, spans)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0], (0, prefix))
        self.assertEqual(segments[1], ((len(prefix) + len(full_carrier())) // 2, suffix))

    def test_corrupt_and_incomplete_carriers_are_rejected(self):
        carrier = full_carrier()
        corrupted = bytearray(carrier)
        corrupted[24] ^= 1
        for bad in (bytes(corrupted), carrier[:-transport.FRAME_SIZE],
                    carrier[transport.FRAME_SIZE:]):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                decoder.carrier_spans(bad)

    def test_unsupported_carrier_version_fails_closed(self):
        future_version = full_carrier().replace(b'IC73RX01', b'IC73RX03')
        with self.assertRaises(ValueError):
            decoder.carrier_spans(future_version)

    def test_diagnostic_marker_must_be_pcm_sample_aligned(self):
        with self.assertRaisesRegex(ValueError, 'sample aligned'):
            decoder.carrier_spans(b'x' + full_carrier() + b'\0')

    def test_real_offline_decoder_sees_signal_after_carrier(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.wav'
            subprocess.run([str(EXE), 'generate', 'CQ K1ABC FN42', str(source)],
                           check=True, capture_output=True, text=True)
            with wave.open(str(source), 'rb') as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()),
                                 (1, 2, decoder.DECODER_RATE))
                source_samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
            recorder_samples = resample_poly(source_samples.astype(np.float64), 2, 3,
                                             window=('kaiser', 5.0), padtype='constant')
            recorder_samples = np.clip(np.rint(recorder_samples), -32768, 32767).astype('<i2')
            audio = bytes(800 * 2) + full_carrier() + recorder_samples.tobytes()
            result = decoder.analyze_bytes(pcm_wav(audio), EXE)

        self.assertEqual(result['diagnostic_frame_count'], transport.FRAME_COUNT)
        self.assertEqual(len(result['segments']), 2)
        self.assertEqual(result['segments'][0]['window_count'], 0)
        self.assertEqual(result['segments'][1]['window_count'], 1)
        messages = [message['message'] for segment in result['segments']
                    for window in segment['windows'] for message in window['messages']]
        self.assertEqual(messages, ['CQ K1ABC FN42'])
        self.assertNotIn('slot_utc_ms', result['segments'][1]['windows'][0])


if __name__ == '__main__':
    unittest.main()
