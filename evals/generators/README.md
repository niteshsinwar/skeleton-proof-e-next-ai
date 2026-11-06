# Dataset generators

One module per dataset, `<name>.py`, that builds a release deterministically (no clock, no randomness without a fixed
seed) by calling `harness.datasets.release(path, manifest, cases)`, which refuses to overwrite an existing version
(02/D16, 06/E3). `/ai-step` adds one with each new step.
