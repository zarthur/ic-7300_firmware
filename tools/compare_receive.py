#!/usr/bin/env python3
"""Replay a verified local receive capture; catalogue exact-text misses offline."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from development_check import atomic_json, source_state

REFERENCE_LINE = re.compile(r'^\s*(\d{6})\s+(-?\d+)\s+(-?\d+(?:\.\d+)?)\s+(\d+)\s+~\s+(.*?)\s*$')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_reference(text):
    if '<DecodeFinished>' not in text:
        raise ValueError('Reference decoder did not report completion')
    rows = []
    for line in text.splitlines():
        match = REFERENCE_LINE.match(line)
        if match:
            utc, snr, dt, hz, message = match.groups()
            # WSJT-X may append columns separated by multiple spaces.
            message = re.split(r'\s{3,}', message)[0].strip()
            rows.append(dict(message=message, snr_db=int(snr), dt_seconds=float(dt), frequency_hz=int(hz)))
        elif '~' in line:
            raise ValueError('Unrecognized FT8 reference output line')
    return rows


def compare_messages(prototype, reference, candidates):
    observed = {x['message'] for x in prototype}
    expected = {x['message'] for x in reference}
    misses = []
    # The matching unit is unique text within a slot. Keep the strongest reference
    # observation when the same text appears more than once.
    unique_reference = {row['message']: row for row in sorted(reference, key=lambda row: row['snr_db'])}
    for row in unique_reference.values():
        if row['message'] in observed:
            continue
        nearby = [c for c in candidates if abs(c['frequency_hz'] - row['frequency_hz']) <= 6.25]
        if not 200 <= row['frequency_hz'] <= 2956.25:
            category = 'outside_or_at_search_band_edge'
        elif not nearby:
            category = 'no_nearby_candidate'
        elif any(c['stage'] == 'unpack' for c in nearby):
            category = 'nearby_unpack_failure'
        else:
            category = 'nearby_candidates_without_matching_message'
        misses.append(dict(**row, category=category, nearby_candidates=nearby,
                           attribution='Proximity is diagnostic evidence, not proof a candidate belongs to this transmission.'))
    return dict(prototype_count=len(observed), reference_count=len(expected),
                matched=sorted(observed & expected), prototype_only=sorted(observed - expected),
                missed=misses, candidate_stages=dict(Counter(x['stage'] for x in candidates)))


def baseline_changes(comparison, baseline):
    previous = set(baseline['matched']) if baseline is not None else set(comparison['matched'])
    current = set(comparison['matched'])
    return dict(new_reference_matches=sorted(current - previous), lost_reference_matches=sorted(previous - current))


def capture_slots(directory):
    manifest_path = directory / 'capture.json'
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError('Capture manifest must be an object')
    if not isinstance(manifest.get('wav_sha256'), dict) or not all(
            isinstance(name, str) and isinstance(digest, str)
            for name, digest in manifest['wav_sha256'].items()):
        raise ValueError('Capture manifest requires a WAV hash mapping')
    if not all(manifest.get(k) is True for k in ('complete', 'continuity_ok', 'alignment_usable')):
        raise ValueError('Capture completeness/continuity/alignment did not pass')
    slots = sorted((directory / 'slots').glob('*.wav'))
    if not slots:
        raise ValueError('No complete slots to compare')
    expected = {name for name in manifest['wav_sha256'] if name.startswith('slots/')}
    if {str(p.relative_to(directory)) for p in slots} != expected:
        raise ValueError('Slot inventory differs from capture manifest')
    for path in slots:
        if path.is_symlink() or sha(path) != manifest['wav_sha256'][str(path.relative_to(directory))]:
            raise ValueError(f'Slot hash mismatch: {path.name}')
    return manifest, slots


def file_identity(path):
    """Detect content changes and replacements, including restored file contents."""
    before = path.stat()
    digest = sha(path)
    after = path.stat()
    def stamp(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if stamp(before) != stamp(after):
        raise ValueError(f'File changed while hashing: {path}')
    return dict(sha256=digest, stat=stamp(after))


def require_unchanged(expected):
    for path, identity in expected.items():
        if file_identity(path) != identity:
            raise ValueError(f'Replay artifact changed: {path}')


def run_decoder(command, folder, label):
    start = time.monotonic()
    result = subprocess.run(list(map(str, command)), cwd=folder, capture_output=True, text=True, timeout=90)
    (folder / (label + '.stdout.txt')).write_text(result.stdout)
    (folder / (label + '.stderr.txt')).write_text(result.stderr)
    if result.returncode:
        raise ValueError(f'{label} failed with exit {result.returncode}; inspect local logs')
    return result.stdout, time.monotonic() - start


def replay_slot(path, folder, exe, jt9, cached=None, identities=None):
    if identities is not None:
        require_unchanged(identities)
    folder.mkdir()
    text, elapsed = run_decoder([exe, 'inspect', path], folder, 'prototype')
    rows = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
    messages = [row for row in rows if 'message' in row]
    candidates = [row for row in rows if 'candidate_rank' in row]
    metrics = [row for row in rows if 'decoded_count' in row or 'codec_peak_heap_bytes' in row]
    if len(metrics) != 2 or not any('decoded_count' in x for x in metrics):
        raise ValueError('Missing prototype completion metrics')
    if cached is None:
        reference_text, reference_elapsed = run_decoder([jt9, '-8', '-p', '15', '-d', '3', '-a', folder, '-t', folder, path], folder, 'wsjtx')
        reference = parse_reference(reference_text)
    else:
        if cached['sha256'] != sha(path):
            raise ValueError('Cached reference input differs')
        reference = cached['reference']
        reference_elapsed = cached['reference_elapsed_seconds']
    if identities is not None:
        require_unchanged(identities)
    comparison = compare_messages(messages, reference, candidates)
    return dict(file=path.name, sha256=sha(path), prototype=messages, reference=reference,
                **comparison, **baseline_changes(comparison, cached), metrics=metrics, prototype_elapsed_seconds=elapsed,
                reference_elapsed_seconds=reference_elapsed, reference_reused=cached is not None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--jt9', type=Path, default=Path('/Applications/wsjtx.app/Contents/MacOS/jt9'))
    parser.add_argument('--reference', type=Path, help='Reuse a completed report on exactly the same capture')
    parser.add_argument('--require-no-regressions', action='store_true', help='With --reference, fail if any previously matched message is lost')
    parser.add_argument('--output', type=Path, required=True, help='New local evidence directory; contains station data')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    if args.require_no_regressions and not args.reference:
        parser.error('--require-no-regressions requires --reference')
    capture = args.capture.resolve(); exe = args.exe.resolve(); jt9 = args.jt9.resolve()
    source_before = source_state()
    protected = [capture / 'capture.json', exe, jt9]
    if args.reference:
        args.reference = args.reference.resolve()
        protected.append(args.reference)
    identities = {path: file_identity(path) for path in protected}
    manifest, slots = capture_slots(capture)
    for path in slots:
        identity = file_identity(path)
        if identity['sha256'] != manifest['wav_sha256'][str(path.relative_to(capture))]:
            raise ValueError(f'Slot changed after manifest validation: {path}')
        identities[path] = identity
    cached = None
    reference_sha = identities[jt9]['sha256']
    if args.reference:
        prior = json.loads(args.reference.read_text())
        if prior['outcome'] != 'PASS' or prior['capture_manifest_sha256'] != identities[capture / 'capture.json']['sha256'] or prior['reference_sha256'] != reference_sha:
            raise ValueError('Reference cache is incomplete or belongs to another capture/decoder')
        cached = {row['file']: row for row in prior['slots']}
        if set(cached) != {p.name for p in slots}:
            raise ValueError('Reference cache slot set differs')
    require_unchanged(identities)
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    report = dict(schema_version=1, outcome='RUNNING', capture=str(capture),
                  capture_manifest_sha256=identities[capture / 'capture.json']['sha256'], capture_quality={k: manifest[k] for k in
                      ('complete', 'continuity_ok', 'alignment_usable', 'captured_frames', 'channel_statistics')},
                  source=source_before, prototype_sha256=identities[exe]['sha256'], reference_sha256=reference_sha,
                  reference_cache_sha256=identities[args.reference]['sha256'] if args.reference else None,
                  slots=[], errors=[], total_slots=len(slots),
                  require_no_regressions=args.require_no_regressions,
                  limitations=['Exact decoded text per slot is the matching unit, not unique stations or individual RF transmissions.',
                               'WSJT-X output is a comparison reference, not exhaustive ground truth.',
                               'Candidate frequency proximity cannot prove the failure cause.',
                               'Prototype candidate time includes window delay and is not directly comparable with WSJT-X DT.',
                               'Inspect timings include diagnostic output and are host-only, not target performance.'])
    atomic_json(output / 'report.json', report)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(replay_slot, path, output / path.stem, exe, jt9,
                               None if cached is None else cached[path.name],
                               {p: identities[p] for p in (*protected, path)}): path for path in slots}
        for future in as_completed(futures):
            path = futures[future]
            try:
                row = future.result(); report['slots'].append(row)
                print(f'{path.name}: prototype {row["prototype_count"]}, reference {row["reference_count"]}, matched {len(row["matched"])}', flush=True)
            except Exception as exc:
                report['errors'].append(dict(file=path.name, error=str(exc)))
            report['slots'].sort(key=lambda x: x['file'])
            atomic_json(output / 'report.json', report)
    try:
        require_unchanged(identities)
        _, final_slots = capture_slots(capture)
        if final_slots != slots:
            raise ValueError('Capture slot inventory changed during replay')
        report['source_after'] = source_state()
        if report['source_after'] != source_before:
            raise ValueError('Source changed during replay')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report['errors'].append(dict(stage='provenance', error=str(exc)))
    report['summary'] = dict(prototype_decodes=sum(x['prototype_count'] for x in report['slots']),
                             reference_decodes=sum(x['reference_count'] for x in report['slots']),
                             matched=sum(len(x['matched']) for x in report['slots']),
                             prototype_only=sum(len(x['prototype_only']) for x in report['slots']),
                             new_reference_matches=sum(len(x['new_reference_matches']) for x in report['slots']),
                             lost_reference_matches=sum(len(x['lost_reference_matches']) for x in report['slots']),
                             misses=sum(len(x['missed']) for x in report['slots']),
                             miss_categories=dict(Counter(m['category'] for x in report['slots'] for m in x['missed'])))
    report['outcome'] = 'PASS' if not report['errors'] and len(report['slots']) == len(slots) else 'FAIL'
    if args.require_no_regressions and report['summary']['lost_reference_matches']:
        report['outcome'] = 'FAIL'
    atomic_json(output / 'report.json', report)
    print(json.dumps(report['summary']), flush=True)
    print(f'{report["outcome"]}: {output / "report.json"}')
    return 0 if report['outcome'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
