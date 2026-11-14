"""Tests for the input-sampling runner's admission gates and derivations. Run:
python3 -I -m unittest discover -s sim/integrator-ci -p 'test_*.py'

No fleet, no ngspice, no klt: `run_klt` and `pdk_stamp` are patched and the
runner's HERE / .partials are redirected into a temporary directory, so the
committed record-i106.json is never read or written. `shas()` is NOT patched --
the real request and deck files are copied into the temporary HERE, so the
.partials hash gate is exercised as written. Same harness shape as
test_run_ci.py.

What is pinned here (issue #106):

- the issue #102 requests, decks and their committed `record.json` provenance
  are NOT disturbed by adding this campaign -- the sampling measurements live in
  separate request files over the same decks;
- a grid that did not actually measure the sampled differential, or measured it
  in an empty window, is refused rather than recorded;
- `error_rel` really is `1 - sampled/ideal` against the applied input, the
  binding corner is the worst of both amplitudes, and the reference line is
  carried as a labelled scale and never as a pass/fail limit.
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent


def load_runner():
    """Load run_sampling.py by path: 'integrator-ci' is not importable."""
    spec = importlib.util.spec_from_file_location(
        "run_sampling_under_test", HERE / "run_sampling.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUNNER = load_runner()
MK = sys.modules["make_request"]
PIN = json.loads((RUNNER.REPO / "sim/pdk.json").read_text())
SENTINEL = RUNNER.SENTINEL
AMPS = RUNNER.VARIANTS

PROCESS = ("tt", "ss", "ff", "sf", "fs")
VDDA = ("1p620", "1p800", "1p980")
TEMP = ("m40", "27", "125")
CORNER_IDS = tuple(f"{p}_{v}_{t}" for p in PROCESS for v in VDDA for t in TEMP)


def corner(sampled, vin_diff=0.2, **over):
    """One klt corner entry: every i106 key present, windows occupied."""
    half = vin_diff / 2.0
    c = {k: 1.0 for k in MK.I106_KEYS}
    c.update({k: 0.0006 for k in MK.I106_WINDOW_KEYS})
    for k in MK.SAMP_CYCLES:
        c[f"samp_s{k}"] = sampled
        c[f"samp_bpi_s{k}"] = sampled
        c[f"bpip_s{k}"] = 0.9 + half
        c[f"bpin_s{k}"] = 0.9 - half
        c[f"tpip_s{k}"] = 0.9
        c[f"tpin_s{k}"] = 0.9
    c[f"samp_f{MK.SAMP_REPORT}"] = sampled
    c.update({"status": "pass", "diagnostics": []})
    c.update(over)
    return c


def grid(sampled=0.2, vin_diff=0.2, n=45, ids=CORNER_IDS):
    return {cid: corner(sampled, vin_diff) for cid in ids[:n]}


def report(status="pass", job="job-0001"):
    return {"status": status,
            "environment": {"engine_version": "ngspice-47",
                            "engine_host": "fleet-node-1",
                            "remote": {"job_id": job}}}


def ideal(v):
    return MK.i106_variant(v)["vin_diff"]


class RunnerCase(unittest.TestCase):
    """Runs main() against a temporary HERE with run_klt / pdk_stamp patched."""

    maxDiff = None

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-run-sampling-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.here = self.tmp / "bench"
        self.here.mkdir()
        for v in AMPS:                       # real inputs: real shas()
            for name in (f"request_i106_{v}.json", MK.deck_name(v)):
                (self.here / name).write_bytes((HERE / name).read_bytes())
        self.partials = self.here / ".partials"
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.calls, self.kwargs = [], []

    def shas(self, v):
        with mock.patch.object(RUNNER, "HERE", self.here), \
             mock.patch.object(MK, "HERE", self.here):
            return RUNNER.shas(v)

    def write_partial(self, v, corners=None, passed=True, stale=False):
        self.partials.mkdir(exist_ok=True)
        d = {"summary": {"corner_count": 45, "pass": 45, "fail": 0},
             "corners": grid(ideal(v), ideal(v)) if corners is None else corners,
             "pass": passed, "ngspice": "ngspice-47", "engine_host": "fleet-node-0",
             "remote": {"job_id": f"job-earlier-{v}"}, **self.shas(v)}
        if stale:
            d["deck_sha256"] = "0" * 64
        (self.partials / f"i106-{v}.json").write_text(json.dumps(d, indent=2) + "\n")
        return d

    def run_main(self, argv, submits):
        """main() with argv; `submits` maps run_klt tag -> its return value."""
        def fake_run_klt(request_path, probe, tmpdir, tag, probe_path, **kw):
            self.calls.append(tag)
            self.kwargs.append(kw)
            return submits.get(tag)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(RUNNER, "HERE", self.here))
            st.enter_context(mock.patch.object(MK, "HERE", self.here))
            st.enter_context(mock.patch.object(RUNNER, "PARTIALS", self.partials))
            st.enter_context(mock.patch.object(RUNNER, "ARTIFACTS", self.here / ".artifacts"))
            st.enter_context(mock.patch.object(
                RUNNER, "pdk_stamp",
                lambda variant, root: (pathlib.Path("/fake/pdk"), PIN["sources_stamp"])))
            st.enter_context(mock.patch.object(RUNNER, "run_klt", fake_run_klt))
            st.enter_context(mock.patch.object(
                RUNNER.tempfile, "mkdtemp", lambda *a, **k: str(self.work)))
            st.enter_context(mock.patch.object(
                RUNNER.subprocess, "run",
                lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="klt 0.0.0-test\n",
                                                            stderr="")))
            st.enter_context(mock.patch.object(sys, "argv", ["run_sampling.py", *argv]))
            st.enter_context(contextlib.redirect_stdout(out))
            st.enter_context(contextlib.redirect_stderr(err))
            rc = RUNNER.main()
        return rc, out.getvalue(), err.getvalue()

    def all_submits(self, sampled=None):
        """A passing submit for every amplitude; `sampled` maps amplitude -> V."""
        sampled = sampled or {}
        return {f"i106-{v}": (report(), grid(sampled.get(v, ideal(v)), ideal(v)))
                for v in AMPS}

    def assertNoRecord(self, name="record-i106.json"):
        self.assertFalse((self.here / name).exists(),
                         f"{name} was written from a run that should have refused")

    def record(self, name="record-i106.json"):
        return json.loads((self.here / name).read_text())


class Issue102IsNotDisturbed(unittest.TestCase):
    """The #102 campaign's provenance must survive this issue untouched."""

    def test_the_sampling_measurements_are_in_separate_request_files(self):
        for v in AMPS:
            self.assertTrue((HERE / f"request_i106_{v}.json").exists())
        for v in MK.VARIANTS:
            r = json.loads((HERE / f"request_{v}.json").read_text())
            names = {m["name"] for m in r["measurements"]}
            self.assertEqual(names, set(MK.KEYS),
                             f"request_{v}.json gained or lost a measurement")

    def test_the_small_amplitude_reuses_the_issue_102_deck_byte_for_byte(self):
        """So record.json's deck_sha256 for post_v0p2 still resolves."""
        self.assertIn("post_v0p2", AMPS)
        self.assertEqual(json.loads((HERE / "request_i106_post_v0p2.json").read_text())
                         ["netlist"], MK.deck_name("post_v0p2"))

    def test_the_committed_record_shas_still_match_the_tree(self):
        rec = json.loads((HERE / "record.json").read_text())
        for v, got in rec["variants"].items():
            self.assertEqual(
                got["request_sha256"],
                RUNNER.sha256(HERE / f"request_{v}.json"),
                f"record.json's request_sha256 for {v} no longer matches the tree")
            self.assertEqual(
                got["deck_sha256"], RUNNER.sha256(HERE / MK.deck_name(v)),
                f"record.json's deck_sha256 for {v} no longer matches the tree")

    def test_the_new_amplitude_is_not_in_the_issue_102_variant_set(self):
        """run_ci.py iterates mk.VARIANTS; post_v0p6 must not join its grids."""
        self.assertNotIn("post_v0p6", MK.VARIANTS)
        self.assertIn("post_v0p6", MK.I106_EXTRA_VARIANTS)


