"""Tests for the integrator's matched-pair summing routing (issue #284). Run:
python3 -I -m unittest discover -s layout/analog -p 'test_*.py'

The 50-device regeneration let the first-come router drift the `sump`/`sumn`
pair to 9.30 % asymmetry (120.695 / 133.075 um) where the 44-device cell had
asserted 2.97 %. Two pieces of gen_integrator.py now exist so that cannot
come back silently, and both are pinned here without klt, a PDK or fixtures:

- `summing_node_report()` gates the figure: past
  `SUMMING_ASYMMETRY_MAX_PCT` (3 %, the old cell's measured figure) it
  raises, quoting both lengths, in either direction (abs()).
- `match_mirrored_anchors()` guards the assumption the allocator's
  correspondence rests on: every p-side summing anchor needs an n-side
  mirror partner within `SUMMING_MIRROR_TOL_UM` on the same plane, and a
  residual beyond that is a floorplan regression (raised), not a routing
  choice to absorb; unpaired leftovers raise too.
- `route_summing_pair()`'s degraded-pair fallback keeps the run when the
  n-side pinned commit fails: the greedy connector's own (col, y) is what
  lands in `placed`, the monotonicity key and the evidence log -- a tuple
  or a stale pinned column here loses the run with a TypeError two frames
  away and writes a column the stream does not carry into
  route-summary.json.

Both are pure geometry over synthetic `Anchor`/`Rect` inputs, exactly like
test_router_core.py / test_router_shared.py; the generator module is loaded
by path the way test_drc_guard.py does it.
"""
import unittest

from layout_common import (Anchor, L_MET1, L_MET2, Rect, RouteError, nm,
                           snap)
from layout_test_common import load_generator

GI = load_generator("integrator/gen_integrator.py")


class FakeRouter:
    """Just what `summing_node_report` reads: the by-net shape index and the
    matched-pair log the allocator leaves behind."""

    def __init__(self, by_net=None, pair_log=None):
        self.by_net = by_net or {}
        self.pair_log = pair_log


def anchor(net, block, y, half=0.5):
    return Anchor(net, block, "met1", y, y - half, y + half, ())


def lengths(sump, sumn):
    return {"sump": {"wire_length_um": sump},
            "sumn": {"wire_length_um": sumn},
            "vcm": {"wire_length_um": 1954.73}}


class SummingAsymmetryBoundTests(unittest.TestCase):
    """The gate behind the README's 'symmetric to 0.85 %' claim."""

    def test_within_bound_passes_and_records_the_figure(self):
        router = FakeRouter(pair_log={"greedy_fallbacks": 0, "pairs": []})
        report = GI.summing_node_report(router, lengths(121.465, 122.505))
        self.assertEqual(report["asymmetry_pct"], 0.85)
        self.assertEqual(report["asymmetry_bound_pct"],
                         GI.SUMMING_ASYMMETRY_MAX_PCT)
        self.assertEqual(report["wire_length_um"],
                         {"sump": 121.465, "sumn": 122.505})

    def test_exact_bound_passes(self):
        # 3.0 % of 100.0: the comparison is strict (abs() > bound), so the
        # bound itself is still a legal cell.
        report = GI.summing_node_report(FakeRouter(), lengths(97.0, 100.0))
        self.assertEqual(report["asymmetry_pct"], 3.0)

    def test_past_bound_raises_in_either_direction(self):
        for sump, sumn in ((120.695, 133.075), (133.075, 120.695)):
            with self.subTest(sump=sump, sumn=sumn):
                with self.assertRaises(RouteError) as ctx:
                    GI.summing_node_report(FakeRouter(), lengths(sump, sumn))
                self.assertIn("exceeds the 3.0% bound", str(ctx.exception))
                self.assertIn(f"sump {sump} um", str(ctx.exception))
                self.assertIn(f"sumn {sumn} um", str(ctx.exception))


