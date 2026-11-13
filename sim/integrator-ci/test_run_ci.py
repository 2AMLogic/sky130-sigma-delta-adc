"""Tests for the charge-injection runner's record-admission and derivations. Run:
python3 -I -m unittest discover -s sim/integrator-ci -p 'test_*.py'

No fleet, no ngspice, no klt: `run_klt` and `pdk_stamp` are patched and the
runner's HERE / .partials are redirected into a temporary directory, so the
committed records are never read or written. `shas()` is NOT patched -- the real
request and deck files are copied into the temporary HERE, so the .partials hash
gate is exercised as written.

What is pinned here:

- The issue #94 rule, for this bench: a variant requested in this invocation
  whose submit fails is never served from .partials/ -- the run refuses with
  exit 1 and writes no record -- while reuse of a partial for a variant *not*
  requested this invocation still works.
- A grid that is short a point, or whose points returned no `dvod_mean`, is
  refused before a record is written. The Monte Carlo mode's expected count is
  anchors x N, not 45.
- The derivations: the FS-unit mapping, the `ci_gain_error` slope fit, the
  Monte Carlo sigma/ratio statistics, and the sqrt(W L) area prediction read off
  the real committed netlists.
- The --self-test skew substitution hits exactly one instance of the shipped
  netlist, so a netlist change cannot silently turn the sensitivity check into
  a no-op.
- The committed pre-#92 fixture still matches `design/integrator/integrator.spice`
  at the commit its header names (skipped when git history is unavailable).
"""
import contextlib
import importlib.util
import io
import json
import math
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent


