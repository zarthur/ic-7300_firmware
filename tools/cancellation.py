"""Bounded desktop-only experimental FT8 cancellation; no device access.

Fits actual decoded tone sequences to samples. No fixture parameters or reference
messages enter the estimator. This is not qualified for embedded memory/runtime.
"""
from __future__ import annotations
import json
import math
import resource
import sys
from pathlib import Path
import subprocess
import time
import wave
import numpy as np
from scipy import optimize, signal, special

RATE = 12000
FIT_RATE = 300
SIGNAL_SAMPLES = 151680


def waveform(tones):
    """Complex GFSK envelope following codec.c, including its phase convention."""
    tones = np.asarray(tones)
    if tones.shape != (79,) or not np.all((tones >= 0) & (tones <= 7)):
        raise ValueError('expected 79 FT8 tones')
    n = np.arange(SIGNAL_SAMPLES)
    center = n + 1920
    weighted = np.zeros(len(n))
    for delta in (-2, -1, 0):
        tone = center // 1920 + delta
        p = center - tone * 1920
        t = p / 1920.0 - 1.5
        pulse = (special.erf(5.336446 * 2 * (t + .5)) - special.erf(5.336446 * 2 * (t - .5))) / 2
        weighted += tones[np.clip(tone, 0, 78)] * pulse
    phase = np.r_[0., np.cumsum(weighted[:-1]) * (2 * np.pi / 1920)]
    ramp = np.minimum(np.minimum(n, SIGNAL_SAMPLES - 1 - n), 240)
    envelope = (1 - np.cos(np.pi * ramp / 240)) / 2
    return envelope * np.exp(1j * phase)


def write_wav(path, samples):
    samples = np.asarray(samples)
    with wave.open(str(path), 'wb') as f:
        f.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        f.writeframes(np.rint(np.clip(samples, -1, 32767 / 32768) * 32768).astype('<i2').tobytes())


def decode(samples, exe, workspace, label, deadline):
    path = workspace / (label + '.wav')
    write_wav(path, samples)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('slot deadline')
    run = subprocess.run([str(exe), 'decode-payload', str(path)], capture_output=True, text=True, timeout=min(30, remaining))
    (workspace / (label + '.jsonl')).write_text(run.stdout)
    (workspace / (label + '.stderr')).write_text(run.stderr)
    if run.returncode:
        raise RuntimeError('decoder failure')
    rows = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
    if not any('decoded_count' in row for row in rows):
        raise RuntimeError('missing decoder completion')
    return [row for row in rows if 'message' in row]


def fit_signal(samples, decoded, deadline):
    """Search +/-240 ms and +/-4 Hz around decoder candidate, then refine."""
    base_hz = float(decoded['frequency_hz'])
    candidate_start = float(decoded['time_offset_s'])
    full = waveform(decoded['tones'])
    template = signal.resample_poly(full, 1, 40)
    t = np.arange(len(samples)) / RATE
    observed = signal.resample_poly(2 * samples * np.exp(-2j * np.pi * base_hz * t), 1, 40)
    fit_t = np.arange(len(observed)) / FIT_RATE
    template_t = np.arange(len(template)) / FIT_RATE
    def model(start):
        x = fit_t - start
        return np.interp(x, template_t, template.real, left=0, right=0) + 1j * np.interp(x, template_t, template.imag, left=0, right=0)
    best = (-1., None)
    start_min, start_max = candidate_start - .24, candidate_start + .24
    lag_min, lag_max = math.ceil(start_min * FIT_RATE), math.floor(start_max * FIT_RATE)
    lags = signal.correlation_lags(len(observed), len(template))
    mask = (lags >= lag_min) & (lags <= lag_max)
    for delta in np.linspace(-4, 4, 81):
        if time.monotonic() >= deadline:
            raise TimeoutError('fit deadline')
        shifted = observed * np.exp(-2j * np.pi * delta * fit_t)
        corr = signal.correlate(shifted, template, method='fft')[mask]
        i = int(np.argmax(np.abs(corr)))
        value = float(abs(corr[i]))
        if value > best[0]:
            best = (value, (lags[mask][i] / FIT_RATE, delta))
    evaluations = 0
    def objective(parameters):
        nonlocal evaluations
        evaluations += 1
        if time.monotonic() >= deadline:
            raise TimeoutError('fit deadline')
        start, delta = parameters
        ref = model(start) * np.exp(2j * np.pi * delta * fit_t)
        energy = float(np.vdot(ref, ref).real)
        return -float(abs(np.vdot(ref, observed)) ** 2 / max(energy, 1e-20))
    result = optimize.minimize(objective, best[1], method='Nelder-Mead', bounds=[(start_min, start_max), (-4, 4)], options={'maxiter': 100, 'xatol': 1e-7, 'fatol': 1e-8})
    start, delta = map(float, result.x)
    ref = model(start) * np.exp(2j * np.pi * delta * fit_t)
    energy = float(np.vdot(ref, ref).real)
    amplitude = np.vdot(ref, observed) / max(energy, 1e-20)
    coherence = float(abs(np.vdot(ref, observed)) / math.sqrt(max(energy * np.vdot(observed, observed).real, 1e-20)))
    report = {'message': decoded['message'], 'payload_hex': decoded['payload_hex'], 'frequency_hz': base_hz + delta, 'start_s': start, 'amplitude': float(abs(amplitude)), 'phase_rad': float(np.angle(amplitude)), 'coherence': coherence, 'optimizer_success': bool(result.success), 'evaluations': evaluations, 'search': {'time_radius_s': .24, 'frequency_radius_hz': 4, 'frequency_grid_points': 81, 'max_refine_iterations': 100, 'minimum_coherence': .65}}
    if not result.success or coherence < .65 or abs(delta) > 3.99 or min(start - start_min, start_max - start) < 1e-4:
        report.update(accepted=False, reason='fit_quality_or_search_boundary')
        return None, report
    x = t - start
    native_t = np.arange(len(full)) / RATE
    aligned = np.interp(x, native_t, full.real, left=0, right=0) + 1j * np.interp(x, native_t, full.imag, left=0, right=0)
    prediction = np.real(amplitude * aligned * np.exp(2j * np.pi * (base_hz + delta) * t))
    # Reuse one full-slot residual buffer; extrema avoid an additional abs array.
    trial_residual = samples - prediction
    if np.max(trial_residual) > 32767 / 32768 or np.min(trial_residual) < -32767 / 32768:
        report.update(accepted=False, reason='residual_would_clip')
        return None, report
    before = float(np.dot(samples, samples))
    after = float(np.dot(trial_residual, trial_residual))
    report.update(accepted=after < before, reason='accepted' if after < before else 'energy_increased', energy_before=before, energy_after=after)
    return (prediction if after < before else None), report