class Measurements(unittest.TestCase):
    def test_no_sampling_measurement_carries_a_limit(self):
        """The reference line is a scale, never a fleet pass/fail verdict."""
        for m in MK.SAMPLING_MEASUREMENTS:
            self.assertNotIn("limits", m, f"{m['name']} carries a limit")
        for v in AMPS:
            r = json.loads((HERE / f"request_i106_{v}.json").read_text())
            self.assertFalse(any("limits" in m for m in r["measurements"]),
                             f"request_i106_{v}.json carries a limit")

    def test_the_sample_window_ends_before_the_phi1e_fall(self):
        """The sampled charge is frozen at 90.5 ns; the window must precede it."""
        self.assertLess(MK.W_SAMP[1], 90.5e-9)
        self.assertGreater(MK.W_SAMP[0], 0.2e-9)

    def test_the_frozen_window_sits_in_the_phi1_to_phi2_non_overlap_gap(self):
        self.assertGreater(MK.W_FROZEN[0], 92.7e-9)    # after phi1 has opened
        self.assertLess(MK.W_FROZEN[1], 97.46e-9)      # before phi2 closes

    def test_cycle_zero_is_not_read(self):
        """Its bottom plates were never phi2-reset: the bench reset held to 40 ns."""
        self.assertNotIn(0, MK.SAMP_CYCLES)
        self.assertIn(MK.SAMP_REPORT, MK.SAMP_CYCLES)

    def test_both_amplitudes_are_recorded_and_differ(self):
        """Input-level dependence is only visible with two amplitudes."""
        self.assertEqual(len(AMPS), 2)
        self.assertNotEqual(*[ideal(v) for v in AMPS])

    def test_the_amplitudes_are_the_filing_point_and_the_full_spec_range(self):
        self.assertEqual(ideal("post_v0p2"), 0.2)      # vinp/vinn = 1.0/0.8 V
        self.assertEqual(ideal("post_v0p6"), 0.6)      # vinp/vinn = 1.2/0.6 V

    def test_the_sampled_differential_is_taken_across_the_capacitor(self):
        expr = {m["name"]: m["expr"] for m in MK.SAMPLING_MEASUREMENTS}
        self.assertEqual(expr[SENTINEL],
                         f"(bpip_s{MK.SAMP_REPORT} - tpip_s{MK.SAMP_REPORT}) - "
                         f"(bpin_s{MK.SAMP_REPORT} - tpin_s{MK.SAMP_REPORT})")

    def test_every_window_mean_has_its_own_occupancy_divisor(self):
        names = {m["name"] for m in MK.SAMPLING_MEASUREMENTS}
        for m in MK.SAMPLING_MEASUREMENTS:
            if m["expr"].startswith("mean(v("):
                self.assertIn(m["expr"].rsplit("/", 1)[1], names)


