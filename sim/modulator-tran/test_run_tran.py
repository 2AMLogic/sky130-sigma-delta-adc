"""Tests for the short full-modulator transient bench. Run:
python3 -I -m unittest discover -s sim/modulator-tran -p 'test_*.py'

No fleet, no ngspice, no klt: every test works on synthetic klt sim reports, so
no run is repeated and the committed samples are never touched. The one
exception is `RecordBindings`, which reads the committed `record.json` only to
re-derive its deck/request hashes against the committed tree.

What is pinned here:

- A missing anchor, a missing scalar measurement, a short per-clock sample set,
  a clock that did not run at fs, and two power routes that disagree each
  refuse the record (issue #94's rule for this bench: a partial or failed batch
  submit must not become a record).
- A same-count substitution -- the 27 C tt anchor's corner replaced by a
  125 C one at the same voltage, corner ID updated to match -- refuses it
  too: coverage is anchor identities, not a row count (issue #393, the
  shared rule in settling_common).
- A corner that *fails* a limit is still recorded, and recorded as failing --
  the opposite of a missing corner, and what the issue asks for.
- The request is what the record says it is: 7 DR-002 anchors with `vclk`
  swept alongside `vdda`, the three graded spec rows carrying both `limits`
  and `spec_row`, a coherent tone, per-clock sample cards on every recorded
  clock, and every `cycle_mean`/`energy` signal named in `save_vectors`
  (klt only auto-saves vectors named by `expr`/`spice`/`crossings`).
- The record binds itself to the tree: `deck_sha256`/`request_sha256` equal
  the sha256 of the committed deck and request. The design-netlist hashes are
  deliberately unbound -- a mismatch there is the record's signal that it
  describes an older netlist, not a failure.
- The per-clock reduction: the sampling grid, the analytic u[n], and the
  bitstream polarity.
"""
import json
import math
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
# `sim/` is not on sys.path under `python3 -I`: isolated mode drops CWD and
# PYTHONPATH, and `discover -s sim/modulator-tran` puts only the bench directory
# there. run_tran.py inserts it once loaded, which is too late for this import.
sys.path.insert(0, str(HERE.parent))

import runner_test_common as rtc                                    # noqa: E402

RUNNER = rtc.load_runner("run_tran_under_test", HERE / "run_tran.py")
MK = sys.modules["make_request"]          # put on sys.path by run_tran.py above
REQUEST = json.loads((HERE / "request.json").read_text())
ANCHOR_IDS = tuple(f"{p}/vclk={v:.3f}_vdda={v:.3f}V/{t:g}C"
                   for p, v, t in MK.ANCHOR_POINTS)

WINDOW_S = MK.N_REC * MK.TPER


def scalars(**over):
    """A plausible set of scalar measurement values for one anchor."""
    p_vdda = 4.7e-4
    v = {k: 1.0 for k in RUNNER.KEYS}
    v.update({
        "vdda_v": 1.8,
        "p_ana": 4.8e-4, "p_vdda": p_vdda, "p_ref": 1.3e-5, "p_vcm": 3.8e-7,
        "e_vdda": p_vdda * WINDOW_S, "e_vrefp": 2.5e-11,
        "e_vrefn": -5.0e-12, "e_vvcm": 5.9e-13,
        "o1_max": 1.1, "o1_min": -1.0, "o1_swing_pp": 2.1,
        "o2_max": 0.6, "o2_min": -0.8, "o2_swing_pp": 1.4,
        "o1p_max": 1.47, "o1p_min": 0.41, "o2p_max": 1.21, "o2p_min": 0.52,
        "phi1_edges": MK.N_REC, "bs_edges": 500, "bs_mean": 0.9,
    })
    v.update(over)
    return v


def report_corner(cid, n_clocks=None, status="pass", **over):
    """One `corners[]` entry of a klt sim report, as `extract` consumes it."""
    n_clocks = MK.N_REC if n_clocks is None else n_clocks
    proc, _, temp = cid.split("/")
    vdda = float(cid.split("vdda=")[1].split("V")[0])
    vals = scalars(**over)
    ms = []
    for name, value in vals.items():
        ms.append({"name": name, "value": value, "status": "pass"})
    ms.append({"name": "bs_edges", "value": vals["bs_edges"], "status": "pass",
               "crossings": {"times": [1e-6, 2e-6], "edges": ["rise", "fall"],
                             "truncated": False}})
    for i, k in enumerate(MK.REC_CLOCKS[:n_clocks]):
        ms.append({"name": f"sb_{k:05d}", "value": vdda if i % 2 else 0.0})
        ms.append({"name": f"s1_{k:05d}", "value": 0.1 * ((i % 7) - 3)})
        ms.append({"name": f"s2_{k:05d}", "value": 0.05 * ((i % 5) - 2)})
    return {"corner_id": cid, "process": proc, "supply_v": {"vdda": vdda},
            "temperature_c": float(temp.rstrip("C")), "status": status,
            "measurements": ms, "diagnostics": []}


