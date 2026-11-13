#!/usr/bin/env python3
"""Decompose the gap between ideal model B and the spec section 5.1 ceiling.

    python3 -I sim/bmodel/ceiling_gap.py --params sim/bmodel/ideal.json

Issue #108 / DR-007. One bitstream is generated at the row-11 operating point
(-6 dBFS) and read three ways, so the 8 dB gap between the spec section 5.1
figure and the model's peak SNDR is split into named terms:

1. ``formula_full_scale_convention`` -- section 5.1 writes the quantizer term
   as ``6.02*N + 1.76`` = ``10*log10(1.5 * 2^(2N))``, which assumes a
   full-scale sine of amplitude ``2^(N-1)*delta``. For N = 1 that is
   ``delta`` = 2 in the model's units: twice the +/-1 feedback level that
   ``model.py`` and spec row 11 call full scale. The level-count form
   ``10*log10(1.5 * (2^N - 1)^2)`` is 6.02 dB lower at N = 1 and 0.0003 dB
   lower at N = 16. Closed form, no simulation.
2. ``single_bit_loop`` -- the corrected closed-form bound against a brick-wall
   reading of the same bitstream. This is what the real single-bit loop costs
   against the linear model with a white error of variance ``delta^2/12``:
   the quantizer's effective gain is not the value that makes the 0.5/0.5
   loop's NTF exactly ``(1-z^-1)^2``, and its error is neither white nor of
   that variance. Measured.
3. ``sinc3_decimator`` -- the brick-wall reading against the committed sinc^3
   path. Negative: the decimator's passband droop attenuates shaped noise
   toward 20 kHz by more than its finite stopband aliases back in, so the
   committed path reads *higher* than a brick wall. Measured.

The three terms sum to the observed deficit by construction (they are three
differences along one chain of four figures); the content is the two measured
intermediate figures, not the closure. Two independent cross-checks are run
against them: the sinc^3 figure is predicted from the full-rate spectrum by
folding it through the decimator's own response, and the single-bit term is
compared against a describing-function model using the loop's measured
effective quantizer gain and error variance.

Single process, numpy only, no SPICE. Source B, simulated -- not measured.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python -I does not add the script directory

import numpy as np  # noqa: E402

import model  # noqa: E402
import run  # noqa: E402
import sndr  # noqa: E402

AMP_DBFS = -6          # spec row 11: peak differential input <= 0.5*VREF
ORDER = 2              # spec row 3: second-order loop
N_BITS = 1             # spec row 3: single-bit quantizer
OSR = 128              # spec row 4


# ---------------------------------------------------------------- closed form

def quantizer_term_db(n_bits, level_count):
    """The ``6.02*N + 1.76`` term of spec section 5.1, both conventions.

    ``level_count=False`` reproduces the spec as written: a full-scale sine of
    amplitude ``2^(n_bits-1)*delta``, i.e. ``10*log10(1.5 * 2^(2N))``.
    ``level_count=True`` uses the amplitude the outer quantizer levels
    actually reach, ``((2^n_bits - 1)/2)*delta``, i.e.
    ``10*log10(1.5 * (2^N - 1)^2)``. They differ by 6.02 dB at N = 1.
    """
    span = (2.0**n_bits - 1.0) if level_count else 2.0**n_bits
    return 10.0 * np.log10(1.5 * span**2)


def bound_db(amp_dbfs=AMP_DBFS, order=ORDER, n_bits=N_BITS, osr=OSR, level_count=True):
    """Spec section 5.1 ideal quantization-noise ceiling, in dB.

    ``SQNR = Q(N) - 10*log10(pi^(2L)/(2L+1)) + (2L+1)*10*log10(OSR) + amp``
    with ``Q(N)`` from `quantizer_term_db`. The second term is the small-angle
    integral of ``|(1-z^-1)^L|^2`` over the band; `exact_ntf_bound_db` shows
    the approximation is worth 0.0001 dB at OSR = 128.
    """
    shaping = 10.0 * np.log10(np.pi ** (2 * order) / (2 * order + 1))
    return (quantizer_term_db(n_bits, level_count) - shaping
            + (2 * order + 1) * 10.0 * np.log10(osr) + amp_dbfs)


def exact_ntf_bound_db(amp_dbfs=AMP_DBFS, order=ORDER, osr=OSR, err_var=1.0 / 3.0,
                       gain=None, n_int=200001):
    """Linear-model SNDR with white quantizer error, by numerical integration.

    ``gain=None`` integrates the unscaled ``(1-z^-1)^order`` NTF the spec
    assumes -- a control on the small-angle step in `bound_db`. A ``gain``
    linearises the loop's own quantizer as ``y = gain*x2 + e`` (describing
    function), giving the NTF of the 0.5/0.5 loop with that gain:

        NTF(z) = (1-z^-1)^2 / (1 + (C2*gain - 2)z^-1 + (1 - C2*gain + C1*C2*gain)z^-2)

    ``gain = 1/(C1*C2) = 4`` makes the denominator 1, recovering ``(1-z^-1)^2``.
    """
    fs = 2.0 * sndr.BW_HZ * osr
    f = np.linspace(0.0, sndr.BW_HZ, n_int)
    zi = np.exp(-2j * np.pi * f / fs)        # z^-1
    num = np.abs((1.0 - zi) ** order) ** 2
    if gain is None:
        mag2 = num
    else:
        g2, g12 = model.C2 * gain, model.C1 * model.C2 * gain
        den = 1.0 + (g2 - 2.0) * zi + (1.0 - g2 + g12) * zi**2
        mag2 = num / np.abs(den) ** 2
    noise = err_var * (2.0 / fs) * np.trapz(mag2, f)
    amp = 10.0 ** (amp_dbfs / 20.0)
    return 10.0 * np.log10((amp * amp / 2.0) / noise)


# ------------------------------------------------------------------- measured

def bitstream(params, amp_dbfs, n_out, cycles):
    """The +/-1 bitstream over the analysed clocks, plus the input tone.

    ``run.run_point`` discards ``run.WARMUP_OUT`` output samples; output
    sample k of `sndr.sinc3_decimate` starts at input clock ``DECIM*k``, so
    the analysed clocks start at ``WARMUP_OUT*DECIM`` of the generated array,
    which is clock 0 of the coherent tone. The slice therefore carries exactly
    ``cycles`` tone periods and is coherent at the modulator rate too.
    """
    amp = 10.0 ** (amp_dbfs / 20.0)
    rng = np.random.default_rng(params["seed"])
    u = model.tone_input(amp, cycles, n_out, sndr.DECIM, run.WARMUP_OUT, params, rng=rng)
    y = model.modulate(u, params, rng=rng)
    skip = run.WARMUP_OUT * sndr.DECIM
    n_clk = n_out * sndr.DECIM
    return y, u, skip, n_clk


def sinc3_path(y, n_out, cycles):
    """The committed path: sinc^3 decimate by 64, then `sndr.sndr_db`.

    This is `run.run_point` inlined, and it is bit-identical to it -- including
    that `sndr.sinc3_decimate` returns two samples fewer than the requested
    ``n_out`` after the warm-up slice, so the analysed window is 65534 samples
    at ``n_out`` = 2^16 and the tone sits at 1638.95 rather than 1639 cycles.
    The record reports the analysed length and that residual per path; it is
    `run.py`'s own behaviour and is not corrected here (it would change every
    committed B figure). The brick-wall path below is exactly coherent, so the
    sinc^3 term carries this residual; `fold_through_decimator` bounds it.
    """
    out = sndr.sinc3_decimate(y)
    rec = out[run.WARMUP_OUT : run.WARMUP_OUT + n_out]
    val, det = sndr.sndr_db(rec, cycles)
    return val, det, len(rec)


def brickwall_path(y, skip, n_clk, cycles):
    """Brick-wall reading: the same bitstream, FFT at ``fs``, summed to 20 kHz.

    `sndr.sndr_db` with ``fout_hz = fs`` is exactly that measurement -- same
    window, same tone bin, same DC and tone-lobe exclusions, and the same bin
    bandwidth, because ``fs/(n_out*DECIM) == fout/n_out``. No filter is
    designed, so there is no filter to defend.
    """
    rec = y[skip : skip + n_clk]
    val, det = sndr.sndr_db(rec, cycles, fout_hz=model.FS_HZ)
    return val, det, len(rec)


def decimator_mag2(j, n_clk, n_out, decim=sndr.DECIM):
    """``|H(f)|^2`` of `sndr.sinc3_decimate` at full-rate rfft bins ``j``.

    ``H = (sin(pi*j/n_out) / (decim*sin(pi*j/n_clk)))^3``, the triple box of
    length ``decim`` normalised to unity gain at DC.
    """
    j = np.asarray(j, dtype=np.float64)
    den = decim * np.sin(np.pi * j / n_clk)
    with np.errstate(divide="ignore", invalid="ignore"):
        h = np.sin(np.pi * j / n_out) / den
    return np.where(j == 0.0, 1.0, h) ** 6


def fold_through_decimator(y, skip, n_clk, n_out, cycles, decim=sndr.DECIM):
    """Predict the sinc^3 figure from the full-rate spectrum, droop vs alias.

    Decimation by ``decim`` maps full-rate bin ``j`` onto output bin
    ``j mod n_out``, folded into ``[0, n_out/2]``. So the noise in output bin
    ``b`` is the sum over ``j = m*n_out +/- b`` of ``P(j)*|H(j)|^2``. The
    ``m = 0`` term is passband droop; every ``m >= 1`` term is alias leakage
    through the CIC's finite stopband.

    Returns (sndr_droop_only_db, sndr_predicted_db, alias_over_droop).
    """
    win = sndr.blackman_harris(n_clk)
    p = np.abs(np.fft.rfft(y[skip : skip + n_clk] * win)) ** 2
    edge = int(round(sndr.BW_HZ * n_clk / model.FS_HZ))
    lobe = np.arange(cycles - sndr.LOBE, cycles + sndr.LOBE + 1)
    band = np.arange(sndr.DC_EXCL_BINS + 1, edge + 1)
    b = np.setdiff1d(band, lobe)                     # in-band noise bins

    nyq = n_clk // 2
    m = np.arange(0, nyq // n_out + 2)[:, None]
    j = np.concatenate([m * n_out + b[None, :], m * n_out - b[None, :]])
    keep = (j >= 0) & (j <= nyq)
    jj = np.where(keep, j, 0)
    contrib = np.where(keep, p[jj] * decimator_mag2(jj, n_clk, n_out), 0.0)

    is_droop = (j == b[None, :])                     # m = 0, the +b branch only
    droop = float(contrib[is_droop].sum())
    total = float(contrib.sum())
    sig = float((p[lobe] * decimator_mag2(lobe, n_clk, n_out)).sum())
    return (10.0 * np.log10(sig / droop), 10.0 * np.log10(sig / total),
            (total - droop) / droop)


def effective_quantizer(y, u, params, skip, n_clk):
    """Describing-function gain and error variance of the 1-bit quantizer.

    Reconstructs the integrator states from ``u`` and ``y`` -- exact for ideal
    parameters (``pole`` = 1, no offsets, no noise) -- and asserts
    ``y[n] == sign(x2[n])`` on every clock, which is the check that the
    reconstruction is the loop's own state and not an approximation of it.
    The recursion is run from the loop's own zero initial state over the whole
    generated array, warm-up included, and only then sliced to the analysed
    clocks -- the state at the start of the analysed window is not zero.

    The minimum-mean-square linearisation ``y ~ gain*x2 + e`` gives
    ``gain = E[y*x2]/E[x2^2] = E[|x2|]/E[x2^2]`` and
    ``err_var = E[(y - gain*x2)^2] = 1 - gain*E[|x2|]``.
    """
    if params != model.PARAM_DEFAULTS:
        return None
    x1 = np.concatenate(([0.0], np.cumsum(model.C1 * (u - y))))[:-1]
    x2 = np.concatenate(([0.0], np.cumsum(model.C2 * (x1 - y))))[:-1]
    if not np.array_equal(y, np.where(x2 > 0.0, 1.0, -1.0)):
        raise AssertionError("state reconstruction does not reproduce the bitstream")
    x2 = x2[skip : skip + n_clk]
    abs_x2, sq_x2 = float(np.mean(np.abs(x2))), float(np.mean(x2 * x2))
    gain = abs_x2 / sq_x2
    return {"gain": gain, "err_var": 1.0 - gain * abs_x2,
            "mean_abs_x2": abs_x2, "mean_sq_x2": sq_x2,
            "gain_for_unscaled_ntf": 1.0 / (model.C1 * model.C2)}


# --------------------------------------------------------------------- record

def decompose(params, n_out, amp_dbfs=AMP_DBFS):
    cycles = sndr.odd_cycles(n_out)
    y, u, skip, n_clk = bitstream(params, amp_dbfs, n_out, cycles)
    s3_db, s3_det, s3_n = sinc3_path(y, n_out, cycles)
    bw_db, bw_det, bw_n = brickwall_path(y, skip, n_clk, cycles)
    droop_db, pred_db, alias_ratio = fold_through_decimator(y, skip, n_clk, n_out, cycles)

    spec_db = bound_db(amp_dbfs, level_count=False)
    corr_db = bound_db(amp_dbfs, level_count=True)
    terms = {
        "formula_full_scale_convention": spec_db - corr_db,
        "single_bit_loop": corr_db - bw_db,
        "sinc3_decimator": bw_db - s3_db,
    }
    eq = effective_quantizer(y, u, params, skip, n_clk)
    df_db = None if eq is None else exact_ntf_bound_db(
        amp_dbfs, err_var=eq["err_var"], gain=eq["gain"])

    return {
        "source": "B",
        "record_kind": "ceiling-gap decomposition (issue #108, DR-007)",
        "result_kind": "simulated (behavioural model B, uncross-checked)",
        "corner": "none (ideal parameters)",
        "cross_check": "none (ideal parameters)",
        "amplitude_dbfs": amp_dbfs,
        "record_len": n_out,
        "modulator_clocks": n_clk,
        "warmup_clocks_discarded": skip,
        "window": s3_det["window"],
        "tone_cycles": cycles,
        "tone_hz": cycles * sndr.FOUT_HZ / n_out,
        "band_hz": [0, sndr.BW_HZ],
        "oversampling_ratio": OSR,
        "fs_hz": model.FS_HZ,
        "fout_hz": sndr.FOUT_HZ,
        "paths": {
            "sinc3": {
                "sndr_db": s3_db,
                "what": "committed path: sinc^3 decimate by 64, FFT of the output record",
                "rate_hz": sndr.FOUT_HZ,
                "analysed_samples": s3_n,
                "tone_cycles_in_analysed_window": cycles * s3_n / n_out,
                "bin_bw_hz": s3_det["bin_bw_hz"],
                "band_edge_bin": s3_det["band_edge_bin"],
                "excluded_bins": s3_det["excluded_bins"],
                "enbw_bins": s3_det["enbw_bins"],
            },
            "brick_wall": {
                "sndr_db": bw_db,
                "what": "same bitstream, FFT at the modulator rate, summed to 20 kHz",
                "rate_hz": model.FS_HZ,
                "analysed_samples": bw_n,
                "tone_cycles_in_analysed_window": float(cycles),
                "bin_bw_hz": bw_det["bin_bw_hz"],
                "band_edge_bin": bw_det["band_edge_bin"],
                "excluded_bins": bw_det["excluded_bins"],
                "enbw_bins": bw_det["enbw_bins"],
            },
        },
        "bounds": {
            "spec_5_1_as_written_db": spec_db,
            "spec_5_1_level_count_corrected_db": corr_db,
            "quantizer_term_as_written_db": quantizer_term_db(N_BITS, False),
            "quantizer_term_level_count_db": quantizer_term_db(N_BITS, True),
            "closed_form_is_small_angle": True,
            "exact_ntf_integral_db": exact_ntf_bound_db(amp_dbfs),
            "order": ORDER,
            "n_bits": N_BITS,
        },
        "deficit_db": spec_db - s3_db,
        "terms_db": terms,
        "terms_sum_db": sum(terms.values()),
        "closure_db": (spec_db - s3_db) - sum(terms.values()),
        "closure_note": ("algebraic: the three terms are successive differences "
                         "along spec -> corrected -> brick wall -> sinc^3"),
        "coherence_note": (
            "the brick-wall path analyses exactly n_out*64 clocks and is exactly "
            "coherent; the sinc^3 path is run.run_point unchanged, whose analysed "
            "window is two output samples short of record_len, so its tone sits "
            "at tone_cycles_in_analysed_window rather than tone_cycles. The "
            "residual is carried by the sinc3_decimator term and bounded by "
            "cross_checks.sinc3_prediction_error_db."),
        "cross_checks": {
            "sinc3_droop_only_db": droop_db,
            "sinc3_predicted_from_full_rate_db": pred_db,
            "sinc3_prediction_error_db": pred_db - s3_db,
            "alias_power_over_drooped_in_band_power": alias_ratio,
            "effective_quantizer": eq,
            "describing_function_sndr_db": df_db,
            "describing_function_error_db": None if df_db is None else df_db - bw_db,
        },
        "loop": run.LOOP,
        "decimation": {"filter": "sinc^3 float64", "factor": sndr.DECIM},
        "params": params,
        "numpy": np.__version__,
        **run.git_state(),
    }


def report(d):
    t, c, b = d["terms_db"], d["cross_checks"], d["bounds"]
    eq = c["effective_quantizer"]
    lines = [
        f"source B, simulated, ideal parameters, {d['amplitude_dbfs']} dBFS, "
        f"N = {d['record_len']} output samples ({d['modulator_clocks']} clocks)",
        f"  window {d['window']}, band 0-{sndr.BW_HZ/1e3:.0f} kHz; "
        f"sinc^3 {d['paths']['sinc3']['analysed_samples']} samples at "
        f"{d['paths']['sinc3']['bin_bw_hz']:.4f} Hz, brick wall "
        f"{d['paths']['brick_wall']['analysed_samples']} at "
        f"{d['paths']['brick_wall']['bin_bw_hz']:.4f} Hz",
        "",
        f"spec 5.1 as written                      {b['spec_5_1_as_written_db']:8.2f} dB",
        f"  level-count corrected                  {b['spec_5_1_level_count_corrected_db']:8.2f} dB",
        f"brick-wall reading of the bitstream      {d['paths']['brick_wall']['sndr_db']:8.2f} dB",
        f"committed sinc^3 path                    {d['paths']['sinc3']['sndr_db']:8.2f} dB",
        "",
        f"deficit, spec 5.1 to sinc^3              {d['deficit_db']:8.2f} dB",
        f"  1. formula full-scale convention       {t['formula_full_scale_convention']:+8.2f} dB",
        f"  2. single-bit loop                     {t['single_bit_loop']:+8.2f} dB",
        f"  3. sinc^3 decimator                    {t['sinc3_decimator']:+8.2f} dB",
        f"  sum                                    {d['terms_sum_db']:8.2f} dB  "
        f"(closure {d['closure_db']:+.4f} dB, algebraic)",
        "",
        "cross-checks",
        f"  sinc^3 droop only, aliasing removed    {c['sinc3_droop_only_db']:8.2f} dB",
        f"  alias power / drooped in-band power    {c['alias_power_over_drooped_in_band_power']:8.3f}",
        f"  sinc^3 predicted from the full rate    {c['sinc3_predicted_from_full_rate_db']:8.2f} dB  "
        f"(error {c['sinc3_prediction_error_db']:+.2f} dB)",
        f"  exact (1-z^-1)^2 integral vs closed    {b['exact_ntf_integral_db']:8.2f} dB  "
        f"(error {b['exact_ntf_integral_db'] - b['spec_5_1_level_count_corrected_db']:+.4f} dB)",
    ]
    if eq is not None:
        lines += [
            f"  effective quantizer gain               {eq['gain']:8.3f}  "
            f"(unscaled NTF would need {eq['gain_for_unscaled_ntf']:.1f})",
            f"  effective quantizer error variance     {eq['err_var']:8.4f}  "
            f"(white delta^2/12 assumes {1/3:.4f})",
            f"  describing-function SNDR               {c['describing_function_sndr_db']:8.2f} dB  "
            f"(error {c['describing_function_error_db']:+.2f} dB vs brick wall)",
        ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", required=True, help="JSON parameter file (see ideal.json)")
    ap.add_argument("--record-len", type=int, default=2**16,
                    help="output samples (power of two, >= 2^16 for evidence)")
    ap.add_argument("--out-dir", default=str(run.RECORDS))
    ap.add_argument("--no-record", action="store_true",
                    help="print the decomposition without writing a record")
    a = ap.parse_args(argv)
    if a.record_len & (a.record_len - 1):
        ap.error("--record-len must be a power of two")
    params = model.load_params(a.params)
    d = decompose(params, a.record_len)
    print(report(d))
    if a.no_record:
        return 0
    canon = json.dumps(params, sort_keys=True, separators=(",", ":"))
    sha = hashlib.sha256(canon.encode()).hexdigest()
    d["params_sha256"] = sha
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = pathlib.Path(a.out_dir) / f"{ts}-ceiling-gap-{sha[:8]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    run.write_record(path, d)
    print(f"\n-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