class AdmissionGates(RunnerCase):
    def test_a_complete_grid_is_recorded(self):
        rc, out, err = self.run_main(["--record"], self.all_submits())
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(self.calls), [f"i106-{v}" for v in sorted(AMPS)])
        self.assertEqual(set(self.record()["amplitudes"]), set(AMPS))

    def test_a_short_grid_is_refused(self):
        subs = self.all_submits()
        subs[f"i106-{AMPS[0]}"] = (report(), grid(ideal(AMPS[0]), ideal(AMPS[0]), n=44))
        rc, out, err = self.run_main(["--record"], subs)
        self.assertEqual(rc, 1)
        self.assertIn("not all 45 grid points returned", err)
        self.assertNoRecord()

    def test_a_grid_with_no_sampled_differential_is_refused(self):
        """A dead fleet job returns one entry per point with no measurement."""
        dead = {cid: {**corner(0.2), SENTINEL: None,
                      "status": "fail", "diagnostics": ["batch_job_failed"]}
                for cid in CORNER_IDS}
        subs = self.all_submits()
        subs[f"i106-{AMPS[0]}"] = (report("fail"), dead)
        rc, out, err = self.run_main(["--record"], subs)
        self.assertEqual(rc, 1)
        self.assertIn(f"returned no {SENTINEL}", err)
        self.assertIn("batch_job_failed", err)
        self.assertNoRecord()

    def test_one_measurementless_point_is_enough_to_refuse(self):
        subs = self.all_submits()
        g = grid(ideal(AMPS[0]), ideal(AMPS[0]))
        g[CORNER_IDS[7]][SENTINEL] = None
        subs[f"i106-{AMPS[0]}"] = (report(), g)
        rc, out, err = self.run_main(["--record"], subs)
        self.assertEqual(rc, 1)
        self.assertNoRecord()

    def test_an_empty_measurement_window_is_refused(self):
        """w_s4 = 0 makes every plate reading a 0/0, not a measurement."""
        subs = self.all_submits()
        g = grid(ideal(AMPS[0]), ideal(AMPS[0]))
        g[CORNER_IDS[3]][f"w_s{MK.SAMP_REPORT}"] = 0.0
        subs[f"i106-{AMPS[0]}"] = (report(), g)
        rc, out, err = self.run_main(["--record"], subs)
        self.assertEqual(rc, 1)
        self.assertIn("empty or impossible measurement window", err)
        self.assertIn(CORNER_IDS[3], err)
        self.assertNoRecord()

    def test_a_missing_window_key_is_refused_too(self):
        subs = self.all_submits()
        g = grid(ideal(AMPS[0]), ideal(AMPS[0]))
        g[CORNER_IDS[3]][f"w_s{MK.SAMP_REPORT}"] = None
        subs[f"i106-{AMPS[0]}"] = (report(), g)
        rc, _, err = self.run_main(["--record"], subs)
        self.assertEqual(rc, 1)
        self.assertNoRecord()

    def test_a_failed_submit_is_not_served_from_a_matching_partial(self):
        """Issue #94's rule: a failed submit must never become a result."""
        self.write_partial(AMPS[0])
        subs = self.all_submits()
        subs.pop(f"i106-{AMPS[0]}")          # run_klt returns None
        rc, out, err = self.run_main(["--record"], subs)
        self.assertEqual(rc, 1)
        self.assertIn("no result for", err)
        self.assertNoRecord()

    def test_a_partial_is_reused_for_an_amplitude_not_requested_this_run(self):
        self.write_partial(AMPS[0])
        subs = {f"i106-{AMPS[1]}": (report(), grid(ideal(AMPS[1]), ideal(AMPS[1])))}
        rc, out, err = self.run_main(["--variant", AMPS[1], "--record"], subs)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.calls, [f"i106-{AMPS[1]}"])
        self.assertIn("reusing", out)

    def test_a_stale_partial_is_refused_rather_than_used(self):
        self.write_partial(AMPS[0], stale=True)
        subs = {f"i106-{AMPS[1]}": (report(), grid(ideal(AMPS[1]), ideal(AMPS[1])))}
        rc, out, err = self.run_main(["--variant", AMPS[1], "--record"], subs)
        self.assertEqual(rc, 1)
        self.assertIn("stale", err)
        self.assertNoRecord()

    def test_from_partials_submits_nothing(self):
        for v in AMPS:
            self.write_partial(v)
        rc, out, err = self.run_main(["--from-partials", "--record"], {})
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.calls, [])
        self.assertIn("nothing was submitted", self.record()["assembled_from"])

    def test_from_partials_with_a_missing_partial_refuses(self):
        self.write_partial(AMPS[0])
        rc, out, err = self.run_main(["--from-partials", "--record"], {})
        self.assertEqual(rc, 1)
        self.assertIn("no cached partial for", err)
        self.assertNoRecord()

    def test_an_existing_record_is_never_overwritten(self):
        (self.here / "record-i106.json").write_text("{}\n")
        rc, out, err = self.run_main(["--record"], self.all_submits())
        self.assertEqual(rc, 2)
        self.assertIn("append-only", err)
        self.assertEqual((self.here / "record-i106.json").read_text(), "{}\n")

    def test_a_complete_grid_without_the_record_flag_writes_nothing(self):
        rc, out, err = self.run_main([], self.all_submits())
        self.assertEqual(rc, 0, err)
        self.assertIn("re-run with --record", out)
        self.assertNoRecord()

    def test_every_submit_waits_for_fleet_capacity(self):
        """Host rule: a batch submit waits with backoff, it does not fail."""
        self.run_main(["--record"], self.all_submits())
        for kw in self.kwargs:
            self.assertEqual(kw["capacity_wait_s"], RUNNER.CAPACITY_WAIT_S)

    def test_the_capacity_wait_is_raisable(self):
        self.run_main(["--capacity-wait", "1800", "--record"], self.all_submits())
        for kw in self.kwargs:
            self.assertEqual(kw["capacity_wait_s"], 1800)

    def test_hosts_is_passed_through_without_changing_the_request(self):
        before = {v: self.shas(v) for v in AMPS}
        self.run_main(["--hosts", "3", "--record"], self.all_submits())
        for kw in self.kwargs:
            self.assertEqual(kw["hosts"], 3)
        self.assertEqual({v: self.shas(v) for v in AMPS}, before)

    def test_the_record_states_it_has_no_pass_criterion(self):
        self.run_main(["--record"], self.all_submits())
        rec = self.record()
        self.assertIn("NONE", rec["pass_criterion"])
        self.assertIn("SIMULATED, NEVER MEASURED", rec["result_kind"])

    def test_the_record_says_which_reading_is_the_headline(self):
        rc, _, err = self.run_main(["--record"], self.all_submits())
        self.assertEqual(rc, 0, err)
        self.assertIn("across Csi",
                      self.record()["conditions"]["which_reading_is_the_headline"])

    def test_the_record_names_the_phi1_duration_actually_applied(self):
        self.run_main(["--record"], self.all_submits())
        self.assertEqual(self.record()["conditions"]["phi1_sampling_time_ns"],
                         MK.SAMP_PHI1_NS)

    def test_the_record_names_the_fleet_job_id(self):
        self.run_main(["--record"], self.all_submits())
        for v in AMPS:
            self.assertEqual(self.record()["amplitudes"][v]["remote"],
                             {"job_id": "job-0001"})

    def test_the_record_disclaims_any_sndr_or_resolution_consequence(self):
        """Issue #106 claims none: nothing here has been through model B."""
        self.run_main(["--record"], self.all_submits())
        rec = self.record()
        self.assertIn("No SNDR, ENOB or resolution consequence is claimed",
                      rec["pass_criterion"])
        # No number in the record is in dB, which is the unit every SNDR /
        # resolution claim in this repo is stated in.
        self.assertNotIn("_db", json.dumps(rec).lower())