def report(n_anchors=len(ANCHOR_IDS), n_clocks=None, **over):
    return {"corners": [report_corner(cid, n_clocks, **over)
                        for cid in ANCHOR_IDS[:n_anchors]],
            "environment": {"engine_version": "46"}, "measurements": []}


refuses = rtc.call


class RecordGates(unittest.TestCase):
    def setUp(self):
        self.corners, self.samples = RUNNER.extract(report())

    def test_complete_run_passes_every_gate(self):
        self.assertTrue(RUNNER.anchors_complete(self.corners))
        self.assertTrue(RUNNER.scalars_present(self.corners))
        self.assertTrue(RUNNER.samples_present(self.samples))
        self.assertTrue(RUNNER.clock_ran_at_fs(self.corners))
        self.assertTrue(RUNNER.power_routes_agree(self.corners, WINDOW_S))

    def test_missing_anchor_is_refused(self):
        corners, _ = RUNNER.extract(report(n_anchors=6))
        ok, err = refuses(RUNNER.anchors_complete, corners)
        self.assertFalse(ok)
        self.assertIn("6 of 7 DR-002 anchor points", err)

    def test_same_count_substitution_is_refused(self):
        rep = report()
        for vdda, temp in [(1.8, 125), (1.8, 27.5), (1.8004, 27)]:
            with self.subTest(vdda=vdda, temp=temp):
                rep["corners"][0] = report_corner(f"tt/vclk={vdda}_vdda={vdda}V/{temp}C")
                corners, samples = RUNNER.extract(rep)
                self.assertEqual(len(corners), len(ANCHOR_IDS))
                self.assertTrue(RUNNER.scalars_present(corners))
                self.assertTrue(RUNNER.samples_present(samples))
                self.assertTrue(RUNNER.clock_ran_at_fs(corners))
                self.assertTrue(RUNNER.power_routes_agree(corners, WINDOW_S))
                ok, err = refuses(RUNNER.anchors_complete, corners)
                self.assertFalse(ok)
                self.assertIn("missing: [('tt', 1.8, 27)]", err)
                key = ("tt", vdda, float(temp))
                self.assertIn(f"unexpected: [{key!r}]", err)

    def test_missing_scalar_measurement_is_refused(self):
        # A fleet job that dies still returns one entry per point, so the
        # count gate alone would let an empty grid become a record.
        corners, _ = RUNNER.extract(report(p_ana=None))
        self.assertTrue(RUNNER.anchors_complete(corners))
        ok, err = refuses(RUNNER.scalars_present, corners)
        self.assertFalse(ok)
        self.assertIn("p_ana", err)
        self.assertIn("no record is written", err)

    def test_short_sample_set_is_refused(self):
        _, samples = RUNNER.extract(report(n_clocks=MK.N_REC - 1))
        ok, err = refuses(RUNNER.samples_present, samples)
        self.assertFalse(ok)
        self.assertIn("incomplete per-clock sample set", err)

    def test_clock_that_did_not_run_at_fs_is_refused(self):
        corners, _ = RUNNER.extract(report(phi1_edges=MK.N_REC - 2))
        ok, err = refuses(RUNNER.clock_ran_at_fs, corners)
        self.assertFalse(ok)
        self.assertIn("not clocked at fs", err)

    def test_disagreeing_power_routes_are_refused(self):
        # The energy integral and the cycle-aligned mean are different code on
        # different vectors; if they disagree, one is not measuring P(VDDA).
        corners, _ = RUNNER.extract(report(e_vdda=4.7e-4 * WINDOW_S * 1.05))
        ok, err = refuses(RUNNER.power_routes_agree, corners, WINDOW_S)
        self.assertFalse(ok)
        self.assertIn("disagree", err)

    def test_agreeing_power_routes_pass(self):
        corners, _ = RUNNER.extract(
            report(e_vdda=4.7e-4 * WINDOW_S * (1 + RUNNER.POWER_ROUTE_TOL / 2)))
        self.assertTrue(RUNNER.power_routes_agree(corners, WINDOW_S))

    def test_failing_corner_is_recorded_as_failing_not_dropped(self):
        rep = report()
        rep["corners"][3]["status"] = "fail"
        corners, samples = RUNNER.extract(rep)
        # Every admission gate still passes: the corner was simulated.
        self.assertTrue(RUNNER.anchors_complete(corners))
        self.assertTrue(RUNNER.scalars_present(corners))
        self.assertTrue(RUNNER.clock_ran_at_fs(corners))
        rec = RUNNER.build_record(
            {"corners": corners, "samples_index": {}},
            "open_pdks test", {"open_pdks_revision": "deadbeef"},
            {"engine_version": "46"}, WINDOW_S)
        self.assertEqual(len(rec["corners"]), 7)
        self.assertEqual(rec["summary"]["fail"], 1)
        self.assertFalse(rec["pass"])


