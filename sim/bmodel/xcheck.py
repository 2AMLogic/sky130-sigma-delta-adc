#!/usr/bin/env python3
"""DR-001 cross-check: model B (corner parameters) against the short T transient.

    python3 -I sim/bmodel/xcheck.py \
        --corner sim/bmodel/corners/tt-1.800V-27C.json \
        --b-side /tmp/bx-tt.json \
        --record sim/bmodel/xcheck-record.json
    python3 -I sim/bmodel/xcheck.py --all --b-dir /tmp/bx --record out.json

Compares, per DR-002 anchor, the B-side per-clock samples (run.py --xcheck)
against the committed transistor-level samples (sim/modulator-tran/samples/,
issue #125) and writes one append-only record. The tolerance stays DR-001's
3 dB; nothing here changes a spec row, budget or tolerance.

What is compared, and what is honestly not computable
----------------------------------------------------

DR-001 item 3 accepts the model at a corner only if "the in-band SNDR of the
two agrees to within 3 dB over the same short record, and the integrator
output waveforms agree". At the committed record length the SNDR leg is NOT
computable, exactly as sim/modulator-tran/README.md ("What it does not
claim") anticipated: 1024 modulator clocks give 5 kHz bins on the bitstream,
so the 20 kHz band of spec row 1 is four bins wide while the 4-term
Blackman-Harris main lobe (+/- 4 bins) covers all four -- the lobe-summed
signal has no in-band noise bins left to be compared against. The decimated
route (8 output samples at OSR 128) has an incoherent tone (3 cycles over
1024 clocks = 3/8 cycles over 8 output samples) and cannot resolve the band
either. That tension is DR-001's own flagged first-revisit item; changing the
record length or the tolerance needs a new decision record and is not done
here.

What this record reports instead, per corner:

- `inband_power_delta_db` -- total windowed power in the band bins (bins 1-4,
  DC bin 0 excluded) of B and of T over the same 1024-clock window, compared
  against DR-001's 3 dB. The tone is identical by construction (same input
  sequence), so this is the computable ancestor of the intended in-band
  SNDR comparison: with the signal fixed, an in-band power agreement bounds
  the in-band noise agreement. It is NOT called an SNDR and does not satisfy
  DR-001's letter.
- integrator waveform statistics -- span (peak-to-peak), standard deviation
  and mean of both integrators, B against T; gated on span agreement.
- loop duty -- mean bitstream value, B against T.
- reported, NOT gated: sample-wise waveform difference and bit-by-bit
  agreement. A single-bit loop is chaotic (sim/modulator-tran/README, "A
  note for whoever writes the cross-check"): two realizations differing in
  initial state or in any unmodelled micro-effect decorrelate within a few
  clocks and then agree at about chance. Sample-wise metrics therefore
  measure the chaos, not the model, and are recorded for transparency only.

Acceptance gates (fixed before any corner other than tt was run; tt was
inspected while the metrics were being designed and that is disclosed here):

- |10*log10(P_inband_B / P_inband_T)| <= 3.0 dB  (DR-001's tolerance verbatim)
- |p2p_B - p2p_T| / p2p_T <= 0.10 for BOTH integrators
- |mean(y_B) - mean(y_T)| <= 0.05

A corner whose every computable leg passes is still reported
`cross_check_status: "incomplete"`: DR-001's acceptance needs the in-band
SNDR leg, which this record length cannot express, so numbers from B remain
**uncross-checked** and are not used for row 2 (DR-001 item 3; issue #128).
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
SAMPLES = REPO / "sim/modulator-tran/samples"

FS_VOLTS = brun.FS_VOLTS
BAND_HZ = sndr.BW_HZ
TOLERANCE_SNDR_DB = 3.0     # DR-001 item 3, verbatim
SPAN_REL_LIMIT = 0.10
DUTY_LIMIT = 0.05
WINDOW_TRIM = 0             # both sides are compared over the full committed window

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


def tone_bin_of(t_samples_path):
    """The tone's bin in the committed window: 3 cycles over 1024 clocks
    (sim/modulator-tran/record.json input_sequence.tone_cycles_in_record),
    read from the record rather than assumed."""
    rec = REPO / "sim/modulator-tran/record.json"
    if rec.is_file():
        with open(rec) as f:
            cycles = json.load(f)["input_sequence"]["tone_cycles_in_record"]
        return int(cycles)
    return 3  # make_request.py CYCLES; the record above is the primary source


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


def waveform_stats(a):
    a = np.asarray(a, dtype=np.float64)
    return {
        "mean": float(a.mean()),
        "std": float(a.std()),
        "p2p": float(a.max() - a.min()),
    }


def compare_corner(corner_path, b_side_path, t_samples_path):
    """All comparisons for one corner. Returns the record entry."""
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
    tone_bin = tone_bin_of(t_samples_path)
    pb, pt = spectrum(yb), spectrum(yt)
    inb_b, oob_b, edge, noise_bins = inband_and_noise(pb, n, fs, BAND_HZ, tone_bin)
    inb_t, oob_t, _, _ = inband_and_noise(pt, n, fs, BAND_HZ, tone_bin)
    inband_delta_db = 10.0 * np.log10(inb_b / inb_t)
    oob_delta_db = 10.0 * np.log10(oob_b / oob_t)

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

    legs = {
        "inband_power_3db": {
            "pass": bool(abs(inband_delta_db) <= TOLERANCE_SNDR_DB),
            "limit_db": TOLERANCE_SNDR_DB,
            "delta_db": float(inband_delta_db),
            "what": ("total windowed power in band bins 1..%d (0, 20 kHz] of B "
                     "over T, same 1024-clock window, same 4-term "
                     "Blackman-Harris window; the tone is identical by "
                     "construction" % edge),
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
        "sndr_inband_db": {"b": None, "t": None, **INBAND_NOT_COMPUTABLE},
        "inband_power_fs_norm": {"b": inb_b, "t": inb_t,
                                 "delta_db": float(inband_delta_db)},
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


def finalise_entry(entry):
    """Attach the cross_check_status statement to a computed entry."""
    if entry.get("error") is not None:
        entry["cross_check_status"] = (
            f"uncross-checked: no T bitstream comparison was possible ({entry['error']})")
        return entry
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


def no_t_samples_entry(corner_path):
    """A corner with no committed T bitstream is reported uncross-checked,
    never skipped (issue #128 acceptance criteria)."""
    corner = brun.load_corner(corner_path)
    return {
        "corner_id": corner["corner_id"],
        "corner_params_file": rel_path(corner_path),
        "corner_params_sha256": sha256(corner_path),
        "t_samples_file": None,
        "error": (f"no committed T samples at {SAMPLES / (corner['sample_slug'] + '.json')}"),
    }


def git_state():
    def g(*a):
        r = subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return {"git_commit": g("rev-parse", "HEAD"), "git_dirty": bool(g("status", "--porcelain"))}


def build_record(entries):
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
    ap.add_argument("--record", required=True, help="output record (exclusive create)")
    args = ap.parse_args(argv)

    corners = sorted(HERE.glob("corners/*.json")) if args.all else [pathlib.Path(args.corner)]
    if not args.all and not args.corner:
        ap.error("give --corner or --all")

    entries = []
    for cpath in corners:
        corner = brun.load_corner(cpath)
        tpath = SAMPLES / f"{corner['sample_slug']}.json"
        if not tpath.is_file():
            entries.append(no_t_samples_entry(cpath))
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
        entries.append(compare_corner(cpath, bpath, tpath))
    entries = [finalise_entry(e) for e in entries]

    rec = build_record(entries)
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
