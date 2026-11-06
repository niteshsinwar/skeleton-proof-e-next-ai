# Deploy

Promote one image digest, built once by CI for the exact commit, from staging to production (07/O1). Never build per
environment and never copy a working tree. Production runs need a human: the GitHub environment asks a reviewer and
the person who approves runs the steps.

## Before you start

### 1. Find the digest CI built for the commit

```bash
git rev-parse HEAD
gh run list --workflow ci.yml --commit "$(git rev-parse HEAD)" --json conclusion,headSha
```

Copy the image digest (`sha256:...`) from that run's `images` job summary.

**Verify:** the run's `conclusion` is `success` and its `headSha` equals the commit you mean to ship.

### 2. Run the go-live preconditions

```bash
make go-live-check ENV=staging
echo "exit=$?"
```

**Verify:** `exit=0`. Any refusal (red CI, a missing digest, a missing secret, a private key in the JWKS, no known
rollback digest) stops the deploy; fix the cause, never the check (07/O4).

## Staging

### 3. Deploy the digest to staging

Migrations run from the same image before the new version takes traffic (07/O2).

```bash
make deploy ENV=staging DIGEST=sha256:<digest>
echo "exit=$?"
```

**Verify:** `exit=0`, and `/ready` answers 200 (it stays 503 until the migration revision matches the code).

### 4. Smoke-test staging

```bash
make smoke BASE_URL=https://<staging host>
echo "exit=$?"
```

**Verify:** `exit=0`; the smoke lane confirms `/health` reports the commit you shipped.

## Production

### 5. Approve and deploy the same digest to production

```bash
make go-live-check ENV=production
echo "exit=$?"
make deploy ENV=production DIGEST=sha256:<digest>
echo "exit=$?"
```

**Verify:** both print `exit=0`. The digest is the one staging ran, character for character.

### 6. Smoke-test production

```bash
make smoke BASE_URL=https://<production host>
echo "exit=$?"
```

**Verify:** `exit=0`. A red smoke means the canary reverts automatically (07/O6); if it didn't, follow
[rollback.md](rollback.md).

### 7. Record the release

Add a line to `docs/STATE.md`: the commit SHA, the image digest, the migration revision (`/ready` shows it), who
approved and when (07/O3).

**Verify:** `git log -1 -- docs/STATE.md` shows the record committed, and the SHA in it equals `/health`'s.

### 8. Watch the first hour

Open the SLO dashboard for each journey (`ops/slo/`) and the error rate.

**Verify:** no burn-rate alert fires in the first hour; if one does, start [incident.md](incident.md).
