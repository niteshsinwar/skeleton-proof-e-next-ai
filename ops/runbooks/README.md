# Runbooks

What a person does, step by step, when something has to happen in production or has gone wrong. Each runbook is
executable: a step says what to run, then how to know it worked (07/O16).

| Runbook | When |
|---|---|
| [deploy.md](deploy.md) | Promoting an image digest to staging, then production |
| [rollback.md](rollback.md) | A release is broken and the previous one is known good |
| [go-live.md](go-live.md) | The first production release, or a release after a long pause |
| [incident.md](incident.md) | Anything users or the alerts say is wrong, AI incidents included |
| [secret-rotation.md](secret-rotation.md) | A secret leaked, expired or touched git |

## Conventions (checked by `make harness-check`)

- A step is a numbered level-3 heading: `### 1. Do the thing`.
- **Every step has a `**Verify:**` line**: what you see when it worked. A step you can't verify is a hope.
- **An exit code is read on its own line, straight after the command:**

  ```bash
  make smoke BASE_URL=https://staging.example.com
  echo "exit=$?"
  ```

  Never `make smoke ... | tail -5`: a pipe reports the status of its last command (`tail`), so a red smoke reads
  green. The lint refuses a pipe into `tail` or `head` and an exit code read after any pipe.
- Facts about the infrastructure (hosts, digests, versions) are re-checked by a command in the step, never copied
  from memory or an old ticket.
- Production is read-only to tools and agents; **a deploy, a rollback and a secret rotation are human actions** (07/O3).
- An incident ends with a new or corrected runbook step and an entry in `ops/failure-log.md` (07/O17, 10/H17).
