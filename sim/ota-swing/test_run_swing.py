"""Tests for the OTA swing bench. Run:
python3 -I -m unittest discover -s sim/ota-swing -p 'test_*.py'

No fleet, no ngspice, no klt: every corner set here is hand-built. What is
pinned:

- The extraction arithmetic the record depends on: the finite-gain inversion
  (a known OTA gain round-trips through a synthetic settled vod), the
  railed-output refusal, the compression-point interpolation (crossed and
  never-crossed curves), and the interpolation at the #257 recorded swings.
- The record-admission gates (issue #94's rule for this bench): a missing
  anchor, a segment with no measurement, and a segment still moving at the
  measurement instant each refuse the record.
- The small-signal reference gate: a per-anchor disagreement with
  sim/ota-gain's record larger than the tolerance refuses the record.
- The committed deck and request are exactly what make_request.py builds,
  the request is the DR-002 anchor set with the fleet capacity wait, and the
  #257 swing reference table covers all 7 anchors with a cited sha256.
"""
import importlib.util
import io
import json
import math
import pathlib
import sys
import unittest
from contextlib import redirect_stderr

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import settling_common as sc  # noqa: E402


def load_runner():
    spec = importlib.util.spec_from_file_location("run_swing_under_test",
                                                  HERE / "run_swing.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUNNER = load_runner()
MK = sys.modules["make_request"]
SC = sys.modules["settling_common"]
REQUEST = json.loads((HERE / "request.json").read_text())

ANCHOR_KEYS = [RUNNER.anchor_key(a) for a in SC.ANCHOR_POINTS]


def segment(vod, rip=None, outp=None, outn=None, amp=0.2, direction=1):
    return {"amp_vpp": amp, "direction": direction, "vod": vod,
            "rip": vod if rip is None else rip,
            "outp": 0.9 + vod / 2 if outp is None else outp,
            "outn": 0.9 - vod / 2 if outn is None else outn}


def settled_segments(beta_scale=1.0, gain_db=56.6, rail_from=None):
    """A full two-cell segment table whose OTA gain is `gain_db` at every
    amplitude up to `rail_from` (Vpp), beyond which the output pins."""
    cells = {}
    for cell in sorted(MK.CELLS):
        beta = MK.beta(MK.CELLS[cell]["ci_pf"]) * beta_scale
        segs = {}
        for i, seg in enumerate(MK.SEGMENTS):
            pol = "u" if seg["direction"] > 0 else "d"
            target = seg["amp_vpp"] / 2.0
            if rail_from is not None and seg["amp_vpp"] > rail_from:
                vod = math.copysign(target - 0.05, seg["direction"])   # railed short
            else:
                a = 10 ** (gain_db / 20.0)
                vod = math.copysign(target * beta * a / (1 + beta * a), seg["direction"])
            segs[f"{i:02d}{pol}"] = segment(vod, amp=seg["amp_vpp"],
                                            direction=seg["direction"])
        cells[cell] = segs
    return cells


def corner(segments=None, status="pass", key=("tt", 1.8, 27)):
    return {"status": status, "corner_key": key, "runtime_s": 12.0,
            "vdda_v": key[1], "segments": segments or settled_segments(),
            "diagnostics": []}


def full_corners():
    return {f"c{i}": corner(key=k) for i, k in enumerate(ANCHOR_KEYS)}


def refuses(fn, *args, **kw):
    buf = io.StringIO()
    with redirect_stderr(buf):
        ok = fn(*args, **kw)
    return ok, buf.getvalue()


class SegGain(unittest.TestCase):
    def test_known_gain_round_trips(self):
        beta = MK.beta(2.0)
        a = 10 ** (56.6 / 20.0)
        target = 0.1
        vod = target * beta * a / (1 + beta * a)
        got, _ = RUNNER.seg_gain(segment(vod, amp=0.2, direction=1), beta)
        self.assertAlmostEqual(20 * math.log10(got), 56.6, places=6)

    def test_negative_polarity_uses_absolute_values(self):
        beta = MK.beta(3.334)
        a = 500.0
        seg = segment(-0.1 * beta * a / (1 + beta * a), amp=0.2, direction=-1)
        got, _ = RUNNER.seg_gain(seg, beta)
        self.assertAlmostEqual(got, a, places=3)

    def test_railed_output_is_refused_as_unresolvable(self):
        beta = MK.beta(2.0)
        # output pinned essentially at the target: err/target below ERR_MIN_REL
        got, vod = RUNNER.seg_gain(segment(0.1 - 1e-9, amp=0.2), beta)
        self.assertIsNone(got)
        self.assertAlmostEqual(vod, 0.1 - 1e-9)

    def test_overshot_output_is_refused(self):
        got, _ = RUNNER.seg_gain(segment(0.11, amp=0.2), MK.beta(2.0))
        self.assertIsNone(got)


class Compression(unittest.TestCase):
    def make_curve(self, drops):
        """amps/dB curve from {amp_vpp: drop_db} with a flat small-signal ref."""
        amps = sorted({MK.SMALL_REF_VPP, *drops.keys()})
        gains = [-drops.get(a, 0.0) for a in amps]
        return amps, gains

    def test_flat_curve_has_no_compression_points(self):
        amps, gains = self.make_curve({})
        self.assertIsNone(RUNNER.compression_point(amps, gains, 1.0))
        self.assertIsNone(RUNNER.compression_point(amps, gains, 3.0))

    def test_crossing_is_interpolated_not_snapped(self):
        amps, gains = self.make_curve({2.2: 1.6, 2.4: 3.2})
        cp1 = RUNNER.compression_point(amps, gains, 1.0)
        # amps are [0.2, 2.2, 2.4]; 1 dB sits on the 0.2->2.2 span
        self.assertAlmostEqual(cp1, 0.2 + 2.0 * (1.0 / 1.6), places=9)
        cp3 = RUNNER.compression_point(amps, gains, 3.0)
        self.assertAlmostEqual(cp3, 2.2 + 0.2 * ((3.0 - 1.6) / 1.6), places=9)

    def test_first_crossing_wins_on_a_nonmonotone_curve(self):
        amps, gains = self.make_curve({1.0: 1.5, 1.2: 0.2, 1.4: 2.5})
        self.assertAlmostEqual(RUNNER.compression_point(amps, gains, 1.0),
                               0.2 + 0.8 * (1 / 1.5), places=9)

    def test_gain_at_recorded_swing_interpolates_and_extrapolation_refuses(self):
        amps = [0.2, 0.4, 0.6]
        gains = [56.0, 55.0, 54.0]
        self.assertAlmostEqual(RUNNER.gain_at(amps, gains, 0.5), 54.5, places=9)
        self.assertAlmostEqual(RUNNER.gain_at(amps, gains, 0.2), 56.0, places=9)
        self.assertIsNone(RUNNER.gain_at(amps, gains, 0.61))
        self.assertIsNone(RUNNER.gain_at(amps, gains, 0.1))


class DeriveCell(unittest.TestCase):
    def test_flat_gain_curve_derives_cleanly(self):
        d = RUNNER.derive_cell(settled_segments(), "a")
        self.assertAlmostEqual(d["small_signal_gain_db"], 56.6, places=4)
        self.assertAlmostEqual(d["compression"]["cp1_vpp"], None)
        self.assertEqual(len(d["gain_vs_swing"]), len(MK.SWEEP_VPP) + 1)
        self.assertLessEqual(d["compression"]["worst_drift_v"], 1e-12)

    def test_railed_tail_marks_compression_early(self):
        d = RUNNER.derive_cell(settled_segments(rail_from=2.2), "b")
        # beyond 2.2 Vpp the synthetic output pins 50 mV short: gain collapses
        self.assertLess(d["compression"]["cp3_vpp"], 2.4)
        self.assertIsNotNone(d["compression"]["cp3_vpp"])

    def test_compression_point_carries_single_ended_range(self):
        d = RUNNER.derive_cell(settled_segments(rail_from=2.2), "a")
        some = next(iter(d["at_compression_points"].values()))
        lo, hi = some["single_ended_range_v"]
        self.assertLess(lo, 0.9)
        self.assertGreater(hi, 0.9)

    def test_drifting_segment_is_reported(self):
        segs = settled_segments()
        s = segs["a"]["26u"]            # 2.8 Vpp, up (even index)
        s["rip"] = s["vod"] + 0.02
        d = RUNNER.derive_cell(segs, "a")
        self.assertGreater(d["compression"]["worst_drift_v"], 0.01)


class RecordGates(unittest.TestCase):
    def test_complete_run_passes_every_gate(self):
        corners = full_corners()
        self.assertTrue(RUNNER.anchors_complete(corners))
        self.assertTrue(RUNNER.segments_present(corners))
        self.assertTrue(RUNNER.segments_settled(corners))

    def test_missing_anchor_refuses(self):
        corners = full_corners()
        del corners["c3"]
        ok, err = refuses(RUNNER.anchors_complete, corners)
        self.assertFalse(ok)
        self.assertIn("REFUSE", err)
        self.assertIn("6 of 7", err)

    def test_unexpected_anchor_refuses(self):
        corners = full_corners()
        corners["c99"] = corner(key=("tt", 1.8, 125))       # not an anchor
        self.assertFalse(RUNNER.anchors_complete(corners))

    def test_missing_segment_measurement_refuses(self):
        corners = full_corners()
        corners["c0"]["segments"]["a"]["04u"]["outn"] = None
        ok, err = refuses(RUNNER.segments_present, corners)
        self.assertFalse(ok)
        self.assertIn("missing a measurement", err)

    def test_short_segment_table_refuses(self):
        corners = full_corners()
        del corners["c1"]["segments"]["b"]["13d"]
        ok, err = refuses(RUNNER.segments_present, corners)
        self.assertFalse(ok)
        self.assertIn("segments", err)

    def test_drifting_segment_refuses(self):
        corners = full_corners()
        s = corners["c2"]["segments"]["a"]["26u"]
        s["rip"] = s["vod"] + 0.01
        ok, err = refuses(RUNNER.segments_settled, corners)
        self.assertFalse(ok)
        self.assertIn("still moving", err)
        self.assertIn("mV", err)
    def test_settled_below_the_limit_passes(self):
        corners = full_corners()
        for cid in corners:
            for cell in corners[cid]["segments"]:
                for name, s in corners[cid]["segments"][cell].items():
                    s["rip"] = s["vod"] + 1e-6
        self.assertTrue(RUNNER.segments_settled(corners))


class GainReferenceGate(unittest.TestCase):
    def build_xcheck(self, corner_gain_db, record_gain_db=56.6):
        corners = full_corners()
        derived = {cid: {c: RUNNER.derive_cell(settled_segments(gain_db=corner_gain_db), c)
                         for c in sorted(MK.CELLS)}
                   for cid in corners}
        xc = RUNNER.gain_xcheck(corners, derived)
        for cell in xc:
            for cid in xc[cell]:
                xc[cell][cid]["ota_gain_record_db"] = record_gain_db
                xc[cell][cid]["delta_db"] = corner_gain_db - record_gain_db
        return corners, xc

    def test_matching_reference_passes(self):
        _, xc = self.build_xcheck(56.6)
        self.assertTrue(RUNNER.gain_reference_matches(None, xc))

    def test_disagreeing_reference_refuses(self):
        _, xc = self.build_xcheck(53.0)   # 3.6 dB off the record
        ok, err = refuses(RUNNER.gain_reference_matches, None, xc)
        self.assertFalse(ok)
        self.assertIn("sim/ota-gain", err)

    def test_missing_record_entry_refuses(self):
        # an empty xcheck means nothing was verified against the record
        ok, err = refuses(RUNNER.gain_reference_matches, None, {})
        self.assertFalse(ok)
        self.assertIn("REFUSE", err)


class SwingReference(unittest.TestCase):
    def test_reference_table_covers_exactly_the_anchor_set(self):
        want = {RUNNER.anchor_key(a) for a in SC.ANCHOR_POINTS}
        self.assertEqual(set(RUNNER.C0P3_SWINGS.keys()), want)

    def test_reference_block_cites_the_record_hash(self):
        blk = RUNNER.swing_reference_block()
        self.assertEqual(blk["file_sha256"], RUNNER.C0P3_RECORD_SHA256)
        self.assertEqual(len(blk["per_anchor_vpp"]), len(SC.ANCHOR_POINTS))
        for v in blk["per_anchor_vpp"].values():
            self.assertGreater(v["o1_swing_pp"], 2.2)
            self.assertLess(v["o1_swing_pp"], 2.6)

    def test_recorded_swings_lie_inside_the_sweep_grid(self):
        # the bench must be able to interpolate at every recorded swing
        top = max(v["o1_swing_pp"] for v in RUNNER.C0P3_SWINGS.values())
        self.assertLessEqual(top, MK.SWEEP_VPP[-1])
        o2 = max(v["o2_swing_pp"] for v in RUNNER.C0P3_SWINGS.values())
        self.assertGreaterEqual(min(v["o2_swing_pp"] for v in RUNNER.C0P3_SWINGS.values()),
                                MK.SWEEP_VPP[0])
        self.assertLessEqual(o2, MK.SWEEP_VPP[-1])


class RequestShape(unittest.TestCase):
    def test_request_is_the_anchor_set_tran_on_the_batch_backend(self):
        self.assertEqual(REQUEST["backend"], "batch")
        self.assertEqual(REQUEST["analysis"]["kind"], "tran")
        units = REQUEST["corners"]["units"]
        self.assertEqual(len(units), 7)
        want = sorted((p, v, t) for p, v, t in SC.ANCHOR_POINTS)
        self.assertEqual(sorted((u["process"], u["supply_v"]["vdda"],
                                 u["temperature_c"]) for u in units), want)
        self.assertEqual(REQUEST["batch"]["capacity_wait_s"], sc.CAPACITY_WAIT_S)
        self.assertIn("measureprec", REQUEST["options"]["ngspice_init"][1])

    def test_committed_deck_and_request_match_the_builder(self):
        self.assertEqual((HERE / "ota_swing.cir").read_text(), MK.build_deck())
        self.assertEqual(json.loads((HERE / "request.json").read_text()),
                         MK.build_request())

    def test_amplitude_grid_is_small_signal_then_beyond_2_6_vpp(self):
        self.assertEqual(MK.AMPS_VPP[0], MK.SMALL_REF_VPP)
        self.assertLess(MK.AMPS_VPP[0], 0.3)
        self.assertGreater(MK.SWEEP_VPP[-1], 2.6)

    def test_every_segment_has_its_measurement_cards(self):
        names = {m["name"] for m in REQUEST["measurements"]}
        for i, seg in enumerate(MK.SEGMENTS):
            pol = "u" if seg["direction"] > 0 else "d"
            for cell in sorted(MK.CELLS):
                for kind in ("vod", "outp", "outn", "rip"):
                    self.assertIn(MK.seg_name(cell, i, pol, kind), names)
        self.assertEqual(len(names), 1 + len(MK.SEGMENTS) * len(MK.CELLS) * 4)

    def test_small_signal_cards_carry_a_loop_closed_limit(self):
        by_name = {m["name"]: m for m in REQUEST["measurements"]}
        self.assertIn("limits", by_name[MK.seg_name("a", 0, "u", "vod")])
        self.assertIn("limits", by_name[MK.seg_name("b", 1, "d", "vod")])

    def test_segment_times_do_not_overlap_and_end_inside_t_end(self):
        prev_end = MK.T_PRE
        for seg in MK.SEGMENTS:
            self.assertGreaterEqual(seg["reset_start"], prev_end)
            self.assertGreater(seg["measure_t"], seg["steps"][-1])
            self.assertGreater(seg["end_t"], seg["measure_t"])
            self.assertLess(seg["ripple_t"], seg["measure_t"])
            prev_end = seg["end_t"]
        self.assertLessEqual(prev_end, MK.T_END + 1e-15)

    def test_each_cell_sees_its_own_bias_source(self):
        deck = (HERE / "ota_swing.cir").read_text()
        for c in sorted(MK.CELLS):
            self.assertIn(f"Ibias{c} vdda ibias{c} 5u", deck)
        self.assertNotIn("Ibias vdda ibias 5u", deck)


if __name__ == "__main__":
    unittest.main()
