---
description: Audit a behaviour that looks wrong in real data - trace the path, establish ground truth, measure, classify each miss, fix deterministic causes first and prompts last.
argument-hint: "<behaviour or output to audit>"
---
# /audit: measure before you fix

1. **Trace the path by reading:** where each value is produced, transformed, excluded and displayed. Check that any two exclusion lists agree; look for state that is written and never read.
2. **Ground truth** from the real source (live system or the original document), not from a fixture.
3. **Measure** on a stated set with its denominator; for model behaviour, at least 3 runs.
4. **Classify** each miss: data, deterministic code, retrieval, prompt, model limitation, or the expectation itself.
5. **Fix deterministic causes first**; change prompts last, one variable at a time, with eval evidence.
6. Record the audit in `ops/failure-log.md` with its hardening.