class PerClockReduction(unittest.TestCase):
    def test_sampling_grid_is_the_clock_falling_edge(self):
        # Clock k's falling 50 % crossing: half a period after its rising one.
        for k in (MK.N_SETTLE, MK.N_SETTLE + MK.N_REC - 1):
            self.assertAlmostEqual(MK.sample_time(k),
                                   MK.TRISE0 + (k + 0.5) * MK.TPER, places=15)
        self.assertLess(MK.sample_time(MK.REC_CLOCKS[-1]), MK.T_END)
        self.assertGreater(MK.sample_time(MK.REC_CLOCKS[0]), MK.T_REC0)

    def test_u_is_the_analytic_tone_at_the_sample_instant(self):
        _, samples = RUNNER.extract(report())
        s = samples[ANCHOR_IDS[0]]
        self.assertEqual(len(s["u_diff_v"]), MK.N_REC)
        for i in (0, 17, MK.N_REC - 1):
            t = MK.sample_time(MK.REC_CLOCKS[i])
            want = 2 * MK.AMP_SE_V * math.sin(2 * math.pi * MK.FIN_HZ * t)
            self.assertAlmostEqual(s["u_diff_v"][i], want, places=8)
        self.assertLessEqual(max(abs(x) for x in s["u_diff_v"]),
                             2 * MK.AMP_SE_V + 1e-12)

    def test_bitstream_polarity_is_thresholded_at_half_vdda(self):
        rep = report()
        c = rep["corners"][0]
        by = {m["name"]: m for m in c["measurements"]}
        by[f"sb_{MK.REC_CLOCKS[0]:05d}"]["value"] = 1.79
        by[f"sb_{MK.REC_CLOCKS[1]:05d}"]["value"] = 0.01
        _, samples = RUNNER.extract(rep)
        y = samples[ANCHOR_IDS[0]]["y"]
        self.assertEqual(y[0], 1)
        self.assertEqual(y[1], -1)

    def test_runtime_is_carried_into_the_record(self):
        rep = report()
        for i, c in enumerate(rep["corners"]):
            c["runtime_s"] = 600.0 + 10 * i
        corners, _ = RUNNER.extract(rep)
        rec = RUNNER.build_record(
            {"corners": corners, "samples_index": {}},
            "open_pdks test", {"open_pdks_revision": "deadbeef"},
            {"engine_version": "46"}, WINDOW_S)
        self.assertEqual(rec["summary"]["slowest_corner_runtime_s"][0], 660.0)

    def test_samples_file_round_trips(self):
        # The committed samples files are what the cross-check reads, and the
        # record binds them by sha256, so the compacting must be lossless.
        _, samples = RUNNER.extract(report())
        s = samples[ANCHOR_IDS[0]]
        self.assertEqual(json.loads(RUNNER.dump_samples(s)), s)
        text = RUNNER.dump_samples(s)
        self.assertNotIn("@@", text)
        # one line per array, not one line per number
        self.assertLess(len(text.splitlines()), 40)

    def test_samples_index_binds_each_file_by_hash(self):
        import tempfile
        _, samples = RUNNER.extract(report())
        with tempfile.TemporaryDirectory() as td:
            outdir = pathlib.Path(td) / "samples"
            index = RUNNER.write_samples(samples, outdir)
            self.assertEqual(len(index), len(MK.ANCHOR_POINTS))
            for cid, entry in index.items():
                self.assertEqual(entry["n_clocks"], MK.N_REC)
                self.assertEqual(len(entry["sha256"]), 64)
                # repo-relative, naming the bench's own samples directory
                self.assertTrue(entry["file"].startswith("samples/"))
                self.assertFalse(entry["file"].startswith("samples//"))

    def test_later_records_do_not_reuse_the_committed_samples_dir(self):
        self.assertEqual(RUNNER.samples_dir_for(MK.RECORD_NAME), RUNNER.SAMPLES)
        self.assertEqual(RUNNER.samples_dir_for("record-c0p3.json"),
                         HERE / "samples-record-c0p3")

    def test_corner_slug_is_a_safe_filename(self):
        for c in report()["corners"]:
            slug = RUNNER.corner_slug(c)
            self.assertNotIn("/", slug)
            self.assertNotIn("=", slug)
        self.assertEqual(
            RUNNER.corner_slug({"process": "ss", "supply_v": {"vdda": 1.62},
                                "temperature_c": -40}),
            "ss-1.620V-m40C")

    def test_slugs_are_unique_across_the_anchor_set(self):
        slugs = [RUNNER.corner_slug(c) for c in report()["corners"]]
        self.assertEqual(len(set(slugs)), len(MK.ANCHOR_POINTS))