class Derivations(unittest.TestCase):
    def test_error_rel_is_one_minus_sampled_over_ideal(self):
        results = {v: {"corners": grid(ideal(v) * 0.46, ideal(v))} for v in AMPS}
        d = RUNNER.derive(results)
        for v in AMPS:
            row = d["amplitudes"][v]["per_corner"][CORNER_IDS[0]]
            self.assertAlmostEqual(row["error_rel"], 0.54, places=9)
            self.assertAlmostEqual(row["sampled_V"], ideal(v) * 0.46, places=12)
            self.assertEqual(row["ideal_V"], ideal(v))

    def test_a_complete_sample_reads_as_zero_error(self):
        results = {v: {"corners": grid(ideal(v), ideal(v))} for v in AMPS}
        d = RUNNER.derive(results)
        for v in AMPS:
            self.assertEqual(d["amplitudes"][v]["worst_error_rel"], 0.0)
            self.assertEqual(d["amplitudes"][v]["corners_over_reference_line"], [])

    def test_the_binding_corner_is_the_worst_over_both_amplitudes(self):
        g0 = grid(ideal(AMPS[0]), ideal(AMPS[0]))
        g0[CORNER_IDS[5]] = corner(ideal(AMPS[0]) * 0.9, ideal(AMPS[0]))
        g1 = grid(ideal(AMPS[1]), ideal(AMPS[1]))
        g1[CORNER_IDS[9]] = corner(ideal(AMPS[1]) * 0.5, ideal(AMPS[1]))
        d = RUNNER.derive({AMPS[0]: {"corners": g0}, AMPS[1]: {"corners": g1}})
        self.assertEqual(d["binding"]["amplitude"], AMPS[1])
        self.assertEqual(d["binding"]["corner"], CORNER_IDS[9])
        self.assertAlmostEqual(d["binding"]["error_rel"], 0.5, places=9)

    def test_corners_over_the_reference_line_are_listed_not_failed(self):
        over = ideal(AMPS[0]) * (1 - 5e-4)        # 5x the 1e-4 reference line
        g = grid(ideal(AMPS[0]), ideal(AMPS[0]))
        g[CORNER_IDS[2]] = corner(over, ideal(AMPS[0]))
        d = RUNNER.derive({AMPS[0]: {"corners": g},
                           AMPS[1]: {"corners": grid(ideal(AMPS[1]), ideal(AMPS[1]))}})
        amp = d["amplitudes"][AMPS[0]]
        self.assertEqual(amp["corners_over_reference_line"], [CORNER_IDS[2]])
        self.assertAlmostEqual(
            amp["per_corner"][CORNER_IDS[2]]["error_vs_reference_line"], 5.0, places=6)
        self.assertEqual(d["reference_line_rel"], MK.SAMP_REFERENCE_LINE)
        self.assertIn("NOT A LIMIT", d["reference_line_label"])
        self.assertIn("has NOT failed anything", d["reference_line_label"])

    def test_input_level_dependence_compares_the_two_amplitudes_corner_by_corner(self):
        g0 = grid(ideal(AMPS[0]) * 0.5, ideal(AMPS[0]))      # 50 % error
        g1 = grid(ideal(AMPS[1]) * 0.9, ideal(AMPS[1]))      # 10 % error
        d = RUNNER.derive({AMPS[0]: {"corners": g0}, AMPS[1]: {"corners": g1}})
        dep = d["input_level_dependence"]
        self.assertAlmostEqual(dep["worst_difference_rel"], 0.4, places=9)
        self.assertAlmostEqual(dep[f"error_rel_{AMPS[0]}_at_worst"], 0.5, places=9)
        self.assertAlmostEqual(dep[f"error_rel_{AMPS[1]}_at_worst"], 0.1, places=9)

    def test_an_equal_fractional_error_shows_no_level_dependence(self):
        results = {v: {"corners": grid(ideal(v) * 0.8, ideal(v))} for v in AMPS}
        d = RUNNER.derive(results)
        self.assertAlmostEqual(d["input_level_dependence"]["worst_difference_rel"],
                               0.0, places=12)

    def test_the_per_side_shortfall_is_signed_towards_its_target(self):
        """A bottom plate short of vinp and one short of vinn both read positive."""
        g = grid(0.1, 0.2)
        cid = CORNER_IDS[0]
        g[cid][f"bpip_s{MK.SAMP_REPORT}"] = 0.97       # target 1.0
        g[cid][f"bpin_s{MK.SAMP_REPORT}"] = 0.87       # target 0.8
        d = RUNNER.derive({AMPS[0]: {"corners": g},
                           AMPS[1]: {"corners": grid(ideal(AMPS[1]), ideal(AMPS[1]))}})
        row = d["amplitudes"][AMPS[0]]["per_corner"][cid]
        self.assertAlmostEqual(row["bpi_p_shortfall_V"], 0.03, places=9)
        self.assertAlmostEqual(row["bpi_n_shortfall_V"], 0.07, places=9)

    def test_the_bottom_plate_only_reading_is_carried_with_its_own_error(self):
        """It differs from the headline by the top-plate differential."""
        g = grid(0.2, 0.2)
        cid = CORNER_IDS[0]
        g[cid][f"samp_bpi_s{MK.SAMP_REPORT}"] = 0.21
        g[cid][f"tpip_s{MK.SAMP_REPORT}"] = 0.905
        g[cid][f"tpin_s{MK.SAMP_REPORT}"] = 0.895
        d = RUNNER.derive({AMPS[0]: {"corners": g},
                           AMPS[1]: {"corners": grid(ideal(AMPS[1]), ideal(AMPS[1]))}})
        row = d["amplitudes"][AMPS[0]]["per_corner"][cid]
        self.assertAlmostEqual(row["top_plate_differential_V"], 0.01, places=9)
        self.assertAlmostEqual(row["error_rel_bpi_only"], -0.05, places=9)
        # The headline stays the across-plate reading, not this one.
        self.assertAlmostEqual(row["error_rel"], 0.0, places=9)
        self.assertAlmostEqual(
            row["sampled_bpi_only_V"] - row["sampled_V"],
            row["top_plate_differential_V"], places=9)

    def test_the_frozen_control_difference_is_carried(self):
        g = grid(0.2, 0.2)
        g[CORNER_IDS[0]][f"samp_f{MK.SAMP_REPORT}"] = 0.2004
        d = RUNNER.derive({AMPS[0]: {"corners": g},
                           AMPS[1]: {"corners": grid(ideal(AMPS[1]), ideal(AMPS[1]))}})
        row = d["amplitudes"][AMPS[0]]["per_corner"][CORNER_IDS[0]]
        self.assertAlmostEqual(row["frozen_minus_sampled_V"], 4e-4, places=9)

    def test_a_missing_sample_does_not_crash_the_derivation(self):
        g = grid(0.2, 0.2)
        g[CORNER_IDS[0]][SENTINEL] = None
        d = RUNNER.derive({AMPS[0]: {"corners": g},
                           AMPS[1]: {"corners": grid(ideal(AMPS[1]), ideal(AMPS[1]))}})
        self.assertIsNone(
            d["amplitudes"][AMPS[0]]["per_corner"][CORNER_IDS[0]]["error_rel"])

    def test_every_read_cycle_gets_its_own_error(self):
        results = {v: {"corners": grid(ideal(v) * 0.46, ideal(v))} for v in AMPS}
        d = RUNNER.derive(results)
        by_cycle = d["amplitudes"][AMPS[0]]["per_corner"][CORNER_IDS[0]][
            "error_rel_by_cycle"]
        self.assertEqual(set(by_cycle), {f"c{k}" for k in MK.SAMP_CYCLES})
        for val in by_cycle.values():
            self.assertAlmostEqual(val, 0.54, places=9)

    def test_the_amplitude_block_states_explicit_vinp_and_vinn(self):
        """"+/-0.1 V" must not be readable two ways."""
        results = {v: {"corners": grid(ideal(v), ideal(v))} for v in AMPS}
        d = RUNNER.derive(results)
        self.assertEqual(d["amplitudes"]["post_v0p2"]["vinp_V"], 1.0)
        self.assertEqual(d["amplitudes"]["post_v0p2"]["vinn_V"], 0.8)
        self.assertEqual(d["amplitudes"]["post_v0p6"]["vinp_V"], 1.2)
        self.assertAlmostEqual(d["amplitudes"]["post_v0p6"]["vinn_V"], 0.6)


