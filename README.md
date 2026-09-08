# nw_ssc_data_engineering_protorype
Data engineering assignment

## Running the app

```
uv sync
uv run streamlit run app.py
```

Log in with the published demo credentials:

- **Username:** `demo`
- **Password:** `SscDemo2026!`

This is a literal-but-lightweight HIPAA-style demonstration (login, encryption
at rest, audit logging) gated by these published credentials, not a real
access-control boundary -- see [docs/spec.md](docs/spec.md) and
[ADR 0001](docs/adr/0001-hipaa-controls-with-public-demo-credentials.md).
Every login attempt (success and failure) is appended to a local
`audit.log` file with timestamp and user; this log does not persist across
restarts/redeploys under the chosen ephemeral hosting (documented limitation,
spec "Audit logging").

## Secrets

`.streamlit/secrets.toml` is committed to this repo, which is not normal
practice for a secrets file. It's deliberate here (see
[ADR 0004](docs/adr/0004-commit-demo-secrets-file.md)): the values it holds
(the public demo login and the at-rest encryption key) are intentionally
public so a reviewer can `git clone` and run the app with no manual
secret-provisioning step. **A real (non-demo) deployment would never commit
this file.**