class RequestShape(unittest.TestCase):
    def test_committed_request_matches_make_request(self):
        # The record names request.json's sha256; a stale committed request
        # would make that provenance a lie.
        self.assertEqual(REQUEST, MK.build_request())
        self.assertEqual((HERE / MK.DECK).read_text(), MK.build_deck())

    def test_seven_anchors_with_vclk_swept_alongside_vdda(self):
        units = REQUEST["corners"]["units"]
        self.assertEqual(len(units), len(MK.ANCHOR_POINTS))
        for u, (p, v, t) in zip(units, MK.ANCHOR_POINTS):
            self.assertEqual(u["process"], p)
            self.assertEqual(u["temperature_c"], t)
            self.assertEqual(u["supply_v"], {"vdda": v, "vclk": v})
        # corners.supply_waveforms requires its entries to be a supply_v key
        # of every unit, which is why vclk is there at all.
        self.assertEqual(REQUEST["corners"]["supply_waveforms"], ["vclk"])

    def test_graded_rows_carry_both_limits_and_spec_row(self):
        graded = {m["name"]: m for m in REQUEST["measurements"] if "spec_row" in m}
        self.assertEqual(
            {n: (m["spec_row"], sorted(m["limits"])) for n, m in graded.items()},
            {"p_ana": ("13", ["max"]),
             "o1_swing_pp": ("11", ["max"]),
             "o2_swing_pp": ("11", ["max"]),
             "phi1_edges": ("5", ["max", "min"]),
             "bs_edges": ("5", ["max", "min"])})
        self.assertEqual(graded["p_ana"]["limits"]["max"], MK.P_ANA_MAX_W)
        self.assertEqual(graded["o1_swing_pp"]["limits"]["max"], MK.SWING_MAX_VPP)

    def test_tone_is_coherent_over_the_recorded_window(self):
        cycles = MK.FIN_HZ * MK.N_REC * MK.TPER
        self.assertAlmostEqual(cycles, MK.CYCLES, places=9)
        self.assertEqual(math.gcd(MK.CYCLES, MK.N_REC), 1)
        self.assertLess(MK.FIN_HZ, 20e3)      # inside spec row 1's band

    def test_amplitude_is_minus_6_dbfs_of_the_differential_reference(self):
        self.assertAlmostEqual(
            20 * math.log10(2 * MK.AMP_SE_V / MK.VREF_DIFF_V),
            MK.AMP_DBFS, places=9)

    def test_one_sample_card_per_recorded_clock_per_signal(self):
        cards = [m for m in REQUEST["measurements"] if "spice" in m]
        self.assertEqual(len(cards), 3 * MK.N_REC)
        for tag in ("sb", "s1", "s2"):
            names = {m["name"] for m in cards if m["name"].startswith(tag + "_")}
            self.assertEqual(names,
                             {f"{tag}_{k:05d}" for k in MK.REC_CLOCKS})
        for m in cards:
            self.assertIn(" FIND ", m["spice"])
            self.assertIn(" AT=", m["spice"])

    def test_measurement_windows_lie_inside_the_transient(self):
        self.assertLess(MK.T_REC1, MK.T_END)
        args = REQUEST["analysis"]["args"].split()
        self.assertAlmostEqual(float(args[1]), MK.T_END, places=12)
        for m in REQUEST["measurements"]:
            for form in ("cycle_mean", "energy", "crossings"):
                w = m.get(form)
                if not w:
                    continue
                self.assertGreaterEqual(w.get("from", 0.0), 0.0)
                self.assertLessEqual(w.get("to", MK.T_REC1), MK.T_END)

    def test_cycle_mean_spans_the_whole_record(self):
        for m in REQUEST["measurements"]:
            if "cycle_mean" in m:
                self.assertEqual(m["cycle_mean"]["cycles"], MK.N_REC)
                self.assertEqual(m["cycle_mean"]["align"], "v(clk)-0.5*v(vdda)")

    def test_save_vectors_covers_the_signals_klt_does_not_auto_save(self):
        # klt adds vectors named by expr / spice / crossings.signal itself, but
        # not those named by cycle_mean or energy -- a `save` card that dropped
        # them would make those measurements error out on the fleet.
        saved = {v.lower() for v in REQUEST["options"]["save_vectors"]}
        for m in REQUEST["measurements"]:
            if "cycle_mean" in m:
                self.assertIn(m["cycle_mean"]["signal"].lower(), saved)
                for tok in ("v(clk)", "v(vdda)"):
                    self.assertIn(tok, saved)
            if "energy" in m:
                self.assertIn(m["energy"]["voltage"].lower(), saved)
                self.assertIn(f"i({m['energy']['source']})".lower(), saved)

    def test_batch_submission_waits_for_capacity(self):
        self.assertEqual(REQUEST["backend"], "batch")
        self.assertGreaterEqual(REQUEST["batch"]["capacity_wait_s"], 600)

    def test_deck_includes_exactly_the_three_prescribed_netlists(self):
        deck = (HERE / MK.DECK).read_text()
        includes = [ln.split('"')[1] for ln in deck.splitlines()
                    if ln.startswith(".include")]
        self.assertEqual(includes, ["../../design/ota/ota_fd.spice",
                                    "../../design/modulator/comparator/comparator.spice",
                                    "../../design/modulator/modulator.spice"])
        # design/modulator/README.md: modulator.spice already defines both.
        self.assertNotIn("design/integrator/integrator.spice", deck)
        self.assertNotIn("design/clkgen/clkgen.spice", deck)

    def test_record_length_is_stated_in_clocks_and_output_samples(self):
        rec = RUNNER.build_record(
            {"corners": RUNNER.extract(report())[0], "samples_index": {}},
            "open_pdks test", {"open_pdks_revision": "deadbeef"},
            {"engine_version": "46"}, WINDOW_S)
        rl = rec["record_length"]
        self.assertEqual(rl["modulator_clocks"], MK.N_REC)
        self.assertEqual(rl["output_samples_at_osr_128"], MK.N_REC / 128)
        self.assertEqual(rl["settling_clocks_discarded"], MK.N_SETTLE)
        self.assertIn("Cost", rl["chosen_because"])
        self.assertFalse(rec["sndr"]["computed"])
        self.assertIn("subset", rec["corner_set"]["subset_statement"])
        self.assertIn("simulated", rec["result_kind"])


