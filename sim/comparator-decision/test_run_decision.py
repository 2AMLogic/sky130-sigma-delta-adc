"""Tests for the comparator-decision runner's derivations and admission gates.

Run: python3 -I -m unittest discover -s sim/comparator-decision -p 'test_*.py'

No fleet, no ngspice, no klt: `run_klt` and `pdk_stamp` are patched and the
runner's HERE / .partials / .artifacts are redirected into a temporary
directory, so the committed record.json is never read or written. `shas()` is
NOT patched -- the real request and deck files are copied into the temporary
HERE, so the .partials hash gate is exercised as written.

What is pinned here:

- the model-B conversions (volts at the integrator-2 output -> x2 FS units)
  and the offset / hysteresis inversion, including its sign;
- that the decision-time limit is the *measured* phi1 width, not the bare
  half-period;
- that a comparator which never resolves inside the window is reported as a
  graded failure carrying a number, not as a missing measurement;
- that a partial grid, or a grid whose admission measurement is absent,
  writes no record;
- that the staircase the bench actually generates brackets the trip point,
  steps by the designed amount, and never asks for a decision on an exactly
  zero differential (which would be a metastable bench artefact).
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent


def load_runner():
    """Load run_decision.py by path: 'comparator-decision' is not importable."""
    spec = importlib.util.spec_from_file_location(
        "run_decision_under_test", HERE / "run_decision.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUNNER = load_runner()
MR = RUNNER.MR
SC = sys.modules["settling_common"]
GRID_POINTS = SC.GRID_POINTS

PROCESS = ("tt", "ss", "ff", "sf", "fs")
VDDA = ("1.620", "1.800", "1.980")
TEMP = ("-40", "27", "125")
CORNER_IDS = tuple(f"{p}/{v}V/{t}C" for p in PROCESS for v in VDDA for t in TEMP)


# --------------------------------------------------------------- derivations

class DerivationCase(unittest.TestCase):

    def test_parse_corner_reads_klt_corner_ids(self):
        self.assertEqual(RUNNER.parse_corner("ss/1.620V/-40C"),
                         {"process": "ss", "vdda_V": 1.62, "temperature_C": -40.0})
        self.assertEqual(RUNNER.parse_corner("ff/1.980V/125C"),
                         {"process": "ff", "vdda_V": 1.98, "temperature_C": 125.0})

    def test_parse_corner_rejects_anything_else(self):
        for bad in ("tt_1p800_27", "tt/1.8/27", "xx/1.800V/27C", "tt/1.800V"):
            with self.assertRaises(ValueError):
                RUNNER.parse_corner(bad)

    def test_fs_uses_1v2_per_x2_unit(self):
        # One model-B x2 unit is 1.2 V of differential output at integrator 2.
        self.assertEqual(MR.FS_VOLTS, 1.2)
        self.assertAlmostEqual(RUNNER.fs(1.2), 1.0)
        self.assertAlmostEqual(RUNNER.fs(-600e-6), -5e-4)
        self.assertIsNone(RUNNER.fs(None))

    def test_offset_hysteresis_inverts_the_model_b_thresholds(self):
        # Model B trips to +1 at x2 = +h/2 - off and back to -1 at -h/2 - off.
        off, h = 0.3e-3, 0.8e-3
        up, dn = h / 2 - off, -h / 2 - off
        got_off, got_h = RUNNER.offset_hysteresis(up, dn)
        self.assertAlmostEqual(got_off, off, places=12)
        self.assertAlmostEqual(got_h, h, places=12)

    def test_offset_hysteresis_is_zero_for_a_symmetric_comparator(self):
        self.assertEqual(RUNNER.offset_hysteresis(0.0, 0.0), (0.0, 0.0))

    def test_negative_hysteresis_is_reported_not_clamped(self):
        # A falling trip ABOVE the rising one cannot come from hysteresis; the
        # record has to show it rather than hide it behind a max(0, .).
        off, h = RUNNER.offset_hysteresis(-1e-4, +2e-4)
        self.assertLess(h, 0.0)
        self.assertAlmostEqual(off, -0.5e-4)

    def test_offset_hysteresis_passes_missing_values_through(self):
        self.assertEqual(RUNNER.offset_hysteresis(None, 1e-3), (None, None))

    def test_decision_limit_is_the_measured_phi1_width(self):
        # Not the bare 97.65625 ns half-period: clkgen spends part of each
        # half on the non-overlap gaps, so the limit is what phi1 delivered.
        self.assertEqual(RUNNER.decision_limit(97.82e-9), 97.82e-9)
        self.assertNotEqual(RUNNER.decision_limit(97.82e-9), MR.T_HALF)

    def test_worst_picks_the_largest_and_skips_valueless_corners(self):
        c = {"a": {"x": 1.0}, "b": {"x": 3.0}, "c": {"x": None}, "d": {"x": -9.0}}
        self.assertEqual(RUNNER.worst(c, "x"), ("b", 3.0))
        self.assertEqual(RUNNER.worst(c, "x", sign=-1), ("d", -9.0))
        self.assertEqual(RUNNER.worst_abs(c, "x"), ("d", -9.0))
        self.assertEqual(RUNNER.worst({"a": {"x": None}}, "x"), (None, None))


# ----------------------------------------------------------- bench geometry

class StaircaseCase(unittest.TestCase):
    """The trip variant's designed input, checked as arithmetic."""

    def setUp(self):
        self.card, self.sched = MR.trip_input_pwl()
        # what the comparator is shown at the phi1 rise of clock n is o2d[n-1]
        self.seen = {}
        prev = 0.0
        for n, _u, _o1, o2 in self.sched:
            self.seen[n] = prev
            prev = o2

    def test_no_decision_is_taken_on_an_exactly_zero_differential(self):
        graded = list(range(MR.TRIP_UP_FIRST, MR.TRIP_UP_LAST + 1)) + \
            list(range(MR.TRIP_DN_FIRST, MR.TRIP_DN_LAST + 1))
        for n in graded:
            self.assertNotEqual(self.seen[n], 0.0, f"clock {n} decides on 0 V")
            self.assertGreaterEqual(abs(self.seen[n]), MR.STEP_V / 2 - 1e-15)

    def test_the_up_sweep_rises_by_one_step_per_clock(self):
        ks = range(MR.TRIP_UP_FIRST, MR.TRIP_UP_LAST + 1)
        for a, b in zip(ks, list(ks)[1:]):
            self.assertAlmostEqual(self.seen[b] - self.seen[a], MR.STEP_V, places=12)

    def test_the_down_sweep_falls_by_one_step_per_clock(self):
        ks = range(MR.TRIP_DN_FIRST, MR.TRIP_DN_LAST + 1)
        for a, b in zip(ks, list(ks)[1:]):
            self.assertAlmostEqual(self.seen[b] - self.seen[a], -MR.STEP_V, places=12)

    def test_both_sweeps_cover_the_graded_span_and_straddle_zero(self):
        up = [self.seen[n] for n in range(MR.TRIP_UP_FIRST, MR.TRIP_UP_LAST + 1)]
        dn = [self.seen[n] for n in range(MR.TRIP_DN_FIRST, MR.TRIP_DN_LAST + 1)]
        self.assertGreaterEqual(up[-1] - up[0], MR.RAMP_SPAN_V)
        self.assertLessEqual(dn[-1] - dn[0], -MR.RAMP_SPAN_V)
        for seq in (up, dn):
            self.assertLess(min(seq), 0.0)
            self.assertGreater(max(seq), 0.0)

    def test_the_input_only_moves_while_the_input_switch_is_open(self):
        # Every PWL breakpoint has to sit inside a phi2, i.e. between the end
        # of one clock's phi1 and the start of the next clock's: the cell
        # samples its input during phi1, so a move inside phi1 would be
        # sampled half-way.
        for tok in self.card[len("pwl("):-1].split()[::2]:
            t = float(tok)
            if t in (0.0, MR.T_END["trip"]):
                continue
            frac = ((t - MR.T0) % MR.TCLK) / MR.TCLK
            self.assertGreater(frac, 0.55, f"breakpoint at {t} is inside phi1")

    def test_every_measurement_name_is_unique_and_carried_into_the_record(self):
        for v in RUNNER.VARIANTS:
            names = [m["name"] for m in MR.VARIANTS[v]["measurements"]()]
            self.assertEqual(len(names), len(set(names)), f"{v}: duplicate names")
            self.assertEqual(RUNNER.keys_for(v), tuple(names))

    def test_the_graded_rows_are_the_ones_the_record_claims(self):
        loop = {m["name"]: m.get("limits") for m in MR.VARIANTS["loop"]["measurements"]()}
        trip = {m["name"]: m.get("limits") for m in MR.VARIANTS["trip"]["measurements"]()}
        self.assertEqual(loop["tdec_frac"], {"max": 1.0})
        self.assertEqual(loop["n_flip"], {"min": 2})
        self.assertEqual(trip["flip_up"], {"min": 1})
        self.assertEqual(trip["flip_dn"], {"min": 1})
        # kickback is reported, never graded -- no limit is invented for it
        for tag, _sig in MR.KICK_NODES:
            for k in MR.LOOP_KICK_CLKS:
                self.assertIsNone(loop[f"kb_{tag}_{k}"])


