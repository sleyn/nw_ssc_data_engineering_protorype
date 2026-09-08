# Spec: NW SSc Data Engineering Prototype

Build reference for implementing the take-home assignment described in `.scratch/description.txt` (gitignored — see that file for the full brief). Full reasoning behind every decision referenced here lives in `CONTEXT.md` (domain glossary) and `docs/adr/0001`–`0005` (architecture decisions) — this spec doesn't re-derive them, it sequences them into buildable work. Data-quality findings referenced here are detailed in `docs/presentation-notes.md`.

## Problem Statement

I have roughly one working day to explore an unfamiliar synthetic clinical dataset (11 CSVs, ~1,500 SSc patients plus 4 healthy controls, spanning demographics, disease classification, and longitudinal clinical/molecular measurements) and produce, for a job-interview take-home: a data-quality assessment, an exploratory analysis with visualizations, an interactive application that lets a reviewer with no prior knowledge of the dataset explore it at multiple levels (raw structure → cohort-level patterns → group/variable comparisons → individual patient trajectories), and documentation — all reproducible from a public GitHub repository with a running hosted link. Separately, this repo's own conventions (`CLAUDE.md`) call for real HIPAA-style controls (authentication, encryption, audit logging) even though the assignment confirms the data is synthetic and non-PHI and explicitly asks for public access.

## Solution

A small, flat-layout Python project that ingests the 11 raw CSVs into a normalized SQLite store built around a `Subject`/`Cohort` schema (correctly modeling the discovered 4-patient healthy-control cohort as a cohort membership rather than a data error), runs an advisory QC pass over that store (surfacing the specific findings already identified during EDA — mixed-unit height, a corroborated data-entry error, a synthetic placeholder-value artifact, medication-name fragmentation, implausible dose values, PFT range clipping, and PII-shaped columns), encrypts the resulting store at rest, and serves both an EDA notebook and a 4-tab Streamlit app from one shared data-access layer — gated by a login screen with published demo credentials, backed by a minimal audit log, and covered by a lean CI pipeline. Scoped to be fully buildable and deployable within one working day.

## User Stories

**Data ingestion & modeling**

1. As the analyst, I want the four inconsistent patient-identifier column names across the raw CSVs normalized to one canonical identifier at ingestion, so that every downstream join, chart, and QC check operates on one consistent key without editing the raw source files.
2. As the analyst, I want the ingestion step to model every clinical/molecular table against a `Subject` supertype (rather than assuming all subject IDs belong to the SSc Registry), so that the 4 healthy Control Subjects are represented correctly instead of surfacing as broken foreign keys.
3. As the analyst, I want `demographics`/`ssc_subtype` modeled as SSc-Patient-only extension tables of `Subject`, so that the Registry/Cohort relationship in `CONTEXT.md` is reflected directly in the schema.
4. As the analyst, I want the raw CSVs left untouched on disk, with all cleaning/normalization happening in the ingestion step that builds the SQLite store, so that the committed source data stays an honest, inspectable record of what was actually delivered.
5. As a reviewer inspecting the repo, I want the raw CSVs still present and readable in the public repository, so that I can verify the analysis against the original source data myself.
6. As the analyst, I want the ingestion step to run automatically (no manual "did you remember to run the build script" step) whenever the EDA notebook or the app starts, so that both always reflect the current source CSVs without a stale cached store.

**Data-quality checks (QC module)**

7. As the analyst, I want an automated check that reports the mismatch between each raw table's declared patient-identifier column and the canonical identifier, so that future raw-file additions with yet another column name are caught rather than silently mis-joined.
8. As the analyst, I want a key-linkage check that reports which subject IDs in each clinical table fall outside the Registry, distinguishing the known Control Subject cohort from any genuinely unexplained ID, so that a real future data issue isn't masked by the already-understood control-cohort case.
9. As the analyst, I want the height-unit split (inches vs. centimeters) corrected at ingestion (cm-scale values converted to inches), so that every downstream height/BMI calculation is correct by construction.
10. As the analyst, I want `subject_8545`'s demographics weight flagged (not silently corrected) as contradicted by 5 corroborating vitals records, so that the discrepancy is visible to a report reader without inventing a specific replacement value we don't have documented provenance for.
11. As the analyst, I want a generic check that flags any patient/measurement combination whose value never varies across visits, so that synthetic-data placeholder artifacts (like the 160.6-lb weight repeated across 195 patients) are caught generally, not just for the one case already found.
12. As the analyst, I want a generic guideline range-check function runnable against any of PFT, MRSS, labs, and vitals, so that implausible values are caught wherever they occur, and so that a clean result (as with PFT) is itself reported as a finding rather than silently passing with no record.
13. As the analyst, I want medication names normalized at ingestion so that brand name, generic name, and generic abbreviation for the same drug (`CellCept` / `mycophenolate mofetil` / `MMF`) are merged into one canonical label, with the original string preserved in an "as recorded" field, so that prevalence charts reflect the true prescribing pattern.
14. As the analyst, I want the dose field parsed via a small lookup table (value, unit, frequency) covering the dataset's 24 distinct dose strings, so that dose becomes usable structured data instead of opaque free text.
15. As the analyst, I want dose-implausibility checks (negative/zero values, magnitude outliers, unit-type mismatches) built on top of the parsed dose data, so that injected data-entry errors in the dose field are surfaced explicitly.
16. As the analyst, I want blank-medication-with-dose and blank-dose-with-medication tracked as two distinct QC findings, so that the two different kinds of missing-data gap aren't conflated into one "has nulls" statistic.
17. As the analyst, I want every QC check to be advisory only — reporting findings without blocking ingestion or silently altering the underlying data — so that the tool remains an exploration aid rather than a gate that could hide or "fix" data a reviewer should be able to see for themselves.
18. As a reviewer, I want a generated QC report (in the app and as a standalone document) that lists every finding above in plain language, so that I can assess the candidate's data-quality judgment without re-deriving it myself.

