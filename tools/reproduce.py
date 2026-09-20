#!/usr/bin/env python3
"""Verify a committed clean checkout with separate official firmware acquisition.

Creates an isolated temporary local clone; does not modify this worktree. Codec
interoperability benchmarks run separately with tools/validate_codec.py.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,default=ROOT/'research/reproduction.json')
args=p.parse_args()
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
checks=[]
with tempfile.TemporaryDirectory(prefix='ic7300-reproduce-') as tmp:
    clone=Path(tmp)/'repo'
    subprocess.run(['git','clone','--local',str(ROOT),str(clone)],check=True)
    commands=[['git','checkout','--detach',commit],[sys.executable,'tools/bootstrap.py'],
              [sys.executable,'tools/acquire.py','--verify'],['make','-j4','test'],
              [sys.executable,'tools/verify_firmware.py','--output','artifacts/firmware-results.json']]
    for command in commands:
        completed=subprocess.run(command,cwd=clone,text=True,capture_output=True,timeout=240)
        print(' '.join(command),completed.returncode,flush=True)
        checks.append({'command':command,'returncode':completed.returncode,'stdout_tail':completed.stdout[-1500:],'stderr_tail':completed.stderr[-1500:]})
        if completed.returncode:raise SystemExit(completed.stderr or completed.stdout)
    status=subprocess.check_output(['git','status','--porcelain'],cwd=clone,text=True)
    if status.strip():raise SystemExit('Clean checkout was modified: '+status)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps({'tested_commit':commit,'clean_after_reproduction':True,'checks':checks},indent=2)+'\n')
