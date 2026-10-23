"""Behavioural model B: second-order single-bit delta-sigma loop (DR-001 item 1).

Units: the 1-bit feedback is +/-1, so +/-1 is full scale and
``amplitude_dbfs = 20*log10(A)``. Spec row 11 (0.5*VREF peak) is -6 dBFS.

Loop (delaying integrators, fixed Boser-Wooley coefficients 0.5 / 0.5,
written into every record, not parameters)::

    y[n]    = sign(x2[n] + comparator_offset)        (with hysteresis)
    x1[n+1] = p*x1[n] + k*(u[n] - y[n]) + ci_offset + ktc[n]
    x2[n+1] = p*x2[n] + k2*(x1[n] - y[n])

With ideal parameters p = 1, k = k2 = 0.5 and NTF = (1-z^-1)^2 / (1 - 1.5 z^-1 + 0.75 z^-2).

Parameter conventions (the T-extraction issues map onto these names):

- ``dc_gain``: integrator amplifier DC gain A in V/V, ``null`` = infinite.
  Leaky pole ``p = A/(A+1)``, applied to both integrators.
- ``settling_error``: unsettled fraction of each charge-transfer step.
  Gain factor ``(1 - settling_error)`` on both integrator inputs.
- ``ci_gain_error``: relative gain error ``(1 + ci_gain_error)`` on both
  integrator inputs (charge-injection / capacitor mismatch).
- ``ci_offset``: additive offset per clock on integrator 1, in FS units
  (shaped by one integrator only; offset on integrator 2 is not modelled).
- ``ktc_noise_var``: variance per sampling event, FS^2, Gaussian, added at the
  integrator-1 input.
- ``comparator_offset``: input-referred offset, FS units, added to x2 before
  the decision. Positive offset favours +1.
- ``comparator_hysteresis``: total hysteresis width h, FS units. The output
  stays +1 until x2 + offset < -h/2 and stays -1 until it exceeds +h/2.
- ``jitter_rms_s``: rms of Gaussian sampling-time jitter on the input sample,
  seconds; the input tone is evaluated at ``t + jitter``.
- ``seed``: integer seed for all random draws.

Unknown or missing keys are an error: the file is the schema.
"""
import json

import numpy as np

C1 = 0.5
C2 = 0.5
FS_HZ = 5.12e6

PARAM_DEFAULTS = {
    "dc_gain": None,
    "settling_error": 0.0,
    "ci_offset": 0.0,
    "ci_gain_error": 0.0,
    "ktc_noise_var": 0.0,
    "comparator_offset": 0.0,
    "comparator_hysteresis": 0.0,
    "jitter_rms_s": 0.0,
    "seed": 1,
}


def validate_params(p):
    if not isinstance(p, dict):
        raise ValueError("parameters must be a JSON object")
    unknown = sorted(set(p) - set(PARAM_DEFAULTS))
    missing = sorted(set(PARAM_DEFAULTS) - set(p))
    if unknown:
        raise ValueError(f"unknown parameter key(s): {unknown}")
    if missing:
        raise ValueError(f"missing parameter key(s): {missing}")
    if p["dc_gain"] is not None and not p["dc_gain"] > 0:
        raise ValueError("dc_gain must be null (infinite) or > 0")
    if not 0.0 <= p["settling_error"] < 1.0:
        raise ValueError("settling_error must be in [0, 1)")
    if p["ktc_noise_var"] < 0 or p["jitter_rms_s"] < 0 or p["comparator_hysteresis"] < 0:
        raise ValueError("ktc_noise_var, jitter_rms_s, comparator_hysteresis must be >= 0")
    if not isinstance(p["seed"], int) or isinstance(p["seed"], bool):
        raise ValueError("seed must be an integer")
    return dict(p)


def load_params(path):
    with open(path) as f:
        return validate_params(json.load(f))


def tone_input(amplitude, cycles, n_out, decim, warmup_out, params, fs_hz=FS_HZ, rng=None):
    """Coherent tone: ``cycles`` periods over the n_out*decim analysed clocks.

    ``warmup_out`` extra output samples are prepended; phase is continuous.
    Jitter (if any) perturbs the sample instants.
    """
    n = np.arange((n_out + warmup_out) * decim, dtype=np.float64) - warmup_out * decim
    phase = 2.0 * np.pi * cycles * n / (n_out * decim)
    jit = params["jitter_rms_s"]
    if jit > 0.0:
        if rng is None:
            rng = np.random.default_rng(params["seed"])
        # time shift dt -> phase shift 2*pi*f_tone*dt, f_tone = cycles*fs/(n_out*decim)
        f_tone = cycles * fs_hz / (n_out * decim)
        phase = phase + 2.0 * np.pi * f_tone * jit * rng.standard_normal(n.size)
    return amplitude * np.sin(phase)


def modulate(u, params, rng=None):
    """Run the loop over input ``u`` (FS units). Returns the +/-1 bitstream."""
    p = validate_params(params)
    if rng is None:
        rng = np.random.default_rng(p["seed"])
    a = p["dc_gain"]
    pole = 1.0 if a is None else a / (a + 1.0)
    k1 = C1 * (1.0 + p["ci_gain_error"]) * (1.0 - p["settling_error"])
    k2 = C2 * (1.0 + p["ci_gain_error"]) * (1.0 - p["settling_error"])
    u = np.asarray(u, dtype=np.float64)
    # Per-clock additive term on integrator 1 (input, offset, kT/C), vectorised.
    d1 = k1 * u + p["ci_offset"]
    if p["ktc_noise_var"] > 0.0:
        d1 = d1 + np.sqrt(p["ktc_noise_var"]) * rng.standard_normal(u.size)
    d1 = d1.tolist()
    off = p["comparator_offset"]
    hh = 0.5 * p["comparator_hysteresis"]
    x1 = x2 = 0.0
    y = 1.0
    out = [0.0] * len(d1)
    for n, d in enumerate(d1):
        thr = -hh if y > 0.0 else hh
        y = 1.0 if x2 + off > thr else -1.0
        out[n] = y
        x2 = pole * x2 + k2 * (x1 - y)
        x1 = pole * x1 + d - k1 * y
    return np.array(out)
