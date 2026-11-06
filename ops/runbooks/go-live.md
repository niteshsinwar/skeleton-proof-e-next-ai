# Go-live

The first production release, or the first after a long pause. Everything here is checked by a command, so it can
be re-run at any time (07/O4, O16).

### 1. Preconditions refuse or pass

```bash
make go-live-check ENV=production
echo "exit=$?"
```

**Verify:** `exit=0`: CI is green on the exact commit, the image digest exists, secrets are in place, the JWKS holds
no private key and the rollback digest is known.

### 2. Rollback rehearsed

```bash
make rehearse-rollback
echo "exit=$?"
```

**Verify:** `exit=0`: release N deployed, N+1 deployed and migrated, rolled back to N one migration step at a time,
`/ready` and the data checked (07/O5).

### 3. Backups restore

```bash
make restore-drill
echo "exit=$?"
```

**Verify:** `exit=0`: a fresh dump restored into a scratch database, which became ready (07/O20).

### 4. Nothing is about to expire

```bash
make expiry-check
echo "exit=$?"
```

**Verify:** `exit=0`: no certificate, key or model retirement date falls inside its warning window (07/O18).

### 5. Every alert has an owner and a runbook

```bash
make alerts
echo "exit=$?"
```

**Verify:** `exit=0`: the alert rules were generated, which only happens when every SLO names a real owner (not
`@OWNER`) and an existing runbook (07/O15). The rules are loaded into the monitoring system and a test alert reached
its owner.

### 6. Load holds at the expected peak

```bash
make load-mixed BASE_URL=https://<staging host>
echo "exit=$?"
```

**Verify:** `exit=0`: people's p95 held while agents were limited with 429s (01/R3, R4, R9).

### 7. Deploy

Follow [deploy.md](deploy.md) from step 1.

**Verify:** its last step's record is in `docs/STATE.md`.
