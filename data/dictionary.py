"""Table/field dictionary for the "Data & Dictionary" tab (User Story 22).

Row/column counts and column names are read live from the built store, so
they can never drift from what is actually in it. The plain-language
descriptions themselves are hand-written -- informed by the domain glossary
(``CONTEXT.md``) and by the QC investigation's findings (``docs/qc_report.md``,
``data/qc.py``), which is why several descriptions below call out a specific
QC finding for that field rather than describing it in the abstract.

PII columns (``CONTEXT.md`` / spec "PII handling": patient first/last name
and birth date) are deliberately left out of the field list this module
returns -- not just undescribed. Suppression is derived from
``data.access.non_pii_columns`` (the same allow-list the access layer itself
enforces for query results) rather than a second, independently maintained
list, so the two views of "what's PII here" can't silently drift apart.
"""

import sqlite3
from typing import NamedTuple

import pandas as pd

from data.access import non_pii_columns

# Every table in the built store, in the order the app should present them.
ALL_TABLES: tuple[str, ...] = (
    "subjects",
    "demographics",
    "ssc_subtype",
    "vitals",
    "lab_report",
    "mrss",
    "pft",
    "antibodies",
    "medications",
    "bal",
    "libraries",
    "skin_biopsies",
)

TABLE_DESCRIPTIONS: dict[str, str] = {
    "subjects": (
        "Every Subject referenced anywhere in the dataset -- the supertype spanning both SSc "
        "Patients and the 4 Control Subjects (CONTEXT.md)."
    ),
    "demographics": (
        "The Registry's static demographic record: one row per SSc Patient (1,500 rows). "
        "Control Subjects have no row here."
    ),
    "ssc_subtype": (
        "The Registry's disease-classification record: SSc subtype and comorbidities, one row "
        "per SSc Patient."
    ),
    "vitals": (
        "Longitudinal Vital Sign readings (e.g. BMI, blood pressure, pulse, weight) -- one row "
        "per Subject per date per vital type."
    ),
    "lab_report": (
        "Longitudinal Lab Result readings (e.g. WBC, hemoglobin) -- one row per Subject per "
        "date per lab component."
    ),
    "mrss": (
        "Longitudinal Modified Rodnan Skin Score (MRSS) readings -- one row per Subject per "
        "visit."
    ),
    "pft": (
        "Longitudinal Pulmonary Function Test (PFT) readings (e.g. FVC, FEV1, DLCO_SB) -- one "
        "row per Subject per test per date."
    ),
    "antibodies": (
        "Autoantibody test results (e.g. scl70) -- one row per Subject per test per date."
    ),
    "medications": (
        "Medication events (drug + dose) -- one row per Subject per prescription entry. "
        "Event-based, not fixed-schedule."
    ),
    "bal": "Bronchoalveolar Lavage (BAL) procedure records. Event-based, not longitudinal.",
    "libraries": (
        "RNA-seq sample-processing metadata. One row generally represents one sample prep, not "
        "a clinical encounter."
    ),
    "skin_biopsies": (
        "Skin biopsy procedure records, including a synthetic (non-backed) pathology image "
        "reference (CONTEXT.md)."
    ),
}

# subject_id is the ingestion-time-normalized canonical identifier in every
# table (data/ingest.py) and is described once here rather than repeated.
_SUBJECT_ID_DESCRIPTION = "Canonical Subject identifier, normalized at ingestion (CONTEXT.md)."

