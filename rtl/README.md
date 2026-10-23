# rtl

Decimation filter: `decimator.v` (CIC order 4 ÷16, then 41-tap FIR ÷4, 16-bit
output at 80 kSps) and `decimator_coef.v` (generated coefficient ROM). Design
decisions, widths, timing, reset/overflow policy and results are in
[`DESIGN_NOTE.md`](DESIGN_NOTE.md); verification is in
[`../verification/decimator/`](../verification/decimator/).
