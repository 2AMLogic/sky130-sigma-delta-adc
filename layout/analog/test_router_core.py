"""Tests for the shared geometry/router core in layout/analog/layout_common.py
(issue #226). Run:
python3 -I -m unittest discover -s layout/analog -p 'test_*.py'

No klt, no PDK, no EDA tool, no network, no fixtures: everything here is pure
integer-nanometre geometry over `Rect` and the `Router` bookkeeping both
analog cells inherit (and #121/#122 will). This is the other half of #191's
coverage: its suite pinned the parsers, this one pins the half that decides
whether a generated stream is DRC-clean.

What is pinned here:

- `Rect`: the four constructors produce the expected nm rectangles, including
  swapped-argument ordering (`um`/`hwire`/`vwire` sort, `centred` mirrors);
  `clashes` is false at exactly `clearance` and true one nanometre inside;
  edge-touching is not a clash at clearance 0; `as_um` round-trips.
- `Router._ok`: no clash is ok; a clash on different nets is not; a same-net
  true overlap merges into one polygon and is ok; a same-net near miss
  (inside the gap, not overlapping) is NOT -- the notch it leaves breaches
  spacing exactly like a two-net violation.
- `met1_free`: the bucketed met1 index finds a clash whose placed rect and
  query rect live in different `BUCKET_NM` y buckets (the query's own bucket
  does not contain the placed rect, so the gap-widened bucket range is what
  finds it), rejects another-net clashes and same-net near misses, and
  accepts same-net true overlaps.
- `add_trunk_via`: a second via1 on the same (net, column) within `WIRE_UM`
  of an existing *via1* adds no shape (the two cuts would merge into an
  oversized via) but still appends to `trunk_y`; one at exactly `WIRE_UM`
  adds a real via1. Suppression is keyed per (net, column), and the
  comparison is against `via1_y`, not `trunk_y` -- the mutation check in the
  PR flips exactly that source and this ladder goes red.
- `reserve_column`/`neighbours_free` (with and without `neighbours=True`),
  `tracks` (distance order from `pref`, y as tiebreak, window plus the
  two-track margin) and `jog_tracks` (`jog_um <= 0` collapses to `[a.y]`).
- `route_spine`: takes the preferred free track nearest the two endpoints'
  mid-y, skips a track occupied by another net, and raises `RouteError` when
  no candidate is free.

The base `Router` deliberately leaves `add_met1` to the cell generators
(#201 owns where it belongs), so the tests drive a minimal subclass
defining exactly the bucket indexing `met1_free` reads -- mirroring the
generators' override. The generators themselves are not imported.
"""
import unittest

import layout_common
from layout_common import (Anchor, BUCKET_NM, L_VIA, MET1_SPACE_UM, Rect,
                           RouteError, Router, VIA_UM, WIRE_UM, nm)

GAP = nm(MET1_SPACE_UM)  # the met1 spacing every router search uses