FIELD_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "subjects": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "cohort": "'ssc_patient' or 'control' -- which Cohort this Subject belongs to.",
    },
    "demographics": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "study": "Study identifier; always 'SSC-REG' for the Registry.",
        "ethnicity": "Self-reported ethnicity.",
        "gender": "Self-reported gender.",
        "races": "Self-reported race(s).",
        "diagnosis": "Diagnosis on file; always 'SSc' for Registry members.",
        "state": "US state of residence.",
        "height": (
            "Height in inches. Raw data mixed inch- and centimeter-scale values; "
            "cm-scale values are converted to inches at ingestion (QC report)."
        ),
        "weight": (
            "Weight in pounds. subject_8545's value here is flagged by QC as physiologically "
            "implausible and contradicted by 5 corroborating vitals records (QC report)."
        ),
    },
    "ssc_subtype": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "ssc_subtype": "'dcSSc' (diffuse cutaneous) or 'lcSSc' (limited cutaneous).",
        "other_dx": (
            "Semicolon-separated comorbidities (e.g. ILD, GERD, PAH) recorded alongside the SSc "
            "subtype -- not an alternate diagnosis, despite the column name (CONTEXT.md)."
        ),
        "raynaud_date": "Date of Raynaud's phenomenon onset, if recorded.",
        "nonraynaud_date": "Date of first non-Raynaud's symptom, if recorded.",
        "nonraynaud_sx": "The first non-Raynaud's symptom recorded, if any.",
        "diagnosis_date": "Date of SSc diagnosis.",
    },
    "vitals": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "date": "Date the Vital Sign was recorded.",
        "vital_type_name_category": (
            "Which Vital Sign this row is (e.g. BMI, BP SYSTOLIC, PULSE, WEIGHT IN POUND)."
        ),
        "vital_value": (
            "The recorded value. WEIGHT IN POUND has a QC-flagged constant-value artifact "
            "(160.6 lb repeated across many patients' visits -- QC report)."
        ),
    },
    "lab_report": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "order_date": "Date the lab was ordered/resulted.",
        "component_name": "Which lab component this row is (e.g. WBC, HEMOGLOBIN).",
        "value": (
            "The recorded value. Several components carry isolated implausible sentinel or "
            "negative values (QC report)."
        ),
    },
    "mrss": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "date": "Date the MRSS was recorded.",
        "ENTRY_USER_NAME": (
            "Clinician who recorded the score -- operational metadata, not a PHI-analogue "
            "field (CONTEXT.md)."
        ),
        "mrss_score": "Modified Rodnan Skin Score total (17 body sites x 0-3, range 0-51).",
    },
    "pft": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "PFT_dts": "Date the PFT was performed.",
        "DESCRIPTION": "Long-form name of the measure in this row.",
        "NAME": (
            "Short measure code (e.g. FVC, FEV1, DLCO_SB). FVC/FEV1/DLCO_SB share an identical "
            "40.0-130.0 guideline range in this dataset -- flagged by QC as likely generator "
            "clipping rather than organic variation (QC report)."
        ),
        "ORD_VALUE": "The recorded value, as percent predicted.",
    },
    "antibodies": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "dts": "Date the antibody test was performed.",
        "test": "Which antibody was tested (e.g. scl70).",
        "value": "Result: negative, positive, borderline, or indeterminate.",
    },
    "medications": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "date": "Date the medication entry was recorded.",
        "medication": (
            "Medication name as recorded. Brand/generic/abbreviation variants of the same drug "
            "(e.g. CellCept / mycophenolate mofetil / MMF) are merged to one canonical label on "
            "read, with the original preserved in an 'as recorded' field (QC report)."
        ),
        "dose": (
            "Dose as free text. Parsed on read into value/unit/frequency; QC flags "
            "implausible doses (negative/zero, magnitude outliers, unit-type mismatches -- "
            "QC report)."
        ),
    },
    "bal": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "bal_id": "Identifier for this BAL procedure record.",
        "procedure_date": "Date the BAL was performed.",
        "procedure_site": "Anatomical site the BAL was performed at.",
        "volume_instilled_ml": "Fluid volume instilled, in mL.",
        "volume_recovered_ml": "Fluid volume recovered, in mL.",
        "bal_comment": "Free-text procedure comment.",
    },
    "libraries": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "cell_viability": "Percent viable cells at sample collection.",
        "processing_date": "Date the sample was processed.",
        "comment": "Free-text processing comment.",
        "RNA isolation kit": "Kit used for RNA extraction.",
        "Kit lot number": "Lot number of the extraction kit.",
        "Elution vol (ul)": "Elution volume, in microliters.",
        "Macrophage RNA Tube ID": "Tube identifier for the macrophage RNA sample.",
        "Macrophage RNA Tube Location Box ID": "Freezer box location for that tube.",
        "Date of RNA QC": "Date RNA quality was assessed.",
        "RNA volume for QC": "Volume of RNA used for the QC assay.",
        "RIN": "RNA Integrity Number -- an RNA-quality metric, range 1-10.",
        "RNA concentration (pg/ul)": "RNA concentration.",
        "TS comment": "TapeStation assay comment.",
        "TechCore comment": "Sequencing core comment.",
        "Sequence?": "Whether the sample was sequenced.",
        "TapeStation assay type": "Assay used to assess RNA quality.",
        "ul for 250 pg": "Volume needed for a 250 pg sequencing input.",
        "Complete?": "Whether sample processing is complete.",
        "Library prep date": "Date the sequencing library was prepared.",
        "Sample": "Sample identifier.",
        "RNA Tube ID": "Tube identifier for the RNA sample.",
        "Library prep plate": "Plate identifier used for library prep.",
        "RNAseq batch": "Sequencing batch identifier.",
    },
    "skin_biopsies": {
        "subject_id": _SUBJECT_ID_DESCRIPTION,
        "biopsy_date": "Date the biopsy was performed.",
        "ENTRY_USER_NAME": (
            "Clinician who recorded the biopsy -- operational metadata, not a PHI-analogue "
            "field (CONTEXT.md)."
        ),
        "biopsy_site": "Anatomical site the biopsy was taken from.",
        "clinical_indication": "Clinical reason the biopsy was performed.",
        "specimen_accession": "Lab accession number for the specimen.",
        "image_file_path": (
            "Reference to a pathology image -- a synthetic path with no backing image data "
            "(CONTEXT.md)."
        ),
        "image_format": "File format of the referenced image.",
    },
}

