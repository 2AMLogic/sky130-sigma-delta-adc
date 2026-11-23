"""Tests for the digital-partition P&R runner's PDK-pin refusal. Run:
python3 -I -m unittest discover -s layout/digital -p 'test_*.py'

No klt, no openroad, no PDK: `subprocess.run` is patched to hand the runner a
synthetic `klt place-and-route` report, and the runner's REPO / HERE are
redirected into a temporary tree holding a copy of `sim/pdk.json`, so the
committed GDS/DEF/netlist are never read or written.

What is pinned here:

- The gate refuses (exit 2) when the report's `provenance.pdk.version` differs
  from `sim/pdk.json`'s `sources_stamp`, and when it is absent in any of the
  shapes a real klt report takes: no `provenance`, `provenance.pdk` null, a
  `pdk` block with no `version`. Absence is an unverified PDK, not a pass --
  this is the property the pre-#158 expression could not have, because the
  default it supplied to `.get()` *was* the value it compared against.
- A matching stamp admits the copy path (artifacts land next to the request)
  and `--check` reports GDS drift as exit 3 without overwriting anything.
- The copy path additionally commits the response envelope itself
  (pnr-decimator.response.json, issue #333): the producing checkout's
  absolute paths are rewritten to repo-relative, and `--check` never writes
  it -- the GDS is the byte-for-byte receipt, the response is not
  reproducible (timing fields), so it is recorded on copy runs only.
- The reason the old gate was inert, replayed against the three committed JSON
  documents in this directory: none of them carries a top-level `pdk.version`,
  so a top-level read can only ever fall through to its default. Each now takes
  a defined branch instead.
- The docstring's exit-2 sentence names the field the code actually reads, so
  the advertised contract and the implementation cannot drift apart again.
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]


def load_runner():
    """Load run_pnr.py by path: 'layout/digital' is not an importable name."""
    spec = importlib.util.spec_from_file_location("run_pnr_under_test", HERE / "run_pnr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUNNER = load_runner()
PIN = json.loads((REPO / "sim/pdk.json").read_text())
STAMP = PIN["sources_stamp"]
WRONG = "open_pdks 0000000000000000000000000000000000000000"

# The three committed JSON documents the issue's replay table feeds the gate.
COMMITTED = {
    "sta-decimator.report.json": STAMP,      # provenance.pdk.version == the pin
    "drc-decimator.report.json": None,       # provenance.pdk is null
    "pnr_request.json": None,                # the request, echoed: no provenance at all
}


def report(stamp=STAMP, *, provenance=True, pdk=True, artifacts=("a.gds", "a.def", "a.v")):
    """A minimal `klt place-and-route --format json` report, in klt's shape."""
    rep = {key: name for key, name in zip(RUNNER.OUT, artifacts) if key != "sdf_path"}
    # post_route_spef/post_route_sdf (issue #162): the SDF path rides inside
    # `spef_sta`, not at the top level the other three artifacts use.
    rep["spef_sta"] = {"spef_path": "a.spef", "sdf_path": "a.sdf"}
    if provenance:
        block = {"klt_version": "0.9.2", "klayout_version": "0.30.13"}
        if pdk:
            block["pdk"] = ({"name": PIN["variant"], "source": "--pdk-root flag"}
                            if stamp is None else
                            {"name": PIN["variant"], "source": "--pdk-root flag", "version": stamp})
        else:
            block["pdk"] = None
        rep["provenance"] = block
    return rep