class AddMet1Router(Router):
    """The base Router leaves add_met1 to the cell generators; the tests
    need exactly the bucket index met1_free reads, so this subclass mirrors
    the generators' override with nothing else added."""

    def add_met1(self, net, rects):
        for rect in rects:
            self.met1.append((net, rect))
            for b in range(rect.y0 // BUCKET_NM, rect.y1 // BUCKET_NM + 1):
                self.met1_index[b].append((net, rect))


def via_shapes(router):
    return [rect for layer, rect in router.shapes if layer == L_VIA]


class RectGeometryTests(unittest.TestCase):
    """The Rect constructors, the clash predicate's exact boundary, as_um."""

    def test_um_sorts_swapped_coordinates(self):
        r = Rect.um(2.0, 2.0, 0.0, 0.0)
        self.assertEqual((r.x0, r.y0, r.x1, r.y1), (0, 0, 2000, 2000))
        r = Rect.um(3.0, 0.0, 1.0, 4.0)
        self.assertEqual((r.x0, r.y0, r.x1, r.y1), (1000, 0, 3000, 4000))

    def test_centred_builds_nm_rectangle_around_point(self):
        r = Rect.centred(1.0, 2.0, 0.5, 0.2)
        self.assertEqual((r.x0, r.y0, r.x1, r.y1), (750, 1900, 1250, 2100))

    def test_hwire_and_vwire_sort_endpoints(self):
        h = Rect.hwire(3.0, 1.0, 2.0, WIRE_UM)
        self.assertEqual((h.x0, h.y0, h.x1, h.y1), (830, 1830, 3170, 2170))
        v = Rect.vwire(1.0, 4.0, 2.0, WIRE_UM)
        self.assertEqual((v.x0, v.y0, v.x1, v.y1), (830, 1830, 1170, 4170))

    def test_clashes_boundary_is_exact(self):
        # Exactly `clearance` away is NOT a clash (strict <); one nanometre
        # inside it is. Checked on both axes.
        a = Rect(0, 0, 1000, 1000)
        c = nm(MET1_SPACE_UM)
        self.assertFalse(a.clashes(Rect(1000 + c, 0, 2000, 1000), c))
        self.assertTrue(a.clashes(Rect(1000 + c - 1, 0, 2000, 1000), c))
        self.assertFalse(a.clashes(Rect(0, 1000 + c, 2000, 2000), c))
        self.assertTrue(a.clashes(Rect(0, 1000 + c - 1, 2000, 2000), c))

    def test_clashes_zero_clearance_overlap_and_edge_touch(self):
        a = Rect(0, 0, 1000, 1000)
        self.assertTrue(a.clashes(Rect(500, 0, 1500, 1000), 0))
        # Touching at an edge is not an overlap: `_ok`'s same-net rule
        # depends on this distinction.
        self.assertFalse(a.clashes(Rect(1000, 0, 2000, 1000), 0))

    def test_as_um_round_trips(self):
        r = Rect.um(0.83, 1.83, 3.17, 2.17)
        rt = Rect.um(*r.as_um())
        self.assertEqual((rt.x0, rt.y0, rt.x1, rt.y1),
                         (r.x0, r.y0, r.x1, r.y1))
        self.assertEqual(Rect(250, 500, 750, 1000).as_um(),
                         [0.25, 0.5, 0.75, 1.0])


class RouterOkTests(unittest.TestCase):
    """The same-net-overlap-vs-near-miss predicate every search bottoms out
    in."""

    def test_far_apart_is_ok_regardless_of_net(self):
        r = Rect(0, 0, 1000, 1000)
        far = Rect(5000, 0, 6000, 1000)
        self.assertTrue(Router._ok(r, far, False, GAP))
        self.assertTrue(Router._ok(r, far, True, GAP))

    def test_other_net_within_spacing_is_rejected(self):
        # 100 nm edge-to-edge gap, inside the 140 nm met1 spacing.
        self.assertFalse(
            Router._ok(Rect(0, 0, 1000, 1000), Rect(1100, 0, 2000, 1000),
                       False, GAP))

    def test_same_net_true_overlap_is_ok(self):
        self.assertTrue(
            Router._ok(Rect(0, 0, 1000, 1000), Rect(500, 0, 1500, 1000),
                       True, GAP))

    def test_same_net_near_miss_is_rejected(self):
        # Within the gap but not overlapping: the notch's own edges sit
        # closer than the minimum spacing and the deck flags it like a
        # two-net violation.
        self.assertFalse(
            Router._ok(Rect(0, 0, 1000, 1000), Rect(1100, 0, 2000, 1000),
                       True, GAP))


class Met1FreeTests(unittest.TestCase):
    """met1_free over the bucketed index the generators' add_met1 builds."""

    def setUp(self):
        self.r = AddMet1Router(0.0, 10.0, 0.0, 4.0)
        self.r.add_met1("n1", [Rect(0, 0, 1000, 1000)])

    def test_other_net_inside_spacing_is_rejected(self):
        self.assertFalse(
            self.r.met1_free("n2", [Rect(1100, 0, 2000, 1000)]))

    def test_same_net_true_overlap_is_accepted(self):
        self.assertTrue(self.r.met1_free("n1", [Rect(500, 0, 1500, 1000)]))

    def test_same_net_near_miss_is_rejected(self):
        self.assertFalse(
            self.r.met1_free("n1", [Rect(1100, 0, 2000, 1000)]))

    def test_clash_found_across_bucket_boundary(self):
        # The placed rect lives entirely in y bucket 0 (0..1900 nm), the
        # query entirely in bucket 1 (2000..3000 nm): the query's own bucket
        # does not hold the placed rect, so only the gap-widened bucket
        # range finds the clash.
        r2 = AddMet1Router(0.0, 10.0, 0.0, 4.0)
        placed = Rect(0, 0, 2000, 1900)
        r2.add_met1("n1", [placed])
        query = Rect(0, 2000, 2000, 3000)
        self.assertLess(placed.y1 // BUCKET_NM, query.y0 // BUCKET_NM)
        self.assertFalse(r2.met1_free("n2", [query]))
        # One nanometre further up the clash is gone -- the boundary is the
        # met1 spacing itself, not the bucket edge.
        clear = Rect(0, 2100, 2000, 3000)
        self.assertTrue(r2.met1_free("n2", [clear]))


class TrunkViaTests(unittest.TestCase):
    """add_trunk_via's via1 merge suppression, keyed per (net, column)."""

    def setUp(self):
        self.r = AddMet1Router(0.0, 10.0, 0.0, 2.0)

    def test_via1_suppression_ladder(self):
        self.r.add_trunk_via("s", 3.0, 1.0)
        self.assertEqual(len(via_shapes(self.r)), 1)
        # 330 nm below WIRE_UM: the two cuts would merge into one oversized
        # via, so no shape -- but the trunk still grows.
        self.r.add_trunk_via("s", 3.0, 1.33)
        self.assertEqual(len(via_shapes(self.r)), 1)
        self.assertEqual(self.r.trunk_y[("s", 3.0)], [1.0, 1.33])
        self.assertEqual(self.r.via1_y[("s", 3.0)], [1.0])
        # Exactly WIRE_UM away from the existing via1: a real via1.
        self.r.add_trunk_via("s", 3.0, 1.34)
        self.assertEqual(len(via_shapes(self.r)), 2)
        self.assertEqual(self.r.trunk_y[("s", 3.0)], [1.0, 1.33, 1.34])
        self.assertEqual(self.r.via1_y[("s", 3.0)], [1.0, 1.34])

    def test_via1_shape_is_exact_cut_on_via_layer(self):
        self.r.add_trunk_via("s", 3.0, 1.0)
        layer, rect = self.r.shapes[-1]
        self.assertEqual(layer, L_VIA)
        self.assertEqual((rect.x0, rect.y0, rect.x1, rect.y1),
                         (2925, 925, 3075, 1075))

    def test_suppression_is_per_net_and_column(self):
        self.r.add_trunk_via("s", 3.0, 1.0)
        self.r.add_trunk_via("s", 4.0, 1.0)
        self.r.add_trunk_via("t", 3.0, 1.0)
        self.assertEqual(len(via_shapes(self.r)), 3)
        self.assertEqual(self.r.via1_y[("s", 3.0)], [1.0])
        self.assertEqual(self.r.via1_y[("s", 4.0)], [1.0])
        self.assertEqual(self.r.via1_y[("t", 3.0)], [1.0])


class ColumnAndTrackTests(unittest.TestCase):
    """Column reservation/neighbor checks and the two track orderings."""

    def setUp(self):
        self.r = Router(0.0, 10.0, 0.0, 2.0)

    def test_reserve_column_records_nm_integer(self):
        self.r.reserve_column(2.0)
        self.assertEqual(self.r.used_cols, {2000})

    def test_neighbours_free_true_without_neighbour_reservation(self):
        self.r.reserve_column(2.0)
        self.assertTrue(self.r.neighbours_free(2.0))
        self.assertTrue(self.r.neighbours_free(3.0))
        self.assertTrue(self.r.neighbours_free(4.0))

    def test_reserve_column_with_neighbours_blocks_both_sides(self):
        self.r.reserve_column(2.0, neighbours=True)
        self.assertEqual(self.r.used_cols, {1500, 2000, 2500})
        self.assertFalse(self.r.neighbours_free(2.0))
        self.assertFalse(self.r.neighbours_free(3.0))
        self.assertTrue(self.r.neighbours_free(4.0))

    def test_tracks_ordered_by_distance_from_pref(self):
        # Window y 0..2 um: candidates run k0..k1, i.e. -2.0..4.5 on the
        # 0.5 um pitch, nearest to pref first, y as tiebreak.
        self.assertEqual(self.r.tracks(1.0),
                         [1.0, 0.5, 1.5, 0.0, 2.0, -0.5, 2.5, -1.0, 3.0,
                          -1.5, 3.5, -2.0, 4.0, 4.5])
        # pref exactly between two tracks: the lower one wins the tiebreak.
        ts = self.r.tracks(1.25)
        self.assertEqual(ts[:2], [1.0, 1.5])

    def test_jog_tracks_nonpositive_returns_anchor_y(self):
        a = Anchor("n", "blk", "met1", 3.0, 1.0, 2.0, (), jog_um=0.0)
        self.assertEqual(self.r.jog_tracks(a), [3.0])
        a = Anchor("n", "blk", "met1", 3.0, 1.0, 2.0, (), jog_um=-0.5)
        self.assertEqual(self.r.jog_tracks(a), [3.0])

    def test_jog_tracks_positive_symmetric_sorted_by_distance(self):
        a = Anchor("n", "blk", "met1", 3.0, 1.0, 2.0, (), jog_um=1.0)
        self.assertEqual(self.r.jog_tracks(a),
                         [3.0, 2.5, 3.5, 2.0, 4.0])


class RouteSpineTests(unittest.TestCase):
    """route_spine's greedy track search and the vias it drops."""

    def setUp(self):
        self.r = AddMet1Router(0.0, 10.0, 0.0, 2.0)

    def test_takes_preferred_track_and_drops_both_vias(self):
        y = self.r.route_spine("s", 3.0, 1.0, 7.0, 2.0)
        self.assertEqual(y, 1.5)  # nearest track to (1.0 + 2.0) / 2
        self.assertEqual(len(self.r.met1), 1)
        net, rect = self.r.met1[0]
        self.assertEqual(net, "s")
        self.assertEqual((rect.x0, rect.y0, rect.x1, rect.y1),
                         (2830, 1330, 7170, 1670))
        vias = via_shapes(self.r)
        self.assertEqual(len(vias), 2)
        for col in (3.0, 7.0):
            centred = Rect.centred(col, 1.5, VIA_UM, VIA_UM)
            self.assertTrue(any((v.x0, v.y0, v.x1, v.y1)
                                == (centred.x0, centred.y0, centred.x1,
                                    centred.y1) for v in vias))
        self.assertEqual(self.r.trunk_y[("s", 3.0)], [1.5])
        self.assertEqual(self.r.trunk_y[("s", 7.0)], [1.5])

    def test_skips_track_occupied_by_another_net(self):
        self.r.add_met1("blocker", [Rect.hwire(3.0, 7.0, 1.5, WIRE_UM)])
        y = self.r.route_spine("s", 3.0, 1.0, 7.0, 2.0)
        # 1.5 is taken; 1.0 and 2.0 tie on distance and 1.0 sorts first.
        self.assertEqual(y, 1.0)
        self.assertEqual([net for net, _rect in self.r.met1],
                         ["blocker", "s"])

    def test_raises_when_no_track_is_free(self):
        # One other-net rect covering every candidate track and the whole
        # spine x range: the search must exhaust and raise, not place.
        self.r.add_met1("blocker", [Rect.um(-5.0, -3.0, 15.0, 6.0)])
        with self.assertRaises(RouteError):
            self.r.route_spine("s", 3.0, 1.0, 7.0, 2.0)
        # The blocker is still the only met1 geometry: nothing was placed.
        self.assertEqual([net for net, _rect in self.r.met1], ["blocker"])


if __name__ == "__main__":
    unittest.main()
