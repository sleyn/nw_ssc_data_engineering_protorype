# nw_ssc_data_engineering_protorype
Data engineering assignment

## Secrets

`.streamlit/secrets.toml` is committed to this repo, which is not normal
practice for a secrets file. It's deliberate here (see
[ADR 0004](docs/adr/0004-commit-demo-secrets-file.md)): the values it holds
(the public demo login and the at-rest encryption key) are intentionally
public so a reviewer can `git clone` and run the app with no manual
secret-provisioning step. **A real (non-demo) deployment would never commit
this file.**
