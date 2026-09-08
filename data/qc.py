"""Advisory data-quality checks over the built Subject/Cohort store, plus a
rendered QC report (docs/presentation-notes.md "Data-quality issues").

Every check here is read-only: it reports findings as plain-English strings
and never mutates the store or blocks anything reading from it. Checks take
plain DataFrames (not a live connection) so they can be exercised directly
against small hand-built fixtures in tests; `generate_report` is the only
function that touches the store itself, pulling the tables each check needs
via `data.store.open_store`.
"""

import sqlite3

import pandas as pd

from data.normalize import add_canonical_medication_columns, parse_dose
from data.store import open_store

# The 4 healthy Control Subjects confirmed by libraries.csv's own "healthy
# control sample" comments (CONTEXT.md). Any other subject_id that ends up
# outside the Registry (data.ingest classifies it cohort='control' too, since
# it has no way to know it isn't a confirmed control) is a genuinely
# unexplained ID, not a second instance of this known case.
CONFIRMED_CONTROL_SUBJECT_IDS: frozenset[str] = frozenset(
    {"SSC_NORM_0101", "SSC_NORM_0102", "SSC_NORM_0104", "SSC_NORM_0110"}
)

# A per-patient value that never varies across their own visits is, on its
# own, common in this dataset for low-cardinality vitals like blood pressure
# or pulse (most patients land on *some* personal constant) — not itself a
# synthetic-data smell. What IS a smell (docs/presentation-notes.md: 160.6 lb
# appearing 870 times across 195 patients, "the next most common weight value
# appears only 39 times") is one specific value dominating far more patients
# than it would if personal-constant values were spread evenly across the
# distinct values actually observed. MIN_CONSTANT_VALUE_DOMINANCE_RATIO is
# that dominance threshold; MIN_CONSTANT_VALUE_SUBJECTS is a floor so a small
# sample can't hit a high ratio by chance.
MIN_CONSTANT_VALUE_VISITS = 2
MIN_CONSTANT_VALUE_SUBJECTS = 10
MIN_CONSTANT_VALUE_DOMINANCE_RATIO = 25.0

# Approximate adult reference ranges used for QC purposes only (not
# diagnostic thresholds). A measure with no entry here is reported as
# "no guideline range defined" rather than silently skipped.
PFT_GUIDELINE_RANGES: dict[str, tuple[float, float]] = {
    "FVC": (30.0, 150.0),
    "FEV1": (30.0, 150.0),
    "DLCO_SB": (20.0, 150.0),
}
MRSS_GUIDELINE_RANGES: dict[str, tuple[float, float]] = {
    "MRSS": (0.0, 51.0),  # 17 body sites x 0-3 (modified Rodnan skin score)
}
VITALS_GUIDELINE_RANGES: dict[str, tuple[float, float]] = {
    "BMI": (15.0, 50.0),
    "BP SYSTOLIC": (70.0, 200.0),
    "BP DIASTOLIC": (40.0, 120.0),
    "PULSE": (40.0, 150.0),
    "WEIGHT IN POUND": (50.0, 400.0),
}
LAB_GUIDELINE_RANGES: dict[str, tuple[float, float]] = {
    "WBC": (4.0, 11.0),
    "HEMOGLOBIN": (12.0, 18.0),
    "HEMATOCRIT": (36.0, 52.0),
    "MCV": (80.0, 100.0),
    "RDW": (11.5, 15.5),
    "Platelet Count": (150.0, 450.0),
    "NEUTROPHILS": (40.0, 75.0),
    "LYMPHOCYTES": (20.0, 45.0),
    "ABSOLUTE LYMPHOCYTES": (1.0, 4.8),
    "ABSOLUTE EOSINOPHILS": (0.0, 0.5),
    "NM BKR ABSOLUTE NEUTROPHIL": (1.5, 8.0),
    "ABSOLUTE MONOCYTE": (0.1, 1.0),
    "MCH": (27.0, 33.0),
    "MCHC": (32.0, 36.0),
    "EOSINOPHILS": (0.0, 6.0),
    "ABSOLUTE BASOPHILS": (0.0, 0.2),
    "BASOPHILS": (0.0, 2.0),
    "RBC": (4.2, 6.1),
}

# A dose's parsed magnitude above this many units is implausible for a single
# administration, regardless of frequency (docs/presentation-notes.md: "250 g
# twice daily", "10000 mg every hour", "999 tablets daily").
DOSE_MAGNITUDE_MAX: dict[str, float] = {
    "mg": 2000.0,
    "g": 10.0,
    "mcg": 1000.0,
    "IU": 100000.0,
    "tablet": 20.0,
    "mL": 1000.0,
}
SOLID_DOSAGE_FORM_KEYWORDS = ("tablet", "tablets", "capsule", "capsules")


