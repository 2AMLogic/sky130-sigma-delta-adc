"""Tests for the analog generators' shared klt block runner (issue #335). Run:
python3 -I -m unittest discover -s layout/analog -p 'test_*.py'

The runner lives once, in layout/analog/layout_common.py (issue #335 moved it
in from the OTA generator); the integrator's `gen_geometries`/`gen_rings`
were paste-copies of the same run/parse/raise/write sequence, and #225 had
already done the same for the DRC-verdict guard. No klt, no PDK, no
subprocess: `run` is replaced by a recorder, so the command lines, the call
order, the report files and the error contract are pinned without a
toolchain -- the same comparison the issue's premise evidence ran against
the real integrator inputs with a stand-in for klt.

What is pinned here:

- The argv is exactly what both generators built separately before #335:
  `klt gen <generator>`, `--params` with the params JSON-encoded under
  sorted keys, the pdk args passed through in place, then the explicit cell
  name, `<id>.gds` as the output and `--format json` -- run with
  `cwd=out_dir`.
- The call order is the caller's list order, not sorted here: the OTA
  passes its floorplan order and the integrator sorts ids before calling,
  so the runner must not re-order. The cell name is used verbatim too (the
  OTA names blocks explicitly, the integrator uppercases the id) while the
  report and GDS file names come from the block id.
- Each reply's stdout bytes are written verbatim to `<id>.json` -- not
  re-serialised -- and the return dict is keyed by block id with the parsed
  report.
- A `{"error": ...}` reply raises RuntimeError naming the block, and when
  it is the first reply no report file is written at all.
- Both generators carry the runner: each re-exports the one layout_common
  definition (same object, no re-pasted copy), so the call sites resolve
  and divergence cannot come back through an import.
"""
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import layout_common
from layout_test_common import load_generator


INTEGRATOR = load_generator("integrator/gen_integrator.py")
OTA_FD = load_generator("ota_fd/gen_ota_fd.py")
RUNNER = layout_common.gen_blocks

PDK_ARGS = ["--pdk", "sky130A", "--pdk-root", "/nonexistent-pdk"]


class Recorder:
    """A `run` stand-in that records each (argv, cwd) and replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[tuple[list[str], pathlib.Path | None]] = []

    def __call__(self, cmd, cwd=None, check=True):
        self.calls.append((list(cmd), cwd))
        reply = mock.Mock()
        reply.stdout = self.replies.pop(0)
        return reply


class BothGeneratorsCarryTheRunnerTests(unittest.TestCase):

    def test_generators_reexport_the_shared_object(self):
        for name, mod in (("gen_integrator", INTEGRATOR),
                          ("gen_ota_fd", OTA_FD)):
            with self.subTest(generator=name):
                self.assertIs(mod.gen_blocks, RUNNER)


class GenBlocksTests(unittest.TestCase):

    def setUp(self):
        self.out_dir = pathlib.Path(tempfile.mkdtemp(prefix="genblocks-"))
        self.addCleanup(shutil.rmtree, self.out_dir, ignore_errors=True)

    def report_stdout(self, block_id):
        # Not json.dumps()'s default formatting, so the file-write test can
        # tell a verbatim copy of stdout from a re-serialised report.
        return ('{\n  "id": "%s",\n  "bbox_um": {"x0": 0, "x1": 1, '
                '"y0": 0, "y1": 1}\n}' % block_id)

    def test_one_command_per_block_in_list_order(self):
        blocks = [("zz", "mos_array", "ZZ", {"w_um": 1.0, "l_um": 0.15}),
                  ("aa", "cap_array", "AA", {"units": 4})]
        rec = Recorder([self.report_stdout(b[0]) for b in blocks])
        with mock.patch.object(layout_common, "run", rec):
            RUNNER(["klt"], PDK_ARGS, self.out_dir, blocks)
        self.assertEqual(
            [cmd for cmd, _cwd in rec.calls],
            [["klt", "gen", "mos_array",
              "--params", json.dumps({"l_um": 0.15, "w_um": 1.0})]
             + PDK_ARGS
             + ["--cell-name", "ZZ", "-o", "zz.gds", "--format", "json"],
             ["klt", "gen", "cap_array",
              "--params", json.dumps({"units": 4})]
             + PDK_ARGS
             + ["--cell-name", "AA", "-o", "aa.gds", "--format", "json"]])
        for _cmd, cwd in rec.calls:
            self.assertIs(cwd, self.out_dir)

    def test_params_are_json_encoded_with_sorted_keys(self):
        params = {"cols": 2, "w_um": 4.0, "dummy": 0, "flavor": "nfet"}
        rec = Recorder([self.report_stdout("x")])
        with mock.patch.object(layout_common, "run", rec):
            RUNNER(["klt"], PDK_ARGS, self.out_dir,
                   [("x", "mos_array", "X", params)])
        (cmd, _cwd), = rec.calls
        self.assertEqual(cmd[cmd.index("--params") + 1],
                         json.dumps(params, sort_keys=True))

    def test_reports_returned_keyed_by_id_and_stdout_filed_verbatim(self):
        blocks = [("bb", "mos_array", "BB", {"w_um": 1.0}),
                  ("aa", "guard_ring", "AA", {"width": 2.0})]
        rec = Recorder([self.report_stdout(b[0]) for b in blocks])
        with mock.patch.object(layout_common, "run", rec):
            reports = RUNNER(["klt"], PDK_ARGS, self.out_dir, blocks)
        self.assertEqual(sorted(reports), ["aa", "bb"])
        self.assertEqual(reports["bb"]["id"], "bb")
        self.assertEqual(reports["aa"]["id"], "aa")
        for block_id, _g, _c, _p in blocks:
            self.assertEqual((self.out_dir / f"{block_id}.json").read_text(),
                             self.report_stdout(block_id))

    def test_error_reply_raises_naming_the_block_and_writes_no_file(self):
        rec = Recorder(['{"error": "bad params"}'])
        with mock.patch.object(layout_common, "run", rec):
            with self.assertRaises(RuntimeError) as ctx:
                RUNNER(["klt"], PDK_ARGS, self.out_dir,
                       [("mb1", "mos_array", "MB1", {"w_um": 1.0})])
        self.assertIn("klt gen mb1", str(ctx.exception))
        self.assertIn("bad params", str(ctx.exception))
        self.assertEqual(list(self.out_dir.iterdir()), [],
                         "a failed first block must leave no report file")


if __name__ == "__main__":
    unittest.main()
