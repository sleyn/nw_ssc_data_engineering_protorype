"""Tests target the Subject Filters support module's external behavior
against the real built store (same fixture pattern as test_compare.py) --
the pure-pandas/SQL logic behind ticket 08's panel, kept independently
testable even though the Streamlit rendering itself is out of scope for
testing (spec "No UI/visual testing of the Streamlit app")."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from data.ingest import DEFAULT_CSV_DIR, build_store
from data.subject_filters import FilterField, FilterValue, filter_subjects, list_filter_fields


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path_factory.mktemp("store") / "ssc.db"
    build_store(db_path=db_path, csv_dir=DEFAULT_CSV_DIR)
    connection = sqlite3.connect(Path(db_path))
    yield connection
    connection.close()


def _find(fields: list[FilterField], key: str) -> FilterField:
    for field in fields:
        if field.key == key:
            return field
    raise AssertionError(f"no {key!r} entry in catalog")


# --- list_filter_fields -------------------------------------------------------------


def test_demographic_categorical_fields_present(conn: sqlite3.Connection) -> None:
    fields = list_filter_fields(conn)
    gender = _find(fields, "demographic:gender")
    assert gender.kind == "categorical"
    assert gender.category == "Demographics"
    assert set(gender.options or ()) == {"Female", "Male"}


def test_demographic_range_fields_have_numeric_bounds(conn: sqlite3.Connection) -> None:
    fields = list_filter_fields(conn)
    height = _find(fields, "demographic:height")
    assert height.kind == "range"
    assert height.min_value is not None and height.max_value is not None
    assert height.min_value < height.max_value


def test_medication_field_is_existence_with_canonical_drug_names(conn: sqlite3.Connection) -> None:
    fields = list_filter_fields(conn)
    medication = _find(fields, "medication")
    assert medication.kind == "existence"
    # CellCept/MMF are canonicalized to their generic name (data.normalize) --
    # neither brand/abbreviation name should leak into the filter's options.
    assert "mycophenolate mofetil" in (medication.options or ())
    assert "CellCept" not in (medication.options or ())
    assert "MMF" not in (medication.options or ())


def test_antibody_field_is_categorical_not_numeric(conn: sqlite3.Connection) -> None:
    fields = list_filter_fields(conn)
    antibody = _find(fields, "antibody")
    assert antibody.kind == "categorical"
    assert antibody.min_value is None and antibody.max_value is None
    assert any(option.endswith(": negative") for option in antibody.options or ())
    assert any(option.endswith(": positive") for option in antibody.options or ())


def test_bal_field_is_existence_toggle_with_no_suboptions(conn: sqlite3.Connection) -> None:
    fields = list_filter_fields(conn)
    bal = _find(fields, "bal")
    assert bal.kind == "existence"
    assert bal.options is None


def test_lab_report_fields_are_one_range_per_component(conn: sqlite3.Connection) -> None:
    fields = list_filter_fields(conn)
    lab_fields = [f for f in fields if f.category == "Lab Report"]
    assert lab_fields
    assert all(f.kind == "range" for f in lab_fields)
    wbc = _find(fields, "lab:WBC")
    assert wbc.min_value is not None and wbc.max_value is not None


# --- filter_subjects: no-op / neutral values ----------------------------------------


def test_empty_selections_returns_every_subject(conn: sqlite3.Connection) -> None:
    all_subjects = filter_subjects(conn, {})
    assert len(all_subjects) == 1504


def test_empty_multiselect_is_a_no_op(conn: sqlite3.Connection) -> None:
    assert filter_subjects(conn, {"demographic:gender": []}) == filter_subjects(conn, {})


def test_full_range_bounds_match_every_subject_with_a_value(conn: sqlite3.Connection) -> None:
    # Not a no-op against *every* Subject -- the 4 Control Subjects have no
    # demographics row at all, so a demographic range filter naturally
    # excludes them the same way a categorical one does.
    height = _find(list_filter_fields(conn), "demographic:height")
    assert height.min_value is not None and height.max_value is not None
    full_range = set(
        filter_subjects(conn, {"demographic:height": (height.min_value, height.max_value)})
    )
    with_height = {
        row[0]
        for row in conn.execute("SELECT subject_id FROM demographics WHERE height IS NOT NULL")
    }
    assert full_range == with_height


def test_bal_false_is_a_no_op(conn: sqlite3.Connection) -> None:
    assert filter_subjects(conn, {"bal": False}) == filter_subjects(conn, {})


# --- filter_subjects: OR within one filter, AND across filters ----------------------


def test_selecting_two_genders_broadens_the_result(conn: sqlite3.Connection) -> None:
    female_only = filter_subjects(conn, {"demographic:gender": ["Female"]})
    both_genders = filter_subjects(conn, {"demographic:gender": ["Female", "Male"]})
    assert len(both_genders) > len(female_only)
    assert set(female_only) <= set(both_genders)


def test_adding_a_second_filter_category_narrows_the_result(conn: sqlite3.Connection) -> None:
    gender_only = filter_subjects(conn, {"demographic:gender": ["Female"]})
    gender_and_bal = filter_subjects(
        conn, {"demographic:gender": ["Female"], "bal": True}
    )
    assert len(gender_and_bal) < len(gender_only)
    assert set(gender_and_bal) <= set(gender_only)


def test_medication_filter_matches_canonical_and_raw_names(conn: sqlite3.Connection) -> None:
    # "CellCept" is recorded verbatim in the raw medications table but should
    # be reachable through its canonical filter option (data.normalize).
    matched = set(filter_subjects(conn, {"medication": ["mycophenolate mofetil"]}))
    raw = {
        row[0]
        for row in conn.execute("SELECT subject_id FROM medications WHERE medication = 'CellCept'")
    }
    assert raw
    assert raw <= matched


def test_antibody_filter_matches_test_result_pair(conn: sqlite3.Connection) -> None:
    matched = set(filter_subjects(conn, {"antibody": ["rna polymerase III: negative"]}))
    expected = {
        row[0]
        for row in conn.execute(
            "SELECT subject_id FROM antibodies "
            "WHERE test = 'rna polymerase III' AND value = 'negative'"
        )
    }
    assert expected
    assert matched == expected


def test_lab_range_filter_matches_component_value_range(conn: sqlite3.Connection) -> None:
    wbc = _find(list_filter_fields(conn), "lab:WBC")
    assert wbc.min_value is not None and wbc.max_value is not None
    midpoint = (wbc.min_value + wbc.max_value) / 2
    narrow = filter_subjects(conn, {"lab:WBC": (wbc.min_value, midpoint)})
    full = filter_subjects(conn, {"lab:WBC": (wbc.min_value, wbc.max_value)})
    assert set(narrow) <= set(full)
    assert len(narrow) < len(full)


def test_lab_full_range_is_a_true_no_op_unlike_demographic_range(
    conn: sqlite3.Connection,
) -> None:
    # Unlike a demographic range (which scopes to a single shared table and
    # so may legitimately exclude the handful of Subjects with no row at
    # all there), a Lab Report component's own full bounds must not exclude
    # Subjects who simply never had *that* component measured -- each
    # component scopes to a different row subset of the shared
    # `lab_report` table.
    wbc = _find(list_filter_fields(conn), "lab:WBC")
    assert wbc.min_value is not None and wbc.max_value is not None
    full = filter_subjects(conn, {"lab:WBC": (wbc.min_value, wbc.max_value)})
    assert full == filter_subjects(conn, {})


def test_every_lab_filter_left_at_its_neutral_value_does_not_collapse_the_pool(
    conn: sqlite3.Connection,
) -> None:
    # Regression: passing every Lab Report component's widget state at its
    # untouched, full-range default (as the Patient Trajectory panel always
    # does) used to AND ~28 different per-component "has this test" subsets
    # together and collapse the Subject pool to empty.
    lab_fields = [
        f for f in list_filter_fields(conn) if f.kind == "range" and f.key.startswith("lab:")
    ]
    assert len(lab_fields) > 1
    selections: dict[str, FilterValue] = {}
    for f in lab_fields:
        assert f.min_value is not None and f.max_value is not None
        selections[f.key] = (f.min_value, f.max_value)
    assert filter_subjects(conn, selections) == filter_subjects(conn, {})