class RecordBindings(unittest.TestCase):
    def test_record_binds_the_committed_deck_and_request(self):
        # record.json's first binding is the deck and request it simulated:
        # both are the bench's own files and cannot change without a re-run,
        # so a mismatch can only mean a post-run edit (a comment-only one broke
        # this once and was indistinguishable from real drift). The three
        # design-netlist hashes are deliberately NOT tested here: a mismatch
        # there is the record's own signal that it describes an older netlist
        # (#106), not an error.
        import hashlib
        record = json.loads((HERE / "record.json").read_text())
        self.assertEqual(
            record["deck_sha256"],
            hashlib.sha256((HERE / MK.DECK).read_bytes()).hexdigest())
        self.assertEqual(
            record["request_sha256"],
            hashlib.sha256((HERE / "request.json").read_bytes()).hexdigest())


LONG_WINDOW_S = MK.N_REC_LONG * MK.TPER


def long_report(n_anchors=len(ANCHOR_IDS)):
    """A klt sim report shaped like the long bench's: the same scalars, but
    per-clock sample cards on the long bench's clock range (64..4159)."""
    def corner(cid):
        proc, _, temp = cid.split("/")
        vdda = float(cid.split("vdda=")[1].split("V")[0])
        vals = scalars()
        vals["e_vdda"] = vals["p_vdda"] * LONG_WINDOW_S
        vals["phi1_edges"] = MK.N_REC_LONG
        vals["bs_edges"] = 2000
        ms = [{"name": k, "value": v, "status": "pass"} for k, v in vals.items()]
        ms.append({"name": "bs_edges", "value": vals["bs_edges"], "status": "pass",
                   "crossings": {"times": [1e-6, 2e-6], "edges": ["rise", "fall"],
                                 "truncated": False}})
        for i, k in enumerate(MK.LONG.REC_CLOCKS):
            ms.append({"name": f"sb_{k:05d}", "value": vdda if i % 2 else 0.0})
            ms.append({"name": f"s1_{k:05d}", "value": 0.1 * ((i % 7) - 3)})
            ms.append({"name": f"s2_{k:05d}", "value": 0.05 * ((i % 5) - 2)})
        return {"corner_id": cid, "process": proc, "supply_v": {"vdda": vdda},
                "temperature_c": float(temp.rstrip("C")), "status": "pass",
                "measurements": ms, "diagnostics": []}
    return {"corners": [corner(cid) for cid in ANCHOR_IDS[:n_anchors]],
            "environment": {"engine_version": "46"}, "measurements": []}


