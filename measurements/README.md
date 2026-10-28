# measurements

No silicon exists, so there is no measured data here. Nothing in this repo is
called measured (see the repo README).

- [`characterization.md`](characterization.md): the T1 item-8 characterization
  report, one row per spec row plus the decimator Fmax/area/power table, each
  verdict citing its evidence file or naming the issue it waits on. Bound to its
  evidence by `attestation/item8-envelope.json`; regenerate with
  `python3 -I attestation/item8_envelope.py` after any edit to the report or to a
  file it cites.
