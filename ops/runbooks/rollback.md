# Rollback

Return production to the previous known-good image digest. Rehearsed before go-live with `make rehearse-rollback`
(07/O5). **Data that looks wrong is never a rollback:** old code on wrong data is still wrong data; that is an
incident ([incident.md](incident.md)).

### 1. Decide what is actually broken

Read the alert, the error rate and the last deploy record in `docs/STATE.md`. A rollback fits when the new release
broke behaviour (errors, latency, a failed journey) and the previous release did not have the problem.

**Verify:** you can name the release that introduced the problem, and it is the one running now (`/health` shows its
SHA).

### 2. Find the previous digest

```bash
git log -3 -- docs/STATE.md
```

The previous release's line holds its digest and migration revision. The previous image stays tagged, so it can be
pulled.

**Verify:** `docker manifest inspect <registry>/<image>@sha256:<previous digest>` prints a manifest (the image still
exists).

### 3. Check whether migrations need reversing

Compare the migration revision of the two releases. Each migration is backward-compatible for one release (expand,
migrate, contract), so the previous code normally runs on the new schema and nothing is reversed.

**Verify:** the previous release's revision equals the current one, or you have listed each revision in between,
newest first, and read its `downgrade()`.

### 4. Roll back the image

```bash
make rollback ENV=production TO=sha256:<previous digest>
echo "exit=$?"
```

**Verify:** `exit=0`, and `/health` shows the previous release's SHA.

### 5. Reverse migrations one step at a time, only if step 3 said so

Never `downgrade base`. One revision, check, then the next. Run it with the migration owner's database URL from the
secret manager, set for this shell only (the app's own role never owns a table).

```bash
cd apps/api
APP_DATABASE_URL="<migration owner URL>" uv run alembic downgrade -1
echo "exit=$?"
APP_DATABASE_URL="<migration owner URL>" uv run alembic current
```

**Verify:** each `downgrade -1` prints `exit=0`, and `alembic current` names the revision you expected before you take
the next step.

### 6. Smoke-test

```bash
make smoke BASE_URL=https://<production host>
echo "exit=$?"
```

**Verify:** `exit=0`, and the burn-rate alert that started this resolves within its short window.

### 7. Record it

Add the rollback to `docs/STATE.md` (from which digest to which, who, when, why) and open an incident entry.

**Verify:** the record is committed, and an entry in `ops/failure-log.md` links the incident.
