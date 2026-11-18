#!/usr/bin/env python3
"""DR-001 cross-check: model B (corner parameters) against the T transient.

    python3 -I sim/bmodel/xcheck.py \
        --corner sim/bmodel/corners/tt-1.800V-27C.json \
        --b-side /tmp/bx-tt.json \
        --record sim/bmodel/xcheck-record.json
    python3 -I sim/bmodel/xcheck.py --all --b-dir /tmp/bx --record out.json
    python3 -I sim/bmodel/xcheck.py --all --long --b-dir /tmp/bx-long \
        --record sim/bmodel/xcheck-record-long.json

Compares, per DR-002 anchor, the B-side per-clock samples (run.py --xcheck)
against the committed transistor-level samples (sim/modulator-tran/samples/
for the committed 1024-clock bench, samples-long/ for the long bench with
--long) and writes one append-only record. The tolerance stays DR-001's
3 dB; nothing here changes a spec row, budget or tolerance.

Two record lengths, one comparison
----------------------------------

- **Default: the committed 1024-clock record.** The in-band SNDR leg is NOT
  computable, exactly as sim/modulator-tran/README.md ("What it does not
  claim") anticipated: 1024 modulator clocks give 5 kHz bins on the
  bitstream, so the 20 kHz band of spec row 1 is four bins wide while the
  4-term Blackman-Harris main lobe (+/- 4 bins) covers all four -- the
  lobe-summed signal has no in-band noise bins left to be compared against.
  The decimated route (8 output samples at OSR 128) has an incoherent tone
  and cannot resolve the band either. A corner whose computable legs pass is
  reported `incomplete`, never passed: B numbers stay **uncross-checked**
  and out of row 2.
- **--long: the corrigendum record (DR-001 corrigendum 01, issue #290).**
  4096 recorded clocks give 1250 Hz bins: the band is bins 1..16, the tone
  sits at bin 12 (15 kHz coherent, -6 dBFS), its lobe covers 8..16, and
  **in-band noise bins 1..7 remain** -- DR-001 item 3's leg is computable,
  thin, on both sides. The compared quantity is in-band SNDR against
  in-band SNDR: for each side, signal = the tone-lobe sum, noise = the
  in-band noise bins, lobe-summed per spec sec 1.2's estimator (no ENBW:
  sum(w^2) cancels in the ratio); the gate is |SNDR_B - SNDR_T| <= 3 dB,
  verbatim. The first record's proxy gates (in-band power, span, duty)
  stay reported, not gating, per the operator ruling (options b/c
  declined). A failing leg is a model finding, not a relaxation.

Both routes also report, NOT gated: sample-wise waveform difference and
bit-by-bit agreement. A single-bit loop is chaotic
(sim/modulator-tran/README, "A note for whoever writes the cross-check"):
two realizations differing in initial state or in any unmodelled
micro-effect decorrelate within a few clocks and then agree at about
chance. Sample-wise metrics therefore measure the chaos, not the model, and
are recorded for transparency only.

Gate limits (fixed before any corner other than tt was run; tt was
inspected while the metrics were designed and that inspection is disclosed
here):

- |10*log10(P_inband_B / P_inband_T)| <= 3.0 dB  (short-record proxy leg)
- |SNDR_inband_B - SNDR_inband_T| <= 3.0 dB      (long-record DR-001 leg)
- |p2p_B - p2p_T| / p2p_T <= 0.10 for BOTH integrators
- |mean(y_B) - mean(y_T)| <= 0.05
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import run as brun  # noqa: E402
import sndr  # noqa: E402

REPO = HERE.parents[1]
FS_VOLTS = brun.FS_VOLTS
BAND_HZ = sndr.BW_HZ
TOLERANCE_SNDR_DB = 3.0     # DR-001 item 3, verbatim (both record lengths)
SPAN_REL_LIMIT = 0.10
DUTY_LIMIT = 0.05
WINDOW_TRIM = 0             # both sides are compared over the full committed window

# T-side records: the committed 1024-clock bench and the long bench (DR-001
# corrigendum 01). tone_bin_of reads tone_cycles_in_record from the named
# record rather than assuming it; SAMPLES long/-short keep the same slugs.
T_RECORDS = {
    False: REPO / "sim/modulator-tran/record.json",
    True: REPO / "sim/modulator-tran/record-long.json",
}
T_SAMPLES_DIRS = {
    False: REPO / "sim/modulator-tran/samples",
    True: REPO / "sim/modulator-tran/samples-long",
}

INBAND_NOT_COMPUTABLE = {
    "computable": False,
    "reason": (
        "1024 modulator clocks give 5 kHz bins on the bitstream, so the 20 kHz "
        "band of spec row 1 is four bins wide while the 4-term Blackman-Harris "
        "main lobe (+/- 4 bins) covers all of them: DR-001's lobe-summed "
        "signal / in-band-noise split has no in-band noise bins to sum. The "
        "decimated route (8 output samples at OSR 128) cannot resolve the band "
        "either and its tone is incoherent (3 cycles over 1024 clocks = 3/8 "
        "cycle over 8 output samples). sim/modulator-tran/README.md 'What it "
        "does not claim' anticipated exactly this; DR-001 flags the short "
        "record and the 3 dB tolerance as its first-revisit items. Lengthening "
        "the T record or changing the tolerance is a new decision record, not "
        "done here."
    ),
}


def tone_bin_of(record_path):
    """The tone's bin in the committed window, read from the bench record
    rather than assumed (input_sequence.tone_cycles_in_record: 3 cycles over
    1024 clocks on the short bench, 12 over 4096 on the long bench)."""
    if record_path is None or not pathlib.Path(record_path).is_file():
        return 3  # make_request.py CYCLES; the record above is the primary source
    with open(record_path) as f:
        cycles = json.load(f)["input_sequence"]["tone_cycles_in_record"]
    return int(cycles)


def sha256(path):
    return "sha256:" + hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def rel_path(p):
    """Repo-relative path for the record; a path outside the repo (a test
    fixture) falls back to its absolute form rather than raising."""
    r = pathlib.Path(p).resolve()
    try:
        return str(r.relative_to(REPO))
    except ValueError:
        return str(r)


def spectrum(y):
    """Windowed one-sided power spectrum of a +/-1 bitstream."""
    w = sndr.blackman_harris(len(y))
    return np.abs(np.fft.rfft(np.asarray(y, dtype=np.float64) * w)) ** 2


def band_bins(n, fs, band_hz):
    """Bitstream-bin indices inside (0, band_hz]; DC bin 0 excluded."""
    bin_hz = fs / n
    edge = int(np.floor(band_hz / bin_hz))  # 20 kHz / 5 kHz -> bin 4
    return np.arange(1, edge + 1), edge


def lobe_bins(tone_bin):
    return np.arange(tone_bin - sndr.LOBE, tone_bin + sndr.LOBE + 1)


def inband_and_noise(p, n, fs, band_hz, tone_bin):
    """(in-band power bins 1..edge, out-of-band noise power excluding the
    tone lobe and DC) for one spectrum."""
    band, edge = band_bins(n, fs, band_hz)
    band = band[(band != 0)]
    noise = np.arange(edge + 1, len(p))
    noise = np.setdiff1d(noise, lobe_bins(tone_bin), assume_unique=False)
    return float(p[band].sum()), float(p[noise].sum()), edge, noise


def inband_noise_bin_indices(edge, tone_bin):
    """In-band bins (1..edge, DC 0 excluded) minus the tone lobe: the bins
    DR-001's in-band SNDR leg sums as noise. Empty at the 1024-clock record
    (the whole band is lobe), 7 bins at the 4096-clock record."""
    band = np.arange(1, edge + 1)
    return np.setdiff1d(band, lobe_bins(tone_bin), assume_unique=False)


def inband_sndr(p, edge, tone_bin):
    """(signal, noise, SNDR dB, noise-bin count) for one spectrum: signal =
    the tone-lobe sum, noise = the in-band noise bins, lobe-summed per spec
    sec 1.2's estimator. No ENBW: the window's sum(w^2) appears in numerator
    and denominator and cancels (issue #107). None when there are no
    in-band noise bins."""
    noise_bins = inband_noise_bin_indices(edge, tone_bin)
    sig = float(p[lobe_bins(tone_bin)].sum())
    if len(noise_bins) == 0:
        return sig, None, None, 0
    noi = float(p[noise_bins].sum())
    return sig, noi, 10.0 * np.log10(sig / noi), int(len(noise_bins))


def waveform_stats(a):
    a = np.asarray(a, dtype=np.float64)
    return {
        "mean": float(a.mean()),
        "std": float(a.std()),
        "p2p": float(a.max() - a.min()),
    }


def compare_corner(corner_path, b_side_path, t_samples_path, long=False):
    """All comparisons for one corner. Returns the record entry.

    `long=True` reads the tone bin from the long bench's record and — when
    the record length resolves the 20 kHz band — computes DR-001 item 3's
    in-band SNDR leg and demotes the in-band-power proxy to a reported
    diagnostic (the operator ruling declined it as a gating leg)."""
    corner = brun.load_corner(corner_path)
    with open(b_side_path) as f:
        b = json.load(f)
    with open(t_samples_path) as f:
        t = json.load(f)

    n = int(t["n_clocks"])
    yb = np.asarray(b["y"], dtype=np.float64)
    yt = np.asarray(t["y"], dtype=np.float64)
    if len(yb) != n or len(yt) != n:
        raise ValueError(f"{corner_path}: B side has {len(yb)} clocks, T side "
                         f"{len(yt)}, committed window {n}")
    x1b = np.asarray(b["x1_fs"], dtype=np.float64)
    x2b = np.asarray(b["x2_fs"], dtype=np.float64)
    x1t = np.asarray(t["o1d_v"], dtype=np.float64) / FS_VOLTS
    x2t = np.asarray(t["o2d_v"], dtype=np.float64) / FS_VOLTS

    fs = brun.model.FS_HZ
    tone_bin = tone_bin_of(T_RECORDS[long])
    pb, pt = spectrum(yb), spectrum(yt)
    inb_b, oob_b, edge, noise_bins = inband_and_noise(pb, n, fs, BAND_HZ, tone_bin)
    inb_t, oob_t, _, _ = inband_and_noise(pt, n, fs, BAND_HZ, tone_bin)
    inband_delta_db = 10.0 * np.log10(inb_b / inb_t)
    oob_delta_db = 10.0 * np.log10(oob_b / oob_t)
    sig_b, noi_b, sndr_b, n_noise_bins = inband_sndr(pb, edge, tone_bin)
    _, _, sndr_t, _ = inband_sndr(pt, edge, tone_bin)
    computable = sndr_b is not None and sndr_t is not None

    # sample-wise diagnostics: reported, never gated (chaos, see module doc).
    rel_rms = {}
    for nm, ab, at in (("o1", x1b, x1t), ("o2", x2b, x2t)):
        rms = float(np.sqrt(np.mean((ab - at) ** 2)))
        rel_rms[nm] = {"rms_fs": rms, "rel_to_t_p2p": rms / (at.max() - at.min())}
    bit_disagree_frac = float(np.mean(yb != yt))

    s1b, s1t = waveform_stats(x1b), waveform_stats(x1t)
    s2b, s2t = waveform_stats(x2b), waveform_stats(x2t)
    span_o1 = abs(s1b["p2p"] - s1t["p2p"]) / s1t["p2p"]
    span_o2 = abs(s2b["p2p"] - s2t["p2p"]) / s2t["p2p"]
    duty_b, duty_t = float(yb.mean()), float(yt.mean())

    if computable:
        sndr_delta = abs(sndr_b - sndr_t)
        sndr_entry = {
            "b": float(sndr_b), "t": float(sndr_t),
            "delta_db": float(sndr_delta),
            "computable": True,
            "estimator": ("lobe-summed signal / in-band noise, no ENBW "
                          "(sum(w^2) cancels in the ratio; issue #107), "
                          "spec sec 1.2's estimator"),
            "bins": {
                "band": "1..%d" % edge,
                "signal": "tone lobe %d..%d" % (tone_bin - sndr.LOBE,
                                                tone_bin + sndr.LOBE),
                "noise": "%d in-band bins beside the lobe" % n_noise_bins,
            },
        }
        sndr_leg = {
            "pass": bool(sndr_delta <= TOLERANCE_SNDR_DB),
            "limit_db": TOLERANCE_SNDR_DB,
            "delta_db": float(sndr_delta),
            "b": float(sndr_b), "t": float(sndr_t),
            "what": ("DR-001 item 3 (corrigendum 01): in-band SNDR of B "
                     "over T, same %d-clock window, same 4-term "
                     "Blackman-Harris window; signal = tone-lobe sum "
                     "bins %d..%d, noise = the %d in-band noise bins "
                     "beside it; 3 dB, unchanged" % (
                         n, tone_bin - sndr.LOBE, tone_bin + sndr.LOBE,
                         n_noise_bins)),
        }
        legs = {
            "sndr_inband_3db": sndr_leg,
            "span_10pct": {
                "pass": bool(span_o1 <= SPAN_REL_LIMIT and span_o2 <= SPAN_REL_LIMIT),
                "limit_rel": SPAN_REL_LIMIT,
                "o1_rel": float(span_o1), "o2_rel": float(span_o2),
            },
            "duty_0p05": {
                "pass": bool(abs(duty_b - duty_t) <= DUTY_LIMIT),
                "limit": DUTY_LIMIT,
                "b": duty_b, "t": duty_t,
            },
        }
    else:
        sndr_entry = {"b": None, "t": None, **INBAND_NOT_COMPUTABLE}
        legs = {
            "inband_power_3db": {
                "pass": bool(abs(inband_delta_db) <= TOLERANCE_SNDR_DB),
                "limit_db": TOLERANCE_SNDR_DB,
                "delta_db": float(inband_delta_db),
                "what": ("total windowed power in band bins 1..%d (0, 20 kHz] "
                         "of B over T, same %d-clock window, same 4-term "
                         "Blackman-Harris window; the tone is identical by "
                         "construction" % (edge, n)),
            },
            "span_10pct": {
                "pass": bool(span_o1 <= SPAN_REL_LIMIT and span_o2 <= SPAN_REL_LIMIT),
                "limit_rel": SPAN_REL_LIMIT,
                "o1_rel": float(span_o1), "o2_rel": float(span_o2),
            },
            "duty_0p05": {
                "pass": bool(abs(duty_b - duty_t) <= DUTY_LIMIT),
                "limit": DUTY_LIMIT,
                "b": duty_b, "t": duty_t,
            },
        }
    legs_passed = [k for k, v in legs.items() if v["pass"]]
    legs_failed = [k for k, v in legs.items() if not v["pass"]]

    return {
        "corner_id": corner["corner_id"],
        "dr002_set": "anchor",
        "corner_params_file": rel_path(corner_path),
        "corner_params_sha256": sha256(corner_path),
        "b_side_file": rel_path(b_side_path),
        "b_side_sha256": sha256(b_side_path),
        "t_samples_file": rel_path(t_samples_path),
        "t_samples_sha256": sha256(t_samples_path),
        "record_length_clocks": n,
        "window": "Blackman-Harris 4-term",
        "bin_bw_hz": fs / n,
        "band_hz": [0, BAND_HZ],
        "amplitude_dbfs": -6.0,
        "amplitude_note": ("the T bench drove spec row 11's 0.5*VREF (-6 dBFS "
                           "nominal); the committed u_diff_v is the analytic "
                           "tone sample values"),
        "tone_hz": 15000.0,
        "tone_bin": tone_bin,
        "compared_bins": {
            "inband": "1..%d" % edge,
            "dc_excluded": [0, 0],
            "out_of_band_noise": "%d..%d excluding tone lobe %d..%d" % (
                edge + 1, len(pb) - 1, tone_bin - sndr.LOBE, tone_bin + sndr.LOBE),
        },
        "sndr_inband_db": sndr_entry,
        "inband_power_fs_norm": {"b": inb_b, "t": inb_t,
                                 "delta_db": float(inband_delta_db),
                                 "role": ("reported proxy; declined as a "
                                          "gating leg by the operator ruling "
                                          "(options b/c)" if computable
                                          else "gating proxy while the SNDR "
                                          "leg is not computable")},
        "out_of_band_noise_power": {"b": oob_b, "t": oob_t,
                                    "delta_db": float(oob_delta_db),
                                    "note": ("auxiliary gross-mismatch detector; "
                                             "not a DR-001 leg")},
        "waveforms": {
            "o1_fs": {"b": s1b, "t": s1t, "span_rel_diff": float(span_o1)},
            "o2_fs": {"b": s2b, "t": s2t, "span_rel_diff": float(span_o2)},
            "units": "1 model-B FS = 1.2 V differential (run.py FS_VOLTS)",
            "sample_wise_reported_not_gated": {
                **rel_rms,
                "bit_disagree_frac": bit_disagree_frac,
                "why_not_gated": ("a single-bit loop is chaotic; B and T "
                                  "decorrelate sample-wise within a few "
                                  "clocks whatever the model's quality "
                                  "(sim/modulator-tran/README.md), so these "
                                  "metrics measure the chaos, not the model"),
            },
        },
        "duty": {"b": duty_b, "t": duty_t},
        "legs": legs,
        "legs_passed": legs_passed,
        "legs_failed": legs_failed,
    }


def finalise_entry(entry, long=False):
    """Attach the cross_check_status statement to a computed entry."""
    if entry.get("error") is not None:
        entry["cross_check_status"] = (
            f"uncross-checked: no T bitstream comparison was possible ({entry['error']})")
        return entry
    if not entry["sndr_inband_db"]["computable"]:
        legs = entry["legs_passed"]
        legtxt = ", ".join(legs) if legs else "none"
        failed = ("; FAILED legs: " + ", ".join(entry["legs_failed"])) if entry["legs_failed"] else ""
        entry["cross_check_status"] = (
            "incomplete: DR-001's in-band-SNDR leg is not computable at the "
            "committed 1024-clock T record (see sndr_inband_db.reason), so DR-001 "
            "item 3 acceptance cannot be declared at any corner. Computable legs: "
            f"{legtxt}{failed}. Model B numbers at this corner are reported "
            "uncross-checked and are not used for row 2.")
        return entry
    failed = entry["legs_failed"]
    failedtxt = ("; FAILED legs: " + ", ".join(failed)) if failed else ""
    if failed:
        entry["cross_check_status"] = (
            "failed at this corner: the in-band SNDR leg of DR-001 item 3 is "
            "computable at the corrigendum's 4096-clock record and disagrees "
            f"beyond 3 dB{failedtxt}. A failing leg is a model finding, not a "
            "relaxation (DR-001 item 3); model B numbers at this corner stay "
            "uncross-checked and are not used for row 2.")
    else:
        entry["cross_check_status"] = (
            "passed: DR-001 item 3's in-band SNDR leg is computable at the "
            "corrigendum's 4096-clock record (in-band noise bins beside the "
            "tone lobe) and agrees within 3 dB, with span and duty agreed. "
            "Model B numbers at this corner are cross-checked "
            "under DR-001 corrigendum 01 (proposed; ratification is two "
            "reviews and then the operator) and may carry a row 2 claim once "
            "it is ratified.")
    return entry


def no_t_samples_entry(corner_path, long=False):
    """A corner with no committed T bitstream is reported uncross-checked,
    never skipped (issue #128 acceptance criteria)."""
    corner = brun.load_corner(corner_path)
    return {
        "corner_id": corner["corner_id"],
        "corner_params_file": rel_path(corner_path),
        "corner_params_sha256": sha256(corner_path),
        "t_samples_file": None,
        "error": (f"no committed T samples at "
                  f"{T_SAMPLES_DIRS[long] / (corner['sample_slug'] + '.json')}"),
    }


def git_state():
    def g(*a):
        r = subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return {"git_commit": g("rev-parse", "HEAD"), "git_dirty": bool(g("status", "--porcelain"))}


def build_record(entries, long=False):
    if long:
        return {
            "source": "cross-check (B vs T), long record",
            "result_kind": (
                "simulated (behavioural model B with T-extracted corner "
                "parameters compared against the 4096-clock transistor-level "
                "transient; DR-001 item 3 as amended by DR-001 corrigendum 01)"),
            "method_basis": (
                "spec/decisions/DR-001-evidence-split.md item 3, as amended by "
                "spec/decisions/DR-001-corrigendum-01.md (issue #290); T side "
                "sim/modulator-tran record-long.json + samples-long/"),
            "acceptance_gates": {
                "sndr_inband_3db": (
                    "|SNDR_inband_B - SNDR_inband_T| <= 3.0 dB -- DR-001's "
                    "tolerance verbatim, on the lobe-summed signal / in-band "
                    "noise estimator of spec sec 1.2, both sides over the "
                    "same 4096-clock window"),
                "span_10pct": "integrator span agreement, both integrators",
                "duty_0p05": "loop duty agreement",
                "reported_not_gating": (
                    "in-band power agreement (the first record's computable "
                    "ancestor of this leg) and out-of-band noise power stay "
                    "reported as auxiliary diagnostics; the operator ruling "
                    "declined them as the closing leg (options b/c)"),
            },
            "dr001_acceptance": (
                "computed per corner: the corrigendum's 4096-clock record "
                "leaves in-band noise bins beside the tone lobe, so item 3's "
                "SNDR-vs-SNDR gate is applied as written (3 dB, unchanged). "
                "A corner that passes is cross-checked under the corrigendum "
                "(proposed until ratified: two reviews, then the operator); "
                "a corner that fails is a model finding, not a relaxation. "
                "The committed 1024-clock record (xcheck-record.json) and "
                "its incomplete-at-every-corner statement are untouched "
                "append-only evidence."),
            "corrigendum_length_evidence": (
                "N_T = 4096 recorded clocks: probe run 1104.6 s (one corner, "
                "tt/27 C/1.80 V, fleet job klt-sim-56a43a043984) against the "
                "fleet's 3600 s whole-job ceiling; 8192 clocks extrapolate "
                "past it at every measured per-clock rate. "
                "spec/decisions/DR-001-corrigendum-01.md holds the full "
                "arithmetic."),
            "corners": entries,
            "record_len_note": ("per DR-001 item 5 each comparison states "
                                "record length, window, bin bandwidth and "
                                "amplitude; every number here is simulated, "
                                "nothing measured"),
            **brun.git_state(),
            **brun.code_state(extra=(HERE / "xcheck.py",)),
        }
    return {
        "source": "cross-check (B vs T)",
        "result_kind": ("simulated (behavioural model B with T-extracted corner "
                        "parameters compared against the short transistor-level "
                        "transient; DR-001 item 3)"),
        "method_basis": "spec/decisions/DR-001-evidence-split.md item 3; T side sim/modulator-tran (issue #125)",
        "acceptance_gates": {
            "inband_power_3db": ("|10*log10(P_inband_B/P_inband_T)| <= 3.0 dB -- "
                                 "DR-001's tolerance verbatim, applied to the "
                                 "computable ancestor of its in-band SNDR leg"),
            "span_10pct": "integrator span agreement, both integrators",
            "duty_0p05": "loop duty agreement",
            "fixed_when": ("fixed before any corner other than tt was run; tt "
                           "was inspected while the metrics were designed and "
                           "that inspection is disclosed here"),
        },
        "dr001_acceptance": ("incomplete at every corner: the in-band SNDR leg "
                             "is not computable at the committed T record "
                             "length (sndr_inband_db.reason). A corner whose "
                             "computable legs all pass is reported "
                             "'incomplete', never 'passed': DR-001 item 3 "
                             "acceptance needs both legs. Lengthening the T "
                             "record or changing the 3 dB tolerance is a new "
                             "decision record."),
        "corners": entries,
        "record_len_note": ("per DR-001 item 5 each comparison states record "
                            "length, window, bin bandwidth and amplitude; "
                            "every number here is simulated, nothing measured"),
        **brun.git_state(),
        **brun.code_state(extra=(HERE / "xcheck.py",)),
    }


def write_record(path, rec):
    with open(path, "x") as f:
        json.dump(rec, f, indent=2)
        f.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corner", help="one sim/bmodel/corners/<anchor>.json")
    ap.add_argument("--b-side", help="B-side samples from run.py --xcheck")
    ap.add_argument("--all", action="store_true",
                    help="every corner file under sim/bmodel/corners/")
    ap.add_argument("--b-dir", help="directory holding <slug> B-side samples (with --all)")
    ap.add_argument("--b-prefix", default="bx-")
    ap.add_argument("--long", action="store_true",
                    help="the corrigendum's 4096-clock record (DR-001 "
                         "corrigendum 01, issue #290): T samples from "
                         "samples-long/, tone bin from record-long.json, and "
                         "DR-001 item 3's in-band SNDR leg computed where the "
                         "band resolves")
    ap.add_argument("--record", required=True, help="output record (exclusive create)")
    args = ap.parse_args(argv)

    corners = sorted(HERE.glob("corners/*.json")) if args.all else [pathlib.Path(args.corner)]
    if not args.all and not args.corner:
        ap.error("give --corner or --all")

    entries = []
    for cpath in corners:
        corner = brun.load_corner(cpath)
        tpath = T_SAMPLES_DIRS[args.long] / f"{corner['sample_slug']}.json"
        if not tpath.is_file():
            entries.append(no_t_samples_entry(cpath, long=args.long))
            continue
        bpath = (pathlib.Path(args.b_dir) / f"{args.b_prefix}{corner['sample_slug']}.json") \
            if args.all else pathlib.Path(args.b_side)
        if not bpath.is_file():
            entries.append({
                "corner_id": corner["corner_id"],
                "corner_params_file": rel_path(cpath),
                "error": f"no B-side samples at {bpath}; run run.py --xcheck first",
            })
            continue
        entries.append(compare_corner(cpath, bpath, tpath, long=args.long))
    entries = [finalise_entry(e, long=args.long) for e in entries]

    rec = build_record(entries, long=args.long)
    write_record(args.record, rec)
    for e in entries:
        line = f"{e['corner_id']}: {e['cross_check_status'].split('.')[0]}"
        if e.get("error") is None:
            line += (f" | inband {e['inband_power_fs_norm']['delta_db']:+.2f} dB, "
                     f"span o1 {e['waveforms']['o1_fs']['span_rel_diff']:.3f} "
                     f"o2 {e['waveforms']['o2_fs']['span_rel_diff']:.3f}")
        print(line)
    print(f"record -> {args.record}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