class MirrorMatchTests(unittest.TestCase):
    """The mirrored-placement assumption the allocator's correspondence
    rests on, and the two ways a floorplan can break it."""

    def test_pairs_mirrored_anchors_and_is_greedy_nearest(self):
        axis = 143.43
        p = [anchor("sump", "sti_p", axis - 18.5),
             anchor("sump", "str_p", axis - 31.0),
             anchor("sump", "ci_p", axis - 48.0)]
        n = [anchor("sumn", "str_n", axis + 31.0),
             anchor("sumn", "ci_n", axis + 48.0),
             anchor("sumn", "sti_n", axis + 18.5)]
        pairs = GI.match_mirrored_anchors(p, n, axis)
        self.assertEqual(len(pairs), 3)
        by_p_block = {pa.block: na.block for pa, na in pairs}
        self.assertEqual(by_p_block,
                         {"sti_p": "sti_n", "str_p": "str_n",
                          "ci_p": "ci_n"})

    def test_no_partner_within_tolerance_raises(self):
        axis = 143.43
        p = [anchor("sump", "sti_p", axis - 18.5)]
        n = [anchor("sumn", "sti_n", axis + 18.5 + GI.SUMMING_MIRROR_TOL_UM
                    + 0.01)]
        with self.assertRaises(RouteError) as ctx:
            GI.match_mirrored_anchors(p, n, axis)
        self.assertIn("no mirror partner within", str(ctx.exception))

    def test_plane_mismatch_leaves_the_anchor_unpaired_and_raises(self):
        axis = 143.43
        p = [Anchor("sump", "ci_p", "cap4", axis - 48.0, 1.0, 2.0, ())]
        n = [Anchor("sumn", "ci_n", "met1", axis + 48.0, 1.0, 2.0, ())]
        with self.assertRaises(RouteError) as ctx:
            GI.match_mirrored_anchors(p, n, axis)
        self.assertIn("left anchors unpaired", str(ctx.exception))

    def test_perfect_mirror_takes_zero_error(self):
        axis = 100.0
        pairs = GI.match_mirrored_anchors([anchor("sump", "s", axis - 5.0)],
                                          [anchor("sumn", "s", axis + 5.0)],
                                          axis)
        self.assertEqual(pairs[0][0].block, pairs[0][1].block)


class ClockProximityShapeTests(unittest.TestCase):
    """beside/over stay scoped to the summing nets against CLOCK_NETS, on
    and across the four router layers -- the list the README discloses."""

    def test_crossing_across_layers_is_listed_with_its_layers(self):
        rect_sum = Rect.um(100.0, 160.0, 100.34, 162.0)
        rect_clk = Rect.um(100.0, 161.0, 103.0, 161.34)
        router = FakeRouter(by_net={("sump", L_MET1): [rect_sum],
                                    ("phi2", L_MET2): [rect_clk]})
        report = GI.summing_node_report(router, lengths(121.465, 122.505))
        self.assertEqual(report["beside_count"], 0)
        self.assertEqual(report["crossings_count"], 1)
        cross = report["crossings"][0]
        self.assertEqual((cross["summing_net"], cross["clock_net"]),
                         ("sump", "phi2"))
        self.assertEqual(cross["summing_layer"], "68/20")
        self.assertEqual(cross["clock_layer"], "69/20")

    def test_same_layer_gap_beyond_clearance_is_not_beside(self):
        rect_sum = Rect.um(100.0, 160.0, 100.34, 162.0)
        rect_clk = Rect.um(102.0, 160.0, 105.0, 162.0)
        router = FakeRouter(by_net={("sump", L_MET1): [rect_sum],
                                    ("phi2", L_MET1): [rect_clk]})
        report = GI.summing_node_report(router, lengths(121.465, 122.505))
        self.assertEqual(report["beside_count"], 0)


