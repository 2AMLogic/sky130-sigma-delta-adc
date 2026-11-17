"""layout/analog/layout_common.py -- plumbing shared by the layout/analog
generators.

`gen_ota_fd.py` and `gen_integrator.py` grew paste-copies of the flow
scaffolding: `nm`/`snap`/`run`/`emit`, the klt build pin, the extracted
netlist parsers, and then the geometry vocabulary and router core themselves
(`Rect`/`RouteError`/`Anchor` and eleven `Router` methods, issue #182).  The
copies had already drifted -- the two extract parsers picked an X-line's model
token with two different predicates, so the two cells' device-count evidence
(`extract-device-count.json`) was not guaranteed to be computed the same way,
and the `_ok` same-net comment survived in only one copy.  One module,
imported by both, is the fix, and the generated-layout flow (#121 clkgen, #122
the assembled top) imports it instead of pasting a third copy.

Import pattern: each generator inserts its parent directory on `sys.path`
(the `sim/` benches do the same for `settling_common`), so
`python3 layout/analog/<cell>/gen_<cell>.py` works from any working
directory, including under `python3 -I`.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

# --- units and PDK pin (mirrors sim/pdk.json) ---------------------------------
DBU = 1000
GRID_UM = 0.005          # manufacturing grid (*.ongrid.1)
PDK_VARIANT = "sky130A"
PDK_ROOT_DEFAULT = "~/.ciel"


def nm(value_um: float) -> int:
    return int(round(value_um * DBU))


def snap(value_um: float) -> float:
    """Round onto the PDK manufacturing grid (*.ongrid.1)."""
    return round(round(value_um / GRID_UM) * GRID_UM, 6)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed (rc={result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def emit(out_dir: Path, cell_dir: Path, top_cell: str) -> None:
    """Copy a flow scratch directory's deliverables into the cell directory."""
    shutil.copyfile(out_dir / f"{top_cell}.gds", cell_dir / f"{top_cell}.gds")
    for name in ("extract-device-count.json", "drc.report.json"):
        shutil.copyfile(out_dir / name, cell_dir / name)
    shutil.copyfile(out_dir / "route.summary.json", cell_dir / "route-summary.json")


def assert_drc_clean(drc: dict, report_path: str) -> None:
    """Raise unless `klt drc` reported a clean verdict.

    `klt drc` already exits 3 on violations; the call site passes
    ``check=False`` to capture stdout, so the verdict has to be re-read here
    or it is lost.  Only an explicit ``clean`` with zero violations passes:
    ``coverage_unknown`` (exit 4 -- the deck resolved no marker layer for a
    family) is an unverified DRC, not a pass, and ``clean_partial`` arises
    only from ``--rules`` subsetting, which this generator never passes.  A
    report with no verdict at all (klt wrote nothing to stdout) has neither
    field and fails the same way.
    """
    status = drc.get("status")
    violations = drc.get("violation_count")
    if status == "clean" and violations == 0:
        return
    rules = ", ".join(f"{rule}={count}"
                      for rule, count
                      in sorted((drc.get("rule_counts") or {}).items())) \
        or "none reported"
    raise RuntimeError(
        f"klt drc status={status!r} violations={violations!r} "
        f"(expected 'clean'/0): {rules}. Report written to {report_path} "
        "before this raise; the flow aborts and nothing is emitted.")


def klt_pin(klt_cmd: list[str]) -> dict:
    """The exact klt build, recorded with the evidence.

    The stream is byte-reproducible at *this* build: a generator change
    upstream moves geometry, so `--check` is an assertion about one klt, and
    the reader has to be told which one.
    """
    r = run([*klt_cmd, "version", "--format", "json"], check=False)
    try:
        d = json.loads(r.stdout)
    except Exception:
        return {"klt": "unknown"}
    return {
        "klt": d.get("version"),
        "git_commit": d.get("git_commit"),
        "reinstall_spec": d.get("reinstall_spec"),
        "klayout": d.get("klayout_version"),
    }


