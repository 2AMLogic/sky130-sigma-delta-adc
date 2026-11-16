#!/usr/bin/env python3
"""Assemble sim/bmodel/corners/<anchor>.json from the committed T records.

Every model-B parameter is read mechanically from the transistor-level record
that extracted it (DR-001 item 2), with the record path, its sha256 and the
field each value came from written into the corner file. A parameter no T
bench delivers is listed under "no_t_source" with its reason -- it is never
silently defaulted (issue #128).

    python3 -I sim/bmodel/make_corners.py --out-dir sim/bmodel/corners

Read-only over the T records; refuses to overwrite an existing corner file
(corner files are committed evidence, regenerated deliberately, one at a
time). Re-run after #148/#138 or any T record changes, then re-run the
cross-check and the long sweeps.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import model  # noqa: E402

# The seven DR-002 anchor corners (spec/decisions/DR-002-pvt-corners.md), in
# the process/supply/temperature key form every parameter record uses.
ANCHORS = [
    "tt/1.800V/27C",
    "ss/1.620V/125C",
    "ss/1.620V/-40C",
    "ff/1.980V/-40C",
    "ff/1.980V/125C",
    "sf/1.800V/27C",
    "fs/1.800V/27C",
]

# slug form used by sim/modulator-tran/samples/ (no "/" or leading minus).
def sample_slug(corner_id):
    process, supply, temp = corner_id.split("/")
    temp = temp.replace("-", "m")
    return f"{process}-{supply}-{temp}"


RECORDS = {
    "dc_gain": HERE.parents[1] / "sim/ota-gain/record.json",
    "settling_error": HERE.parents[1] / "sim/integrator-settling/record-i92.json",
    "ci_offset": HERE.parents[1] / "sim/integrator-ci/record.json",
    "ktc_noise_var": HERE.parents[1] / "sim/integrator-noise/record-i140.json",
    "comparator_offset": HERE.parents[1] / "sim/comparator-decision/record.json",
    "comparator_hysteresis": HERE.parents[1] / "sim/comparator-decision/record.json",
}


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def src(record_rel, field, value, why=None):
    """One parameter's provenance: which record, which field, what value."""
    entry = {
        "record": record_rel,
        "record_sha256": "sha256:" + sha256(REPO / record_rel),
        "field": field,
        "value": value,
    }
    if why:
        entry["why"] = why
    return entry


