import os
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import wave

ROOT=Path(__file__).resolve().parents[1]
EXE=(ROOT/os.environ.get('FT8_PROTO','build/ft8_proto')).resolve()


@unittest.skipUnless(EXE.exists(),'build the C prototype first')
class WavTests(unittest.TestCase):
    def test_candidate_inspection_preserves_decoded_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic.wav'
            subprocess.run([EXE,'generate','CQ K1ABC FN42',path],capture_output=True,check=True)
            outputs={}
            for command in ('decode','inspect'):
                result=subprocess.run([EXE,command,path],capture_output=True,text=True,check=True)
                outputs[command]=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            messages=lambda rows:[row for row in rows if 'message' in row]
            self.assertEqual(messages(outputs['decode']),messages(outputs['inspect']))
            self.assertIn('CQ K1ABC FN42',[row['message'] for row in messages(outputs['inspect'])])
            candidates=[row for row in outputs['inspect'] if 'candidate_rank' in row]
            self.assertTrue(candidates)
            self.assertEqual([row['candidate_rank'] for row in candidates],list(range(len(candidates))))
            self.assertTrue(any(row['stage']=='decoded' for row in candidates))
            self.assertTrue(all(row['stage'] in ('decoded','duplicate','ldpc','crc','unpack') for row in candidates))

    def test_malformed_and_unsupported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.wav'
            for data in (b'',b'RIFF'+struct.pack('<I',0xffffffff)+b'WAVE',
                         b'RIFF'+struct.pack('<I',20)+b'WAVEdata'+struct.pack('<I',12)+b'x'):
                path.write_bytes(data)
                self.assertNotEqual(subprocess.run([EXE,'decode',path],capture_output=True).returncode,0)
            with wave.open(str(path),'wb') as w:
                w.setparams((2,2,48000,0,'NONE','not compressed'));w.writeframes(bytes(100))
            self.assertNotEqual(subprocess.run([EXE,'decode',path],capture_output=True).returncode,0)

    def test_truncated_pcm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'short.wav'
            with wave.open(str(path),'wb') as w:
                w.setparams((1,2,12000,0,'NONE','not compressed'));w.writeframes(bytes(100))
            path.write_bytes(path.read_bytes()[:-3])
            self.assertNotEqual(subprocess.run([EXE,'decode',path],capture_output=True).returncode,0)


if __name__=='__main__':unittest.main()