# ------------------------------------------------------------------ fixtures

def loop_corner(tdec_frac=0.05, n_flip=6, phi1=97.8e-9, status="pass"):
    c = {"status": status, "diagnostics": [],
         "phi1_width": phi1, "n_flip": n_flip,
         "tdec_frac": tdec_frac, "tdec_worst": tdec_frac * phi1,
         "tcmp_worst": 0.9e-9, "tq_worst": 1.5e-9}
    for k in range(MR.LOOP_FIRST, MR.LOOP_LAST + 1):
        c.update({f"tphi1_{k}": 1e-9, f"vod_{k}": 0.2 if k % 2 else -0.2,
                  f"sgn_{k}": 1 if k % 2 else -1, f"ddpre_{k}": -1.8 if k % 2 else 1.8,
                  f"flip_{k}": 1, f"tdec_{k}": tdec_frac * phi1 if k == 9 else 1e-9,
                  f"tcmp_{k}": 0.8e-9, f"tq_{k}": 1.2e-9})
    for k in MR.LOOP_KICK_CLKS:
        for i, (tag, _s) in enumerate(MR.KICK_NODES):
            c[f"kbref_{tag}_{k}"] = 0.9
            c[f"kb_{tag}_{k}"] = 1e-3 * (i + 1) * (1 + k / 10.0)
    return c