class LongBenchRequest(unittest.TestCase):
    """The long-record bench (DR-001 corrigendum 01, issue #290): its own
    deck/request/samples/record files and its own fleet budget, with the
    committed 1024-clock bench untouched. What is pinned here:

    - the committed request_long.json / modulator_tran_long.cir are what
      make_request.py --long generates;
    - the long deck is electrically identical to the short deck (only the
      coherence comment line moves), so the length change cannot silently
      change the circuit;
    - the tone is coherent and lands on an exact integer bin (12 over 4096
      clocks = 15 kHz = bin 12 at 1250 Hz);
    - the fleet budget fits the whole-job ceiling (3300 s x 1 unit + 120
      <= 3600 s), one corner per job, and the submit waits for capacity;
    - the admission gates are parameterized: a complete 4096-clock report
      passes them, and a short one is refused;
    - the long record carries the corrigendum's identity, not the short
      bench's."""

    def test_committed_long_request_matches_make_request(self):
        self.assertEqual(MK.build_request(long=True),
                         json.loads((HERE / MK.REQUEST_LONG).read_text()))

    def test_committed_long_deck_matches_make_request(self):
        self.assertEqual(MK.build_deck(long=True),
                         (HERE / MK.DECK_LONG).read_text())

    def test_long_deck_is_electrically_identical_to_the_short_deck(self):
        short = (HERE / MK.DECK).read_text().splitlines()
        long_deck = (HERE / MK.DECK_LONG).read_text().splitlines()
        self.assertEqual(len(short), len(long_deck))
        diff = [(a, b) for a, b in zip(short, long_deck) if a != b]
        self.assertEqual(len(diff), 1, "only the coherence comment may differ")
        self.assertIn("12 whole cycles over the 4096 recorded", diff[0][1])
        self.assertTrue(all(b.lstrip().startswith("*") for _, b in diff),
                        "the differing line must be a comment")

    def test_tone_is_coherent_and_lands_on_an_exact_integer_bin(self):
        fin = MK.CYCLES_LONG * MK.FS_HZ / MK.N_REC_LONG
        self.assertEqual(fin, 15000.0)
        bin_bw = MK.FS_HZ / MK.N_REC_LONG
        self.assertEqual(bin_bw, 1250.0)
        self.assertEqual(fin / bin_bw, 12.0)
        self.assertEqual(MK.CYCLES_LONG, 12)

    def test_one_corner_per_job_inside_the_whole_job_ceiling(self):
        req = json.loads((HERE / MK.REQUEST_LONG).read_text())
        batch = req["batch"]
        timeout = req["options"]["timeout_s"]
        self.assertEqual(batch["max_units_per_job"], 1)
        self.assertEqual(timeout, 3300)
        self.assertLessEqual(timeout * batch["max_units_per_job"] + 120, 3600)
        self.assertEqual(batch["capacity_wait_s"], 600)

    def test_long_files_are_distinct_from_the_committed_bench(self):
        # the long bench must never overwrite the committed evidence chain
        self.assertNotEqual(MK.DECK, MK.DECK_LONG)
        self.assertNotEqual(MK.REQUEST, MK.REQUEST_LONG)
        self.assertNotEqual(MK.SAMPLES_DIR, MK.LONG.SAMPLES_DIR)
        self.assertNotEqual(MK.RECORD_NAME, MK.LONG.RECORD_NAME)
        self.assertNotEqual(MK.TAG, MK.LONG.TAG)

    def test_complete_4096_clock_run_passes_every_gate(self):
        corners, samples = RUNNER.extract(long_report(),
                                          rec_clocks=MK.LONG.REC_CLOCKS)
        self.assertTrue(RUNNER.anchors_complete(corners))
        self.assertTrue(RUNNER.scalars_present(corners))
        self.assertTrue(RUNNER.samples_present(samples, n_rec=MK.N_REC_LONG))
        self.assertTrue(RUNNER.clock_ran_at_fs(corners, n_rec=MK.N_REC_LONG))
        self.assertTrue(RUNNER.power_routes_agree(corners, LONG_WINDOW_S))

    def test_short_sample_set_is_refused_at_the_long_length(self):
        _, samples = RUNNER.extract(long_report(), rec_clocks=MK.LONG.REC_CLOCKS)
        for cid in samples:
            for key in ("bs_v", "o1d_v", "o2d_v"):
                samples[cid][key] = samples[cid][key][:-1]
        ok, err = refuses(RUNNER.samples_present, samples, n_rec=MK.N_REC_LONG)
        self.assertFalse(ok)
        self.assertIn("want 4096", err)

    def test_long_record_carries_the_corrigendum_identity(self):
        RUNNER.B = MK.LONG
        self.addCleanup(setattr, RUNNER, "B", MK)
        self.assertEqual(RUNNER.samples_dir_for(MK.LONG.RECORD_NAME),
                         HERE / MK.LONG.SAMPLES_DIR)
        corners, _ = RUNNER.extract(long_report(), rec_clocks=MK.LONG.REC_CLOCKS)
        rec = RUNNER.build_record(
            {"corners": corners, "samples_index": {}},
            "open_pdks test", {"open_pdks_revision": "deadbeef"},
            {"engine_version": "46"}, LONG_WINDOW_S)
        self.assertEqual(rec["record_length"]["modulator_clocks"], 4096)
        self.assertEqual(rec["record_length"]["output_samples_at_osr_128"], 32.0)
        self.assertIn("corrigendum 01", rec["fixture"])
        self.assertIn("corrigendum 01", rec["evidence_source"])
        self.assertIn("4096", rec["record_length"]["chosen_because"])
        self.assertFalse(rec["sndr"]["computed"])
        self.assertIn("BOTH sides", rec["sndr"]["why_not"])


