---
paths:
  - "evals/**"
  - "ai/**"
---
# Evals

**Prevents:** a prompt change shipped without evidence, an uncalibrated judge gating a release, and one averaged score hiding a regression [06 §2].

- Evals are written alongside the behaviour; the `eval-author` agent can't edit the prompts it grades [06/E1].
- Layers L0 (hard gates at 100%) to L6 (operations and cost); capability and regression evals both run [06/E2].
- Datasets: anonymised production cases, expert cases, reviewed synthetic cases, every past failure, adversarial tags; released versions immutable; the model never labels its own exam; matched pairs; a held-out set [06/E3].
- **Every real-model case runs at least 3 times** and reports per run; fixes proven red → green on the real model; evals run the production configuration [06/E4].
- Code graders first; an LLM judge only with an anchored rubric, both orders, another model family, and κ ≥ ~0.6 against human labels before it gates [06/E5, 06/EL3].
- Metrics per layer and category, never averaged into one score [06/E6]. Recorded runs are the evidence and are never overwritten [06/E7].
- Regressions block; one variable changes at a time; read transcripts, not just scores [06/E8]. Noise is reported before claiming an improvement [06/E11].
- Runner: the pytest harness in `evals/harness/` (`make eval` live, `make eval-selftest` offline); a library only after
  a pilot [06/EL2]. Datasets are built by `evals/generators/` and released to `evals/datasets/`; runs are recorded in
  the `eval` schema [06/E7].

## Change contract

| | |
|---|---|
| **Load first** | the dataset release notes and the agent file being evaluated |
| **Run** | `make eval` |
| **Same commit** | new cases (incl. adversarial) for any new behaviour or fixed failure |
| **Prove** | a recorded run with per-run results and its denominators |
| **Never** | edit a released dataset; let a model label its own exam; gate on an uncalibrated judge |
