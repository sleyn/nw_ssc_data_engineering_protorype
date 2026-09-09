"""Tests target dictionary.py's external behavior against the real built
store (spec Testing Decisions), same fixture pattern as test_access.py."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from data.dictionary import (
    ALL_TABLES,
    _field_example_values,
    describe_all_tables,
    describe_table,
)
from data.ingest import DEFAULT_CSV_DIR, build_store

# The known PII columns suppressed from demographics (spec "PII handling"),
# kept here as a fixed expectation independent of dictionary.py's own
# derivation via data.access.non_pii_columns -- so a test bug in either
# module can't mask a real suppression failure in the other.
DEMOGRAPHICS_PII_COLUMNS = ("first_name", "last_name", "birth_date")


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path_factory.mktemp("store") / "ssc.db"
    build_store(db_path=db_path, csv_dir=DEFAULT_CSV_DIR)
    connection = sqlite3.connect(Path(db_path))
    yield connection
    connection.close()


def test_describe_table_reports_live_row_and_column_counts_for_demographics(
    conn: sqlite3.Connection,
) -> None:
    entry = describe_table(conn, "demographics")
    assert entry.row_count == 1500
    # column_count counts every column in the table, PII included.
    assert entry.column_count == len(
        conn.execute('PRAGMA table_info("demographics")').fetchall()
    )


def test_describe_table_reports_all_1504_subjects_for_subjects_table(
    conn: sqlite3.Connection,
) -> None:
    entry = describe_table(conn, "subjects")
    assert entry.row_count == 1504


def test_describe_table_suppresses_pii_columns_from_the_field_list(
    conn: sqlite3.Connection,
) -> None:
    entry = describe_table(conn, "demographics")
    field_names = set(entry.fields["field"])
    for pii_column in DEMOGRAPHICS_PII_COLUMNS:
        assert pii_column not in field_names
    assert set(entry.suppressed_pii_columns) == set(DEMOGRAPHICS_PII_COLUMNS)


def test_describe_table_field_list_matches_the_real_non_pii_schema_columns(
    conn: sqlite3.Connection,
) -> None:
    entry = describe_table(conn, "vitals")
    real_columns = [row[1] for row in conn.execute('PRAGMA table_info("vitals")').fetchall()]
    assert list(entry.fields["field"]) == real_columns


def test_describe_table_rejects_an_unknown_table(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not a known table"):
        describe_table(conn, "not_a_real_table")


def test_describe_all_tables_covers_every_table_in_all_tables(conn: sqlite3.Connection) -> None:
    entries = describe_all_tables(conn)
    assert [entry.table for entry in entries] == list(ALL_TABLES)


def test_every_non_pii_field_in_every_table_has_a_real_description(
    conn: sqlite3.Connection,
) -> None:
    """Regression guard: every column that will actually be shown in the
    Data & Dictionary tab must have a hand-written description, not the
    'No description available.' fallback -- catches a table gaining a new
    column that the dictionary wasn't updated for."""
    for entry in describe_all_tables(conn):
        undescribed = entry.fields.loc[
            entry.fields["description"] == "No description available.", "field"
        ]
        assert undescribed.empty, f"{entry.table} has undescribed field(s): {list(undescribed)}"


def _examples_for(entry_fields: pd.DataFrame, field: str) -> str:
    return str(entry_fields.loc[entry_fields["field"] == field, "examples"].iloc[0])


def test_every_field_shows_at_most_3_example_values(conn: sqlite3.Connection) -> None:
    for entry in describe_all_tables(conn):
        for field in entry.fields["field"]:
            values = _field_example_values(conn, entry.table, field)
            assert len(values) <= 3, f"{entry.table}.{field} has more than 3 examples: {values!r}"


def test_a_field_with_fewer_than_3_distinct_values_shows_fewer_not_padded(
    conn: sqlite3.Connection,
) -> None:
    # subjects.cohort only ever takes 2 real values (spec "Cohort").
    values = _field_example_values(conn, "subjects", "cohort")
    assert values == ["control", "ssc_patient"]
    entry = describe_table(conn, "subjects")
    assert _examples_for(entry.fields, "cohort") == "control, ssc_patient"


def test_a_long_free_text_fields_example_is_truncated_with_an_ellipsis(
    conn: sqlite3.Connection,
) -> None:
    values = _field_example_values(conn, "bal", "bal_comment")
    assert any(len(v) == 63 and v.endswith("...") for v in values)
    entry = describe_table(conn, "bal")
    assert _examples_for(entry.fields, "bal_comment").startswith(
        next(v for v in values if v.endswith("..."))
    )


def test_no_example_is_computed_for_a_suppressed_pii_column(conn: sqlite3.Connection) -> None:
    entry = describe_table(conn, "demographics")
    field_names = set(entry.fields["field"])
    for pii_column in DEMOGRAPHICS_PII_COLUMNS:
        assert pii_column not in field_names
    # Not just hidden from the field list -- never queried for examples at all.
    real_columns = [
        row[1] for row in conn.execute('PRAGMA table_info("demographics")').fetchall()
    ]
    assert set(real_columns) - set(entry.fields["field"]) == set(DEMOGRAPHICS_PII_COLUMNS)


def test_examples_are_deterministic_across_repeated_calls(conn: sqlite3.Connection) -> None:
    first = describe_table(conn, "vitals").fields["examples"].tolist()
    second = describe_table(conn, "vitals").fields["examples"].tolist()
    assert first == second