class PinError(RuntimeError):
    """`--check` cannot name the klt build it must assert against."""


def recorded_pin(cell_dir: Path) -> dict:
    """The klt pin recorded in this cell's committed DRC evidence.

    `--check` asserts byte-reproducibility of the stream at one klt build
    *and* one klayout version (the stream writer is klayout's); both are
    read back from `drc.report.json` -> `provenance`
    (`klt_version` / `klt_git_commit` / `klt_reinstall_spec` /
    `klayout_version`) instead of being taken on faith from whatever `klt`
    is on PATH.  A missing or unreadable pin is a hard error: a gate that
    cannot name the build it asserts against must never pass.
    """
    path = cell_dir / "drc.report.json"
    if not path.exists():
        raise PinError(f"{path} does not exist -- no recorded klt pin")
    try:
        prov = json.loads(path.read_text()).get("provenance") or {}
    except Exception as exc:
        raise PinError(f"{path} is unreadable: {exc}") from exc
    missing = [k for k in ("klt_version", "klt_git_commit",
                           "klt_reinstall_spec", "klayout_version")
               if not prov.get(k)]
    if missing:
        raise PinError(f"{path}: provenance lacks {', '.join(missing)}")
    return {"klt": prov["klt_version"],
            "git_commit": prov["klt_git_commit"],
            "reinstall_spec": prov["klt_reinstall_spec"],
            "klayout": prov["klayout_version"]}