class DegradedPairFallbackRouter:
    """A synthetic router whose n-side pinned commit always fails.

    `connect_pinned` commits the p side (reserving the column) and raises on
    the n side, exactly the state the degraded-pair fallback exists for: the
    pinned proposal never became geometry, so the greedy connector answers
    with its own column, `GREEDY_DX` off the anchor, and its own y.
    """

    GREEDY_DX = -3.0

    def __init__(self):
        self.used_cols = set()
        self.pair_log = None
        self.pinned = []
        self.greedy_cols = []

    def neighbours_free(self, _col):
        return True

    def _greedy(self, a):
        col = snap(a.xmid + self.GREEDY_DX)
        self.used_cols.add(nm(col))
        self.greedy_cols.append(col)
        return col, a.y + 2.0

    def connect_pinned(self, a, col):
        self.pinned.append((a.net, col))
        if a.net == "sumn":
            raise RouteError("forced: the n-side pinned commit fails")
        self.used_cols.add(nm(col))
        return col, a.y

    def connect_met1(self, a):
        return self._greedy(a)

    def connect_cap(self, a):
        return self._greedy(a)


class DegradedPairFallbackTests(unittest.TestCase):
    """The degraded pair records what the stream actually carries.

    `connect_cap`/`connect_met1` answer (col, y); the fallback must unpack
    both and record the column the greedy call reserved -- indexing `[1]`
    off it (the old defect) hands `finish_net` a tuple, whose first spine
    statement `(ya + yb) / 2` raises TypeError two frames away from the
    branch whose own comment says "rather than lose the run"; recording the
    failed pinned column instead writes one the stream does not carry into
    route-summary.json.  Both planes that reach the fallback are exercised.
    """

    AXIS_Y = 100.0
    PAIRS = (("a_p", "a_n", 50.0, 20.0), ("b_p", "b_n", 52.0, 30.0))

    def _groups(self, plane):
        groups = {"sump": [], "sumn": []}
        for pblk, nblk, xmid, py in self.PAIRS:
            groups["sump"].append(
                Anchor("sump", pblk, plane, py, xmid - 0.5, xmid + 0.5, ()))
            groups["sumn"].append(
                Anchor("sumn", nblk, plane, 2 * self.AXIS_Y - py,
                       xmid - 0.5, xmid + 0.5, ()))
        return groups

    def test_degraded_pair_records_the_greedy_column_and_a_float_y(self):
        for plane in ("met1", "cap4"):
            with self.subTest(plane=plane):
                router = DegradedPairFallbackRouter()
                placed = GI.route_summing_pair(router, self._groups(plane),
                                               self.AXIS_Y, {})
                greedy = router.greedy_cols
                self.assertEqual(
                    greedy, [snap(50.0 + DegradedPairFallbackRouter.GREEDY_DX),
                             snap(52.0 + DegradedPairFallbackRouter.GREEDY_DX)])
                # The n side carries the greedy call's columns -- never the
                # pinned proposals that failed (50.5 / 52.5).
                self.assertEqual([t[0] for t in placed["sumn"]], greedy)
                for failed in (snap(50.5), snap(52.5)):
                    self.assertNotIn(failed, [t[0] for t in placed["sumn"]])
                # Ys are floats: finish_net feeds them to route_spine, whose
                # first statement is (ya + yb) / 2.
                for _col, y, _a in placed["sumn"]:
                    self.assertIsInstance(y, float)
                for (_ca, ya, _), (_cb, yb, _) in zip(placed["sumn"],
                                                      placed["sumn"][1:]):
                    self.assertIsInstance((ya + yb) / 2, float)
                # The p side is untouched: it committed pinned, as planned.
                self.assertEqual([t[0] for t in placed["sump"]],
                                 [snap(50.0), snap(52.0)])
                # The evidence log is honest: every pair degraded, and the
                # n column / displacement are the ones actually used.
                self.assertEqual(router.pair_log["greedy_fallbacks"], 2)
                for entry, gcol, xmid in zip(router.pair_log["pairs"], greedy,
                                             (50.0, 52.0)):
                    self.assertTrue(entry["degraded"])
                    self.assertEqual(entry["columns_um"]["sumn"], gcol)
                    self.assertEqual(entry["displacement_um"]["sumn"],
                                     round(abs(gcol - xmid), 3))


if __name__ == "__main__":
    unittest.main()
