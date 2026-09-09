---
status: accepted
---

# Commit the demo credentials/secrets file instead of keeping it out of git

Normal practice is to never commit a secrets file. Here, the values inside it (the public demo login and the at-rest encryption key) are deliberately non-sensitive by design — [0001](./0001-hipaa-controls-with-public-demo-credentials.md) already made them public so reviewers can access the demo. Keeping the file out of git (the usual approach) would mean a reviewer cloning the repo has to manually create `.streamlit/secrets.toml` and copy values out of the README before the app runs locally — friction with no actual security benefit, since the values are published either way. We commit `.streamlit/secrets.toml` directly so `git clone` + run works with no setup step, with a code comment and a README note stating explicitly that a real (non-demo) deployment would never commit this file. This is a deliberate deviation from normal secrets hygiene, kept narrow to this one demo file — worth recording so it doesn't get "fixed" by someone assuming it was an oversight.

**Update (ticket 12, deploy to Streamlit Community Cloud):** the "no setup step" claim above holds for a local `git clone`, but not for Streamlit Community Cloud itself — it manages `.streamlit/secrets.toml` on the deployed container via its own dashboard **Settings > Secrets** feature, which overwrites the repo's committed copy of that exact path (empty by default). The Cloud deployment therefore still needed the same values pasted into that dashboard setting once by hand, documented in the [README](../../README.md#deployed-app). This is a platform quirk of Streamlit Cloud's secrets-injection, not a reason to reconsider committing the file for local use.