def cancel_slot(samples, exe, workspace, *, max_passes=2, max_signals=8, deadline_seconds=120):
    """Return a bounded report; union retains all original decoded messages.

    Samples must be mono float PCM at 12 kHz. Workspace must be a dedicated
    per-slot directory. Reports flag deadline stops; they are not successful runs.
    """
    if not 1 <= max_passes <= 2 or not 1 <= max_signals <= 8 or not 0 < deadline_seconds <= 300:
        raise ValueError('cancellation bounds exceeded')
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1 or not 0 < len(samples) <= 180000 or not np.all(np.isfinite(samples)) or np.max(np.abs(samples)) > 1:
        raise ValueError('expected finite bounded mono float PCM')
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    exe = Path(exe).resolve()
    started = time.monotonic()
    deadline = started + deadline_seconds
    residual = samples.copy()
    report = {'baseline': [], 'messages': [], 'new_messages': [], 'fits': [], 'skipped_candidates': [], 'passes_completed': 0, 'limits_reached': [], 'termination': 'completed', 'limits': {'max_passes': max_passes, 'max_signals': max_signals, 'deadline_seconds': deadline_seconds}, 'resources': {'desktop_only': True, 'input_and_residual_bytes': samples.nbytes + residual.nbytes, 'workspace_target_bytes': 393216, 'memory_note': 'NumPy/SciPy temporary arrays and interpreter exceed embedded workspace; these bytes are not peak process memory.'}}
    try:
        baseline = decode(residual, exe, workspace, 'baseline', deadline)
        report['baseline'] = baseline
        messages = {r['message']: r for r in baseline}
        report['messages'] = list(messages.values())
        candidates = baseline
        attempted = set()
        for pass_index in range(max_passes):
            changed = False
            for row in sorted(candidates, key=lambda r: r['sync_score'], reverse=True):
                key = (row['payload_hex'], round(row['frequency_hz'] / 6.25))
                if key in attempted:
                    continue
                if len(attempted) >= max_signals:
                    report['skipped_candidates'].append({'payload_hex': row['payload_hex'], 'frequency_hz': row['frequency_hz'], 'reason': 'signal_limit', 'pass': pass_index + 1})
                    if 'max_signals' not in report['limits_reached']:
                        report['limits_reached'].append('max_signals')
                    continue
                attempted.add(key)
                prediction, fit = fit_signal(residual, row, deadline)
                fit['pass'] = pass_index + 1
                report['fits'].append(fit)
                if prediction is not None:
                    residual -= prediction
                    changed = True
            report['passes_completed'] = pass_index + 1
            if not changed:
                break
            candidates = decode(residual, exe, workspace, f'residual-{pass_index + 1}', deadline)
            for row in candidates:
                messages.setdefault(row['message'], row)
            report['messages'] = list(messages.values())
            if pass_index + 1 == max_passes:
                report['limits_reached'].append('max_passes')
                for row in candidates:
                    key = (row['payload_hex'], round(row['frequency_hz'] / 6.25))
                    if key not in attempted:
                        report['skipped_candidates'].append({'payload_hex': row['payload_hex'], 'frequency_hz': row['frequency_hz'], 'reason': 'pass_limit', 'pass': pass_index + 1})
        base = {r['message'] for r in baseline}
        report['new_messages'] = [r for r in report['messages'] if r['message'] not in base]
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        report['termination'] = 'deadline'
        report['error'] = str(exc)
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        report['termination'] = 'error'
        report['error'] = str(exc)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    report['resources']['process_peak_rss_bytes'] = int(usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024))
    report['resources']['rss_scope'] = 'process lifetime high water including earlier slots; not per-fit allocation'
    report['elapsed_seconds'] = time.monotonic() - started
    report['residual_peak'] = float(np.max(np.abs(residual)))
    return report
