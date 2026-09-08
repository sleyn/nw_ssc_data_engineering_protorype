"""Tests target the access layer's external behavior against the real built
store (spec Testing Decisions) — a module-scoped fixture builds it once via
`data.ingest.build_store` (encryption is `data.store`'s own concern, already
covered by test_store.py; access.py only needs a live connection, however
obtained). Subject IDs used below were confirmed against the real data."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from data.access import (
    SubjectRecord,
    get_subject_record,
    get_variable,
    list_subjects,
    list_variables,
    table_coverage,
)
from data.ingest import DEFAULT_CSV_DIR, build_store

# subject_2005 has a CellCept/MMF medications row (dose "1 g twice daily"),
# useful for checking canonicalization/dose-parsing land in get_subject_record.
AN_SSC_PATIENT_WITH_MEDICATIONS = "subject_2005"
# A Control Subject with vitals/mrss/pft but no labs/medications records.
A_CONTROL_SUBJECT = "SSC_NORM_0101"


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path_factory.mktemp("store") / "ssc.db"
    build_store(db_path=db_path, csv_dir=DEFAULT_CSV_DIR)
    connection = sqlite3.connect(Path(db_path))
    yield connection
    connection.close()


# --- list_subjects ----------------------------------------------------------


def test_list_subjects_has_every_subject_with_cohort_and_subtype(
    conn: sqlite3.Connection,
) -> None:
    subjects = list_subjects(conn)
    assert len(subjects) == 1504
    assert set(subjects["cohort"]) == {"ssc_patient", "control"}

    an_ssc_patient = subjects[subjects["subject_id"] == AN_SSC_PATIENT_WITH_MEDICATIONS].iloc[0]
    assert an_ssc_patient["cohort"] == "ssc_patient"
    assert an_ssc_patient["ssc_subtype"] in {"dcSSc", "lcSSc"}

    a_control = subjects[subjects["subject_id"] == A_CONTROL_SUBJECT].iloc[0]
    assert a_control["cohort"] == "control"
    assert pd.isna(a_control["ssc_subtype"])


# --- table_coverage -----------------------------------------------------------


def test_table_coverage_reports_rows_and_distinct_subjects_per_table(
    conn: sqlite3.Connection,
) -> None:
    coverage = table_coverage(conn)
    assert list(coverage.columns) == ["table", "rows", "distinct_subjects", "subject_coverage"]
    # subjects itself is excluded (its coverage is definitionally 100%).
    assert "subjects" not in set(coverage["table"])

    by_table = coverage.set_index("table")
    # demographics is Registry-only: 1500 of 1504 total Subjects.
    assert by_table.loc["demographics", "rows"] == 1500
    assert by_table.loc["demographics", "distinct_subjects"] == 1500
    assert by_table.loc["demographics", "subject_coverage"] == pytest.approx(1500 / 1504)

    # Every reported coverage is a valid fraction, and no table over-counts
    # distinct Subjects relative to its own row count.
    assert coverage["subject_coverage"].between(0, 1).all()
    assert (coverage["distinct_subjects"] <= coverage["rows"]).all()


# --- get_subject_record ------------------------------------------------------


def test_get_subject_record_returns_all_five_domains_for_an_ssc_patient(
    conn: sqlite3.Connection,
) -> None:
    record = get_subject_record(conn, AN_SSC_PATIENT_WITH_MEDICATIONS)
    assert isinstance(record, SubjectRecord)
    for df in (record.labs, record.vitals, record.mrss, record.pft, record.medications):
        assert isinstance(df, pd.DataFrame)
    assert not record.labs.empty
    assert not record.vitals.empty
    assert not record.medications.empty


def test_get_subject_record_medications_are_qc_normalized(conn: sqlite3.Connection) -> None:
    medications = get_subject_record(conn, AN_SSC_PATIENT_WITH_MEDICATIONS).medications
    merged_row = medications[medications["medication_as_recorded"].isin(["CellCept", "MMF"])]
    assert len(merged_row) == 1
    assert merged_row["medication"].iloc[0] == "mycophenolate mofetil"
    assert merged_row["dose_value"].iloc[0] == 1.0
    assert merged_row["dose_unit"].iloc[0] == "g"
    assert merged_row["dose_frequency"].iloc[0] == "twice daily"


def test_get_subject_record_is_empty_but_correctly_shaped_for_domains_with_no_data(
    conn: sqlite3.Connection,
) -> None:
    record = get_subject_record(conn, A_CONTROL_SUBJECT)
    assert record.labs.empty
    assert list(record.labs.columns) == ["date", "component_name", "value"]
    assert record.medications.empty
    assert "dose_value" in record.medications.columns
    assert not record.vitals.empty
    assert not record.mrss.empty
    assert not record.pft.empty


def test_get_subject_record_rejects_an_unknown_subject_id(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not a known subject_id"):
        get_subject_record(conn, "NOT_A_REAL_SUBJECT")


# --- list_variables / get_variable ------------------------------------------


def test_list_variables_covers_demographic_and_observation_fields(
    conn: sqlite3.Connection,
) -> None:
    variables = list_variables(conn)
    by_name = variables.set_index("field_name")
    assert by_name.loc["gender", "level"] == "demographic"
    assert by_name.loc["gender", "table"] == "demographics"
    assert by_name.loc["WBC", "level"] == "observation"
    assert by_name.loc["WBC", "table"] == "lab_report"
    assert by_name.loc["MRSS", "table"] == "mrss"
    assert by_name.loc["scl70", "table"] == "antibodies"
    # PII must never surface as a queryable field (spec PII handling).
    assert "first_name" not in by_name.index
    assert "last_name" not in by_name.index
    assert "birth_date" not in by_name.index


def test_get_variable_resolves_a_demographic_field_for_every_registry_subject(
    conn: sqlite3.Connection,
) -> None:
    # "gender" lives in demographics, a Registry-only (ssc_patient-only)
    # extension table, so it covers 1500 rows, not all 1504 Subjects.
    genders = get_variable(conn, "gender")
    assert len(genders) == 1500
    assert list(genders.columns) == ["subject_id", "date", "value"]
    assert genders["date"].isna().all()


def test_get_variable_resolves_a_demographic_field_for_every_subject(
    conn: sqlite3.Connection,
) -> None:
    # "cohort" lives on subjects itself, so it covers all 1504 Subjects
    # including the 4 Control Subjects outside the Registry.
    cohorts = get_variable(conn, "cohort")
    assert len(cohorts) == 1504


def test_get_variable_resolves_an_observation_field_scoped_to_one_subject(
    conn: sqlite3.Connection,
) -> None:
    wbc = get_variable(conn, "WBC", subject_id=AN_SSC_PATIENT_WITH_MEDICATIONS)
    assert list(wbc.columns) == ["subject_id", "date", "value"]
    assert not wbc.empty
    assert (wbc["subject_id"] == AN_SSC_PATIENT_WITH_MEDICATIONS).all()
    assert wbc["date"].notna().all()


def test_get_variable_resolves_the_fixed_measure_mrss_table(conn: sqlite3.Connection) -> None:
    mrss = get_variable(conn, "MRSS", subject_id=A_CONTROL_SUBJECT)
    assert len(mrss) == 1
    assert mrss["subject_id"].iloc[0] == A_CONTROL_SUBJECT


def test_get_variable_resolves_an_antibodies_field(conn: sqlite3.Connection) -> None:
    # antibodies.csv shares the same test-name-plus-value-per-date shape as
    # vitals/lab_report/mrss/pft (see data/access.py module docstring) and
    # is reachable through the same generic picker.
    scl70 = get_variable(conn, "scl70")
    assert list(scl70.columns) == ["subject_id", "date", "value"]
    assert not scl70.empty
    assert set(scl70["value"]).issubset({"negative", "positive", "borderline", "indeterminate"})


def test_get_variable_rejects_an_unknown_field_name(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not a known field"):
        get_variable(conn, "NOT_A_REAL_FIELD")


def test_height_returned_by_get_variable_is_already_inch_normalized(
    conn: sqlite3.Connection,
) -> None:
    # data.ingest normalizes height to inches at build time (cm-scale >= 100
    # converted); this asserts access.py doesn't need to redo that work and
    # that no cm-scale value leaks through.
    heights = pd.to_numeric(get_variable(conn, "height")["value"], errors="coerce").dropna()
    assert heights.between(50, 85).all()
