"""Build the canonical Subject/Cohort SQLite store from the raw SSc CSVs.

Reads the 11 raw CSVs (data/data_v3), normalizes their four differently-named
identifier columns to one canonical ``subject_id``, and writes a fresh SQLite
store built around a ``subjects(subject_id, cohort)`` supertype table per
ADR 0005. Raw CSVs are only ever read, never modified. Safe to re-run: any
existing store at the target path is discarded and rebuilt from scratch.
"""

import contextlib
import sqlite3
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).parent
DEFAULT_CSV_DIR = REPO_ROOT / "data" / "data_v3"
DEFAULT_DB_PATH = REPO_ROOT / "data" / "ssc.db"

SUBJECT_ID_COLUMN = "subject_id"

# Registry tables: joined 1:1, they define the ssc_patient Cohort (CONTEXT.md).
DEMOGRAPHICS_ID_COLUMN = "case number"
DEMOGRAPHICS_RENAME = {
    "first name": "first_name",
    "last name": "last_name",
    "birth date": "birth_date",
}
SSC_SUBTYPE_ID_COLUMN = "study_code"

# Every other clinical/molecular table, keyed on Subject (not Registry-only).
CLINICAL_ID_COLUMNS = {
    "antibodies": "case_number",
    "bal": "reg_id",
    "lab_report": "reg_id",
    "libraries": "reg_id",
    "medications": "reg_id",
    "mrss": "reg_id",
    "pft": "case_number",
    "skin_biopsies": "case_number",
    "vitals": "reg_id",
}

# demographics.height is a bimodal cm/inch split at a clean threshold of 100
# (CONTEXT.md, docs/presentation-notes.md) with no ambiguous middle ground.
HEIGHT_CM_THRESHOLD = 100.0
CM_PER_INCH = 2.54

SUBJECTS_SCHEMA = """
CREATE TABLE subjects (
    subject_id TEXT PRIMARY KEY,
    cohort TEXT NOT NULL CHECK (cohort IN ('ssc_patient', 'control'))
)
"""

DEMOGRAPHICS_SCHEMA = """
CREATE TABLE demographics (
    subject_id TEXT PRIMARY KEY REFERENCES subjects(subject_id),
    study TEXT,
    first_name TEXT,
    last_name TEXT,
    birth_date TEXT,
    ethnicity TEXT,
    gender TEXT,
    races TEXT,
    diagnosis TEXT,
    state TEXT,
    height REAL,
    weight REAL
)
"""

SSC_SUBTYPE_SCHEMA = """
CREATE TABLE ssc_subtype (
    subject_id TEXT PRIMARY KEY REFERENCES subjects(subject_id),
    ssc_subtype TEXT,
    other_dx TEXT,
    raynaud_date TEXT,
    nonraynaud_date TEXT,
    nonraynaud_sx TEXT,
    diagnosis_date TEXT
)
"""


def _read_csv(csv_dir: Path, table: str, id_column: str) -> pd.DataFrame:
    df = pd.read_csv(csv_dir / f"{table}.csv")
    return df.rename(columns={id_column: SUBJECT_ID_COLUMN})


def _normalize_height(demographics: pd.DataFrame) -> pd.DataFrame:
    """Convert cm-scale height values to inches; inch-scale values pass through."""
    demographics = demographics.copy()
    is_cm = demographics["height"] >= HEIGHT_CM_THRESHOLD
    demographics.loc[is_cm, "height"] = (demographics.loc[is_cm, "height"] / CM_PER_INCH).round(1)
    return demographics


def _load_registry(csv_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    demographics = _read_csv(csv_dir, "demographics", DEMOGRAPHICS_ID_COLUMN)
    demographics = demographics.rename(columns=DEMOGRAPHICS_RENAME)
    demographics = _normalize_height(demographics)
    ssc_subtype = _read_csv(csv_dir, "ssc_subtype", SSC_SUBTYPE_ID_COLUMN)
    return demographics, ssc_subtype


def _load_clinical_tables(csv_dir: Path) -> dict[str, pd.DataFrame]:
    return {
        table: _read_csv(csv_dir, table, id_column)
        for table, id_column in CLINICAL_ID_COLUMNS.items()
    }


def _build_subjects(
    registry_ids: set[str], clinical_tables: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """Every Subject ID encountered anywhere is a Subject; anyone outside the
    Registry is a Control Subject (CONTEXT.md) rather than an orphan to explain
    away — this is derived generically, not a hardcoded ID list."""
    control_ids: set[str] = set()
    for df in clinical_tables.values():
        control_ids |= set(df[SUBJECT_ID_COLUMN]) - registry_ids
    rows = [(sid, "ssc_patient") for sid in sorted(registry_ids)] + [
        (sid, "control") for sid in sorted(control_ids)
    ]
    return pd.DataFrame(rows, columns=[SUBJECT_ID_COLUMN, "cohort"])


def _assert_no_orphans(conn: sqlite3.Connection, tables: list[str]) -> None:
    """Defensive check that every non-subjects table's subject_id resolves to a
    subjects row. Not expected to ever fire given how subjects is derived above;
    guards against a future table being added without going through that path."""
    for table in tables:
        (orphans,) = conn.execute(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE {SUBJECT_ID_COLUMN} NOT IN (SELECT {SUBJECT_ID_COLUMN} FROM subjects)"
        ).fetchone()
        if orphans:
            raise RuntimeError(f"{table} has {orphans} subject_id value(s) missing from subjects")


def build_store(db_path: Path = DEFAULT_DB_PATH, csv_dir: Path = DEFAULT_CSV_DIR) -> None:
    """(Re)build the SQLite store at db_path from the raw CSVs at csv_dir.

    Safe to re-run: any existing store at db_path is discarded and rebuilt
    from scratch. Never reads back from or writes to csv_dir.
    """
    demographics, ssc_subtype = _load_registry(csv_dir)
    registry_ids = set(demographics[SUBJECT_ID_COLUMN]) | set(ssc_subtype[SUBJECT_ID_COLUMN])

    clinical_tables = _load_clinical_tables(csv_dir)
    subjects = _build_subjects(registry_ids, clinical_tables)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)

    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(SUBJECTS_SCHEMA)
        conn.execute(DEMOGRAPHICS_SCHEMA)
        conn.execute(SSC_SUBTYPE_SCHEMA)

        subjects.to_sql("subjects", conn, if_exists="append", index=False)
        demographics.to_sql("demographics", conn, if_exists="append", index=False)
        ssc_subtype.to_sql("ssc_subtype", conn, if_exists="append", index=False)

        for table, df in clinical_tables.items():
            df.to_sql(table, conn, if_exists="fail", index=False)

        _assert_no_orphans(conn, ["demographics", "ssc_subtype", *clinical_tables])

        conn.commit()


if __name__ == "__main__":
    build_store()
    print(f"Built SQLite store at {DEFAULT_DB_PATH}")
