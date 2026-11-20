# sim/ota-swing — OTA output-swing / gain-compression bench (issue #331)

**Simulated, transistor-level** (ngspice on `design/ota/ota_fd.spice` as
committed on `main`; not the behavioural model). Question, from the operator
ruling on #148 (2026-11-17, step 1): what differential output swing can `ota_fd`
deliver before its gain compresses, in the closed-loop configuration and load
the integrator presents — so the ~2.3 Vpp static-headroom figure in
`design/ota/SIZING.md` becomes a measured number instead of a hand calculation
from one bias point?

This bench is the evidence the ruling conditions the section 5.4
clarification on. It is **not** a spec row: there is no pass/fail against
`spec/modulator-adc.md` here, and `sim/modulator-tran` keeps grading its 1.39
Vpp figure unchanged.

## Fixture (`make_request.py` -> `ota_swing.cir` + `request.json`)

The OTA in the closed-loop integrate-phase configuration
`design/ota/SIZING.md` derives, with the summing-node load the cell really
presents in phi2 — both the input and the DAC sampling cap (`beta =
Ci/(Ci+2Cs+Cp)`, the corrected trace; `sim/ota-settling` models one Cs, this
bench carries the second as a cap parked at `vcm`), `Cp` = 35 fF per side
(the value the settling benches also keep), and 1.1 pF external load per side
(next stage's `Cs` + output parasitics, SIZING case A). Two instances in one
deck, one per load, each with **its own 5 uA ibias source** (a shared bias
node would halve every leg — two diodes on one 5 uA source — and the OTA
would run at half bias; that mis-wiring was caught against the `ota-gain`
cross-check below):

- **main**: `Ci` = 2 pF — the cell as committed on `main` (`C1 = C2 = 0.5`).
- **c0p3**: `Ci` = 3.334 pF — the #257 rescale (`C1 = C2 = 0.3`, DR-007),
  parameterised from that PR's `design/integrator/SIZING.md`. PR #257 is not
  merged (operator ratification hold); this bench does not depend on it.

Per amplitude (0.2 Vpp small-signal reference, then 0.4 to 2.8 Vpp
differential) and polarity: reset (ideal switches short out<->summing node,
unity feedback, `vod` -> 0, plates re-park at `vcm`), then **5 accumulated
plate steps of one clock's charge transfer each** — the way a run of
same-decision clocks builds integrator swing in the modulator, and bounded
the same way (worst step: 0.28 V per side main, 0.47 V c0p3, against the real
per-clock feedback step of 0.3 / 0.23 V per side) — then a hold past the
97.66 ns phase. The driven-plate excursion is `Ci/Cs` x the output swing by
charge conservation: a bench-only consequence of compressing those clocks
into one segment, on linear capacitors that draw no DC current, and it does
not touch the settled operating point the gain is read from.

## Extraction and gates

`A_eff = |vod| / (beta * (|target| - |vod|))` at each settled point — the
exact inversion of the settled closed-loop relation
`vod = target*beta*A/(1+beta*A)`. Compression is the drop below the 0.2 Vpp reference point;
the 1 dB / 3 dB points are linearly interpolated on the gain-vs-swing curve
(worse polarity), and the single-ended output range and output common-mode
shift at those points are read from the same settled samples.

Record-admission gates, all REFUSE-not-record (issue #94's rule):

- all 7 DR-002 anchors returned, and they are exactly the anchor set;
- every cell x amplitude x polarity segment measured `vod`/`outp`/`outn` and
  its settled-ness probe (`vod` again 150 ns earlier; the record refuses if
  the output moved more than 5 mV — an unsettled reading is not a gain);
- the 0.2 Vpp small-signal reference reproduces `sim/ota-gain`'s independent
  45-corner ac record at every anchor to within 0.5 dB. This is the gate that
  makes the curve a gain: it caught the shared-ibias mis-wiring above at
  4.2 dB. The tolerance covers the reference being a secant over 0.2 Vpp
  rather than the `vod` = 0 tangent, and `beta` not containing the OTA's own
  input capacitance.

The request carries `set numdgt=12` / `set measureprec=12`: the extraction
divides by `target - vod`, ~3e-4 V wide at the reference point, far below
ngspice's default six digits.

## The record and what it says

`record.json` (fleet jobs `klt-sim-4c6d83545baf`, `klt-sim-3c649ae9b52b`, `klt-sim-b709fe283c0e` in its `remote` field) — 7/7
anchors, both cells, all gates pass. Small-signal gain 53.31 to 58.63 dB
across the anchors (cross-check vs `ota-gain`: worst 0.19 dB). The
compression points, per anchor (both cells agree to ~0.05 dB — the OTA is the
same, only the load differs, and compression is a property of its output
operating point):

| anchor | cp1 (Vpp) | cp3 (Vpp) | gain at the recorded o1 swing |
|---|---|---|---|
| ff/1.980 V/-40 C | 2.58 | not reached by 2.8 | -0.9 dB |
| ff/1.980 V/125 C | 2.24 | 2.60 | -2.4 dB |
| fs/1.800 V/27 C | 2.20 | 2.49 | -1.9 dB |
| sf/1.800 V/27 C | 2.02 | 2.31 | -5.0 dB |
| ss/1.620 V/-40 C | 1.53 | 1.75 | -15.3 dB |
| ss/1.620 V/125 C | 1.02 | 1.26 | -19.9 dB |
| tt/1.800 V/27 C | 2.15 | 2.44 | -3.6 dB |

(the o1 swings are PR #257's `record-c0p3.json` values, cited by sha256 in
the record's `swing_reference`; at integrator 2's smaller swings the drop
stays inside ~1 dB except ss/1.620 V/125 C at ~-6.8 dB)

**The plain statement the ruling asked for: the OTA compresses.** At the
differential swings the c0p3 modulator actually recorded (2.27-2.53 Vpp), the
gain, read at each anchor's own recorded swing, has fallen more than 3 dB at
4 of 7 anchors (sf, ss/-40 C, ss/125 C, tt; fs is -1.9 dB at its own 2.40 Vpp).
The 3 dB point cp3 lies at or below the top of the recorded range (2.53 Vpp)
at 5 of 7 (fs, sf, both ss, tt), so the gain does fall more than 3 dB somewhere
inside that range at those 5. At the two ss corners it has collapsed
(-15 dB, -20 dB; cp3 there is 1.75 and 1.26 Vpp). The
~2.3 Vpp static-headroom hand calculation holds only near the nominal
corners. This is step 3 of the #148 ruling, not step 2: the simulated result
does **not** back reading section 5.4 as a per-node ~2.3 Vpp differential
figure, and the outcome is reported on #148 rather than written into a
decision record. Two caveats for whoever picks that up: at deep compression
the extracted figure is a secant of the closed-loop transfer, blending true
gain loss with nonlinearity, and it is the *nominal* grid — no mismatch.

## Running

    python3 -I sim/ota-swing/run_swing.py --probe     # 1 corner, local
    python3 -I sim/ota-swing/run_swing.py --record    # 7 anchors, batch fleet

The runner refuses a PDK whose `SOURCES` stamp differs from `sim/pdk.json`
(exit 2). The 7 anchors are one `klt sim` request (`corners.units`, DR-002
anchor set) submitted to the batch fleet with `--wait-for-capacity 600`; both
cells share the one transient, so a corner is one unit (~22 s worst measured
on the fleet). It never falls back to a local grid. `--record` refuses to
overwrite (append-only); use `--record-name`. `python3 -I
sim/ota-swing/make_request.py` regenerates the deck and request; the two
committed files must match it (pinned by `test_run_swing.py`).

Unit tests (no EDA tools):

    python3 -I -m unittest discover -s sim/ota-swing -p 'test_*.py'

## Limits

Slew and settling dynamics inside the phase (`sim/ota-settling` owns those),
noise, mismatch (nominal grid; a Monte Carlo swing campaign would need its own
run), layout parasitics, and the switch charge-injection effects
`sim/integrator-ci` owns. The gain is the OTA's at a *settled* output point:
how the loop behaves *through* the transient at a compressed swing (slew
during the step, CMFB recovery) is `sim/ota-settling`'s question, asked here
only up to its own 0.45 V step.
