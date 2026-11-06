# The product's AI (governed data)

What the product's AI may do, as versioned data the app loads strictly at start (04/Q1, 12/N4). The code that runs
it is `apps/api/src/<package>/intelligence/`; the evidence that it works is `evals/`. A wrong file here stops the app
from starting rather than letting it guess (02/B5).

| File | Holds |
|---|---|
| `models.yaml` | **Providers**, **models** (with dated prices and retirement dates) and **routes**, the kinds of call. **Embeddings** by use, each a model at a fixed size. |
| `agents/<agent>/v<N>.yaml` | One AI step's contract: job, what it must never do, who decides after it, route, what it may be shown, prompt, output schema, budgets, eval set. |
| `agents/pins.json` | The SHA-256 of every released agent version. A released version never changes. |

## Switching a model or a provider

Agent files name a **route** (`default`, `fast`, `deep`, or one you add), never a model. To move a kind of call to
another model, change that route's `model` in `models.yaml`. To use another provider, add it under `providers` (an
adapter exists for each kind of provider; a new kind is one module in `intelligence/providers/`, by ADR) and point a
model at it. Then re-run the evals before merging (04/M2): a model change is a behaviour change.

## Adding an AI step

Run `/ai-step`. In short: the delegation test and a decision-ownership row; a new agent file and its pin; an output
schema and verifiers; the step registered in `intelligence/registry.py`; an eval dataset built by its generator; and
`make eval` run live, at least 3 times per case. A prompt change is a new version file, never an edit.

## Switching AI off

Every step has a kill switch, `ai.<step>`, and `ai` switches every step off, per tenant, audited (05/SG11). With no
provider key configured, AI is off everywhere and the product still works (01/R5).

## Embeddings and search

`embeddings.default` in `models.yaml` names the embedding model and its size; together they are the **embedding
space** stored with every vector (`gemini/gemini-embedding-001@768`). Vectors from two spaces are never compared. To
change the model or the size: add a column of the new size (or a new table) by migration, embed into the new space,
measure retrieval on both, then switch (re-index blue/green, 04/X4). With no `GEMINI_API_KEY`, documents are still
stored and search runs on full text alone, and every answer says `degraded` (01/R5).

Search (`retrieval/engine.py`) runs two lanes, Postgres full text and pgvector, each filtered by tenant and role
before it ranks anything, and fuses them by reciprocal rank (04/X4). An AI step reads hits through
`SearchHit.as_context`, which marks the text untrusted: it may inform an answer, never drive an action (05/SG5).