@contextlib.contextmanager
def fake_flow(rep, *, returncode=0, argv=("run_pnr.py",), committed=None, fresh=b"GDS"):
    """Redirect the runner at a throwaway repo tree and feed it `rep`.

    `committed` maps an OUT file name to the bytes already sitting next to the
    request (as the committed artifacts do); absent names are left absent.
    Yields (tmp_repo, tmp_here, captured_stderr).
    """
    with tempfile.TemporaryDirectory() as td:
        repo = pathlib.Path(td).resolve()
        here = repo / "layout/digital"
        here.mkdir(parents=True)
        (repo / "sim").mkdir()
        (repo / "sim/pdk.json").write_text(json.dumps(PIN))
        (here / "pnr_request.json").write_text("{}")
        for name, blob in (committed or {}).items():
            (here / name).write_bytes(blob)
        # The report's artifact paths are repo-relative, as klt emits them.
        for name in rep.values():
            if isinstance(name, str) and name.endswith((".gds", ".def", ".v", ".sdf", ".spef")):
                (repo / name).write_bytes(fresh if name.endswith(".gds") else b"X")
        for name in (rep.get("spef_sta") or {}).values():
            if isinstance(name, str):
                (repo / name).write_bytes(fresh if name.endswith(".sdf") else b"S")
        out = mock.Mock(returncode=returncode, stdout=json.dumps(rep), stderr="")
        err = io.StringIO()
        with mock.patch.object(RUNNER, "REPO", repo), \
             mock.patch.object(RUNNER, "HERE", here), \
             mock.patch.object(RUNNER.subprocess, "run", return_value=out), \
             mock.patch.object(sys, "argv", list(argv)), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(err):
            yield repo, here, err


class PdkPinRefusal(unittest.TestCase):
    """The refusal the pre-#158 expression could never reach."""

    def test_mismatched_stamp_refuses_and_copies_nothing(self):
        with fake_flow(report(WRONG), committed={"decimator.gds": b"OLD"}) as (_, here, err):
            rc = RUNNER.main()
            self.assertEqual(rc, 2)
            self.assertIn(WRONG, err.getvalue())
            self.assertIn(STAMP, err.getvalue())      # names observed *and* pinned, as the peers do
            self.assertEqual((here / "decimator.gds").read_bytes(), b"OLD")

    def test_absent_stamp_refuses_in_every_real_report_shape(self):
        for label, rep in (
            ("no provenance block", report(provenance=False)),
            ("provenance.pdk is null", report(pdk=False)),
            ("pdk block with no version", report(None)),
        ):
            with self.subTest(shape=label):
                with fake_flow(rep, committed={"decimator.gds": b"OLD"}) as (_, here, err):
                    rc = RUNNER.main()
                    self.assertEqual(rc, 2, f"{label} must refuse, not pass")
                    self.assertIn("REFUSE", err.getvalue())
                    self.assertEqual((here / "decimator.gds").read_bytes(), b"OLD")

    def test_matching_stamp_runs_the_copy_path(self):
        with fake_flow(report()) as (_, here, _err):
            rc = RUNNER.main()
            self.assertEqual(rc, 0)
            self.assertEqual((here / "decimator.gds").read_bytes(), b"GDS")
            for name in RUNNER.OUT.values():
                self.assertTrue((here / name).exists(), f"{name} was not copied")

    def test_check_mode_reports_gds_drift_without_overwriting(self):
        with fake_flow(report(), argv=("run_pnr.py", "--check"),
                       committed={"decimator.gds": b"OLD"}) as (_, here, _err):
            rc = RUNNER.main()
            self.assertEqual(rc, 3)
            self.assertEqual((here / "decimator.gds").read_bytes(), b"OLD")

    def test_check_mode_clean_when_gds_matches(self):
        with fake_flow(report(), argv=("run_pnr.py", "--check"),
                       committed={"decimator.gds": b"GDS"}) as (_, here, _err):
            rc = RUNNER.main()
            self.assertEqual(rc, 0)
            self.assertEqual((here / "decimator.gds").read_bytes(), b"GDS")

    def test_absent_sdf_returns_1_naming_the_request_key(self):
        """A report that reached the gate but wrote no SDF cannot feed the fv
        request (issue #162): the runner says so instead of copying three of
        four artifacts and exiting 0."""
        rep = report()
        rep["spef_sta"] = {"spef_path": "a.spef", "sdf_path": None}
        with fake_flow(rep) as (_, here, err):
            rc = RUNNER.main()
            self.assertEqual(rc, 1)
            self.assertIn("post_route_sdf", err.getvalue())
            self.assertFalse((here / "decimator.sdf").exists())

    def test_failed_flow_returns_1_before_the_gate(self):
        with fake_flow(report(WRONG), returncode=1) as (_, _here, _err):
            rc = RUNNER.main()
            self.assertEqual(rc, 1)