# --- the --check CLI driver (issue #258) ---------------------------------------
def run_cli(prog: str, cell_dir: Path, top_cell: str, flow_fn,
            pdk_root_default: str = PDK_ROOT_DEFAULT) -> int:
    """The `--check` / CLI driver every cell generator shares.

    Both `gen_ota_fd.py` and `gen_integrator.py` used to paste this ~145-line
    `main` (issue #258; #176 had consolidated the rest of the plumbing but
    left `main` "optionally parameterise" undone).  The argparse flags, the
    exit-code contract (0 pass / 1 geometry regression / 2 cannot verify),
    the klt-pin resolution and the klayout-version check are the same logic
    once, here; the "CANNOT VERIFY" branches carry the #172/#186 fixes, so a
    change to the check gate now lands in one place.

    `flow_fn` is the cell's `flow(klt_cmd, pdk_root, out_dir, ...)`.  A
    generator whose flow takes a further argument (the integrator's own
    ``cell_dir``) binds it itself, with ``functools.partial``; the driver
    calls it as ``flow_fn(klt_cmd, pdk_root, scratch, verbose=False)`` under
    ``--check`` and ``flow_fn([klt], pdk_root, cell_dir / "_gen")`` when
    generating.  ``prog`` is the message prefix (``gen_<cell>.py --check:
    ...``) and ``top_cell`` names the committed stream; the scratch prefix
    is ``<top_cell with _ as ->-check-`` (the two prefixes in service today,
    ``integrator-check-`` / ``ota-fd-check-``, follow that rule).
    """
    parser = argparse.ArgumentParser(
        description=f"Generate and verify layout/analog/{cell_dir.name}/"
                    f"{top_cell}.gds and its committed evidence; see this "
                    "directory's README.md.")
    parser.add_argument("--check", action="store_true",
                        help="regenerate into a temp dir and byte-compare the "
                             "GDS against the committed stream, evaluated at "
                             "the klt build and klayout version recorded in "
                             "drc.report.json; write nothing. Exit 0 pass, "
                             "1 geometry regression, 2 cannot verify")
    parser.add_argument("--klt", default="klt")
    parser.add_argument("--pdk-root", default=pdk_root_default)
    parser.add_argument("--keep-scratch", action="store_true",
                        help="with --check, leave the scratch directory in place")
    args = parser.parse_args()

    pdk_root = Path(args.pdk_root).expanduser()

    if args.check:
        committed = cell_dir / f"{top_cell}.gds"
        if not committed.exists():
            print(f"--check: CANNOT VERIFY -- {committed} does not exist yet",
                  file=sys.stderr)
            return 2
        try:
            pin = recorded_pin(cell_dir)
        except PinError as exc:
            print(f"{prog} --check: CANNOT VERIFY -- {exc}",
                  file=sys.stderr)
            return 2
        try:
            running = klt_pin([args.klt])
        except OSError:
            running = {"klt": "unknown"}
        if running.get("git_commit") == pin["git_commit"]:
            got_layout = running.get("klayout")
            if got_layout != pin["klayout"]:
                saw = (f"runs klayout {got_layout}, not the recorded "
                       f"{pin['klayout']}" if got_layout else
                       "does not report a klayout version, so the recorded "
                       f"one ({pin['klayout']}) cannot be checked")
                print(f"{prog} --check: CANNOT VERIFY -- host klt "
                      f"matches the recorded build {pin['klt']} but {saw} "
                      "(drc.report.json provenance); the committed bytes "
                      "were written by the recorded klayout, so a byte "
                      "difference could not be attributed. Run under the "
                      "recorded environment: "
                      f'uvx --from "{pin["reinstall_spec"]}" '
                      f'--with "klayout=={pin["klayout"]}" klt ...',
                      file=sys.stderr)
                return 2
            klt_cmd = [args.klt]
            print(f"{prog} --check: host klt matches the recorded "
                  f"build {pin['klt']} and klayout {got_layout} "
                  "(drc.report.json provenance); byte-comparing directly",
                  flush=True)
        else:
            uvx = shutil.which("uvx")
            if uvx is None:
                print(f"{prog} --check: CANNOT VERIFY -- host klt "
                      f"{running.get('klt', 'unknown')} is not the recorded "
                      f"build {pin['klt']} and uvx is not on PATH to resolve "
                      "it. Run under the recorded build: "
                      f'uvx --from "{pin["reinstall_spec"]}" '
                      f'--with "klayout=={pin["klayout"]}" klt ...',
                      file=sys.stderr)
                return 2
            klt_cmd = [uvx, "--from", pin["reinstall_spec"],
                       "--with", f"klayout=={pin['klayout']}", "klt"]
            print(f"{prog} --check: host klt "
                  f"{running.get('klt', 'unknown')} is not the recorded build "
                  f"{pin['klt']} (drc.report.json provenance); evaluating the "
                  "recorded build via uvx", flush=True)
            for attempt in range(3):
                probe = run([*klt_cmd, "version", "--format", "json"],
                            check=False)
                if probe.returncode == 0:
                    break
                if attempt < 2:
                    time.sleep(2)
            if probe.returncode != 0:
                print(f"{prog} --check: CANNOT VERIFY -- the "
                      f"recorded build did not resolve ({' '.join(klt_cmd)}): "
                      f"{probe.stderr.strip()[-300:]}", file=sys.stderr)
                return 2
            try:
                resolved = json.loads(probe.stdout)
            except Exception:
                resolved = {}
            if resolved.get("git_commit") != pin["git_commit"]:
                print(f"{prog} --check: CANNOT VERIFY -- "
                      f"uvx-resolved klt commit {resolved.get('git_commit')} "
                      f"is not the recorded pin {pin['git_commit']}",
                      file=sys.stderr)
                return 2
            got_layout = resolved.get("klayout_version")
            if got_layout != pin["klayout"]:
                print(f"{prog} --check: CANNOT VERIFY -- the "
                      "pinned resolution resolved with klayout "
                      f"{got_layout}, not the recorded {pin['klayout']}: "
                      "the uvx invocation already carries "
                      f'--with "klayout=={pin["klayout"]}", so the pin was '
                      "not honoured (a stale cached environment, or the "
                      "recorded release being yanked or unavailable for "
                      "this platform). The committed bytes were written by "
                      "the recorded klayout, so a byte difference could not "
                      "be attributed. Diagnose the resolution: "
                      f'uvx --from "{pin["reinstall_spec"]}" '
                      f'--with "klayout=={pin["klayout"]}" --refresh '
                      "klt version --format json",
                      file=sys.stderr)
                return 2
        tmp = Path(tempfile.mkdtemp(
            prefix=f"{top_cell.replace('_', '-')}-check-"))
        try:
            flow_fn(klt_cmd, pdk_root, tmp, verbose=False)
            a, b = committed.read_bytes(), (tmp / f"{top_cell}.gds").read_bytes()
            if a == b:
                print(f"{prog} --check: PASS -- regenerated GDS is "
                      f"byte-identical to {committed.name} ({len(a)} bytes; "
                      f"evaluated against recorded klt {pin['klt']})")
                return 0
            print(f"{prog} --check: FAIL -- regenerated GDS differs "
                  f"from {committed.name} under the recorded build "
                  f"{pin['klt']} (committed {len(a)} bytes, fresh {len(b)} "
                  "bytes) -- a generator or geometry regression, not a "
                  "toolchain mismatch", file=sys.stderr)
            return 1
        finally:
            if args.keep_scratch:
                print(f"scratch kept at {tmp}", file=sys.stderr)
            else:
                shutil.rmtree(tmp, ignore_errors=True)

    result = flow_fn([args.klt], pdk_root, cell_dir / "_gen")
    emit(cell_dir / "_gen", cell_dir, top_cell)
    drc = result["drc"]
    print(f"{prog}: wrote {top_cell}.gds + evidence to {cell_dir} "
          f"(drc status={drc.get('status')!r}, "
          f"violations={drc.get('violation_count')})")
    return 0