class TableDictionaryEntry(NamedTuple):
    """One table's dictionary entry: live row/column counts plus a
    plain-language description of every non-PII field. `column_count` counts
    every column actually in the table, including any suppressed PII ones;
    `fields` lists only the non-PII ones."""

    table: str
    description: str
    row_count: int
    column_count: int
    suppressed_pii_columns: tuple[str, ...]
    fields: pd.DataFrame


def describe_table(conn: sqlite3.Connection, table: str) -> TableDictionaryEntry:
    """Describe one table: live row/column counts from the store, plus a
    plain-language description per non-PII field. Raises `ValueError` for a
    table this module doesn't know about."""
    if table not in TABLE_DESCRIPTIONS:
        raise ValueError(f"{table!r} is not a known table -- see dictionary.ALL_TABLES")

    (row_count,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    schema_rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    all_columns = [row[1] for row in schema_rows]

    allowed = non_pii_columns(table)
    pii_columns = tuple(c for c in all_columns if c not in allowed) if allowed is not None else ()
    visible_columns = [c for c in all_columns if c not in pii_columns]
    descriptions = FIELD_DESCRIPTIONS.get(table, {})
    fields = pd.DataFrame(
        {
            "field": visible_columns,
            "description": [
                descriptions.get(column, "No description available.") for column in visible_columns
            ],
        }
    )

    return TableDictionaryEntry(
        table=table,
        description=TABLE_DESCRIPTIONS[table],
        row_count=int(row_count),
        column_count=len(all_columns),
        suppressed_pii_columns=pii_columns,
        fields=fields,
    )


def describe_all_tables(conn: sqlite3.Connection) -> list[TableDictionaryEntry]:
    """`describe_table` for every table in `ALL_TABLES`, in display order."""
    return [describe_table(conn, table) for table in ALL_TABLES]