class ResponseEnvelope(unittest.TestCase):
    """The response envelope the copy path commits beside the artifacts (#333)."""

    def test_copy_mode_writes_a_scrubbed_response(self):
        rep = report()
        rep["engine"] = {"argv": ["openroad", "-pdk-root", "/opt/pdk"]}
        with fake_flow(rep) as (repo, here, _err):
            # Absolute paths from the producing checkout, in the shapes klt
            # emits: an artifact path under the repo root, and a bare root.
            rep["layout_path"] = str(repo / "build" / "decimator.gds")
            rep["provenance"]["cwd"] = str(repo)
            out = mock.Mock(returncode=0, stdout=json.dumps(rep), stderr="")
            # fake_flow already installed its patched subprocess.run; re-patch
            # to serve the absolute-path-bearing report.
            with mock.patch.object(RUNNER.subprocess, "run", return_value=out):
                rc = RUNNER.main()
            self.assertEqual(rc, 0)
            text = (here / RUNNER.RESPONSE).read_text()
            self.assertNotIn(str(repo), text)          # free of the producer's paths
            saved = json.loads(text)
            self.assertEqual(saved["layout_path"], "build/decimator.gds")
            self.assertEqual(saved["provenance"]["cwd"], ".")
            self.assertEqual(saved["engine"]["argv"], ["openroad", "-pdk-root", "/opt/pdk"])
            self.assertEqual(saved["provenance"]["pdk"]["version"], STAMP)  # stamp survives

    def test_check_mode_never_writes_the_response(self):
        with fake_flow(report(), argv=("run_pnr.py", "--check"),
                       committed={"decimator.gds": b"GDS"}) as (_repo, here, _err):
            rc = RUNNER.main()
            self.assertEqual(rc, 0)
            self.assertFalse((here / RUNNER.RESPONSE).exists())

    def test_scrub_paths_descends_and_passes_scalars_through(self):
        scrub = RUNNER.scrub_paths
        root = "/x/issue-1"
        self.assertEqual(scrub({"a": [root + "/l/d.gds", 3, None, True], "b": root}, root),
                         {"a": ["l/d.gds", 3, None, True], "b": "."})
        self.assertEqual(scrub("no path here", root), "no path here")
        self.assertEqual(scrub("/other/root/f.gds", "/other/root"), "f.gds")  # root arg honoured


class CommittedReportShapes(unittest.TestCase):
    """Replay the gate against the real JSON in this directory (issue #158 step 5)."""

    def test_each_committed_document_takes_a_defined_branch(self):
        for name, expected in COMMITTED.items():
            with self.subTest(document=name):
                rep = json.loads((HERE / name).read_text())
                self.assertEqual(RUNNER.report_pdk_stamp(rep), expected)
                # Defined branch: equal to the pin, or a refusal. Never a silent pass.
                if expected is None:
                    self.assertNotEqual(RUNNER.report_pdk_stamp(rep), STAMP)

    def test_no_committed_klt_report_has_a_top_level_pdk_version(self):
        """Why the old top-level read was inert: the key is not there to find."""
        for name in COMMITTED:
            with self.subTest(document=name):
                rep = json.loads((HERE / name).read_text())
                self.assertIsNone((rep.get("pdk") or {}).get("version"))

    def test_sta_report_pdk_stamp_is_the_pin_verbatim(self):
        """klt's provenance stamp and sim/pdk.json's sources_stamp are the same string."""
        rep = json.loads((HERE / "sta-decimator.report.json").read_text())
        self.assertEqual(rep["provenance"]["pdk"]["version"], STAMP)


class DocstringContract(unittest.TestCase):
    def test_exit_2_sentence_names_the_field_the_code_reads(self):
        doc = RUNNER.__doc__
        self.assertIn("Exit 2", doc)
        self.assertIn("provenance.pdk.version", doc)
        self.assertNotIn('rep.get("pdk"', (HERE / "run_pnr.py").read_text())


if __name__ == "__main__":
    unittest.main()