def check_key_linkage(
    subjects: pd.DataFrame,
    *,
    confirmed_control_ids: frozenset[str] = CONFIRMED_CONTROL_SUBJECT_IDS,
) -> list[str]:
    """Every subject_id outside the Registry (cohort='control') should be one
    of the confirmed Control Subjects; anything else is unexplained and needs
    investigation rather than being silently absorbed into that known case."""
    control_ids = set(subjects.loc[subjects["cohort"] == "control", "subject_id"])
    confirmed_found = sorted(control_ids & confirmed_control_ids)
    missing_confirmed = sorted(confirmed_control_ids - control_ids)
    unexplained = sorted(control_ids - confirmed_control_ids)

    findings = [
        f"{len(confirmed_found)} of {len(confirmed_control_ids)} confirmed Control Subjects "
        f"found outside the Registry ({', '.join(confirmed_found) or 'none'})."
    ]
    if missing_confirmed:
        findings.append(
            "Confirmed Control Subject(s) not present in this data: "
            f"{', '.join(missing_confirmed)}."
        )
    if unexplained:
        findings.append(
            f"{len(unexplained)} subject ID(s) fall outside the Registry and do NOT match the "
            f"confirmed Control Subject cohort — needs investigation: {', '.join(unexplained)}."
        )
    return findings


def check_demographics_weight_vs_vitals(
    demographics: pd.DataFrame,
    vitals: pd.DataFrame,
    *,
    plausible_weight_lbs: tuple[float, float] = (50.0, 600.0),
    min_corroborating: int = 2,
    vitals_weight_measure: str = "WEIGHT IN POUND",
) -> list[str]:
    """Flag (not correct) any demographics.weight outside a physiologically
    plausible range for a living adult, noting whether vitals.csv has enough
    corroborating records to establish what the value plausibly should be."""
    low, high = plausible_weight_lbs
    implausible = demographics[(demographics["weight"] < low) | (demographics["weight"] > high)]
    weight_vitals = vitals[vitals["vital_type_name_category"] == vitals_weight_measure]

    findings = []
    for _, row in implausible.iterrows():
        subject_id = row["subject_id"]
        corroborating = weight_vitals.loc[weight_vitals["subject_id"] == subject_id, "vital_value"]
        if len(corroborating) >= min_corroborating:
            findings.append(
                f"{subject_id}: demographics.weight={row['weight']:g} lbs is physiologically "
                f"implausible and contradicted by {len(corroborating)} vitals record(s) "
                f"averaging {corroborating.mean():g} lbs — flagged, not auto-corrected."
            )
        else:
            findings.append(
                f"{subject_id}: demographics.weight={row['weight']:g} lbs is physiologically "
                "implausible with no corroborating vitals records to cross-check against."
            )
    return findings


def check_constant_value_across_visits(
    observations: pd.DataFrame,
    *,
    subject_col: str,
    measure_col: str,
    value_col: str,
    table_label: str,
    min_visits: int = MIN_CONSTANT_VALUE_VISITS,
    min_subjects: int = MIN_CONSTANT_VALUE_SUBJECTS,
    min_dominance_ratio: float = MIN_CONSTANT_VALUE_DOMINANCE_RATIO,
) -> list[str]:
    """Flag a (measure, value) combination where the same exact value is many
    different patients' own personal constant (never varies across their
    visits) far more often than it would if personal-constant values were
    spread evenly across the distinct values actually observed for that
    measure. A measure where every patient's constant lands on a different
    value (no dominance) or where only one value is ever observed at all
    (no distribution to be uneven within) is left unflagged."""
    df = observations.dropna(subset=[value_col])
    per_subject_measure = df.groupby([subject_col, measure_col])[value_col].agg(
        visits="count", distinct_values="nunique", value="first"
    )
    enough_visits = per_subject_measure["visits"] >= min_visits
    always_the_same = per_subject_measure["distinct_values"] == 1
    constant = per_subject_measure[enough_visits & always_the_same].reset_index()
    if constant.empty:
        return []

    findings: list[tuple[int, str]] = []
    for measure, group in constant.groupby(measure_col):
        by_value = group.groupby("value").agg(
            subjects=(subject_col, "nunique"), records=("visits", "sum")
        )
        n_distinct_values = len(by_value)
        if n_distinct_values <= 1:
            continue  # only one value ever observed - no unevenness to detect

        total_subjects = int(group[subject_col].nunique())
        expected_share = 1 / n_distinct_values
        for value, row in by_value.iterrows():
            subjects = int(row["subjects"])
            if subjects < min_subjects:
                continue
            ratio = (subjects / total_subjects) / expected_share
            if ratio >= min_dominance_ratio:
                records = int(row["records"])
                findings.append(
                    (
                        records,
                        f"{table_label}: {measure} is constant at {value} across all visits "
                        f"for {subjects} patients ({records} total records) — {ratio:.0f}x more "
                        "common than expected if personal-constant values were spread evenly.",
                    )
                )

    findings.sort(key=lambda pair: pair[0], reverse=True)
    return [message for _, message in findings]


