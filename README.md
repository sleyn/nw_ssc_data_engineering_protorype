# nw_ssc_data_engineering_protorype
Data engineering assignment

## Setup

```
uv sync
```

This installs the app, the QC/ingestion modules, and the notebook
dependencies (Jupyter) into a local `.venv` managed by `uv`. The
presentation deck's Jupyter dependencies live in a separate
`presentation` group (`uv sync --group presentation`) since they aren't
needed to run the app or CI.

## Deployed app

**[nw-ssc-de.streamlit.app](https://nw-ssc-de.streamlit.app/)** -- hosted on
Streamlit Community Cloud from this repo's `main` branch.

Streamlit Community Cloud manages its own `.streamlit/secrets.toml` on the
deployed container via the app's dashboard **Settings > Secrets**, which
overwrites whatever is in the repo's committed copy of that file. The demo
secrets are committed here so a local `git clone` + run needs no setup step,
but a Cloud deployment still requires the same file's contents to be pasted
into the dashboard **Settings > Secrets** once, by hand.

## Running the app

```
uv run streamlit run app.py
```

Log in with the published demo credentials:

- **Username:** `demo`
- **Password:** `SscDemo2026!`

This is a literal-but-lightweight HIPAA-style demonstration (login, encryption
at rest, audit logging) gated by these published credentials, not a real
access-control boundary.
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

## Presentation

[presentation/slides.qmd](presentation/slides.qmd) is the ~20-minute
interview deck (Quarto/revealjs), covering dataset understanding, the app,
data-quality findings, and design tradeoffs. Rendered outputs
(`presentation/slides.html`, `presentation/slides.pdf`) are committed so
they can be opened with no local Quarto install.

To re-render both `slides.html` and `slides.pdf` after editing the
source:

```
uv sync --group presentation
presentation/render.sh
```

Requires the [Quarto CLI](https://quarto.org/docs/get-started/) (a
separate system binary, not a `uv`-managed package) on `PATH`. The
`presentation` dependency group covers only the Python/Jupyter side
(chunk execution); it's kept separate from `main` (the app) and `dev`
(CI) since neither needs it. The PDF fallback is generated from the
rendered HTML via [decktape](https://github.com/astefanutti/decktape)
(via `npx`, requires Node -- not part of the `uv` project); the script
handles both steps.

## Secrets

`.streamlit/secrets.toml` is committed to this repo, which is not normal
practice for a secrets file. It's deliberate here: the values it holds
(the public demo login and the at-rest encryption key) are intentionally
public so a reviewer can `git clone` and run the app with no manual
secret-provisioning step. **A real (non-demo) deployment would never commit
this file.**