# --- extracted-netlist parsing ------------------------------------------------
def _symmetric_terminals(terminals: tuple[str, ...]) -> tuple[str, ...]:
    """Normalise a device's terminal order over the terminals it is symmetric in.

    A MOSFET's source and drain are interchangeable, and a multi-finger device
    extracts with them alternating finger by finger (half the fingers come out
    D-G-S-B, half S-G-D-B).  Without this they look like two different
    devices and never combine, so a `fingers=16` tail current source would
    count as two.  Resistors and capacitors are symmetric in both terminals.
    """
    if len(terminals) == 4:          # D G S B
        d, g, src, b = terminals
        lo, hi = sorted((d, src))
        return (lo, g, hi, b)
    if len(terminals) == 3:          # A B bulk (res)
        a, b, bulk = terminals
        lo, hi = sorted((a, b))
        return (lo, hi, bulk)
    return tuple(sorted(terminals))  # 2-terminal (cap)


def _is_model_token(t: str) -> bool:
    """Does this X-line token name the extracted device's model?

    `klt extract` writes the sky130 models as `sky130_fd_pr__<name>`, and can
    emit the bare short names (`nfet`, `pfet`) for subckt-wrapped devices, so
    both forms are accepted.  This is one shared predicate on purpose: the two
    cell generators used to carry two different ones (`"sky130_fd_pr__" in t`
    vs the prefix-or-bare test), which is drift with no behavioural difference
    on the netlists they produce today but no guarantee for the next one.
    """
    return t.startswith("sky130_fd_pr__") or t in ("nfet", "pfet")


def _logical_lines(netlist_text: str) -> list[str]:
    """Fold SPICE `+` continuation lines into the line they continue.

    The semantics are `sim/settling_common.py:join_continuations` verbatim
    (the repo's documented joiner, whose docstring names this exact failure):
    a `+` line contributes its text with the `+` stripped and one space in
    front of whatever precedes it, and a `+` line with nothing before it is
    kept as it stands. Duplicated rather than imported on purpose:
    `settling_common` is `klt sim` bench plumbing (corner grids, the
    `.partials/` cache) and the layout generators import nothing from the
    sim tree.
    """
    out, cur = [], None
    for ln in netlist_text.splitlines():
        if ln.startswith("+") and cur is not None:
            cur += " " + ln[1:].strip()
        else:
            if cur is not None:
                out.append(cur)
            cur = ln
    if cur is not None:
        out.append(cur)
    return out