**Exploratory analysis**

19. As the analyst, I want an EDA notebook that reads from the same ingested SQLite store as the app (not a separate ad-hoc CSV read), so that the analysis and the app can never silently diverge in what they consider "the data."
20. As a reviewer, I want the EDA output to include visualizations of cohort-level structure (demographics distributions, subtype breakdown, missingness patterns across tables), so that I can see the shape of the dataset without reading raw code.
21. As a reviewer, I want the EDA output to explicitly call out the Control Subject cohort discovery and the placeholder-weight-value finding as narrative findings (not just numbers in a table), so that the analytical reasoning behind them is visible, not just their existence.

**Interactive application**

22. As a reviewer with no prior knowledge of the dataset, I want a "Data & Dictionary" view showing each table's structure, row/column counts, and a plain-language description of each field, so that I can orient myself before exploring further.
23. As a reviewer, I want a "Cohort Overview" view showing demographic distributions, subtype breakdown, and per-table coverage (how many patients have each type of record), so that I understand the population before comparing subgroups.
24. As a reviewer, I want a "Compare & Discover" view where I can freely pick any two or more variables — from any table, at any level (demographic, aggregate-per-patient, or a specific longitudinal component series) — and have the app render an appropriate chart automatically, so that I can find structure in the data myself rather than being limited to a fixed set of pre-chosen charts.
25. As a reviewer, I want the option to overlay the 4 Control Subjects on a comparison chart when the selected variable has data for them, so that I can see the SSc-vs-healthy contrast where it's meaningful, without it being forced into every view where the sample is too thin to be useful.
26. As a reviewer, I want a "Patient Trajectory" view where I select one individual and see their longitudinal record (labs, vitals, MRSS, PFT, medications) plotted over time, so that I can understand what the disease course looks like for a single person.
27. As a reviewer, I want every view labeled using the project's actual clinical/domain vocabulary (Lab Result, Vital Sign, MRSS, not a generic "Observation"), so that the app reads as clinically literate rather than generically technical.

**HIPAA-style controls**

28. As the analyst, I want the app gated behind a login screen using published demo credentials, so that the deployment demonstrates real authentication while remaining accessible to reviewers.
29. As the analyst, I want the app's runtime data store encrypted at rest (built fresh from the plaintext committed CSVs, never itself committed to git), so that there's a genuine encryption-at-rest component to point to and explain.
30. As the analyst, I want every login and every patient-record view logged to a local audit log with timestamp and user, so that there's a real audit trail, with the known limitation (ephemeral hosting filesystem) documented rather than silently glossed over.
31. As the analyst, I want the demo credentials and encryption key stored in a committed secrets file with an explicit code comment and README note explaining this is a deliberate demo-only deviation from normal secrets hygiene, so that a reviewer scanning the code understands why it deviates from convention rather than assuming it's an oversight.

**Documentation & reproducibility**

32. As a reviewer, I want a README with clear setup and run instructions (`uv sync`, how to run the QC report, how to run the app locally, the deployed link), so that I can get the project running without guessing.
33. As a reviewer, I want the public GitHub repository to be runnable end-to-end from a fresh clone with no manual secret-provisioning step, so that reproducing the analysis doesn't depend on me having out-of-band access to anything.

## Implementation Decisions

