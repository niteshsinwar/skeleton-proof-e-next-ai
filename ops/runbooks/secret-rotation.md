# Secret rotation

Replace a secret that leaked, expired or touched git. **A secret that ever reached git is rotated, even after the
history has been rewritten:** clones, forks, caches and CI logs keep the old value (05/SG12). Rotation is a human
action; agents can't read secrets.

### 1. Name the secret and where it is used

Find every place that holds or reads it: the secret manager entry, the environments (staging, production), CI
secrets, and the code setting that names it (`APP_...` in `.env.example`, a provider key in
`ai/models.yaml`).

```bash
grep -rn "<SETTING_NAME>" .env.example apps/api/src ai
```

**Verify:** you have a list of every environment and service that reads the secret, and the provider console where it
is issued.

### 2. Issue a new secret beside the old one

Create the new value at its provider (a new API key, a new signing key with a new `kid`, a new database password)
without revoking the old one yet, so nothing breaks in between.

**Verify:** the provider lists two active credentials, the old and the new.

### 3. Store the new value and redeploy

Put the new value in the secret manager for each environment, staging first, then redeploy the same image digest so
it is read (follow [deploy.md](deploy.md) from step 3).

```bash
make smoke BASE_URL=https://<staging host>
echo "exit=$?"
```

**Verify:** `exit=0` on staging, then on production, and the service's logs show no authentication failures.

### 4. Revoke the old secret

Revoke or delete the old value at the provider. For a signing key, remove the old public key from the published JWKS
only after the longest token lifetime has passed.

**Verify:** a request made with the old value is refused by the provider (a 401 from its API, or a failed sign-in).

### 5. Scan for leftovers

```bash
make tools secrets
echo "exit=$?"
```

**Verify:** `exit=0` over the whole history; if the old value is still found, history was not rewritten, which is
fine only because step 4 made it worthless. Note it in the record.

### 6. Record it

Write down in the incident record (or `docs/STATE.md` for a planned rotation) which secret, when, who, and the next
rotation date; add expiring secrets to `make expiry-check`.

**Verify:** the record is committed, and for a leak an `ops/failure-log.md` entry names how it leaked and the hardening
(push protection, a new gitleaks rule, a deny rule).
