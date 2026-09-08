"""Tests target the built store's external behavior (spec Testing Decisions),
not ingest.py's internal helpers."""

import hashlib
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from ingest import DEFAULT_CSV_DIR, build_store

REGISTRY_SIZE = 1500
CONTROL_SIZE = 4


def _query(db_path: Path, sql: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql(sql, conn)


def _table_names(db_path: Path) -> list[str]:
    rows = _query(db_path, "SELECT name FROM sqlite_master WHERE type = 'table'")
    return list(rows["name"])


@pytest.fixture(scope="module")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("store") / "ssc.db"
    build_store(db_path=path, csv_dir=DEFAULT_CSV_DIR)
    return path


def test_subjects_has_exactly_1500_patients_and_4_controls(db_path: Path) -> None:
    counts = _query(db_path, "SELECT cohort, COUNT(*) AS n FROM subjects GROUP BY cohort")
    assert dict(zip(counts["cohort"], counts["n"], strict=True)) == {
        "ssc_patient": REGISTRY_SIZE,
        "control": CONTROL_SIZE,
    }


def test_every_clinical_table_subject_id_resolves_to_subjects(db_path: Path) -> None:
    other_tables = [t for t in _table_names(db_path) if t != "subjects"]
    assert other_tables, "expected at least one non-subjects table to be built"
    for table in other_tables:
        orphans = _query(
            db_path,
            f"SELECT COUNT(*) AS n FROM {table} "
            "WHERE subject_id NOT IN (SELECT subject_id FROM subjects)",
        )["n"].iloc[0]
        assert orphans == 0, f"{table} has subject_id values missing from subjects"


def test_demographics_and_ssc_subtype_are_registry_only(db_path: Path) -> None:
    for table in ("demographics", "ssc_subtype"):
        n = _query(db_path, f"SELECT COUNT(*) AS n FROM {table}")["n"].iloc[0]
        assert n == REGISTRY_SIZE


def test_height_is_normalized_to_a_single_inch_scale(db_path: Path) -> None:
    heights = _query(db_path, "SELECT height FROM demographics")["height"]
    # Raw data's native inch-scale range is 54.7-78.5; no cm-scale (>=100) values
    # should survive ingestion, and the distribution should stay unimodal.
    assert heights.between(50, 85).all()
    assert (heights >= 100).sum() == 0


def test_raw_csvs_are_left_untouched(tmp_path: Path) -> None:
    def _hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    before = {csv_file: _hash(csv_file) for csv_file in DEFAULT_CSV_DIR.glob("*.csv")}
    build_store(db_path=tmp_path / "ssc.db", csv_dir=DEFAULT_CSV_DIR)
    after = {csv_file: _hash(csv_file) for csv_file in DEFAULT_CSV_DIR.glob("*.csv")}

    assert before == after


def test_build_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "ssc.db"
    build_store(db_path=target, csv_dir=DEFAULT_CSV_DIR)
    build_store(db_path=target, csv_dir=DEFAULT_CSV_DIR)

    n = _query(target, "SELECT COUNT(*) AS n FROM subjects")["n"].iloc[0]
    assert n == REGISTRY_SIZE + CONTROL_SIZE
