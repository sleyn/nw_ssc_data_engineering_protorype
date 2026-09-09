# nw_ssc_data_engineering_protorype
Data engineering assignment

## Setup

```
uv sync
```

This installs the app, the QC/ingestion modules, and the notebook
dependencies (Jupyter) into a local `.venv` managed by `uv`.

## Deployed app

**[nw-ssc-de.streamlit.app](https://nw-ssc-de.streamlit.app/)** -- hosted on
Streamlit Community Cloud from this repo's `main` branch.

Streamlit Community Cloud manages its own `.streamlit/secrets.toml` on the
deployed container via the app's dashboard **Settings > Secrets**, which
overwrites whatever is in the repo's committed copy of that file (empty by
default, causing a `RuntimeError` on login until set). So although
[ADR 0004](docs/adr/0004-commit-demo-secrets-file.md) commits the demo
secrets so a local `git clone` + run needs no setup step, a Cloud deployment
still needs the same file's contents pasted into that dashboard setting once,
by hand.

## Running the app

```
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

## Running the QC report standalone

```
uv run python -m data.qc
```

This builds the encrypted store fresh from `data/data_v3`, runs every
advisory QC check against it, and (re)writes
[docs/qc_report.md](docs/qc_report.md). The checks are advisory only --
they report findings in plain language and never mutate the underlying
data. The same report is linked from the app's Data & Dictionary tab.

## Viewing the EDA notebook

[notebooks/eda.ipynb](notebooks/eda.ipynb) is committed with its outputs, so
it renders directly on GitHub with no setup. To run it locally instead:

```
uv run jupyter lab notebooks/eda.ipynb
```

The notebook reads exclusively through `data/access.py`, the same
data-access layer the app uses, and expects to be run with its own
directory (`notebooks/`) as the working directory -- which is how
Jupyter opens it by default.

## Secrets

`.streamlit/secrets.toml` is committed to this repo, which is not normal
practice for a secrets file. It's deliberate here (see
[ADR 0004](docs/adr/0004-commit-demo-secrets-file.md)): the values it holds
(the public demo login and the at-rest encryption key) are intentionally
public so a reviewer can `git clone` and run the app with no manual
secret-provisioning step. **A real (non-demo) deployment would never commit
this file.**