def trip_corner(up=4e-4, dn=-6e-4, step=5e-4, status="pass"):
    c = {"status": status, "diagnostics": [],
         "flip_up": 1, "flip_dn": 1, "tflip_up": 1e-6, "tflip_dn": 2e-6,
         "k_up": 8, "k_dn": 18, "t_up": 1e-6, "t_dn": 2e-6,
         "v_trip_up": up, "v_trip_dn": dn,
         "v_prev_up": None if up is None else up - step,
         "v_prev_dn": None if dn is None else dn + step,
         "step_up": step, "step_dn": -step,
         "tphi1_up": 1e-9, "tphi1_dn": 1e-9, "tdec_up": 8e-9, "tdec_dn": 7e-9,
         "span_up": 4e-3, "span_dn": -4.5e-3,
         "vos_V": None if up is None else -0.5 * (up + dn),
         "hyst_V": None if up is None else up - dn,
         "phi1_width": 97.8e-9}
    return c


def grid(make, n=GRID_POINTS, **kw):
    return {cid: make(**kw) for cid in CORNER_IDS[:n]}


def report(status="pass", job="klt-sim-0001"):
    return {"status": status,
            "environment": {"engine_version": "ngspice-47", "engine_host": "fleet-node-1",
                            "remote": {"job_id": job}}}


