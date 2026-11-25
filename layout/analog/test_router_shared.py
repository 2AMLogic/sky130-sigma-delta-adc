"""Tests for the Router methods #201 unified into layout/analog/layout_common.py:
`connect_met1` (one shared body, per-class `COL_BUDGET`, docstring and richer
exhaust message in the single copy), the net-aware `add_shape` (the base
bookkeeping the integrator's `summing_node_report()` reads), and `finish_trunks`
(one shared body that skips zero-height trunks -- measured in #201 to be
unreachable in the OTA cell and to fire once, on an OTA escape's column, in the
integrator). Run:
python3 -I -m unittest discover -s layout/analog -p 'test_*.py'

No klt, no PDK, no EDA tool, no network, no fixtures: pure geometry over the
shared `Router`, exactly like test_router_core.py. The generators themselves
are not imported; the two subclasses here carry only what the shared body
reads (`columns`, the met1 bucket index in `add_met1`) plus the per-class
`COL_BUDGET` the cells set (24 / 48), so a future divergence between the two
cells has to come back through the shared body or break these pins.
"""
import unittest

from layout_common import (Anchor, BUCKET_NM, L_MET2, L_VIA, Rect, RouteError,
                           Router, VIA_UM, WIRE_UM, nm, snap)


class CellRouter(Router):
    """Minimal stand-in for a cell generator's Router: the shared
    `connect_met1` proposal (`columns`) and the met1 bucket index
    (`met1_free`) are subclass responsibilities in the generators too --
    `columns` genuinely differs (unrestricted vs boundary-clipped), so the
    tests use one fixed proposal for both budgets."""

    def columns(self, x0, x1, pref):
        k0 = int((self.x_lo - 2.0) // 0.5)
        k1 = int((self.x_hi + 2.0) // 0.5) + 1
        cands = [snap(k * 0.5) for k in range(k0, k1 + 1)]
        cands.sort(key=lambda c: (0 if x0 - 1e-9 <= c <= x1 + 1e-9 else 1,
                                  abs(c - pref), c))
        return [c for c in cands if nm(c) not in self.used_cols]

    def add_met1(self, net, rects):
        for rect in rects:
            for b in range(rect.y0 // BUCKET_NM, rect.y1 // BUCKET_NM + 1):
                self.met1_index[b].append((net, rect))


class Budget24(CellRouter):
    COL_BUDGET = 24


class Budget48(CellRouter):
    COL_BUDGET = 48


def wide_anchor(y=3.0):
    # Spanning the whole search window: every candidate column is inside the
    # strap, so the shared search takes the first free one with no met1 jog.
    return Anchor("n", "blk", "met1", y, 1.0, 39.0, (), jog_um=0.0)


class SharedBodyTests(unittest.TestCase):
    """The three methods are defined once, on the shared base, and no
    per-budget subclass carries its own copy."""

    def test_methods_live_on_the_base(self):
        for name in ("connect_met1", "finish_trunks", "add_shape"):
            self.assertIn(name, Router.__dict__, name)

    def test_budget_subclasses_share_one_connect_met1(self):
        self.assertIs(Budget24.connect_met1, Budget48.connect_met1)

    def test_shared_docstring_survived_the_unification(self):
        self.assertIn("met2 trunk", Router.connect_met1.__doc__)


class AddShapeTaggingTests(unittest.TestCase):
    """The base add_shape books a net-tagged copy into `by_net` only when a
    net is named; the shared finish_trunks always names one, so every cell's
    met2 trunks are tagged.  Only the integrator's add_met1/add_met overrides
    name nets on met1/met3/met4."""

    def test_untagged_shape_enters_shapes_only(self):
        r = CellRouter(0.0, 10.0, 0.0, 10.0)
        rect = Rect.centred(5.0, 5.0, 0.5, 0.2)
        r.add_shape(L_MET2, rect)
        self.assertEqual(r.shapes, [(L_MET2, rect)])
        self.assertEqual(dict(r.by_net), {})

    def test_tagged_shape_enters_both(self):
        r = CellRouter(0.0, 10.0, 0.0, 10.0)
        rect = Rect.centred(5.0, 5.0, 0.5, 0.2)
        r.add_shape(L_MET2, rect, "n")
        self.assertEqual(r.shapes, [(L_MET2, rect)])
        self.assertEqual(r.by_net[("n", L_MET2)], [rect])

    def test_same_net_and_layer_accumulates(self):
        r = CellRouter(0.0, 10.0, 0.0, 10.0)
        a = Rect.centred(2.0, 5.0, 0.5, 0.2)
        b = Rect.centred(8.0, 5.0, 0.5, 0.2)
        r.add_shape(L_MET2, a, "n")
        r.add_shape(L_MET2, b, "n")
        self.assertEqual(r.by_net[("n", L_MET2)], [a, b])


class FinishTrunksTests(unittest.TestCase):
    """One shared finish: a trunk whose column collected a single via y
    (zero height) emits nothing; a real span emits one net-tagged met2 vwire
    and grows the net's wire length."""

    def met2_shapes(self, r):
        return [rect for layer, rect in r.shapes if layer == L_MET2]

    def test_single_via_y_emits_nothing(self):
        # The measured degenerate case (#201): one via y on the column, no
        # spine -- a WIRE_UM x WIRE_UM met2 square would be pure DRC surface.
        r = CellRouter(0.0, 10.0, 0.0, 10.0)
        r.trunk_y[("n", 5.0)].append(2.0)
        r.finish_trunks()
        self.assertEqual(self.met2_shapes(r), [])
        self.assertNotIn("n", r.wire_um)

    def test_two_vias_at_one_y_still_zero_height(self):
        r = CellRouter(0.0, 10.0, 0.0, 10.0)
        r.trunk_y[("n", 5.0)].extend([2.0, 2.0])
        r.finish_trunks()
        self.assertEqual(self.met2_shapes(r), [])

    def test_real_span_emits_one_tagged_vwire(self):
        r = CellRouter(0.0, 10.0, 0.0, 10.0)
        r.trunk_y[("n", 5.0)].extend([4.0, 1.0])
        r.finish_trunks()
        got = self.met2_shapes(r)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].as_um(), Rect.vwire(5.0, 1.0, 4.0, WIRE_UM).as_um())
        self.assertEqual(r.by_net[("n", L_MET2)], [got[0]])
        self.assertAlmostEqual(r.wire_um["n"], 3.0, places=9)

    def test_zero_height_trunk_dropped_normal_trunk_kept(self):
        # Both cases in one dict, sorted order: the skip is per trunk, not
        # per router.
        r = CellRouter(0.0, 10.0, 0.0, 10.0)
        r.trunk_y[("n", 5.0)].append(2.0)
        r.trunk_y[("m", 6.0)].extend([7.0, 3.0])
        r.finish_trunks()
        got = self.met2_shapes(r)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].as_um(),
                         Rect.vwire(6.0, 3.0, 7.0, WIRE_UM).as_um())
        self.assertEqual(sorted(r.by_net), [("m", L_MET2)])

    def test_base_router_tags_trunks_without_subclass_help(self):
        # The unification's measured case (#239): the shared finish names the
        # net itself, so a bare Router -- no subclass override at all --
        # still lands its met2 trunks in by_net.
        r = Router(0.0, 50.0, 0.0, 50.0)
        r.trunk_y[("vout", 10.0)].extend([2.0, 8.0])
        r.finish_trunks()
        self.assertEqual(sorted(r.by_net), [("vout", L_MET2)])
        self.assertEqual(len(self.met2_shapes(r)), 1)


