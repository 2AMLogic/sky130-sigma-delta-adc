# Decimation filter — design note

Issue #16. Spec rows 6–10 ([`spec/modulator-adc.md`](../spec/modulator-adc.md)).
Label for every result below: **simulated RTL + synthesized, no timing**
(analytical for the frequency response). Nothing here is measured.

## Structure

```
din (1 bit, fs = 5.12 MHz)
  -> CIC, order 4, R = 16, M = 1, 17-bit modular registers   -> 320 kSps
  -> 41-tap symmetric FIR, decimate by 4, serial MAC          -> 80 kSps
  -> round to nearest, saturate -> 16-bit two's complement
```

Files: `decimator.v` (top, CIC + FIR + output), `decimator_coef.v` (coefficient
ROM, **generated** by `verification/decimator/design_fir.py`; do not edit).

### Why CIC order 4, not 3

Spec row 10 asks for order ≥ 3, and the issue's suggested split was order 3 with
R = 16. The CIC alone protects the band `fs/R ± BW` (300–340 kHz here), where
the FIR passes everything (its response repeats every 320 kHz). At 300 kHz:

| CIC order | CIC attenuation at 300 kHz | Row 9 (≥ 90 dB) |
|---|---|---|
| 3 | 70.6 dB | **fails** by 19 dB, whatever the FIR is |
| 4 | 94.1 dB | passes (whole chain 93.9 dB after the FIR's 0.2 dB gain there) |

Arithmetic: `|sin(πRf/fs) / (R·sin(πf/fs))|^N`, reproduced by
`verification/decimator/model.py:cic_mag`. Order 4 is inside "order ≥ 3"; row 10
is not changed. Register width for a 1-bit input is `N·log2(R) + 1 = 17` bits.

### Input encoding

`din = 1` means **+1**, `din = 0` means **−1** (bipolar). The CIC runs on the 0/1
stream (output 0 … 65536 at DC), and the constant `32768` is subtracted before the
FIR, so a +1 stream settles to `+32768` and a −1 stream to `−32768`. Whatever the
behavioural modulator model (#15) emits must use the same mapping; a stream that
uses the opposite polarity inverts the output code.

### FIR and coefficients

Minimax design by linear programming (scipy/HiGHS): minimise the stopband peak
over 60–160 kHz at the 320 kSps rate, with the **whole-chain** passband (CIC ×
FIR, so the CIC droop is compensated) held within ±0.02 dB of flat over 0–20 kHz
and unity DC gain. 41 taps; coefficients rounded to signed 17-bit integers scaled
by 2⁻¹⁸ and forced to sum to exactly 2¹⁸ (the few-LSB residue goes on the centre
tap, which keeps the filter symmetric). Floating-point stopband peak is −116 dB
(CIC excluded); 16-bit/2⁻¹⁷ coefficients left only 91.7 dB at the 60 kHz edge
after rounding, so one more bit was spent.

`verification/decimator/response.py` judges the **quantized integers in
`rtl/decimator_coef.v`**, not the design floats.

| Row | Requirement | Result (50 Hz grid; 401 passband points, 25 232 alias-band points) |
|---|---|---|
| 8 | passband ripple ≤ 0.1 dB, 0–20 kHz | 0.040 dB peak-to-peak |
| 9 | ≥ 90 dB in the alias bands | 93.91 dB worst, at 300 kHz (CIC-limited) |

**Interpretation of row 9, to be confirmed by the spec owner.** Row 9 says
"≥ 90 dB from `fout − BW` to `fs/2`". The gate here is the alias bands
`[k·80 kHz − 20 kHz, k·80 kHz + 20 kHz]`, k = 1 … 32 (clipped at fs/2), which is
where energy folds into 0–20 kHz and which the issue names as the worst case;
rationale 8–10 of the spec also frames the stopband as alias leakage. The
*literal* reading, every frequency from 60 kHz to fs/2, is **not** met: the gaps
between alias bands are not attenuated to 90 dB (worst 79.2 dB, at 284.5 kHz,
where the FIR's transition band images next to the CIC's first null). Meeting
the literal reading needs a much longer FIR running at the input rate or a
different decimation structure, and would not change the in-band result. This
repo does not edit the spec; if the literal reading is intended, that is a
decision record and a redesign. `response.py` prints that number so it stays visible.

### Arithmetic and widths

| Item | Value |
|---|---|
| CIC registers | 17 bits, wrap-around (two's complement modular arithmetic is exact: the true output is 0 … 65536) |
| FIR sample | 17-bit signed (CIC output − 32768, range ±32768) |
| Coefficient | 17-bit signed, scale 2⁻¹⁸, max 58 590 |
| Accumulator | 35-bit signed; `response.py` computes the no-overflow bound `32768·Σ|h|` and refuses if `ACC_W` in the RTL is smaller |
| Rounding | add 2¹⁷, arithmetic shift right 18 (round half up) |
| Output | 16-bit two's complement, **saturating**: +1.0 → `32767`, −1.0 → `−32768` |

### Timing (one output word per 64 clocks)

The frame counter `fc` free-runs 0…63 from reset. Combs fire when `fc[3:0] = 15`
and shift the new CIC sample into the FIR memory. The MAC runs on `fc = 0 … 40`
(tap `k = fc`; it reads memory index `fc + (fc >> 4)` because the memory shifts
at `fc = 15` and `31` during the MAC). At `fc = 41` the result is rounded,
saturated and registered, and `dout_valid` is high for exactly one clock.
Counting clock edges from the first one with `rst = 0` as edge 0: **the first
strobe is visible after edge 41, then every 64 edges** (pinned by the cocotb
test and by `model.VALID_EDGE`).

Throughput check: 41 taps ≤ 64 clocks, so one multiplier suffices. Group delay
of the chain is `(40/2)·16 + 4·15/2 = 350` input clocks (about 5.5 output words).

### Reset and overflow policy

* **Reset** is synchronous, active high, and clears every register: integrators
  and combs (the CIC remembers "all inputs were 0", i.e. a −1.0 history), the FIR
  memory (0.0), the accumulator, the output (`dout = 0`, `dout_valid = 0`), and
  the frame counter. A reset at any point restarts the 64-clock frame.
* **Start-up transient.** The chain's impulse response spans
  `41·16 + 64 = 720` clocks, so the first **12** output words after reset
  (and after a reset mid-stream) are filter start-up and must be discarded.
  `dout_valid` is not held off during them.
* **Overflow.** CIC arithmetic is exact by construction (modular, output range
  fits). The FIR can exceed ±1.0 FS (ripple, step overshoot); the 16-bit output
  **saturates**, it never wraps. The cocotb test pins this (all-ones input
  gives `32767`, not `−32768`).

### Not built here

Fallback and stretch variants (÷128, ÷32): `decimator.v` takes `CIC_LOG2R`,
`FIR_LOG2D`, `N_TAPS`, `COEF_W`, `COEF_FRAC`, `ACC_W` as parameters so nothing is
hard-wired, but only the target configuration is generated, simulated and
characterised. ÷32 would need more than one tap per clock (41 taps > 32 clocks).

## Synthesis (Yosys via `klt synthesize`, `sky130_fd_sc_hd`, tt_025C_1v80, no timing)

See `verification/decimator/record.json`: 5 390 cells, 49 062 µm², 925 flip-flops
(731 of them the FIR sample memory), netlist sha256 in the record. Untimed and
unconstrained (`clock_period_ns` null), so the area is a lower-effort estimate,
not a P&R result. No STA, no multi-corner, no placement.
