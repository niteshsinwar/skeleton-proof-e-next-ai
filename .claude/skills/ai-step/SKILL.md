---
description: Add or change an AI step, tool or proposal kind - delegation test, decision-ownership row, a new agent-file version and its pin, an output schema with verifiers, registration, an eval dataset from a generator, and live evals run at least 3 times.
argument-hint: "<step, tool or proposal kind>"
---
# /ai-step: the model proposes, code decides

Copy the shape of the EXAMPLE slice (`intelligence/work_item_brief.py`, `api/routers/work_item_brief.py`); never build a
parallel structure.

1. **Delegation test** (04/P2): could plain rules or search do enough? Is a wrong call reversible, what does it cost,
   who answers for it? Write the answer in the spec. If it's weak, it is code, not a model.
2. **Ownership:** add the step's row to `docs/architecture/decision-ownership.md` (what code, the model and a human own).
3. **Agent file:** a new version in `ai/agents/<agent>/v<N>.yaml` naming a **route** from `ai/models.yaml`, never a
   model. Add its SHA-256 to `ai/agents/pins.json` (the test prints the line). A prompt change is a new version file.
4. **Output and verifiers:** an output schema extending `StepOutput` (citations as `Citation`), plus step verifiers;
   an unsupported answer returns `"abstain:<reason>"`. Register the `Step` in `intelligence/project_steps.py`.
5. **Call it** from a use case with the shape in `application/ai_runs.py`: authorise and `admit`, run with no
   transaction open, `record` the attempt, act only on `result.value` when `result.succeeded`.
6. **Writes are proposals:** a tool that changes anything is a `propose` tool in `intelligence/tools.py`; its kind's
   executor (precheck + execute through an existing use case) goes in `api/proposal_kinds.py`.
7. **Evals:** the `eval-author` agent writes the cases (good, thin, absent, contradictory, injection, matched pairs)
   in a generator under `evals/generators/`, released to `evals/datasets/<name>/v1`. Then `make eval` live, every case
   at least 3 times, recorded. A regression blocks.
8. **Mutation:** add the new guard to `scripts/mutations.toml` and run `make mutation`.

**Rules in scope:** `.claude/rules/ai.md` · `.claude/rules/evals.md`. **Exit gate:** `make check` green and a
recorded, non-degraded `make eval` run.
