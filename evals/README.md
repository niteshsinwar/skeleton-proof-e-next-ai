# Evals

Evidence that the product's AI behaves, as recorded runs that could have failed (06 §2). Code first; a model never
grades its own exam; a score with no recorded run is a claim.

| Command | What it does |
|---|---|
| `make eval-selftest` | The harness's own tests, offline, in labelled fixture mode: a correct answer passes and a planted wrong one fails (06/E7). Part of `make check`. Never an eval. |
| `make eval` | Every released dataset, **live**, each case at least 3 times (06/E4). Needs the provider's key, `EVAL_LIVE=1` (it costs money) and `APP_DATABASE_URL` (runs are recorded in the `eval` schema). A degraded run or a regression fails. |

## Layout

- `harness/`: dataset loading, graders, the run loop and recording. Plain pytest (06/EL2).
- `datasets/<name>/v<N>/`: immutable releases (`cases.jsonl` + `manifest.json` with its hash). Never edit one; build a
  new version with its generator.
- `generators/<name>.py`: the one deterministic command that builds each dataset (02/D16).
- `rubrics/`: judge rubrics and their calibration records. A judge sees every pair in both orders (`judge_both_orders`); it can inform, and it gates nothing until calibrated
  (κ ≥ 0.6 against human labels on at least 30 cases, 06/E5).
- `results/`: written-up conclusions from recorded runs. The runs themselves live in the database.

## A case

Each line of `cases.jsonl` is one case: its `id`, `layer` (L0–L6, reported apart), `tags` (`good`, `thin`, `absent`,
`contradictory`, `injection_direct`, `injection_indirect`, `injection_encoded`, `held_out`, …), what a `good` answer
does (written first, 06/E1), the `inputs` (context items and variables), what to `expect` (status, `must_include`,
`must_not_include`, `cites`, `max_cost_usd`), an optional matched `pair`, and an optional `fixture` reply used only by
the self-test. Every past AI failure becomes a case (06/E3, 06/E10).
