"""Tests for the analog generators' DRC-verdict guard (issue #164). Run:
python3 -I -m unittest discover -s layout/analog -p 'test_*.py'

The guard lives once, in layout/analog/layout_common.py (issue #225 moved it
in from the two generators); the case matrix below runs over that one
definition. No klt, no PDK, no subprocess patching: the guard is a pure
function on the report dict, fed synthetic `klt drc` reports.

What is pinned here:

- `status == "clean"` with `violation_count == 0` returns; everything else
  raises, because the call site passes `check=False` to capture stdout and
  the verdict would otherwise be lost.
- `fail` with a non-empty `rule_counts` raises and the message quotes the
  rule names, mirroring the device-count raises.
- `coverage_unknown` (klt exit 4: the deck resolved no marker layer for a
  family) raises -- an unverified DRC, not a pass.
- `clean_partial` raises explicitly: neither generator passes `--rules`, so
  a partial deck scope has no business passing, and the decision is recorded
  here rather than implied by the `!=` comparison.
- The `{"error": ...}` shape (klt wrote nothing to stdout) has neither
  `status` nor `violation_count`, so both `.get()`s come back None -- the
  guard must raise, not TypeError.
- Both generators carry the guard: each re-exports the one layout_common
  definition (same object, no re-pasted copy), so the call sites resolve and
  divergence cannot come back through an import.
"""
import unittest

import layout_common
from layout_test_common import load_generator


INTEGRATOR = load_generator("integrator/gen_integrator.py")
OTA_FD = load_generator("ota_fd/gen_ota_fd.py")
GUARD = layout_common.assert_drc_clean

CLEAN = {"status": "clean", "violation_count": 0, "rule_counts": {}}


class BothGeneratorsCarryTheGuardTests(unittest.TestCase):

    def test_generators_reexport_the_shared_object(self):
        for name, mod in (("gen_integrator", INTEGRATOR),
                          ("gen_ota_fd", OTA_FD)):
            with self.subTest(generator=name):
                self.assertIs(mod.assert_drc_clean, GUARD)


class DrcGuardTests(unittest.TestCase):

    def test_clean_zero_returns(self):
        self.assertIsNone(GUARD(dict(CLEAN), "drc.report.json"))

    def test_fail_with_rule_counts_raises_and_quotes_rules(self):
        report = {"status": "fail", "violation_count": 3,
                  "rule_counts": {"met2.space.1": 2, "via.1a": 1}}
        with self.assertRaises(RuntimeError) as ctx:
            GUARD(report, "drc.report.json")
        self.assertIn("met2.space.1=2", str(ctx.exception))
        self.assertIn("via.1a=1", str(ctx.exception))

    def test_coverage_unknown_raises(self):
        report = {"status": "coverage_unknown", "violation_count": 0,
                  "rule_counts": {}}
        with self.assertRaises(RuntimeError):
            GUARD(report, "drc.report.json")

    def test_clean_partial_raises(self):
        report = {"status": "clean_partial", "violation_count": 0,
                  "rule_counts": {}}
        with self.assertRaises(RuntimeError):
            GUARD(report, "drc.report.json")

    def test_clean_with_nonzero_violations_raises(self):
        report = dict(CLEAN, violation_count=1)
        with self.assertRaises(RuntimeError):
            GUARD(report, "drc.report.json")

    def test_zero_violations_with_nonclean_status_raises(self):
        report = dict(CLEAN, status="fail")
        with self.assertRaises(RuntimeError):
            GUARD(report, "drc.report.json")

    def test_error_report_raises_not_typeerror(self):
        with self.assertRaises(RuntimeError) as ctx:
            GUARD({"error": "some stderr"}, "drc.report.json")
        self.assertIn("None", str(ctx.exception))

    def test_missing_rule_counts_reports_none(self):
        report = {"status": "fail", "violation_count": 2}
        with self.assertRaises(RuntimeError) as ctx:
            GUARD(report, "drc.report.json")
        self.assertIn("none reported", str(ctx.exception))

    def test_message_names_the_report_path(self):
        with self.assertRaises(RuntimeError) as ctx:
            GUARD(dict(CLEAN, status="fail"), "_gen/drc.report.json")
        self.assertIn("_gen/drc.report.json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
