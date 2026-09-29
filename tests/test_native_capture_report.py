"""Host inspection rejects damaged carriers and ambiguous timing claims."""
from pathlib import Path
import struct
import sys
import tempfile
from unittest.mock import patch
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from native_capture_report import analyze, wav_payload, report
from native_capture import STORAGE_SIZE
from native_transport import MAGIC, checksum


def recording(pending=False, wrap=False, duplicate_bank=False, zero=False):
    records = []
    for i in range(512):
        # Derive a coherent 24000-cycle interval even through tick rollover.
        t = (0xfffffff0 if wrap else 100)+(i*24000)//32001
        counter = 32000-((i*24000)%32001)
        a = [((i*36+j)*97)%60000-30000 if not zero else 0 for j in range(36)]
        records.append(struct.pack('<8I72h', i, t&0xffffffff, counter, 64 if pending else 0,
                                   t&0xffffffff, counter, 0,
                                   0x203fb180 if duplicate_bank or i%2 == 0 else 0x203fb3c0,
                                   *a, *([0]*36)))
    storage = struct.pack('<4I', 2, 512, 0, 0)+b''.join(records)
    frames = []
    for offset in range(0, STORAGE_SIZE, 192):
        payload = storage[offset:offset+192]
        frames.append(MAGIC+struct.pack('<4I', STORAGE_SIZE, offset, len(payload), checksum(payload))+payload.ljust(192,b'\0'))
    original = [((i*6)*97)%60000-30000 if not zero else 0 for i in range(300)]
    audio = struct.pack('<300h', *original)+b''.join(frames)
    fmt = b'fmt '+struct.pack('<IHHIIHH',16,1,1,8000,16000,2,16)
    body = b'WAVE'+fmt+b'data'+struct.pack('<I',len(audio))+audio+b'LIST'+struct.pack('<I',4)+b'INFO'
    return b'RIFF'+struct.pack('<I',len(body))+body


class CaptureReportTests(unittest.TestCase):
    def test_complete_recording_identifies_unity_recorder_stream(self):
        r=analyze(recording())
        self.assertEqual(r['records'],512)
        self.assertEqual(r['adjacent_same_bank'],0)
        self.assertEqual(r['timing']['sample_rate_hz'],48000)
        self.assertEqual(r['recorder_matches'],[{'stream':'stream_a','stride':6,'phase':0,'gain':'unity','wav_sample_index':0,'matching_samples':300}])
        self.assertEqual(r['streams']['stream_b']['zero_samples'],18432)

    def test_tick_rollover_projects_without_an_artificial_gap(self):
        self.assertEqual(analyze(recording(wrap=True))['timing']['sample_rate_hz'],48000)

    def test_pending_snapshot_suppresses_clock_projection(self):
        r=analyze(recording(pending=True))
        self.assertFalse(r['timing']['nominal_projection_available'])
        self.assertNotIn('sample_rate_hz',r['timing'])

    def test_duplicate_banks_reported_and_silence_never_identifies_channel(self):
        r=analyze(recording(duplicate_bank=True,zero=True))
        self.assertEqual(r['adjacent_same_bank'],511)
        self.assertEqual(r['recorder_matches'],[])

    def test_truncation_and_chunk_size_mismatch_rejected(self):
        good=recording()
        for bad in (b'',good[:-1],good+b'extra',good[:4]+struct.pack('<I',2)+good[8:]):
            with self.assertRaises(ValueError):wav_payload(bad)

    def test_complete_wav_with_corrupt_diagnostic_rejected(self):
        raw=bytearray(recording());raw[raw.find(MAGIC)+24]^=1
        with self.assertRaisesRegex(ValueError,'checksum'):analyze(bytes(raw))

    def test_report_is_read_only_and_detects_input_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'capture.wav';original=recording();path.write_bytes(original)
            result=report(path)
            self.assertTrue(result['input_unchanged'])
            self.assertEqual(path.read_bytes(),original)
            def change(data):
                path.write_bytes(data+b'changed')
                return {}
            with patch('native_capture_report.analyze',side_effect=change):
                with self.assertRaisesRegex(ValueError,'changed'):report(path)

    def test_duplicate_data_chunks_rejected(self):
        raw=recording()+b'data'+struct.pack('<I',0)
        raw=raw[:4]+struct.pack('<I',len(raw)-8)+raw[8:]
        with self.assertRaisesRegex(ValueError,'duplicate audio'):wav_payload(raw)

if __name__ == '__main__':unittest.main()