def _x_devices(netlist_text: str):
    """Yield `(model, terminals)` for every X-device in an extracted netlist.

    Continuation lines are folded first (`_logical_lines`), so an X-line the
    writer wrapped at any token -- the model token included -- parses as one
    logical line. Without the fold, a wrapped model token made the X-line
    fail the model scan and the `+` line fail the `X` test, silently
    dropping the device from the counts and the nets (issue #204). Both
    extract parsers iterate this one generator, so they cannot disagree
    about which lines are devices.
    """
    for line in _logical_lines(netlist_text):
        tok = line.split()
        if not tok or not tok[0].startswith("X"):
            continue
        model = next((t for t in tok if _is_model_token(t)), None)
        if model is None:
            continue
        yield model, tuple(tok[1:tok.index(model)])


def parse_extract_devices(netlist_text: str) -> tuple[Counter, Counter]:
    """Count extracted devices by model, merging parallel same-net devices.

    One drawn transistor is one line, so a ``splits=8`` leg appears as eight
    W=10 devices where the schematic declares one ``mult=8`` device, and a
    16-finger ``mos_array`` appears as 16.  Counting therefore merges devices
    sharing a model and all terminals -- what an LVS "combine parallel
    devices" pass does -- and reports the raw counts beside the merged ones so
    the merge is visible rather than silent.
    """
    raw: Counter = Counter()
    groups: set[tuple[str, tuple[str, ...]]] = set()
    for model, terminals in _x_devices(netlist_text):
        raw[model] += 1
        groups.add((model, _symmetric_terminals(terminals)))
    combined: Counter = Counter()
    for model, _terminals in groups:
        combined[model] += 1
    return raw, combined


def extract_nets(netlist_text: str) -> list[str]:
    """Every distinct net name appearing on an extracted device terminal."""
    nets: set[str] = set()
    for _model, terminals in _x_devices(netlist_text):
        nets.update(terminals)
    return sorted(nets)


# --- shared geometry and router core (issue #182) ------------------------------
# The two cell generators carried paste-copies of these classes.  The Router
# methods below are the eleven whose bodies the two copies held identically
# (re-verified by `ast.unparse` with docstrings stripped) plus the three that
# #201 unified: `connect_met1` (the budget is per-class `COL_BUDGET`), the
# net-aware `add_shape`, and `finish_trunks` (both cells skip zero-height
# trunks; measured in #201 -- the branch never fired in the OTA cell and
# fired once in the integrator).  What genuinely differs now is only the net
# accounting (`add_met1`/`add_met`, integrator only), the boundary-clipped
# `columns` proposal (integrator only), and each cell's own `connect_*`
# methods; those stay subclass overrides in each generator.
L_MCON = (67, 44)
L_MET1 = (68, 20)
L_MET2 = (69, 20)
L_VIA = (68, 44)
MCON_UM = 0.17           # ct.1 exact size
VIA_UM = 0.15            # via.1a exact size
WIRE_UM = 0.34           # met1/met2 wire width: m1.1/m2.1 minimum is 0.14,
                         # but met1/met2 must enclose a via1 by 0.085 on
                         # two adjacent edges, so 0.15 + 2*0.085 = 0.32 is
                         # the real floor (0.34 leaves 0.16 at 0.50 pitch)
MET1_SPACE_UM = 0.14     # m1.2
TRUNK_PITCH_UM = 0.50    # x grid for met2 trunks (0.30 wire + 0.20 gap)
TRACK_PITCH_UM = 0.50    # y grid for met1 spines
BUCKET_NM = 2000         # y bucket for the met1 overlap index