class LongRecordBindings(unittest.TestCase):
    """record-long.json binds itself to the long bench's own deck/request and
    samples, exactly as record.json does for the short bench -- and the
    committed short record stays the 1024-clock record it has always been."""

    def test_long_record_binds_the_long_deck_and_request(self):
        import hashlib
        record = json.loads((HERE / MK.LONG.RECORD_NAME).read_text())
        self.assertEqual(record["record_length"]["modulator_clocks"],
                         MK.N_REC_LONG)
        self.assertEqual(
            record["deck_sha256"],
            hashlib.sha256((HERE / MK.DECK_LONG).read_bytes()).hexdigest())
        self.assertEqual(
            record["request_sha256"],
            hashlib.sha256((HERE / MK.REQUEST_LONG).read_bytes()).hexdigest())

    def test_long_samples_are_committed_under_samples_long(self):
        import hashlib
        record = json.loads((HERE / MK.LONG.RECORD_NAME).read_text())
        self.assertEqual(len(record["samples"]), len(MK.ANCHOR_POINTS))
        for cid, s in record["samples"].items():
            self.assertTrue(s["file"].startswith(MK.LONG.SAMPLES_DIR + "/"),
                            s["file"])
            self.assertEqual(s["n_clocks"], MK.N_REC_LONG)
            path = HERE / s["file"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             s["sha256"])

    def test_committed_short_record_is_untouched(self):
        record = json.loads((HERE / "record.json").read_text())
        self.assertEqual(record["record_length"]["modulator_clocks"], 1024)
        self.assertIn("samples/", record["samples"][
            "tt/vclk=1.800_vdda=1.800V/27C"]["file"])


if __name__ == "__main__":
    unittest.main()
