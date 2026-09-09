# NW SSc Data Engineering Prototype

A cohort dataset of synthetic (non-PHI) systemic sclerosis patients, spanning demographics, disease classification, and longitudinal clinical/molecular measurements. This context covers the data itself and the tools built to explore, QC, and browse it.

## Language

**Subject**:
Any individual referenced by a Subject ID anywhere in the dataset — the supertype spanning both SSc Patients and Control Subjects. Every clinical/molecular table (labs, vitals, MRSS, PFT, BAL, libraries, biopsies) is keyed on Subject, not exclusively on SSc Patient.

**SSc Patient**:
A Subject who is a member of the Registry (has a `demographics`/`ssc_subtype` row). The vast majority of Subjects are SSc Patients; the exception is the 4 Control Subjects.
_Avoid_: "Patient" alone when Control Subjects might also be in scope for a given view — say Subject for the general case.

**Cohort**:
The two-valued grouping every Subject belongs to: `ssc_patient` or `control`. Determines which Registry-only tables (`demographics`, `ssc_subtype`) apply — Control Subjects have none.

**Registry**:
The 1,500 SSc-Patient master list, formed by `demographics.csv` joined 1:1 with `ssc_subtype.csv` (both files have exactly 1,500 unique patient IDs with full overlap). It covers only the `ssc_patient` Cohort — Control Subjects are Subjects but never Registry members.
_Avoid_: Cohort (a specific ssc_patient/control grouping, not this join), master table, "patient population" when Control Subjects might be included (say Subject population instead).

**SSc (Systemic Sclerosis)**:
The autoimmune disease that defines this patient cohort. Two subtypes are recorded in `ssc_subtype.csv`: `dcSSc` (diffuse cutaneous) and `lcSSc` (limited cutaneous).

**MRSS (Modified Rodnan Skin Score)**:
A longitudinal clinical severity score for skin thickening, recorded per patient per visit in `mrss.csv`.

**PFT (Pulmonary Function Test)**:
A longitudinal lung-function measurement (e.g. FVC, FEV1, reported as % predicted), recorded per patient per test in `pft.csv`.

**BAL (Bronchoalveolar Lavage)**:
A procedure record (fluid instilled/recovered volumes, site) in `bal.csv`. Event-based, not a fixed-schedule longitudinal measurement.

**Library** (RNA-seq):
A molecular sample-processing record (RNA extraction/QC/sequencing metadata) in `libraries.csv`. One row generally represents one sample prep, not a clinical encounter.

**Skin Biopsy**:
A procedure record (site, clinical indication, pathology image reference) in `skin_biopsies.csv`. Referenced image files are synthetic paths with no backing image data.

**Subject ID**:
The canonical identifier for a Subject, used everywhere downstream of the loading layer (`subject_id`). Raw files use four different column names for this same concept — `case_number`, `reg_id`, `study_code`, `case number` (with a space) — which the loader renames on ingest; the raw files themselves are left untouched.
_Avoid_: case_number, reg_id, study_code (as identifiers outside the raw-file/loader context — fine to use when referring to the literal source column).

**Observation** (internal/code-level term only):
The generic shape shared by `lab_report.csv`, `vitals.csv`, and `mrss.csv`: a component/category name paired with a value, per patient per date. Used internally by the loader/QC/plotting code to avoid duplicating near-identical long-format handling three times. Does **not** replace the user-facing vocabulary below — Lab Result, Vital Sign, and MRSS/Skin Score stay distinct concepts in any UI, report, or documentation aimed at a person.

**Lab Result**:
One row of `lab_report.csv` — a named lab component (e.g. WBC, HEMOGLOBIN) and its value for a patient on a given date. A user-facing instance of Observation.

**Vital Sign**:
One row of `vitals.csv` — a named vital (e.g. BMI, BP SYSTOLIC, PULSE) and its value for a patient on a given date. A user-facing instance of Observation. Some vitals are naturally paired (BP SYSTOLIC/BP DIASTOLIC) but are stored as independent rows in the source data.

**Control Subject**:
A Subject in the `control` Cohort — one of 4 non-SSc healthy individuals (`SSC_NORM_0101`, `0102`, `0104`, `0110`) that appear in `libraries.csv` (all 4) and partially in `mrss.csv`/`pft.csv`/`vitals.csv` (3 of the 4 — `0104`'s RNA-seq sample failed QC and it has no other records). Confirmed by explicit "healthy control"/"control sample" comments in `libraries.csv`. Never a Registry member (no `demographics`/`ssc_subtype` row). Used as a comparator arm for the RNA-seq work, not a general-purpose control cohort.
_Avoid_: Orphan record, invalid ID — these IDs are a real, intentional Cohort segment, not a data error.

**Subject Filter** (Patient Trajectory):
A criterion that narrows the pool of Subjects available for selection, without itself plotting anything. Three kinds: **Categorical filter** (multi-select over enumerated values, e.g. gender, ethnicity, SSc subtype), **Range filter** (numeric min/max, e.g. height, a Lab Result value), and **Existence filter** (boolean presence-of-any-record check with no value comparison, e.g. "was BAL performed," "ever prescribed drug X"). Selected values within one filter combine with OR; separate filters combine with AND.

**Comorbidity flags** (`ssc_subtype.other_dx`):
A semicolon-separated list of co-occurring conditions (ILD, GERD, PAH, or combinations) recorded alongside the SSc subtype. Despite the column name, this is not a differential/alternate diagnosis — every Registry patient's `diagnosis` is SSc; `other_dx` records comorbidities on top of that.
_Avoid_: "other diagnosis" as a user-facing label — prefer "comorbidities" to avoid implying diagnostic uncertainty.
