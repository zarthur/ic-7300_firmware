#!/usr/bin/env python3
"""Two bounded input-only recordings: development followed by reserved holdout."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import signal
import sys
import wave
from datetime import datetime, timezone

from development_check import ROOT, atomic_json, run_step
from compare_receive import capture_slots


def validate_slot_audio(slots):
    """Require complete 15-second mono PCM16 slots at the replay sample rate."""
    for path in slots:
        try:
            with wave.open(str(path), 'rb') as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(),
                        wav.getnframes(), wav.getcomptype()) != (1, 2, 12000, 180000, 'NONE'):
                    raise ValueError(f'Invalid complete-slot WAV format: {path.name}')
                if len(wav.readframes(180000)) != 360000:
                    raise ValueError(f'Truncated complete-slot WAV: {path.name}')
        except (wave.Error, EOFError) as exc:
            raise ValueError(f'Invalid complete-slot WAV: {path.name}') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--device-name', default='USB Audio CODEC')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('Duration must be between 1 and 600 seconds')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    tool = ROOT / 'tools/capture_receive.py'
    tool_hash = hashlib.sha256(tool.read_bytes()).hexdigest()
    report = dict(outcome='RUNNING', started_utc=datetime.now(timezone.utc).isoformat(),
                  capture_tool_sha256=tool_hash,
                  batch_tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  seconds=args.seconds,
                  device_name=args.device_name, recordings=[],
                  limitations=['Input-only USB audio; no radio controls or serial access.',
                               'Frequency/mode and unchanged tuning are not independently monitored.',
                               'Holdout is reserved for evaluation after candidate freeze.'])
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    atomic_json(output / 'report.json', report)
    try:
        if shutil.disk_usage(output).free < 1024 ** 3:
            raise ValueError('Require at least 1 GiB free for bounded capture batch')
        for role in ('development', 'holdout'):
            record = dict(role=role, outcome='NOT_RUN', attempts=[])
            report['recordings'].append(record)
            for attempt in (1, 2):
                if hashlib.sha256(tool.read_bytes()).hexdigest() != tool_hash:
                    raise ValueError('Capture tool changed during batch')
                folder = output / f'{role}-{attempt}'
                command = [sys.executable, str(tool), '--device-name', args.device_name,
                           '--seconds', str(args.seconds), '--output', str(folder)]
                record['outcome'] = 'RUNNING'
                atomic_json(output / 'report.json', report)
                print(f'{role}: attempt {attempt} started', flush=True)
                result = run_step(command, output / f'{role}-{attempt}.log', os.environ.copy(), args.seconds + 30)
                result['capture'] = str(folder)
                record['attempts'].append(result)
                if result['outcome'] == 'INTERRUPTED':
                    raise KeyboardInterrupt('Capture process interrupted')
                if result['outcome'] == 'PASS':
                    try:
                        manifest_bytes = (folder / 'capture.json').read_bytes()
                        manifest, slots = capture_slots(folder)
                        validate_slot_audio(slots)
                    except (OSError, ValueError) as exc:
                        result.update(outcome='FAIL', error=f'Invalid capture manifest: {exc}')
                    else:
                        record.update(outcome='PASS', capture=str(folder),
                                      manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                                      slots=len(slots))
                        atomic_json(folder / 'session-context.json', dict(role=role,
                            operator_context='Owner left radio powered and connected for unattended input-only captures.',
                            configuration='Not independently verified; no tuning/settings commands issued.',
                            holdout_reserved=role == 'holdout'))
                        break
                record['outcome'] = 'FAIL'
                atomic_json(output / 'report.json', report)
            print(f'{role}: {record["outcome"]}', flush=True)
            atomic_json(output / 'report.json', report)
        report['outcome'] = 'PASS' if all(r['outcome'] == 'PASS' for r in report['recordings']) else 'INCOMPLETE'
    except (Exception, KeyboardInterrupt) as exc:
        report.update(outcome='INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'FAIL', error=str(exc))
        for record in report['recordings']:
            if record['outcome'] == 'RUNNING':
                record.update(outcome=report['outcome'], error=str(exc))
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        for role in ('development', 'holdout'):
            if not any(r['role'] == role for r in report['recordings']):
                report['recordings'].append(dict(role=role, outcome='NOT_RUN', attempts=[]))
        atomic_json(output / 'report.json', report)
    return 0 if report['outcome'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