def check_guideline_range(
    observations: pd.DataFrame,
    *,
    measure_col: str,
    value_col: str,
    ranges: dict[str, tuple[float, float]],
    table_label: str,
) -> list[str]:
    """Run a guideline range against every measure present, reporting a line
    per measure regardless of outcome — a clean result (no violations) is
    itself a finding worth recording, not a silent pass. Also flags any two
    or more measures in the same table that share an identical observed
    range, a sign of generator clipping rather than organic variation."""
    findings: list[str] = []
    observed_bounds: dict[str, tuple[float, float]] = {}

    for measure, group in observations.groupby(measure_col):
        measure = str(measure)
        values = pd.to_numeric(group[value_col], errors="coerce").dropna()
        if values.empty:
            findings.append(f"{table_label}: {measure} has no numeric readings to check — skipped.")
            continue

        obs_min, obs_max = float(values.min()), float(values.max())
        if measure not in ranges:
            findings.append(
                f"{table_label}: {measure} has no guideline range defined — skipped "
                f"({len(values)} readings, observed range {obs_min:g}-{obs_max:g})."
            )
            continue

        low, high = ranges[measure]
        violations = int(((values < low) | (values > high)).sum())
        observed_bounds[measure] = (obs_min, obs_max)
        findings.append(
            f"{table_label}: {measure} — {violations} of {len(values)} readings fall outside "
            f"the guideline range {low:g}-{high:g} (observed range: {obs_min:g}-{obs_max:g})."
        )

    by_bounds: dict[tuple[float, float], list[str]] = {}
    for measure, bounds in observed_bounds.items():
        by_bounds.setdefault(bounds, []).append(measure)
    for bounds, measures in sorted(by_bounds.items()):
        if len(measures) >= 2:
            findings.append(
                f"{table_label}: {', '.join(sorted(measures))} all share an identical observed "
                f"range of {bounds[0]:g}-{bounds[1]:g} despite being different measures — "
                "suggestive of generator clipping rather than organic variation."
            )

    return findings


def check_medication_name_merge(medications: pd.DataFrame) -> list[str]:
    """Report every group of raw medication strings that canonicalize to the
    same drug — generic over whatever MEDICATION_CANONICAL_MAP contains, not
    hardcoded to the CellCept/MMF case."""
    normalized = add_canonical_medication_columns(medications).dropna(subset=["medication"])

    findings = []
    for canonical, group in normalized.groupby("medication"):
        counts = group["medication_as_recorded"].value_counts()
        if len(counts) <= 1:
            continue
        detail = ", ".join(f"{name} ({n})" for name, n in counts.items())
        findings.append(
            f"{detail} are the same drug, canonicalized to '{canonical}' "
            f"({int(counts.sum())} combined records; original preserved in an as-recorded field)."
        )
    return findings


def check_dose_implausibility(medications: pd.DataFrame) -> list[str]:
    """Flag non-positive doses, magnitude outliers, and unit-type mismatches
    among the dataset's distinct dose strings (built on `parse_dose`)."""
    findings = []
    counts = medications["dose"].value_counts(dropna=True)
    for raw_dose in sorted(counts.index):
        parsed = parse_dose(raw_dose)
        reasons = []

        if parsed.value is not None and parsed.value <= 0:
            reasons.append(f"non-positive dose ({parsed.value:g} {parsed.unit})")
        elif (
            parsed.value is not None
            and parsed.unit is not None
            and parsed.unit in DOSE_MAGNITUDE_MAX
            and parsed.value > DOSE_MAGNITUDE_MAX[parsed.unit]
        ):
            reasons.append(
                f"magnitude outlier — {parsed.value:g} {parsed.unit} is far above the plausible "
                f"per-dose range for {parsed.unit} (~{DOSE_MAGNITUDE_MAX[parsed.unit]:g} "
                f"{parsed.unit})"
            )

        has_solid_form_word = any(kw in raw_dose.lower() for kw in SOLID_DOSAGE_FORM_KEYWORDS)
        if parsed.unit == "mL" and has_solid_form_word:
            reasons.append(
                "unit-type mismatch — a volume unit (mL) paired with a solid dosage form"
            )

        if reasons:
            n = int(counts[raw_dose])
            findings.append(f"Dose {raw_dose!r} ({n} occurrence(s)): {'; '.join(reasons)}.")
    return findings


