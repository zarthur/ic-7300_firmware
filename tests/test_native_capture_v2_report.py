"""V2 host reports must not hide aborts or project across lifecycle boundaries."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import native_capture_v2_report as report
from native_capture_v2 import STORAGE_SIZE, MAGIC as STORAGE_MAGIC
from native_transport_v2 import MAGIC, checksum


def recording(status=2,count=512,changes=None,wrap=False,zero=False):
    records=[]
    for i in range(count):
        tick=((0xfffffff0 if wrap else 100)+(i*24000)//32001)&0xffffffff
        counter=32000-(i*24000)%32001
        a=[((i*36+j)*97)%60000-30000 if not zero else 0 for j in range(36)]
        row=dict(before=[1,4,0],after=[1,4,0],extra=8 if status==5 and i==count-1 else 0,
                 observations=[tick,counter,0,tick,counter,0,report.BANKS[i%2],0x3c2b0033,0xcc,2,0x10301,0])
        if changes: changes(i,row)
        before,after=row['before'],row['after']
        flags=row['extra']|int(before[0]!=after[0])|(2 if not before[0] or not after[0] else 0)|(4 if before[2] or after[2] else 0)
        records.append(struct.pack('<20I72h',i,flags,*before,*after,*row['observations'],*a,*([0]*36)))
    storage=struct.pack('<4I',status,count,STORAGE_MAGIC,2)+b''.join(records)
    storage=storage.ljust(STORAGE_SIZE,b'\0')
    frames=[]
    for offset in range(0,STORAGE_SIZE,192):
        payload=storage[offset:offset+192]
        frames.append(MAGIC+struct.pack('<4I',STORAGE_SIZE,offset,len(payload),checksum(payload))+payload.ljust(192,b'\0'))
    prefix=struct.pack('<300h',*([0]*300 if zero else [((i*6)*97)%60000-30000 for i in range(300)]))
    audio=prefix+b''.join(frames)
    fmt=b'fmt '+struct.pack('<IHHIIHH',16,1,1,8000,16000,2,16)
    body=b'WAVE'+fmt+b'data'+struct.pack('<I',len(audio))+audio
    return b'RIFF'+struct.pack('<I',len(body))+body


class CaptureV2ReportTests(unittest.TestCase):
    def test_full_capture_and_tick_rollover_project_nominal_48k(self):
        for wrap in (False,True):
            r=report.analyze(recording(wrap=wrap))
            self.assertTrue(r['export_complete']);self.assertTrue(r['capture_full'])
            self.assertEqual((r['capture_outcome'],r['records'],r['diagnostic_frames']),('full',512,598))
            self.assertEqual(r['timing']['sample_rate_hz'],48000)
            self.assertEqual(r['timing']['segments'][0]['records'],512)
            self.assertEqual(r['recorder_matches'],[dict(stream='stream_a',stride=6,phase=0,gain='unity',
                first_capture_sequence=0,last_capture_sequence=511,wav_sample_index=0,matching_samples=300)])
            self.assertEqual(r['raw_streams']['stream_b']['zero_samples'],18432)

    def test_empty_and_one_record_aborts_are_export_success_without_projection(self):
        for status,count,outcome in ((6,0,'aborted_without_record'),(6,1,'aborted_without_record'),(5,1,'aborted_with_record')):
            r=report.analyze(recording(status,count))
            self.assertTrue(r['export_complete']);self.assertFalse(r['capture_full'])
            self.assertEqual(r['capture_outcome'],outcome)
            self.assertFalse(r['timing']['full_capture_projection_available'])
            self.assertNotIn('sample_rate_hz',r['timing'])
            self.assertEqual(r['recorder_matches'],[])
            self.assertEqual(r['raw_streams']['stream_a']['samples'],count*36)
            if count==0:self.assertIsNone(r['raw_streams']['stream_a']['rms'])
            if status==5:self.assertEqual(r['timing']['excluded_records'][0]['reasons'],['nested_callback'])

    def test_between_record_epoch_change_splits_even_when_flags_are_zero(self):
        def change(i,row):
            if i>=128:row.update(before=[2,4,0],after=[2,4,0])
        r=report.analyze(recording(changes=change))
        self.assertEqual(r['flag_counts']['epoch_changed'],0)
        self.assertEqual([s['records'] for s in r['timing']['segments']],[128,384])
        self.assertEqual(r['timing']['boundaries'],[{'before_sequence':128,'reasons':['between_record_epoch_change']}])
        self.assertFalse(r['timing']['full_capture_projection_available'])
        self.assertNotIn('sample_rate_hz',r['timing'])
        self.assertEqual(r['recorder_matches'][0]['last_capture_sequence'],127)

    def test_within_record_epoch_change_retained_but_excluded(self):
        def change(i,row):
            if i>=128:row['after']=[2,4,0]
            if i>128:row['before']=[2,4,0]
        r=report.analyze(recording(changes=change))
        self.assertEqual(r['flag_counts']['epoch_changed'],1)
        self.assertEqual(r['record_details'][128]['epoch_after'],[2,4,0])
        self.assertEqual([s['records'] for s in r['timing']['segments']],[128,383])
        self.assertEqual(r['timing']['excluded_records'],[dict(sequence=128,reasons=['epoch_changed'])])

    def test_unknown_exhausted_and_inconsistent_epoch_reason_suppress_projection(self):
        for epoch in ([0,0,0],[3,4,1],[3,99,0]):
            def change(i,row):row.update(before=epoch,after=epoch)
            r=report.analyze(recording(changes=change))
            self.assertEqual(r['timing']['segments'],[])
            self.assertEqual(len(r['timing']['excluded_records']),512)
            self.assertEqual(r['recorder_matches'],[])

    def test_timer_ambiguity_and_repeated_bank_split_segments(self):
        for case in ('pending','counter','tick_change','backwards','bank'):
            def change(i,row):
                if i!=128:return
                o=row['observations']
                if case=='pending':o[2]=64
                elif case=='counter':o[1]=32001
                elif case=='tick_change':o[3]+=1
                elif case=='backwards':o[0]=o[3]=0
                else:o[6]=report.BANKS[1]
            r=report.analyze(recording(changes=change))
            self.assertFalse(r['timing']['full_capture_projection_available'])
            self.assertNotIn('sample_rate_hz',r['timing'])
            self.assertGreater(len(r['timing']['segments']),1)

    def test_ssi_unavailable_preserves_raw_words_without_disabling_clock(self):
        def change(i,row):row['extra']=16;row['observations'][7:]=[0xffffffff]*5
        r=report.analyze(recording(changes=change))
        self.assertEqual(r['flag_counts']['ssi_unavailable'],512)
        self.assertEqual(r['record_details'][0]['observations'][7:],[0xffffffff]*5)
        self.assertEqual(r['timing']['sample_rate_hz'],48000)
        def observed(i,row):row['observations'][7:]=[0xffffffff]*5
        self.assertEqual(report.analyze(recording(changes=observed))['flag_counts']['ssi_unavailable'],0)

    def test_flagged_final_record_is_not_matched_across(self):
        r=report.analyze(recording(5,32))
        self.assertEqual(r['timing']['segments'][0]['last_sequence'],30)
        self.assertEqual(r['recorder_matches'][0]['matching_samples'],31*6)
        self.assertFalse(r['timing']['full_capture_projection_available'])
        self.assertEqual(report.analyze(recording(zero=True))['recorder_matches'],[])

    def test_corrupt_wav_carrier_and_unknown_bank_rejected(self):
        good=recording();bad=bytearray(good);bad[bad.find(MAGIC)+24]^=1
        for raw in (good[:-1],good+b'x',bytes(bad)):
            with self.assertRaises(ValueError):report.analyze(raw)
        def change(i,row):row['observations'][6]=0
        with self.assertRaisesRegex(ValueError,'bank'):report.analyze(recording(changes=change))

    def test_report_is_read_only_and_detects_recording_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'capture.wav';data=recording(6,0);path.write_bytes(data)
            result=report.report(path)
            self.assertTrue(result['input_unchanged']);self.assertEqual(path.read_bytes(),data)
            def change(raw):path.write_bytes(raw+b'changed');return {}
            with patch.object(report,'analyze',side_effect=change):
                with self.assertRaisesRegex(ValueError,'changed'):report.report(path)


if __name__=='__main__':unittest.main()