def load_runner():
    """Load run_ci.py by path: 'integrator-ci' is not an importable name."""
    spec = importlib.util.spec_from_file_location("run_ci_under_test", HERE / "run_ci.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUNNER = load_runner()
MK = sys.modules["make_request"]          # put on sys.path by run_ci.py above
PIN = json.loads((RUNNER.REPO / "sim/pdk.json").read_text())
SENTINEL = RUNNER.SENTINEL
GRID = RUNNER.GRID_VARIANTS
MCV = RUNNER.MC_VARIANTS

PROCESS = ("tt", "ss", "ff", "sf", "fs")
VDDA = ("1p620", "1p800", "1p980")
TEMP = ("m40", "27", "125")
CORNER_IDS = tuple(f"{p}_{v}_{t}" for p in PROCESS for v in VDDA for t in TEMP)
ANCHOR_IDS = tuple(f"{p}_{v:.3f}_{t}" for p, v, t in MK.ANCHOR_POINTS)


def corner(dvod, **over):
    c = {k: 1.0 for k in MK.KEYS}
    c.update({"status": "pass", SENTINEL: dvod, "diagnostics": []})
    c.update(over)
    return c


def grid(dvod=1e-6, n=45, ids=CORNER_IDS):
    return {cid: corner(dvod) for cid in ids[:n]}


def mc_grid(per_point, n_samples=None):
    """{base_id: [dvod per sample]} -> the flat corner dict klt would return."""
    out = {}
    for base, vals in per_point.items():
        for i, v in enumerate(vals[:n_samples] if n_samples else vals):
            out[f"{base}/mc{i}"] = corner(v, monte_carlo={"sample_index": i, "seed": 7 + i})
    return out


def report(status="pass", job="job-0001"):
    return {"status": status,
            "environment": {"engine_version": "ngspice-47", "engine_host": "fleet-node-1",
                            "remote": {"job_id": job},
                            "monte_carlo": {"n": MK.MC_N, "seed": MK.MC_SEED,
                                            "vary": "mismatch"}}}


class RunnerCase(unittest.TestCase):
    """Runs main() against a temporary HERE with run_klt / pdk_stamp patched."""

    maxDiff = None

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="test-run-ci-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.here = self.tmp / "bench"
        self.here.mkdir()
        for v in GRID:                                  # real inputs: real shas()
            for name in (f"request_{v}.json", MK.deck_name(v)):
                (self.here / name).write_bytes((HERE / name).read_bytes())
        for v in MCV:
            (self.here / f"request_mc_{v}.json").write_bytes(
                (HERE / f"request_mc_{v}.json").read_bytes())
        (self.here / MK.PRE_CELL).write_bytes((HERE / MK.PRE_CELL).read_bytes())
        self.partials = self.here / ".partials"
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.calls = []
        self.kwargs = []

    def shas(self, v, mc=False):
        with mock.patch.object(RUNNER, "HERE", self.here), mock.patch.object(MK, "HERE", self.here):
            return RUNNER.mc_shas(v) if mc else RUNNER.shas(v)

    def write_partial(self, v, corners=None, mc=False, passed=True, stale=False):
        self.partials.mkdir(exist_ok=True)
        d = {"summary": {"corner_count": 45, "pass": 45, "fail": 0},
             "corners": grid() if corners is None else corners,
             "pass": passed, "ngspice": "ngspice-47", "engine_host": "fleet-node-0",
             "remote": {"job_id": f"job-earlier-{v}"}, **self.shas(v, mc)}
        if stale:
            d["deck_sha256"] = "0" * 64
        (self.partials / (f"mc-{v}.json" if mc else f"{v}.json")).write_text(
            json.dumps(d, indent=2) + "\n")
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
            st.enter_context(mock.patch.object(sys, "argv", ["run_ci.py", *argv]))
            st.enter_context(contextlib.redirect_stdout(out))
            st.enter_context(contextlib.redirect_stderr(err))
            rc = RUNNER.main()
        return rc, out.getvalue(), err.getvalue()

    def assertNoRecord(self, name="record.json"):
        self.assertFalse((self.here / name).exists(),
                         f"{name} was written from a run that should have refused")

    def all_grid_submits(self, dvod=None):
        """A passing nominal submit for every variant; dvod maps variant -> value."""
        dvod = dvod or {}
        return {v: (report(), grid(dvod.get(v, 1e-6))) for v in GRID}


class FailedSubmitIsNotServedFromPartials(RunnerCase):
    def test_requested_variant_with_failed_submit_refuses_despite_matching_partial(self):
        for v in GRID:
            self.write_partial(v)
        before = (self.partials / "post_v0.json").read_text()

        rc, out, err = self.run_main(["--variant", "post_v0", "--record"], {"post_v0": None})

        self.assertEqual(rc, 1)
        self.assertNoRecord()
        self.assertIn("not falling back to a local grid or to .partials/", err)
        self.assertIn("REFUSE: no result for post_v0", err)
        # A variant not requested this time still comes from its partial ...
        self.assertIn("pre_v0: reusing pre_v0.json", out)
        # ... and the failed one's partial is left on disk to re-run into.
        self.assertEqual((self.partials / "post_v0.json").read_text(), before)
        self.assertEqual(self.calls, ["post_v0"])

    def test_all_submits_failing_refuses_every_variant(self):
        for v in GRID:
            self.write_partial(v)

        rc, out, err = self.run_main(["--record"], {})

        self.assertEqual(rc, 1)
        self.assertNoRecord()
        for v in GRID:
            self.assertIn(v, err)
        self.assertEqual(self.calls, list(GRID))

    def test_stale_partial_with_failed_submit_also_refuses(self):
        self.write_partial("post_v0", stale=True)
        for v in GRID[1:]:
            self.write_partial(v)

        rc, _, err = self.run_main(["--variant", "post_v0", "--record"], {"post_v0": None})

        self.assertEqual(rc, 1)
        self.assertNoRecord()
        self.assertIn("REFUSE: no result for post_v0", err)

    def test_record_name_variant_is_not_written_either(self):
        for v in GRID:
            self.write_partial(v)

        rc, _, err = self.run_main(
            ["--variant", "post_v0", "--record", "--record-name", "record-retry.json"],
            {"post_v0": None})

        self.assertEqual(rc, 1)
        self.assertNoRecord("record-retry.json")

    def test_existing_record_is_never_overwritten(self):
        (self.here / "record.json").write_text("{}\n")

        rc, _, err = self.run_main(["--record"], self.all_grid_submits())

        self.assertEqual(rc, 2)
        self.assertIn("records are append-only", err)
        self.assertEqual(self.calls, [], "nothing is submitted once the record exists")
        self.assertEqual((self.here / "record.json").read_text(), "{}\n")


class AdmissionGates(RunnerCase):
    def test_short_grid_is_refused(self):
        s = self.all_grid_submits()
        s["post_v0"] = (report(), grid(n=44))

        rc, _, err = self.run_main(["--record"], s)

        self.assertEqual(rc, 1)
        self.assertIn("REFUSE: not all 45 grid points returned", err)
        self.assertNoRecord()

    def test_grid_with_no_dvod_mean_anywhere_is_refused(self):
        s = self.all_grid_submits()
        dead = grid()
        for c in dead.values():
            c[SENTINEL] = None
            c["diagnostics"] = ["batch_job_failed"]
        s["pre_v0"] = (report(), dead)

        rc, _, err = self.run_main(["--record"], s)

        self.assertEqual(rc, 1)
        self.assertIn(f"returned no {SENTINEL}", err)
        self.assertIn("batch_job_failed", err)
        self.assertNoRecord()

    def test_one_measurementless_point_is_enough_to_refuse(self):
        s = self.all_grid_submits()
        g = grid()
        g[CORNER_IDS[7]][SENTINEL] = None
        s["post_v0p2"] = (report(), g)

        rc, _, err = self.run_main(["--record"], s)

        self.assertEqual(rc, 1)
        self.assertIn(f"1 corner(s) returned no {SENTINEL}", err)
        self.assertNoRecord()

    def test_dead_grid_from_a_partial_still_fails_the_measurement_gate(self):
        dead = grid()
        for c in dead.values():
            c[SENTINEL] = None
        self.write_partial("post_v0", corners=dead)
        s = {v: (report(), grid()) for v in GRID[1:]}

        rc, _, err = self.run_main([*sum((["--variant", v] for v in GRID[1:]), []),
                                    "--record"], s)

        self.assertEqual(rc, 1)
        self.assertIn(f"returned no {SENTINEL}", err)
        self.assertNoRecord()

    def test_complete_grid_without_record_flag_writes_nothing(self):
        rc, out, err = self.run_main([], self.all_grid_submits())

        self.assertEqual(rc, 0, f"stderr={err!r}")
        self.assertIn("re-run with --record", out)
        self.assertNoRecord()


class MonteCarloMode(RunnerCase):
    """--mc has its own request files, its own partials and anchors x N points."""

    def mc_submits(self, post=None, pre=None, n=None):
        n = n or MK.MC_N
        post = post if post is not None else {b: [1e-5 + 1e-7 * i for i in range(n)]
                                              for b in ANCHOR_IDS}
        pre = pre if pre is not None else {b: [5e-6 + 5e-8 * i for i in range(n)]
                                           for b in ANCHOR_IDS}
        return {"mc-post_v0": (report(), mc_grid(post)),
                "mc-pre_v0": (report(), mc_grid(pre))}

    def test_mc_expects_anchors_times_n_not_45(self):
        rc, out, err = self.run_main(["--mc", "--record"], self.mc_submits())

        self.assertEqual(rc, 0, f"stderr={err!r}")
        rec = json.loads((self.here / "record-mc.json").read_text())
        self.assertEqual(rec["run_kind"], "monte_carlo_mismatch")
        self.assertEqual(self.calls, ["mc-post_v0", "mc-pre_v0"])
        self.assertNoRecord("record.json")

    def test_mc_short_by_one_sample_is_refused(self):
        s = self.mc_submits()
        s["mc-pre_v0"] = (report(), mc_grid(
            {b: [5e-6] * MK.MC_N for b in ANCHOR_IDS}, n_samples=None))
        # drop a single sample
        corners = s["mc-pre_v0"][1]
        corners.pop(next(iter(corners)))

        rc, _, err = self.run_main(["--mc", "--record"], s)

        self.assertEqual(rc, 1)
        self.assertIn(f"not all {len(MK.ANCHOR_POINTS) * MK.MC_N} grid points returned", err)
        self.assertNoRecord("record-mc.json")

    def test_mc_partials_are_separate_from_nominal_ones(self):
        """A nominal partial must not satisfy the same variant's Monte Carlo slot."""
        self.write_partial("post_v0", mc=False)         # a NOMINAL partial only
        rc, out, err = self.run_main(
            ["--mc", "--variant", "pre_v0", "--record"], self.mc_submits())

        self.assertEqual(rc, 1)
        self.assertIn("REFUSE: no result for post_v0", err)
        self.assertNotIn("reusing", out)
        self.assertEqual(self.calls, ["mc-pre_v0"], "only pre_v0 was requested")
        self.assertNoRecord("record-mc.json")
        self.assertFalse((self.partials / "mc-post_v0.json").exists())

    def test_mc_record_trims_per_sample_rows_but_keeps_the_statistics(self):
        """anchors x N x 41 keys would be megabytes; the stats must survive it."""
        rc, out, err = self.run_main(["--mc", "--record"], self.mc_submits())

        self.assertEqual(rc, 0, f"stderr={err!r}")
        rec = json.loads((self.here / "record-mc.json").read_text())
        sample = next(iter(rec["variants"]["post_v0"]["corners"].values()))
        self.assertEqual(set(sample) - set(RUNNER.MC_SAMPLE_KEYS), set())
        self.assertIn("dvod_mean", sample, "the step itself must be kept")
        self.assertIn("vod_rst", sample, "the OTA-offset confounder must be kept")
        self.assertNotIn("vod_c0", sample, "the per-cycle reads are dropped")
        self.assertEqual(rec["variants"]["post_v0"]["corner_keys_kept"],
                         list(RUNNER.MC_SAMPLE_KEYS))
        # The derivation ran on the untrimmed corners, so sigma is still there.
        d = rec["derived"]
        self.assertEqual(len(d["post_i92"]), len(MK.ANCHOR_POINTS))
        for st in d["post_i92"].values():
            self.assertEqual(st["n"], MK.MC_N)
            self.assertGreater(st["sigma_dvod_V"], 0.0)
        self.assertEqual(len(d["sigma_ratio"]), len(MK.ANCHOR_POINTS))
        self.assertIn("sqrt_wl_prediction", d)

    def test_hosts_is_passed_through_to_every_submission(self):
        """Sharding is how a campaign fits under the fleet's whole-job ceiling."""
        rc, _, err = self.run_main(["--mc", "--hosts", "4"], self.mc_submits())

        self.assertEqual(rc, 0, f"stderr={err!r}")
        self.assertEqual([k.get("hosts") for k in self.kwargs], [4, 4])

    def test_capacity_wait_defaults_to_the_host_rule_floor_and_is_raisable(self):
        rc, _, _ = self.run_main(["--mc"], self.mc_submits())
        self.assertEqual(rc, 0)
        self.assertEqual([k.get("capacity_wait_s") for k in self.kwargs],
                         [RUNNER.CAPACITY_WAIT_S] * 2)
        self.assertGreaterEqual(RUNNER.CAPACITY_WAIT_S, 600,
                                "the host rule floor for a batch submit is 600s")
        self.kwargs.clear()
        self.run_main(["--mc", "--capacity-wait", "1800"], self.mc_submits())
        self.assertEqual([k.get("capacity_wait_s") for k in self.kwargs], [1800, 1800])

    def test_hosts_does_not_change_the_request_files(self):
        """A sharded re-run must still match an unsharded partial's sha."""
        before = {v: (self.here / f"request_mc_{v}.json").read_bytes() for v in MCV}
        self.run_main(["--mc", "--hosts", "7"], self.mc_submits())
        for v in MCV:
            self.assertEqual((self.here / f"request_mc_{v}.json").read_bytes(), before[v])

    def test_mc_variant_filter_rejects_a_nominal_only_variant(self):
        rc, _, err = self.run_main(["--mc", "--variant", "post_dac"], self.mc_submits())

        self.assertEqual(rc, 2)
        self.assertIn("--variant names nothing in this mode", err)
        self.assertEqual(self.calls, [])


class Derivations(unittest.TestCase):
    def test_fs_mapping_is_volts_over_the_dac_swing(self):
        self.assertEqual(RUNNER.fs(1.2), 1.0)
        self.assertAlmostEqual(RUNNER.fs(12e-6), 1e-5)
        self.assertIsNone(RUNNER.fs(None))

    def test_ci_offset_and_gain_error_come_off_the_three_amplitudes(self):
        cid = CORNER_IDS[0]
        # Construct a cell with a 6 uV offset and an exactly 0.5 V/V slope:
        # dvod = 0.5*vin + 6e-6, so ci_gain_error_bound must be 0.
        results = {v: {"corners": {cid: corner(0.5 * MK.VARIANTS[v]["vin_diff"] + 6e-6)}}
                   for v in ("post_v0", "post_v0p1", "post_v0p2")}
        results["post_dac"] = {"corners": {}}
        d = RUNNER.nominal_derivation(results)
        row = d["per_corner"][cid]
        self.assertAlmostEqual(row["ci_offset_fs"], 6e-6 / 1.2)
        self.assertAlmostEqual(row["step_slope_v_per_v"], 0.5)
        self.assertAlmostEqual(row["ci_gain_error_bound"], 0.0, places=12)
        self.assertAlmostEqual(row["fit_max_residual_V"], 0.0, places=15)
        self.assertEqual(d["worst_ci_offset_fs"]["corner"], cid)

    def test_a_2_percent_slope_excess_reads_as_a_2_percent_gain_error(self):
        cid = CORNER_IDS[1]
        results = {v: {"corners": {cid: corner(0.51 * MK.VARIANTS[v]["vin_diff"])}}
                   for v in ("post_v0", "post_v0p1", "post_v0p2")}
        results["post_dac"] = {"corners": {}}
        row = RUNNER.nominal_derivation(results)["per_corner"][cid]
        self.assertAlmostEqual(row["ci_gain_error_bound"], 0.02, places=10)

    def test_mc_sigma_and_ratio_are_the_sample_statistics(self):
        post = {ANCHOR_IDS[0]: [1.0, 2.0, 3.0, 4.0]}
        pre = {ANCHOR_IDS[0]: [1.0, 1.5, 2.0, 2.5]}
        results = {"post_v0": {"corners": mc_grid(post)},
                   "pre_v0": {"corners": mc_grid(pre)}}
        d = RUNNER.mc_derivation(results, {"note": "x"})
        p = d["post_i92"][ANCHOR_IDS[0]]
        self.assertEqual(p["n"], 4)
        self.assertAlmostEqual(p["mean_dvod_V"], 2.5)
        self.assertAlmostEqual(p["sigma_dvod_V"], 1.2909944487358056)   # stdev, n-1
        self.assertAlmostEqual(p["sigma_ci_offset_fs"], 1.2909944487358056 / 1.2)
        self.assertAlmostEqual(p["sigma_rel_standard_error"], 1 / math.sqrt(6))
        r = d["sigma_ratio"][ANCHOR_IDS[0]]
        self.assertAlmostEqual(r["sigma_ratio_post_over_pre"], 2.0)
        self.assertAlmostEqual(r["sigma_ratio_standard_error"],
                               2.0 * math.sqrt(2) / math.sqrt(6))
        self.assertEqual(d["worst_abs_dvod_V"]["value"], 4.0)

    def test_mc_sigma_is_zero_for_an_mc_off_control(self):
        """The negative control klt documents: no spread must read as exactly 0."""
        flat = {ANCHOR_IDS[0]: [3e-6] * 5}
        d = RUNNER.mc_derivation({"post_v0": {"corners": mc_grid(flat)},
                                  "pre_v0": {"corners": mc_grid(flat)}}, {})
        self.assertEqual(d["post_i92"][ANCHOR_IDS[0]]["sigma_dvod_V"], 0.0)
        self.assertIsNone(d["sigma_ratio"][ANCHOR_IDS[0]]["sigma_ratio_post_over_pre"])

    def test_dac_crosscheck_reads_the_leak_as_a_dc_gain(self):
        cid = CORNER_IDS[0]
        # vod leaked from 0.6 V by 1/1000 over two clocks -> dvod_2clk = 0.3e-3.
        c = corner(0.0, dvod_2clk=-0.3e-3)
        c[f"vod_c{MK.STEADY_TO - 1}"] = 0.6
        d = RUNNER.dac_crosscheck({"post_dac": {"corners": {cid: c}}})
        self.assertAlmostEqual(d["per_corner"][cid]["implied_dc_gain"], 1000.0)
        self.assertAlmostEqual(d["per_corner"][cid]["implied_dc_gain_db"], 60.0, places=6)


class DrawnCapRatio(unittest.TestCase):
    """Cs/Ci comes off the drawn MIM geometry, so a capacitor-ratio slope
    contribution is visible instead of being booked as charge injection."""

    def setUp(self):
        self.c = RUNNER.cap_ratio(RUNNER.REPO / "design/integrator/integrator.spice")

    def test_ratio_is_the_drawn_area_ratio_not_the_nominal_one_half(self):
        self.assertAlmostEqual(self.c["cs_drawn_area_um2"], 22.17 ** 2, places=3)
        self.assertAlmostEqual(self.c["ci_drawn_area_um2"], 31.43 ** 2, places=3)
        self.assertAlmostEqual(self.c["drawn_area_ratio_cs_over_ci"],
                               22.17 ** 2 / 31.43 ** 2, places=9)
        self.assertNotAlmostEqual(self.c["drawn_area_ratio_cs_over_ci"], 0.5, places=4,
                                  msg="if the drawn ratio were exactly 0.5 there "
                                      "would be nothing to separate")
        self.assertLess(self.c["drawn_vs_model_b_c1_rel"], 0.0)

    def test_the_slope_is_reported_against_both_references(self):
        cid = CORNER_IDS[0]
        ratio = self.c["drawn_area_ratio_cs_over_ci"]
        # A cell whose slope is exactly the drawn capacitor ratio has no gain
        # error to attribute to injection, but a nonzero bound against C1 = 0.5.
        results = {v: {"corners": {cid: corner(ratio * MK.VARIANTS[v]["vin_diff"])}}
                   for v in ("post_v0", "post_v0p1", "post_v0p2")}
        results["post_dac"] = {"corners": {}}
        row = RUNNER.nominal_derivation(results, self.c)["per_corner"][cid]
        self.assertAlmostEqual(row["slope_vs_drawn_cap_ratio_rel"], 0.0, places=12)
        self.assertAlmostEqual(row["ci_gain_error_bound"],
                               self.c["drawn_vs_model_b_c1_rel"], places=12)

    def test_derivation_without_caps_still_reports_the_c1_bound(self):
        cid = CORNER_IDS[0]
        results = {v: {"corners": {cid: corner(0.5 * MK.VARIANTS[v]["vin_diff"])}}
                   for v in ("post_v0", "post_v0p1", "post_v0p2")}
        results["post_dac"] = {"corners": {}}
        row = RUNNER.nominal_derivation(results)["per_corner"][cid]
        self.assertAlmostEqual(row["ci_gain_error_bound"], 0.0, places=12)
        self.assertNotIn("slope_vs_drawn_cap_ratio_rel", row)


class AreaPrediction(unittest.TestCase):
    """The sqrt(W L) prediction is read off the two real committed netlists."""

    def setUp(self):
        self.pred = RUNNER.area_prediction(
            HERE / MK.PRE_CELL, RUNNER.REPO / "design/integrator/integrator.spice")

    def test_summing_node_pair_grew_less_than_all_four_vcm_switches(self):
        s = self.pred["summing_node_switches"]
        a = self.pred["all_phi2_vcm_switches"]
        # Sti/Str: 12x0.15 NMOS + 4x0.35 PMOS = 1.8 + 1.4 um2 per switch.
        self.assertAlmostEqual(s["channel_area_um2_per_side_pre"], 2 * 1.8, places=4)
        self.assertAlmostEqual(s["channel_area_um2_per_side_post"], 2 * (1.8 + 1.4), places=4)
        self.assertAlmostEqual(s["area_ratio"], 3.2 / 1.8, places=3)
        # Sbi/Sbr add 24x0.35 = 8.4 um2 each, so all four grow much more.
        self.assertAlmostEqual(a["channel_area_um2_per_side_pre"], 4 * 1.8, places=4)
        self.assertAlmostEqual(a["channel_area_um2_per_side_post"],
                               2 * (1.8 + 1.4) + 2 * (1.8 + 8.4), places=4)
        self.assertGreater(a["sqrt_area_ratio"], s["sqrt_area_ratio"],
                           "SIZING.md's framing must predict more growth than the "
                           "summing-node pair alone, or the two predictions are "
                           "not distinguishable and the record says nothing")

    def test_the_pre_fixture_really_has_no_pmos_halves(self):
        pre = RUNNER.switch_areas(HERE / MK.PRE_CELL)
        for name in RUNNER.VCM_SWITCHES:
            self.assertEqual(pre[name]["pmos"], [], f"{name} has a PMOS half pre-#92")
            self.assertEqual(len(pre[name]["nmos"]), 2, f"{name} has two sides")

    def test_the_shipped_cell_has_the_pmos_halves(self):
        post = RUNNER.switch_areas(RUNNER.REPO / "design/integrator/integrator.spice")
        for name in RUNNER.VCM_SWITCHES:
            self.assertEqual(len(post[name]["pmos"]), 2, f"{name} is missing a PMOS half")


class SelfTestSkew(unittest.TestCase):
    def test_the_skew_hits_exactly_one_instance(self):
        with tempfile.TemporaryDirectory() as td:
            dst = pathlib.Path(td) / "skew.spice"
            RUNNER.write_skewed_cell(dst)
            orig = (RUNNER.REPO / "design/integrator/integrator.spice").read_text()
            lines = [ln for ln in dst.read_text().splitlines()
                     if ln.startswith("XSti_p_p ")]
            self.assertEqual(len(lines), 1)
            self.assertIn("W=4.4", lines[0])
            self.assertEqual(sum(1 for a, b in zip(orig.splitlines(),
                                                   dst.read_text().splitlines()) if a != b), 1,
                             "the self-test must change exactly one line")

    def test_a_netlist_without_the_instance_refuses_rather_than_no_op(self):
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td)
            (repo / "design/integrator").mkdir(parents=True)
            (repo / "design/integrator/integrator.spice").write_text(
                "* no switches here\n.subckt integrator a b\n.ends\n")
            with mock.patch.object(RUNNER, "REPO", repo):
                with self.assertRaises(SystemExit) as e:
                    RUNNER.write_skewed_cell(repo / "out.spice")
            self.assertIn("--self-test needs updating", str(e.exception))
            self.assertFalse((repo / "out.spice").exists(),
                             "a refused skew must not leave a no-op cell behind")