def check_blank_medication_dose_gaps(medications: pd.DataFrame) -> list[str]:
    """Report blank-medication-with-dose and blank-dose-with-medication as two
    distinct counts rather than conflating them into one "has nulls" stat."""
    dose_no_medication = int((medications["medication"].isna() & medications["dose"].notna()).sum())
    medication_no_dose = int((medications["dose"].isna() & medications["medication"].notna()).sum())
    return [
        f"{dose_no_medication} row(s) have a dose but no medication name.",
        f"{medication_no_dose} row(s) have a medication name but no dose.",
    ]


def generate_report(conn: sqlite3.Connection) -> str:
    """Run every QC check against the built store and render the results as a
    human-readable Markdown report."""
    subjects = pd.read_sql("SELECT * FROM subjects", conn)
    demographics = pd.read_sql("SELECT * FROM demographics", conn)
    vitals = pd.read_sql("SELECT * FROM vitals", conn)
    lab_report = pd.read_sql("SELECT * FROM lab_report", conn)
    mrss = pd.read_sql("SELECT * FROM mrss", conn).assign(measure="MRSS")
    pft = pd.read_sql("SELECT * FROM pft", conn)
    medications = pd.read_sql("SELECT * FROM medications", conn)

    sections = [
        ("Key linkage", check_key_linkage(subjects)),
        (
            "Demographics weight vs. vitals",
            check_demographics_weight_vs_vitals(demographics, vitals),
        ),
        (
            "Constant value across visits",
            [
                *check_constant_value_across_visits(
                    vitals,
                    subject_col="subject_id",
                    measure_col="vital_type_name_category",
                    value_col="vital_value",
                    table_label="vitals",
                ),
                *check_constant_value_across_visits(
                    lab_report,
                    subject_col="subject_id",
                    measure_col="component_name",
                    value_col="value",
                    table_label="lab_report",
                ),
                *check_constant_value_across_visits(
                    mrss,
                    subject_col="subject_id",
                    measure_col="measure",
                    value_col="mrss_score",
                    table_label="mrss",
                ),
                *check_constant_value_across_visits(
                    pft,
                    subject_col="subject_id",
                    measure_col="NAME",
                    value_col="ORD_VALUE",
                    table_label="pft",
                ),
            ],
        ),
        (
            "Guideline range checks",
            [
                *check_guideline_range(
                    pft,
                    measure_col="NAME",
                    value_col="ORD_VALUE",
                    ranges=PFT_GUIDELINE_RANGES,
                    table_label="pft",
                ),
                *check_guideline_range(
                    mrss,
                    measure_col="measure",
                    value_col="mrss_score",
                    ranges=MRSS_GUIDELINE_RANGES,
                    table_label="mrss",
                ),
                *check_guideline_range(
                    lab_report,
                    measure_col="component_name",
                    value_col="value",
                    ranges=LAB_GUIDELINE_RANGES,
                    table_label="lab_report",
                ),
                *check_guideline_range(
                    vitals,
                    measure_col="vital_type_name_category",
                    value_col="vital_value",
                    ranges=VITALS_GUIDELINE_RANGES,
                    table_label="vitals",
                ),
            ],
        ),
        ("Medication name merge", check_medication_name_merge(medications)),
        ("Dose implausibility", check_dose_implausibility(medications)),
        ("Blank medication/dose gaps", check_blank_medication_dose_gaps(medications)),
    ]

    lines = [
        "# QC Report",
        "",
        "Advisory findings only — nothing here blocks ingestion or mutates the underlying data.",
        "",
    ]
    for title, findings in sections:
        lines.append(f"## {title}")
        lines.append("")
        if findings:
            lines.extend(f"- {finding}" for finding in findings)
        else:
            lines.append("No findings.")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    from pathlib import Path

    from data.store import build_encrypted_store

    build_encrypted_store()
    conn = open_store()
    try:
        report = generate_report(conn)
    finally:
        conn.close()

    out_path = Path(__file__).parent.parent / "docs" / "qc_report.md"
    out_path.write_text(report)
    print(f"Wrote QC report to {out_path}")