# ------------------------------------------------------------- record gating

class RunnerCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-run-decision-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.here = self.tmp / "bench"
        self.here.mkdir()
        for v in RUNNER.VARIANTS:                       # real inputs: real shas()
            for name in (f"request_{v}.json", f"comparator_decision_{v}.cir"):
                (self.here / name).write_bytes((HERE / name).read_bytes())
        for p, val in (("HERE", self.here), ("PARTIALS", self.here / ".partials"),
                       ("ARTIFACTS", self.here / ".artifacts")):
            self.enterContext(mock.patch.object(RUNNER, p, val))
        self.enterContext(mock.patch.object(
            RUNNER, "pdk_stamp",
            lambda variant, root: (pathlib.Path("/pdk"),
                                   json.loads((RUNNER.REPO / "sim/pdk.json").read_text())
                                   ["sources_stamp"])))

    def run_main(self, corners, argv=(), status="pass"):
        """main() with run_klt returning `corners[variant]`; returns (rc, out)."""
        def fake(request_path, probe, tmpdir, tag, probe_path, **kw):
            if corners.get(tag) is None:
                return None
            return report(status), corners[tag]
        buf = io.StringIO()
        with mock.patch.object(RUNNER, "run_klt", fake), \
                mock.patch.object(sys, "argv", ["run_decision.py", *argv]), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = RUNNER.main()
        return rc, buf.getvalue()

    def test_a_full_grid_writes_a_record_with_the_derived_quantities(self):
        rc, out = self.run_main({"loop": grid(loop_corner), "trip": grid(trip_corner)},
                                ["--record"])
        self.assertEqual(rc, 0, out)
        rec = json.loads((self.here / "record.json").read_text())
        self.assertIn("simulated", rec["result_kind"])
        self.assertNotIn("measured", rec["result_kind"].split("Not measured")[0])
        self.assertEqual(rec["pdk_pin"]["open_pdks_revision"],
                         json.loads((RUNNER.REPO / "sim/pdk.json").read_text())
                         ["open_pdks_revision"])
        self.assertEqual(set(rec["netlist_sha256"]), {
            "design/modulator/modulator.spice",
            "design/modulator/comparator/comparator.spice",
            "design/modulator/comparator/comparator_core.spice",
            "design/ota/ota_fd.spice"})
        self.assertEqual(rec["variants"]["loop"]["remote"], {"job_id": "klt-sim-0001"})
        d = rec["derived"]
        self.assertAlmostEqual(d["comparator_offset"]["V"], 1e-4)
        self.assertAlmostEqual(d["comparator_offset"]["FS"], 1e-4 / 1.2)
        self.assertAlmostEqual(d["comparator_hysteresis"]["V"], 1e-3)
        self.assertAlmostEqual(d["comparator_hysteresis"]["FS"], 1e-3 / 1.2)
        self.assertEqual(d["model_b_units"]["resolution_V"], 5e-4)
        self.assertEqual(len(d["per_corner"]), GRID_POINTS)
        self.assertEqual(d["decision_time"]["limit_s"], 97.8e-9)
        self.assertEqual(d["decision_time"]["worst_clock"], 9)
        self.assertEqual(d["kickback"]["corner"], d["decision_time"]["corner"])
        self.assertEqual(set(d["kickback"]["nodes"]),
                         {t for t, _ in MR.KICK_NODES})

    def test_the_binding_decision_corner_is_the_worst_fraction(self):
        loop = grid(loop_corner)
        loop["ss/1.620V/-40C"] = loop_corner(tdec_frac=0.42)
        rc, out = self.run_main({"loop": loop, "trip": grid(trip_corner)}, ["--record"])
        self.assertEqual(rc, 0, out)
        d = json.loads((self.here / "record.json").read_text())["derived"]
        self.assertEqual(d["decision_time"]["corner"], "ss/1.620V/-40C")
        self.assertEqual(d["decision_time"]["process"], "ss")
        self.assertEqual(d["decision_time"]["temperature_C"], -40.0)
        self.assertEqual(d["decision_time"]["vdda_V"], 1.62)

    def test_a_comparator_that_never_resolves_is_a_failure_carrying_a_number(self):
        # The deck saturates tdec at the search-window length rather than
        # leaving it unmeasured, so this corner is `fail` WITH a value -- not
        # an absent measurement that the admission gate would reject as
        # "nothing was simulated there".
        loop = grid(loop_corner)
        stuck = loop_corner(tdec_frac=MR.W_DEC / 97.8e-9, status="fail")
        loop["ss/1.620V/-40C"] = stuck
        rc, out = self.run_main({"loop": loop, "trip": grid(trip_corner)},
                                ["--record"], status="fail")
        self.assertEqual(rc, 1, out)                      # a failing record
        rec = json.loads((self.here / "record.json").read_text())
        self.assertFalse(rec["pass"])
        self.assertEqual(rec["derived"]["decision_time"]["corner"], "ss/1.620V/-40C")
        self.assertGreater(rec["derived"]["decision_time"]["fraction_of_limit"], 1.0)
        self.assertIsNotNone(rec["derived"]["decision_time"]["t_decision_to_dp_dn_s"])

    def test_a_partial_grid_writes_no_record(self):
        rc, out = self.run_main({"loop": grid(loop_corner, n=44),
                                 "trip": grid(trip_corner)}, ["--record"])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSE", out)
        self.assertFalse((self.here / "record.json").exists())

    def test_an_absent_admission_measurement_writes_no_record(self):
        trip = grid(trip_corner)
        trip["tt/1.800V/27C"]["v_trip_up"] = None
        rc, out = self.run_main({"loop": grid(loop_corner), "trip": trip}, ["--record"])
        self.assertEqual(rc, 1)
        self.assertIn("REFUSE", out)
        self.assertIn("v_trip_up", out)
        self.assertFalse((self.here / "record.json").exists())

    def test_a_failed_submit_is_never_served_from_partials(self):
        # Pin the sibling benches' rule (#94): a variant asked for in THIS
        # invocation whose submit fails is a refusal, not a reused partial.
        rc, _ = self.run_main({"loop": grid(loop_corner), "trip": grid(trip_corner)})
        self.assertEqual(rc, 0)
        self.assertTrue((self.here / ".partials/loop.json").exists())
        rc, out = self.run_main({"loop": None, "trip": grid(trip_corner)},
                                ["--variant", "loop", "--record"])
        self.assertEqual(rc, 1)
        self.assertIn("no result for loop", out)
        self.assertFalse((self.here / "record.json").exists())

    def test_a_variant_not_asked_for_is_reused_from_partials(self):
        rc, _ = self.run_main({"loop": grid(loop_corner), "trip": grid(trip_corner)})
        self.assertEqual(rc, 0)
        rc, out = self.run_main({"loop": None, "trip": grid(trip_corner)},
                                ["--variant", "trip", "--record"])
        self.assertEqual(rc, 0, out)
        self.assertIn("reusing .partials/loop.json", out)
        self.assertTrue((self.here / "record.json").exists())

    def test_records_are_append_only(self):
        rc, _ = self.run_main({"loop": grid(loop_corner), "trip": grid(trip_corner)},
                              ["--record"])
        self.assertEqual(rc, 0)
        rc, out = self.run_main({"loop": grid(loop_corner), "trip": grid(trip_corner)},
                                ["--record"])
        self.assertEqual(rc, 2)
        self.assertIn("append-only", out)

    def test_a_pdk_other_than_the_pin_is_refused_before_anything_runs(self):
        with mock.patch.object(RUNNER, "pdk_stamp",
                               lambda variant, root: (pathlib.Path("/pdk"), "open_pdks deadbeef")):
            rc, out = self.run_main({"loop": grid(loop_corner), "trip": grid(trip_corner)},
                                    ["--record"])
        self.assertEqual(rc, 2)
        self.assertIn("REFUSE", out)


if __name__ == "__main__":
    unittest.main()
