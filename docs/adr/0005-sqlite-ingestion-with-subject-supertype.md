---
status: accepted
---

# SQLite as the ingestion boundary, with a Subject supertype table

The 11 CSVs are small enough (~4MB) that pandas alone would work end-to-end, and a database adds no performance benefit here. We chose SQLite as the real ingestion boundary anyway, for two reasons specific to this dataset: (1) the assignment and role both center on data modeling across clinical sources, so a designed schema is a more direct demonstration of that than ad-hoc pandas filtering; (2) it gives a clean, correct home for the Control Subject finding — a `subjects(subject_id, cohort)` supertype table (`cohort` ∈ `ssc_patient`/`control`) that every clinical table's foreign key targets, with `demographics`/`ssc_subtype` as `ssc_patient`-only extension tables. This models cohort membership as a real relationship instead of the 4 Control Subjects showing up as foreign-key violations to be explained away.

Both the EDA notebook and the Streamlit app read from this SQLite store via one shared `data/access.py` (`pandas.read_sql`), never re-parsing the raw CSVs downstream of the build step — pandas remains the tool for actual interactive filtering/plotting, so the app does not grow a hand-written SQL query per view. The built `.db` file is the artifact that gets encrypted at rest per [0002](./0002-encrypt-runtime-store-not-source-csvs.md); it's generated fresh from the committed CSVs at build/startup time and is not itself committed to git.