class Rect:
    """An axis-aligned rectangle in integer nanometres."""

    __slots__ = ("x0", "y0", "x1", "y1")

    def __init__(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1

    @classmethod
    def um(cls, x0: float, y0: float, x1: float, y1: float) -> "Rect":
        return cls(nm(min(x0, x1)), nm(min(y0, y1)), nm(max(x0, x1)), nm(max(y0, y1)))

    @classmethod
    def centred(cls, cx: float, cy: float, w: float, h: float) -> "Rect":
        return cls.um(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    @classmethod
    def hwire(cls, xa: float, xb: float, y: float, w: float) -> "Rect":
        lo, hi = sorted((xa, xb))
        return cls.um(lo - w / 2, y - w / 2, hi + w / 2, y + w / 2)

    @classmethod
    def vwire(cls, x: float, ya: float, yb: float, w: float) -> "Rect":
        lo, hi = sorted((ya, yb))
        return cls.um(x - w / 2, lo - w / 2, x + w / 2, hi + w / 2)

    def as_um(self) -> list[float]:
        return [self.x0 / DBU, self.y0 / DBU, self.x1 / DBU, self.y1 / DBU]

    def clashes(self, other: "Rect", clearance: int) -> bool:
        return (self.x0 - clearance < other.x1 and other.x0 < self.x1 + clearance
                and self.y0 - clearance < other.y1 and other.y0 < self.y1 + clearance)


class RouteError(RuntimeError):
    """The floorplan/router could not place a wire."""


class Anchor:
    """One place a net can be reached inside one block.

    ``plane`` is how a met2 trunk gets onto it: ``met1`` for an li1 pad or an
    in-block met1 strap, ``cap3``/``cap4`` for a MiM terminal that needs a
    same-layer run out of the block first, and (in the integrator)
    ``ota`` for one of the eight landing points inside the placed OTA
    instance.  ``x0``/``x1`` bound the x where a via may land with no extra
    metal; a column outside that range costs one met1 jog.
    """

    __slots__ = ("net", "block", "plane", "y", "x0", "x1", "ports", "port_dir",
                 "block_y0", "block_y1", "pad_xs", "jog_um")

    def __init__(self, net, block, plane, y, x0, x1, ports,
                 port_dir=0, block_y0=0.0, block_y1=0.0, pad_xs=(), jog_um=0.0):
        self.net, self.block, self.plane = net, block, plane
        self.y, self.x0, self.x1 = y, x0, x1
        self.ports = ports
        self.port_dir = port_dir
        self.block_y0, self.block_y1 = block_y0, block_y1
        #: x of each li1 pad this anchor straps (a vertical met1 jog off the
        #: strap may start at any of them).
        self.pad_xs = tuple(pad_xs) if pad_xs else (x0,)
        #: how far off the strap's own y a jog may climb before it leaves the
        #: pads it is allowed to shadow.
        self.jog_um = jog_um

    @property
    def xmid(self) -> float:
        return (self.x0 + self.x1) / 2


class Router:
    """met1 horizontal + met2 vertical, one global x column per trunk.

    Every trunk owns its x column outright (``used_cols``), so two met2 runs
    can never come within one pitch of each other and no met2-met2 spacing
    search is needed; met1 is the only layer the greedy search has to keep
    clear, and met3/met4 only carry the MiM risers.

    The cell generators subclass this and keep the parts that genuinely
    differ as overrides (see the section comment above); a cell with its own
    anchor kinds adds its own ``connect_*`` methods (the integrator's OTA
    instance escapes).  ``add_met1`` stays a subclass responsibility too --
    the integrator tags every met1 shape with its net.
    """

    #: how many candidate columns one ``connect_met1`` search may try before
    #: it gives up.  The OTA cell sits on a dense 0.42um S/D pad row and
    #: finds its columns sooner; the integrator straddles the placed OTA
    #: instance and needs the wider sweep.  An explicit ``col_budget``
    #: argument overrides it for one call.
    COL_BUDGET = 24

    def __init__(self, x_lo: float, x_hi: float, y_lo: float, y_hi: float) -> None:
        self.x_lo, self.x_hi, self.y_lo, self.y_hi = x_lo, x_hi, y_lo, y_hi
        self.shapes: list[tuple[tuple[int, int], Rect]] = []
        self.labels: list[tuple[tuple[int, int], str, float, float]] = []
        self.met1: list[tuple[str, Rect]] = []
        self.met1_index: dict[int, list[tuple[str, Rect]]] = defaultdict(list)
        self.met3: list[tuple[str, Rect]] = []
        self.met4: list[tuple[str, Rect]] = []
        self.used_cols: set[int] = set()
        self.trunk_y: dict[tuple[str, float], list[float]] = defaultdict(list)
        self.via1_y: dict[tuple[str, float], list[float]] = defaultdict(list)
        self.wire_um: dict[str, float] = defaultdict(float)
        #: Every routed rectangle, keyed by (net, layer).  Populated only by
        #: ``add_shape`` calls that name a net -- the OTA generator names
        #: none, so its dict stays empty; the integrator reads it back after
        #: the fact, in ``summing_node_report()``.
        self.by_net: dict[tuple[str, tuple[int, int]], list[Rect]] = defaultdict(list)

    # -- geometry bookkeeping -------------------------------------------------
    def add_shape(self, layer, rect: Rect, net: str | None = None) -> None:
        self.shapes.append((layer, rect))
        if net is not None:
            self.by_net[(net, layer)].append(rect)

    def add_mcon(self, x: float, y: float) -> None:
        rect = Rect.centred(x, y, MCON_UM, MCON_UM)
        self.add_shape(L_MCON, rect)

    def add_trunk_via(self, net: str, col: float, y: float) -> None:
        """Drop a met1<->met2 via1 on this net's column, and grow the trunk.

        A second via1 within a wire width of an existing *via1* would merge
        into one oversized cut (via.width.1) and breach via.space.1 -- but the
        two met1 runs that close together already overlap (see `_ok`), so the
        connection survives without it.  The comparison is deliberately
        against `via1_y` and not `trunk_y`: a MiM riser contributes a via2 at
        its own y and no met1 at all, and suppressing a via1 near it would
        leave the met1 spine with nothing to reach the trunk through.
        """
        self.trunk_y[(net, col)].append(y)
        if any(abs(y - prev) < WIRE_UM for prev in self.via1_y[(net, col)]):
            return
        self.add_shape(L_VIA, Rect.centred(col, y, VIA_UM, VIA_UM))
        self.via1_y[(net, col)].append(y)

    @staticmethod
    def _ok(rect: Rect, placed: Rect, same_net: bool, gap: int) -> bool:
        if not rect.clashes(placed, gap):
            return True
        # Same net: a real overlap merges the two into one polygon, which is
        # fine.  A near miss does not -- it leaves a notch whose own edges are
        # closer than the minimum spacing, which the deck flags exactly like a
        # two-net violation.
        return same_net and rect.clashes(placed, 0)

    @classmethod
    def _free(cls, store, net: str, rects: list[Rect], clearance: float) -> bool:
        gap = nm(clearance)
        for owner, placed in store:
            for rect in rects:
                if not cls._ok(rect, placed, owner == net, gap):
                    return False
        return True

    def met1_free(self, net: str, rects: list[Rect]) -> bool:
        gap = nm(MET1_SPACE_UM)
        for rect in rects:
            lo = (rect.y0 - gap) // BUCKET_NM
            hi = (rect.y1 + gap) // BUCKET_NM
            for b in range(lo, hi + 1):
                for owner, placed in self.met1_index.get(b, ()):
                    if not self._ok(rect, placed, owner == net, gap):
                        return False
        return True

    # -- candidate orders ------------------------------------------------------
    def neighbours_free(self, col: float) -> bool:
        return not any(nm(snap(col + d * TRUNK_PITCH_UM)) in self.used_cols
                       for d in (-1, 1))

    def reserve_column(self, col: float, neighbours: bool = False) -> None:
        self.used_cols.add(nm(col))
        if neighbours:
            self.used_cols.add(nm(snap(col - TRUNK_PITCH_UM)))
            self.used_cols.add(nm(snap(col + TRUNK_PITCH_UM)))

    def tracks(self, pref: float):
        k0 = int((self.y_lo - 2.0) // TRACK_PITCH_UM)
        k1 = int((self.y_hi + 2.0) // TRACK_PITCH_UM) + 1
        cands = [snap(k * TRACK_PITCH_UM) for k in range(k0, k1 + 1)]
        cands.sort(key=lambda y: (abs(y - pref), y))
        return cands

    def jog_tracks(self, a: Anchor) -> list[float]:
        if a.jog_um <= 0:
            return [a.y]
        n = int(a.jog_um / TRACK_PITCH_UM)
        ys = {a.y}
        for i in range(1, n + 1):
            ys.add(snap(a.y + i * TRACK_PITCH_UM))
            ys.add(snap(a.y - i * TRACK_PITCH_UM))
        return sorted(ys, key=lambda y: (abs(y - a.y), y))

    # -- the ways a net reaches a block ---------------------------------------
    def connect_met1(self, a: Anchor,
                     col_budget: int | None = None) -> tuple[float, float]:
        """Drop a met2 trunk onto this anchor.

        Cheapest first: a column that already lies inside the strap, so the
        via lands on metal that exists.  Failing that the jog climbs off the
        strap on a free met1 track (``jog_um`` bounds how far) and reaches
        sideways -- the freedom a 0.42um-wide S/D pad row needs, where every
        net sits on the strap's own y and only a different y can get past a
        neighbour's pad.
        """
        cols = self.columns(a.x0, a.x1, a.xmid)[
            :self.COL_BUDGET if col_budget is None else col_budget]
        for y in self.jog_tracks(a):
            for col in cols:
                if nm(col) in self.used_cols:
                    continue
                pad_x = min(a.pad_xs, key=lambda px: (abs(px - col), px))
                extra: list[Rect] = []
                if abs(y - a.y) > 1e-9:
                    extra.append(Rect.vwire(pad_x, a.y, y, WIRE_UM))
                    if abs(col - pad_x) > 1e-9:
                        extra.append(Rect.hwire(pad_x, col, y, WIRE_UM))
                elif not (a.x0 - 1e-9 <= col <= a.x1 + 1e-9):
                    extra.append(Rect.hwire(min(a.x0, col), max(a.x1, col), y,
                                            WIRE_UM))
                if extra and not self.met1_free(a.net, extra):
                    continue
                self.reserve_column(col)
                if extra:
                    self.add_met1(a.net, extra)
                self.add_trunk_via(a.net, col, y)
                return col, y
        raise RouteError(
            f"no free met2 column for {a.net} at {a.block} y={a.y}: "
            f"{len(self.used_cols)} columns already taken, "
            f"{len(cols)} free within the budget")

    # -- trunk-to-trunk spine --------------------------------------------------
    def route_spine(self, net: str, ca: float, ya: float,
                    cb: float, yb: float) -> float:
        for y in self.tracks((ya + yb) / 2):
            rect = Rect.hwire(ca, cb, y, WIRE_UM)
            if not self.met1_free(net, [rect]):
                continue
            self.add_met1(net, [rect])
            self.add_trunk_via(net, ca, y)
            self.add_trunk_via(net, cb, y)
            return y
        raise RouteError(f"no free met1 track for {net} spine {ca} <-> {cb}")

    def finish_trunks(self) -> None:
        """Draw one met2 vwire per (net, column) trunk over its via span.

        A column that collected a single via y has no span to cover: the
        via's own enclosure is the whole trunk, and a degenerate
        ``WIRE_UM x WIRE_UM`` square on met2 would only sit there for DRC to
        grade.  The integrator measured one such trunk per generation (its
        router sees the placed OTA instance's escapes); the OTA cell none --
        so the skip is the shared behaviour, not a per-cell choice.
        """
        for (net, col), ys in sorted(self.trunk_y.items()):
            lo, hi = min(ys), max(ys)
            if hi - lo < 1e-9:
                continue
            rect = Rect.vwire(col, lo, hi, WIRE_UM)
            self.add_shape(L_MET2, rect, net)
            self.wire_um[net] += (hi - lo)