- **Package layout**: flat, not layered — a data/ingestion module (CSV → normalized SQLite build, per ADR 0005), a QC module (the checks in User Stories 7–17), an access module (shared `pandas.read_sql`-based read layer used by both the notebook and the app), an auth module (login + audit logging), and the Streamlit app itself (4 tabs). No deep package hierarchy beyond this.
- **Schema**: a `subjects(subject_id, cohort)` supertype table (`cohort` ∈ `ssc_patient`/`control`); `demographics`/`ssc_subtype` become `ssc_patient`-only extension tables; all other clinical/molecular tables foreign-key to `subjects` broadly, per ADR 0005.
- **Data access pattern**: the notebook and app never read raw CSVs directly past the ingestion step — both go through the same `pandas.read_sql`-based access layer against the built SQLite store. Interactive filtering in the app happens in pandas after a table/query read, not via hand-written per-view SQL.
- **Encryption**: the built SQLite file is the artifact encrypted at rest (Fernet, key from a committed secrets file), decrypted to a temp path at process startup, per ADR 0002. It is rebuilt fresh from the CSVs at every process start, not persisted or committed.
- **Auth**: a login form checked against one hashed credential pair read from the committed secrets file (`.streamlit/secrets.toml`), per ADR 0004.
- **Audit logging**: append-only local log file recording login events and patient-record-view events (user, timestamp, action). No database, no external log shipping. Documented as ephemeral under the chosen hosting (Streamlit Community Cloud resets local files on redeploy/restart) rather than engineered around.
- **PII handling**: patient first/last name and birth date are excluded from every downstream view and output (subject_id + derived age-at-event only); `ENTRY_USER_NAME` (clinician identity) is retained and shown, since it's operational metadata rather than a PHI-analogue field.
- **Vocabulary display mapping**: raw category/vocabulary values (`component_name`, `vital_type_name_category`, PFT `DESCRIPTION`/`NAME`) are left untouched in the QC report (so the source inconsistency is visible as a finding) but mapped to clean display labels for the app's variable picker via a separate lookup, not by rewriting the underlying values.
- **Medication/dose normalization**: hardcoded lookup tables (not fuzzy matching or NLP) — a 3-way merge for medication names, a 24-row lookup for dose strings — since the full space of distinct raw values is small and fully enumerable in this dataset.
- **Deployment target**: Streamlit Community Cloud, using the existing `origin` remote (`github.com/sleyn/nw_ssc_data_engineering_protorype`).
- **CI**: a single GitHub Actions workflow running ruff, mypy, and pytest.

## Testing Decisions

- Tests target external behavior — what a check reports or what the access layer returns — not internal implementation details of how a module is structured internally.
- **Ingestion**: given the raw CSVs, the built store's `subjects` table contains exactly 1,504 rows (1,500 `ssc_patient` + 4 `control`), and every clinical table's identifier resolves to a row in `subjects`. Given the raw height column's known bimodal split, the built store contains only inch-scale height values.
- **QC checks**: each check (key-linkage, constant-value-across-visits, range-check, dose-implausibility) is tested against small fixture tables engineered to contain a known instance of what it's supposed to catch, plus a clean table it should pass without any findings.
- **Normalization lookups**: given each of the 17 raw medication strings and 24 raw dose strings actually present in the dataset, the normalization functions produce the expected canonical label / parsed value-unit-frequency for every one of them (an exhaustive table-driven test, since the input space is fully enumerable).
- **Prior art**: none yet in this repo — this is the first test suite; these tests establish the pattern for anything added later.
- No UI/visual testing of the Streamlit app itself is in scope given the time budget; the app is manually exercised against the golden path (each of the 4 tabs, plus the Control Subject overlay toggle) before calling the build done.

## Out of Scope

- The ~20-minute presentation deck — only needed if the committee invites an interview; today's deliverable is the repo, the running app link, and documentation.
- Persistent audit logging across app restarts/redeploys — accepted as a documented limitation of the ephemeral hosting filesystem rather than engineered around.
- A general-purpose free-text medication/dose parser — the lookup-table approach is scoped specifically to this dataset's fully-enumerable 17/24 distinct values, not a reusable NLP component.
- Full production-grade HIPAA compliance — this is a literal-but-lightweight demonstration gated by published demo credentials, not a real access-control boundary.
- SQL written per-view for the app's interactive filtering — pandas after `read_sql` is used instead.
- Fuzzy-matching or heuristic reconciliation of unexplained subject IDs beyond the confirmed Control Subject cohort — any future unexplained ID is reported as a QC finding, not auto-resolved.
- A layered/abstracted package architecture, a multi-page (multi-file) Streamlit app structure, or exhaustive test coverage — all traded against the one-day time budget in favor of analytical depth.

## Further Notes

- Full domain vocabulary: `CONTEXT.md`. Full architecture reasoning: `docs/adr/0001`–`0005`. Full data-quality findings narrative (for presentation prep): `docs/presentation-notes.md`.
- This spec was produced via a grilling + domain-modeling session rather than a formal issue-tracker workflow (this repo does not use GitHub Issues or the `triage` skill's label vocabulary for this project — see conversation history for that decision) — it lives as a plain file in `docs/` rather than a tracked issue.
- Time budget: same-day (originally: "finish tomorrow by end of work day"), which is the primary constraint behind every scope cut listed above.
