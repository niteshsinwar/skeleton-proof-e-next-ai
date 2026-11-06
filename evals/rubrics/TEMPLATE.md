# Rubric: <what it judges>

An anchored rubric for an LLM judge (06/E5). A judge informs a report; it gates nothing until
`calibration-<rubric>.json` shows κ ≥ 0.6 against human labels on at least 30 cases.

- **Judges:** one quality, stated as a question with a yes or no answer.
- **Anchors:** a short example of a "yes" and of a "no", taken from real, reviewed cases.
- **Judge route:** a model family other than the one it grades (the catalogue refuses the same family).
- **Order:** run both orders when it compares two answers; length is not quality.
- **Not for:** anything a code grader can check (schema, citations, exact values) or a human must decide.
