#!/usr/bin/env python3
"""Reproducible offline waveform tests and independent WSJT-X comparisons."""
import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import re
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from firmware import revision


def run(cmd, cwd=ROOT):
    return subprocess.run([str(x) for x in cmd], cwd=cwd, capture_output=True, text=True, timeout=90, check=True)


def read_wav(path):
    with wave.open(str(path),'rb') as w:
        if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,12000):
            raise ValueError('Expected PCM16 mono 12kHz')
        samples=array('h',w.readframes(w.getnframes()))
    if sys.byteorder!='little':samples.byteswap()
    return [x/32768 for x in samples]


def write_wav(path,samples):
    clipped=sum(abs(s)>0.999 for s in samples)
    data=array('h',(int(max(-32767,min(32767,round(x*32767)))) for x in samples))
    if sys.byteorder!='little':data.byteswap()
    with wave.open(str(path),'wb') as w:
        w.setparams((1,2,12000,0,'NONE','not compressed'));w.writeframes(data.tobytes())
    return clipped


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--jt9',type=Path,default=Path('/Applications/wsjtx.app/Contents/MacOS/jt9'))
    p.add_argument('--output',type=Path,default=ROOT/'research/codec-results.json')
    args=p.parse_args(); exe=ROOT/'build/ft8_proto'; work=ROOT/'artifacts/validation';work.mkdir(parents=True,exist_ok=True)
    jt9=args.jt9.resolve()
    if not jt9.is_file():raise SystemExit('Supply --jt9 PATH for required independent interoperability checks')
    cases=[]

    def evaluate(name,path,expected,required=True,notes=None):
        result=run([exe,'decode',path]); rows=[json.loads(x) for x in result.stdout.splitlines() if x.startswith('{')]
        decoded=[x['message'] for x in rows if 'message' in x]
        sandbox=work/name;sandbox.mkdir(exist_ok=True)
        independent=run([jt9,'-8','-p','15','-d','3','-a',sandbox,'-t',sandbox,path],cwd=sandbox)
        reference=[]
        for line in independent.stdout.splitlines():
            if '~' in line: reference.append(line.split('~',1)[1].strip().split('   ')[0].strip())
        record=dict(name=name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),expected=expected,
                    decoded=decoded,wsjtx_decoded=reference,metrics=[r for r in rows if 'message' not in r],
                    required=required,notes=notes,
                    expected_found=all(x in decoded for x in expected),
                    reference_found=all(x in reference for x in expected))
        if name.startswith('noise'):record['expected_found']=not decoded;record['reference_found']=not reference
        cases.append(record);print(name,len(decoded),len(reference),record['expected_found'],flush=True)

    messages=['CQ K1ABC FN42','W9XYZ K1ABC FN42','K1ABC W9XYZ -12','W9XYZ K1ABC R-10','K1ABC W9XYZ RR73','W9XYZ K1ABC 73']
    for i,message in enumerate(messages):
        path=work/f'260920_120{i}00.wav';run([exe,'generate',message,path]);evaluate('standard_'+str(i),path,[message])
    base=read_wav(work/'260920_120000.wav')
    rng=random.Random(7300)
    # SNR referenced to 2500 Hz bandwidth; noise occupies 6000 Hz Nyquist bandwidth.
    for snr in (10,-5,-10,-15,-20):
        signal_rms=math.sqrt(sum(x*x for x in base[6000:157680])/151680)
        noise_rms=signal_rms*math.sqrt(6000/2500)*10**(-snr/20)
        scale=0.07/max(signal_rms,noise_rms)
        samples=[scale*(x+rng.gauss(0,noise_rms)) for x in base]
        path=work/f'snr_{snr}_120000.wav';clipped=write_wav(path,samples)
        evaluate('snr_'+str(snr),path,[messages[0]],required=snr>=-10,
                 notes={'snr_db_2500hz':snr,'seed':7300,'clipped_samples':clipped,'statistical_sensitivity_measurement':False})
    for offset in (-0.4,1.0):
        n=round(offset*12000);samples=([0]*n+base)[:180000] if n>=0 else base[-n:]+[0]*(-n)
        path=work/f'time_{offset}_120000.wav';write_wav(path,samples);evaluate('time_'+str(offset),path,[messages[0]])
    path=work/'freq_120000.wav';run([exe,'generate',messages[0],path,'1002.8']);evaluate('fractional_frequency',path,[messages[0]])
    other=work/'other_120000.wav';run([exe,'generate','CQ W9XYZ EN50',other,'1500']);second=read_wav(other)
    path=work/'overlap_120000.wav';write_wav(path,[0.5*(a+b) for a,b in zip(base,second)]);evaluate('overlap',path,[messages[0],'CQ W9XYZ EN50'])
    for seed in (1,2,3):
        rng=random.Random(seed);path=work/f'noise_{seed}_120000.wav';write_wav(path,[rng.gauss(0,0.07) for _ in range(180000)]);evaluate('noise_'+str(seed),path,[])
    for name in ('191111_110115','191111_110200','websdr_test9'):
        path=ROOT/f'third_party/ft8_lib/test/wav/{name}.wav'
        evaluate('recorded_'+name,path,[],required=False,notes='Comparison corpus from pinned ft8_lib; no assumption of decoder parity')
    failed=[r['name'] for r in cases if r['required'] and not(r['expected_found'] and r['reference_found'])]
    result={'source_revision':revision(),'host':platform.platform(),'machine':platform.machine(),
            'cpu':run(['sysctl','-n','machdep.cpu.brand_string']).stdout.strip() if sys.platform=='darwin' else platform.processor(),
            'compiler':run(['cc','--version']).stdout.splitlines()[0],
            'codec_executable_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
            'wsjtx_decoder_path':str(jt9),'wsjtx_decoder_sha256':hashlib.sha256(jt9.read_bytes()).hexdigest(),
            'rss_units':'bytes on macOS, KiB on Linux',
            'size_output':run(['size','-m',exe]).stdout if sys.platform=='darwin' else run(['size',exe]).stdout,
            'cases':cases,'failed_required_cases':failed,
            'limits':'Single deterministic realizations, not a sensitivity curve. Host times do not establish radio deadlines. Decode uses full-slot capture.'}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
    if failed:raise SystemExit('Required cases failed: '+', '.join(failed))


if __name__=='__main__':main()
