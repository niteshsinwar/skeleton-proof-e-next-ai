---
description: Release a commit - preconditions, tag, deploy.yml builds once and promotes the same digest, a person approves production, smoke, record in STATE. Production deploys are human actions.
disable-model-invocation: true
---
# /release: build once, promote, record

Claude prepares and records; **a person approves and runs the production step** (07/O3, README #14). Claude never
deploys to production, never approves its own run, and never runs a write script against production.

1. **Preconditions on the exact commit.** `git status` is clean and the commit is on `main`; CI's `gate` is green on
   it: `python3 -I scripts/deploy.py ci-status --sha <sha>` (needs `GH_TOKEN`; it refuses rather than assumes).
   The release scorecard is reviewed (`docs/scorecard.md`); the rollback path is known: the digest running in
   production now (`make deploy-status ENV=production`) is the one to return to. The rollback was rehearsed on
   this release's migrations: `make rehearse-rollback`, and a restore was proved: `make restore-drill` (07/O5, O20).
2. **Tag** `vX.Y.Z` on that commit with release notes from its commits (`git tag -a vX.Y.Z -m ...`, then push the
   tag; ask first: pushing is the person's call).
3. **`.github/workflows/deploy.yml` runs on the tag:** it checks the gate again, builds the images once and pushes
   by digest, then deploys to staging (migrate, deploy, smoke, revert on failure), then waits for **production's
   required reviewer**. Production runs `make go-live-check`'s preconditions (CI green, images exist, secrets in
   place, a public-only JWKS, rollback known, a reviewer on the environment), migrates, deploys, smoke-tests and
   reverts to the previous digest if smoke fails (07/O4, O6). The very first production go-live is a manual run
   with `first-release` ticked.
4. **The person approves** the production job in GitHub (Claude says what will run and where, then waits).
5. **Record** the job summary's JSON (SHA, image digests, migration revision, who, when, result) as a row in
   `docs/STATE.md` under *Deploys*. A revert or a failed smoke is recorded too, with the reason, and a
   `/failure-log` entry when something was learned.

At a terminal the same steps are `make deploy ENV=staging DIGEST=sha256:... WEB_DIGEST=sha256:...`, then the person runs
`make deploy ENV=production ...`; `make rollback ENV=... TO=<digest>` returns to an older release one migration step
at a time (07/O5). "The data looks wrong" is never a rollback: find what is broken first.
