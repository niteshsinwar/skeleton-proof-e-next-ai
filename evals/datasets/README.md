# Dataset releases

One folder per dataset and version: `<name>/v<N>/cases.jsonl` and `manifest.json`. A release is immutable: its manifest
pins the cases' SHA-256 and the loader refuses an edited one. To change a dataset, run its generator to make `v<N+1>`.

A release must expect at least one success and one other outcome (no one-sided evals, 06/E3), keep matched pairs to
exactly two cases with the same expected outcome (04/H3), and, at tiers S and E, include injection cases (05/SG5).
Synthetic data says so in its manifest (02/D16). No real personal data enters a dataset unless that use is authorised
and recorded (05/SG8).