class PreI92Fixture(unittest.TestCase):
    """The committed fixture must stay identical to the commit its header names."""

    def test_fixture_body_matches_the_commit_it_names(self):
        r = subprocess.run(["git", "show", "e310b5f:design/integrator/integrator.spice"],
                           cwd=RUNNER.REPO, capture_output=True, text=True)
        if r.returncode:
            self.skipTest("git history for e310b5f is unavailable (shallow clone)")
        committed = (HERE / MK.PRE_CELL).read_text()
        # The fixture is the blob with a provenance header prepended; everything
        # from the first non-comment card on must match byte for byte.
        start = committed.index(".subckt integrator")
        self.assertEqual(committed[start:], r.stdout[r.stdout.index(".subckt integrator"):])

    def test_fixture_header_names_the_commit_and_the_vth_swap(self):
        head = (HERE / MK.PRE_CELL).read_text()[:2000]
        self.assertIn("e310b5f", head)
        self.assertIn("nfet_01v8_lvt", head, "the Vth half of the #92 delta must be stated")


class DeckGeneration(unittest.TestCase):
    def test_every_placeholder_is_substituted_in_every_variant(self):
        for v, d in MK.VARIANTS.items():
            text = MK.render(v, d)            # raises if a placeholder survives
            self.assertNotIn("@", text.replace("@VARIANT@", ""), f"{v} has a stray @")

    def test_committed_decks_match_the_template_and_table(self):
        """A hand-edited deck would make the committed requests' shas a lie."""
        for v, d in MK.VARIANTS.items():
            self.assertEqual((HERE / MK.deck_name(v)).read_text(), MK.render(v, d),
                             f"{MK.deck_name(v)} is stale: re-run make_request.py")

    def test_committed_requests_match_the_generator(self):
        for v in MK.VARIANTS:
            self.assertEqual(json.loads((HERE / f"request_{v}.json").read_text()),
                             MK.nominal_request(v), f"request_{v}.json is stale")
        for v in MK.MC_VARIANTS:
            self.assertEqual(json.loads((HERE / f"request_mc_{v}.json").read_text()),
                             MK.mc_request(v), f"request_mc_{v}.json is stale")

    def test_the_pre_and_post_decks_differ_only_in_the_cell_and_its_instantiation(self):
        pre = (HERE / MK.deck_name("pre_v0")).read_text().splitlines()
        post = (HERE / MK.deck_name("post_v0")).read_text().splitlines()
        self.assertEqual(len(pre), len(post))
        diff = [(a, b) for a, b in zip(pre, post) if a != b]
        # The cell .include, the Xint line, and the three header comment lines
        # that name the variant and the cell file.
        self.assertTrue(any(".include" in a for a, _ in diff))
        self.assertTrue(any(a.startswith("Xint ") for a, _ in diff))
        for a, b in diff:
            self.assertTrue(a.startswith("*") or ".include" in a or a.startswith("Xint "),
                            f"unexpected non-cell difference: {a!r} vs {b!r}")

    def test_mc_request_names_mismatch_sections_at_the_anchor_points(self):
        for v in MK.MC_VARIANTS:
            r = MK.mc_request(v)
            units = r["corners"]["units"]
            self.assertEqual(len(units), len(MK.ANCHOR_POINTS))
            for u in units:
                self.assertTrue(u["process"].endswith("_mm"),
                                "per-instance mismatch needs sky130's _mm sections")
            self.assertEqual(r["monte_carlo"]["vary"], "mismatch")
            self.assertEqual(r["monte_carlo"]["n"], MK.MC_N)
            self.assertNotIn("process", r["corners"],
                             "corners.units is mutually exclusive with the crossed axes")

    def test_nominal_requests_are_the_full_dr002_grid_with_no_sampling(self):
        for v in MK.VARIANTS:
            r = MK.nominal_request(v)
            self.assertNotIn("monte_carlo", r)
            self.assertEqual(len(r["corners"]["process"]), 5)
            self.assertEqual(len(r["corners"]["supply_v"]["vdda"]), 3)
            self.assertEqual(len(r["corners"]["temperature_c"]), 3)

    def test_read_window_sits_inside_the_phi1_hold(self):
        """The window must contain no clock edge: that is what makes it a hold."""
        a, b = MK.W_READ
        self.assertGreater(a, 0.0)
        self.assertLess(b, 90.3e-9, "phi1e falls at ~90.5 ns; the window must end before it")
        for lo, hi in (MK.W_DRIFT, MK.W_RESET):
            self.assertLess(hi, a, "the earlier windows must not overlap the read window")
        self.assertLess(MK.W_RESET[1], 39.9e-9, "the reset window must end before reset opens")
        self.assertGreater(MK.T_END, (MK.N_CYC - 1) * MK.T_CLK + b,
                           "the transient must cover the last cycle's read window")


if __name__ == "__main__":
    unittest.main()
