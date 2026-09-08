# QC Report

Advisory findings only — nothing here blocks ingestion or mutates the underlying data.

## Key linkage

- 4 of 4 confirmed Control Subjects found outside the Registry (SSC_NORM_0101, SSC_NORM_0102, SSC_NORM_0104, SSC_NORM_0110).

## Demographics weight vs. vitals

- subject_8545: demographics.weight=22.5 lbs is physiologically implausible and contradicted by 5 vitals record(s) averaging 160.6 lbs — flagged, not auto-corrected.

## Constant value across visits

- vitals: WEIGHT IN POUND is constant at 160.6 across all visits for 178 patients (848 total records) — 106x more common than expected if personal-constant values were spread evenly.

## Guideline range checks

- pft: DLCO_SB — 0 of 829 readings fall outside the guideline range 20-150 (observed range: 40-130).
- pft: FEV1 — 0 of 1723 readings fall outside the guideline range 30-150 (observed range: 40-130).
- pft: FVC — 0 of 1723 readings fall outside the guideline range 30-150 (observed range: 40-130).
- pft: DLCO_SB, FEV1, FVC all share an identical observed range of 40-130 despite being different measures — suggestive of generator clipping rather than organic variation.
- mrss: MRSS — 0 of 3113 readings fall outside the guideline range 0-51 (observed range: 0-39).
- lab_report: ABSOLUTE BASOPHILS — 0 of 1357 readings fall outside the guideline range 0-0.2 (observed range: 0-0.14).
- lab_report: ABSOLUTE EOSINOPHILS — 18 of 1391 readings fall outside the guideline range 0-0.5 (observed range: 0-0.71).
- lab_report: ABSOLUTE LYMPHOCYTES — 279 of 1322 readings fall outside the guideline range 1-4.8 (observed range: 0.18-9999).
- lab_report: ABSOLUTE MONOCYTE — 39 of 1399 readings fall outside the guideline range 0.1-1 (observed range: 0.1-1.63).
- lab_report: BASOPHILS — 0 of 1362 readings fall outside the guideline range 0-2 (observed range: 0-1.6).
- lab_report: DIFFERENTIAL TYPE has no numeric readings to check — skipped.
- lab_report: EOSINOPHILS — 16 of 1366 readings fall outside the guideline range 0-6 (observed range: 0-6.6).
- lab_report: HEMATOCRIT — 515 of 1914 readings fall outside the guideline range 36-52 (observed range: 24.8-52.9).
- lab_report: HEMOGLOBIN — 444 of 1917 readings fall outside the guideline range 12-18 (observed range: -4-17).
- lab_report: LYMPHOCYTES — 608 of 1609 readings fall outside the guideline range 20-45 (observed range: -12-47.5).
- lab_report: MCH — 360 of 2044 readings fall outside the guideline range 27-33 (observed range: 24-9999).
- lab_report: MCHC — 350 of 1874 readings fall outside the guideline range 32-36 (observed range: 30-9999).
- lab_report: MCV — 85 of 1888 readings fall outside the guideline range 80-100 (observed range: -10-102).
- lab_report: MONOCYTES, BODY FLUID has no guideline range defined — skipped (819 readings, observed range 2-14.4).
- lab_report: NEUTROPHILS — 178 of 1587 readings fall outside the guideline range 40-75 (observed range: -12-90).
- lab_report: NM BKR ABSOLUTE NEUTROPHIL — 15 of 785 readings fall outside the guideline range 1.5-8 (observed range: -10-9.78).
- lab_report: Platelet Count — 85 of 1854 readings fall outside the guideline range 150-450 (observed range: 90-486).
- lab_report: RBC — 384 of 1842 readings fall outside the guideline range 4.2-6.1 (observed range: 0-6).
- lab_report: RDW — 586 of 1914 readings fall outside the guideline range 11.5-15.5 (observed range: 11-18.3).
- lab_report: WBC — 169 of 1878 readings fall outside the guideline range 4-11 (observed range: 3-999).
- vitals: BMI — 65 of 7777 readings fall outside the guideline range 15-50 (observed range: 10.3-56.7).
- vitals: BP DIASTOLIC — 0 of 7848 readings fall outside the guideline range 40-120 (observed range: 55-102).
- vitals: BP SYSTOLIC — 0 of 7848 readings fall outside the guideline range 70-200 (observed range: 95-165).
- vitals: PULSE — 0 of 8381 readings fall outside the guideline range 40-150 (observed range: 50-110).
- vitals: WEIGHT IN POUND — 0 of 8396 readings fall outside the guideline range 50-400 (observed range: 54.2-278.9).

## Medication name merge

- mycophenolate mofetil (211), CellCept (192), MMF (189) are the same drug, canonicalized to 'mycophenolate mofetil' (592 combined records; original preserved in an as-recorded field).

## Dose implausibility

- Dose '-1 tablet daily' (7 occurrence(s)): non-positive dose (-1 tablet).
- Dose '-25 mg daily' (4 occurrence(s)): non-positive dose (-25 mg).
- Dose '0 mg daily' (8 occurrence(s)): non-positive dose (0 mg).
- Dose '10000 mg every hour' (7 occurrence(s)): magnitude outlier — 10000 mg is far above the plausible per-dose range for mg (~2000 mg).
- Dose '250 g twice daily' (7 occurrence(s)): magnitude outlier — 250 g is far above the plausible per-dose range for g (~10 g).
- Dose '500 mL tablets daily' (5 occurrence(s)): unit-type mismatch — a volume unit (mL) paired with a solid dosage form.
- Dose '999 tablets daily' (7 occurrence(s)): magnitude outlier — 999 tablet is far above the plausible per-dose range for tablet (~20 tablet).

## Blank medication/dose gaps

- 20 row(s) have a dose but no medication name.
- 85 row(s) have a medication name but no dose.