class CommittedRecordProse(unittest.TestCase):
    """The committed record's definitional prose, against its own rows.

    Issue #106 round 3: `conditions.measured_quantity` asserted that the
    across-`Csi` reading equals the bottom-plate-only one -- the very premise
    this campaign disproved, three keys below a field that said the opposite.
    Nothing caught it: `request_sha256` covers the request and `deck_sha256`
    the deck, so the runner strings and the record's prose are pinned by no
    hash and, before this class, by no test either. Once merged the record is
    append-only evidence, so a false sentence here is not editable in place.
    """

    REC = HERE / "record-i106.json"

    def setUp(self):
        if not self.REC.exists():
            self.skipTest("record-i106.json is not committed")
        self.rec = json.loads(self.REC.read_text())

    def worst_top_plate_differential_V(self):
        """How far apart the two sampling forms actually get on this grid."""
        worst = 0.0
        for amp in self.rec["derived"]["amplitudes"].values():
            for row in amp["per_corner"].values():
                v = row.get("top_plate_differential_V")
                if v is not None:
                    worst = max(worst, abs(v))
        return worst

    def test_the_prose_does_not_claim_an_equality_the_rows_contradict(self):
        worst = self.worst_top_plate_differential_V()
        self.assertGreater(worst, 1e-6,
                           "the record carries no top-plate split at all -- "
                           "this guard would be vacuous")
        mq = " ".join(self.rec["conditions"]["measured_quantity"].split())
        # A period only ends a sentence when whitespace (or the end) follows:
        # the node name this looks for, v(xint.bpi_p), contains one itself.
        within = r"(?:[^.]|\.(?!\s|$))*?"
        claim = re.search(
            r"(?i)\b(?:so|hence|therefore|thus)\b" + within
            + r"\bequals?\b" + within + r"bpi_p", mq)
        self.assertIsNone(
            claim,
            "conditions.measured_quantity asserts the across-Csi form equals "
            "the bottom-plate-only form, but this record's own per-corner rows "
            f"put them up to {worst * 1e3:.1f} mV apart. Say when the equality "
            "holds and when it does not, as which_reading_is_the_headline does."
            + (f" Offending text: {claim.group(0)!r}" if claim else ""))

    def test_the_prose_names_both_forms_and_their_difference(self):
        """A reader must be able to get from the definition to the split."""
        mq = self.rec["conditions"]["measured_quantity"]
        for field in ("sampled_bpi_only_V", "top_plate_differential_V"):
            self.assertIn(field, mq,
                          f"measured_quantity does not mention {field}")

    def test_the_committed_conditions_block_still_matches_the_runner(self):
        """Generator and record must not drift.

        `conditions()` takes no arguments -- it is a pure function of the
        source constants and depends on no simulated value -- so this holds
        without re-running anything. It is what stops a corrected sentence
        from silently reverting the next time the record is regenerated, and
        what catches a hand-edit to either side.
        """
        self.assertEqual(self.rec["conditions"], RUNNER.conditions())


if __name__ == "__main__":
    unittest.main()