def build_corner(corner_id):
    """(params, sources, no_t_source, notes) for one anchor, or None refs."""
    gain = json.loads((REPO / RECORDS["dc_gain"]).read_text())
    settle = json.loads((REPO / RECORDS["settling_error"]).read_text())
    ci = json.loads((REPO / RECORDS["ci_offset"]).read_text())
    noise = json.loads((REPO / RECORDS["ktc_noise_var"]).read_text())
    comp = json.loads((REPO / RECORDS["comparator_offset"]).read_text())

    c = corner_id
    dc_gain = gain["corners"][c]["dc_gain_v_per_v"]
    settling = settle["variants"]["int1"]["corners"][c]["err_phase"]
    ci_off = ci["derived"]["per_corner"][c]["ci_offset_fs"]
    ci_gain_bound = ci["derived"]["per_corner"][c]["ci_gain_error_bound"]
    ktc = noise["corners"][c]["verdict"]["model_b_equiv_ktc_noise_var_fs2_accumulated"]
    ktc_static = noise["corners"][c]["verdict"]["model_b_equiv_ktc_noise_var_fs2_static"]
    cmp_off = comp["derived"]["per_corner"][c]["comparator_offset_FS"]
    cmp_hyst = comp["derived"]["per_corner"][c]["comparator_hysteresis_FS"]

    params = {
        "dc_gain": dc_gain,
        "settling_error": settling,
        "ci_offset": ci_off,
        "ci_gain_error": 0.0,
        "ktc_noise_var": ktc,
        "comparator_offset": cmp_off,
        "comparator_hysteresis": cmp_hyst,
        "jitter_rms_s": 0.0,
        "seed": 1,
    }
    model.validate_params(params)

    sources = {
        "dc_gain": src(
            "sim/ota-gain/record.json", f"corners.{c}.dc_gain_v_per_v", dc_gain,
            "OTA open-loop gain from the 1-1000 Hz AC asymptote; one OTA type "
            "serves both integrators, so one value enters the pole of both "
            "(model.py p = A/(A+1)).",
        ),
        "settling_error": src(
            "sim/integrator-settling/record-i92.json",
            f"variants.int1.corners.{c}.err_phase", settling,
            "residual error at the 97.66 ns sample instant of the phi2 "
            "integrate phase, relative to the settled step, on the #92-switch-"
            "fixed cell; variant int1 is stage-phasing case B (0.1 pF load), "
            "which is the phasing the assembled delaying loop presents "
            "(sim/integrator-settling/README.md). This record is the one whose "
            "integrator_netlist_sha256 matches the tree.",
        ),
        "ci_offset": src(
            "sim/integrator-ci/record.json", f"derived.per_corner.{c}.ci_offset_fs", ci_off,
            "nominal per-clock differential charge-injection residual in FS "
            "units, post-#92 cell (variant post_v0). At most corners it sits "
            "at the bench's own vntol floor (1e-7 V = 8.3e-8 FS). PDK-mismatch "
            "spread is a Monte Carlo quantity (issue #34, out of scope); "
            "record-mc.json puts the switch-attributable sigma at 59-90 uV "
            "per clock (4.9e-05..7.5e-05 FS) and the study value at "
            "sim/integrator-ci/bmodel-ci-injection.json.",
        ),
        "ktc_noise_var": src(
            "sim/integrator-noise/record-i140.json",
            f"corners.{c}.verdict.model_b_equiv_ktc_noise_var_fs2_accumulated", ktc,
            "white per-event variance (FS^2) that reproduces the measured "
            "in-band thermal noise through model B's own 1/OSR link: the "
            "sampling-switch kT/C part plus the integrate-phase amplifier "
            "part referred where it accumulates, across Ci (the #140 "
            "correction; the static referral over-counts and is recorded "
            f"beside it as {ktc_static:.6e}). Flicker is inside the amplifier "
            "share: ngspice .noise gives no thermal/flicker split per corner, "
            "so the model draws it white. Misses the spec 5.3 budget by "
            "-11.3 dB at tt (total_thermal_accumulated_pass false) -- issue "
            "#138, open, recorded not fixed.",
        ),
        "comparator_offset": src(
            "sim/comparator-decision/record.json",
            f"derived.per_corner.{c}.comparator_offset_FS", cmp_off,
            "input-referred offset from the staircase trip points "
            "(v_trip_up + v_trip_dn)/2, resolved to +/- half the staircase "
            "step at each corner (the per-corner quantization block).",
        ),
        "comparator_hysteresis": src(
            "sim/comparator-decision/record.json",
            f"derived.per_corner.{c}.comparator_hysteresis_FS", cmp_hyst,
            "v_trip_up - v_trip_dn: an UPPER BOUND on the hysteresis width "
            "(a comparator with none reads one whole staircase step); the "
            "lower bound is 0. The upper bound is the conservative value for "
            "model B (sim/comparator-decision/README.md, model_b_units).",
        ),
    }

    no_t_source = {
        "ci_gain_error": {
            "value": 0.0,
            "why": "no T source: the signal-dependent part of charge injection "
                   "is below the integrator-ci bench's resolution (the slope "
                   "it fits is accounted for by the drawn capacitor ratio, "
                   "the finite-gain leak and, at slow/cold corners, the "
                   "incomplete input sampling of #106). The per-corner BOUND "
                   f"is {ci_gain_bound:.4f} (derived.per_corner.{c}."
                   "ci_gain_error_bound) and is recorded here, not entered: "
                   "entering a bound as a value would double-count the gain "
                   "deficit the bench attributes elsewhere.",
        },
        "jitter_rms_s": {
            "value": 0.0,
            "why": "no T source: clock jitter is a DR-001 item 2 parameter "
                   "but no bench extracts it -- every T bench drives "
                   "behavioural rail-to-rail clocks with no non-overlap "
                   "generator, and design/clkgen has no jitter extraction. "
                   "Entered 0 (the ideal value), not a measurement.",
        },
    }

    notes = [
        "Tree state these values were read from is the corner file's own "
        "tree_commit; #148 (integrator swing 2.4-2.5x over spec 5.4 at every "
        "anchor) and #138 (integrator-1 thermal noise 11-17 dB over the 5.3 "
        "budget) were open and are recorded, not absorbed: re-run "
        "make_corners.py, the cross-check and the sweeps if either lands.",
    ]
    if corner_id == "ss/1.620V/-40C":
        notes.append(
            "#106 is anchored here: the input sampling switch Sin is ~46% "
            "incomplete at this corner. Model B has no parameter for an "
            "input-path transfer deficit, so the cross-check at this corner "
            "carries whatever the mismatch shows; ci_gain_error's bound at "
            "this corner (-0.54) is that bench's reading of #106, not charge "
            "injection."
        )
    return params, sources, no_t_source, notes


def git_commit():
    r = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", default=str(HERE / "corners"))
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out_dir)
    commit = git_commit()
    written = []
    for corner_id in ANCHORS:
        params, sources, no_t_source, notes = build_corner(corner_id)
        doc = {
            "schema": "sky130-sigma-delta-adc model-B corner parameters v1",
            "corner_id": corner_id,
            "dr002_set": "anchor",
            "sample_slug": sample_slug(corner_id),
            "t_sample_file": f"sim/modulator-tran/samples/{sample_slug(corner_id)}.json",
            "tree_commit": commit,
            "params": params,
            "params_sha256": hashlib.sha256(
                json.dumps(params, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "sources": sources,
            "no_t_source": no_t_source,
            "notes": notes,
        }
        path = out / f"{sample_slug(corner_id)}.json"
        if path.exists():
            print(f"refusing to overwrite {path}; delete it first if a "
                  "regeneration is intended", file=sys.stderr)
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2) + "\n")
        written.append(str(path))
    print("\n".join(f"wrote {w}" for w in written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
