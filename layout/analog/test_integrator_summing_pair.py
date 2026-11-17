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

Both are pure geometry over synthetic `Anchor`/`Rect` inputs, exactly like
test_router_core.py / test_router_shared.py; the generator module is loaded
by path the way test_drc_guard.py does it.
"""
import importlib.util
import pathlib
import unittest

from layout_common import Anchor, L_MET1, L_MET2, Rect, RouteError

HERE = pathlib.Path(__file__).resolve().parent


def load_generator(rel: str):
    """Load a generator module by path: 'layout/analog/...' is not importable."""
    spec = importlib.util.spec_from_file_location(
        rel.replace("/", "_") + "_under_test", HERE / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


if __name__ == "__main__":
    unittest.main()