class ConnectMet1BudgetTests(unittest.TestCase):
    """Each subclass resolves its own COL_BUDGET; the richer exhaust message
    carries the taken/free counts; an explicit argument overrides the class.

    The setup is the honest kind of 24-vs-48 difference: `columns()` only
    proposes free columns and rejection is monotone in each candidate's own
    jog metal, so the two budgets can only diverge when the failing prefix
    and the succeeding tail pick *different pads*.  The anchor straps two li1
    pads (28.0 near, 38.0 far); candidates nearer than the 33.0 pad tie climb
    at 28.0, whose vwire a blocker crosses, and candidates beyond it climb at
    38.0, clear of every blocker.  Rank 25+ is the first pad-38 candidate, so
    a 24-column budget dies on every jog track while a 48-column budget
    lands."""

    SPAN = (20.1, 20.4)          # strictly between two 0.5-grid columns
    WINDOW = (22.5, 42.0)        # x_lo keeps candidates one-sided (right)

    def padded_router(self, cls):
        r = cls(*self.WINDOW, 0.0, 10.0)
        a = Anchor("n", "blk", "met1", 3.0, self.SPAN[0], self.SPAN[1], (),
                   pad_xs=(28.0, 38.0), jog_um=1.0)
        cols = r.columns(a.x0, a.x1, a.xmid)
        # One-sided proposal: every candidate sits right of the strap, rank
        # order is plain ascending column, and the pad tie at 33.0 splits the
        # ranks: 20.5..33.0 climb at 28.0, 33.5.. climb at 38.0.
        self.assertEqual(cols[0], 20.5)
        self.assertEqual(len([c for c in cols if c <= 33.0]), 26)
        self.assertEqual(cols[26], 33.5)
        # Track-1 flank: every one-sided hwire reaches x=20.67, so a flank
        # at 20.55 rejects the whole track ...
        flank = Rect.um(20.55, 2.86, 25.0, 3.14)
        # ... and the pad-28 vwire (x 27.83..28.17) crosses this band on both
        # jog tracks, while the pad-38 vwire at x 37.83..38.17 clears it.
        band = Rect.um(27.5, 3.19, 28.5, 3.31)
        for b in (flank, band):
            for bucket in range(b.y0 // BUCKET_NM, b.y1 // BUCKET_NM + 1):
                r.met1_index[bucket].append(("blocker", b))
        return r, a

    def test_budget24_exhausts_with_counts_in_message(self):
        r, a = self.padded_router(Budget24)
        with self.assertRaises(RouteError) as ctx:
            r.connect_met1(a)
        msg = str(ctx.exception)
        self.assertIn("no free met2 column for n at blk y=3.0", msg)
        self.assertIn("0 columns already taken", msg)
        self.assertIn("24 free within the budget", msg)

    def test_budget48_lands_on_a_pad38_column(self):
        r, a = self.padded_router(Budget48)
        col, y = r.connect_met1(a)
        # Rank 27 (33.5) is the first pad-38 candidate; its vwire clears the
        # band, so the landing is one jog up, at the second track y=2.5.
        self.assertEqual((col, y), (33.5, 2.5))
        self.assertIn(nm(col), r.used_cols)
        vias = [rect.as_um() for layer, rect in r.shapes if layer == L_VIA]
        self.assertEqual(vias, [Rect.centred(col, y, VIA_UM, VIA_UM).as_um()])
        self.assertEqual(r.trunk_y[("n", col)], [y])

    def test_explicit_argument_overrides_the_class_attribute(self):
        r, a = self.padded_router(Budget24)
        self.assertEqual(r.connect_met1(a, col_budget=48), (33.5, 2.5))
        r48, a48 = self.padded_router(Budget48)
        with self.assertRaises(RouteError):
            r48.connect_met1(a48, col_budget=24)

    def test_in_span_landing_takes_first_free_column(self):
        # No blockers: the anchor spans its columns, so the search takes the
        # nearest one on the strap's own y with no jog metal at all -- and
        # books via, trunk and column for it.
        r = Budget48(0.0, 40.0, 0.0, 10.0)
        a = wide_anchor()
        first_free = r.columns(a.x0, a.x1, a.xmid)[0]
        col, y = r.connect_met1(a)
        self.assertEqual((col, y), (first_free, a.y))
        self.assertNotIn(a.net, r.wire_um)  # no jog: no met1 wire length
        vias = [rect.as_um() for layer, rect in r.shapes if layer == L_VIA]
        self.assertEqual(vias, [Rect.centred(col, y, VIA_UM, VIA_UM).as_um()])
        self.assertEqual(r.trunk_y[("n", col)], [y])


if __name__ == "__main__":
    unittest.main()
