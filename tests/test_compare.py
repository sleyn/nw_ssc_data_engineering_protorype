"""Tests target the Compare & Discover support module's external behavior
against the real built store (same fixture pattern as test_access.py) --
these are the pure-pandas logic pieces behind Tab 3, kept independently
testable even though the Streamlit rendering itself is out of scope for
testing (spec "No UI/visual testing of the Streamlit app")."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from data.compare import (
    CompareVariable,
    build_comparison,
    choose_chart_type,
    control_overlay_available,
    infer_dtype,
    list_compare_variables,
    resolve_compare_variable,
)
from data.ingest import DEFAULT_CSV_DIR, build_store


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path_factory.mktemp("store") / "ssc.db"
    build_store(db_path=db_path, csv_dir=DEFAULT_CSV_DIR)
    connection = sqlite3.connect(Path(db_path))
    yield connection
    connection.close()


def _find(catalog: list[CompareVariable], field_name: str, level: str) -> CompareVariable:
    for variable in catalog:
        if variable.field_name == field_name and variable.level == level:
            return variable
    raise AssertionError(f"no {field_name!r}/{level!r} entry in catalog")


# --- list_compare_variables ---------------------------------------------------


def test_demographic_fields_appear_once_at_demographic_level(conn: sqlite3.Connection) -> None:
    catalog = list_compare_variables(conn)
    gender_entries = [v for v in catalog if v.field_name == "gender"]
    assert len(gender_entries) == 1
    assert gender_entries[0].level == "demographic"
    assert gender_entries[0].domain_label == "Demographic"


def test_observation_fields_appear_once_at_per_patient_aggregate_with_domain_labels(
    conn: sqlite3.Connection,
) -> None:
    catalog = list_compare_variables(conn)
    pulse_entries = [v for v in catalog if v.field_name == "PULSE"]
    assert len(pulse_entries) == 1
    pulse = pulse_entries[0]
    assert pulse.level == "per_patient_aggregate"
    # Domain vocabulary (User Story 27) -- never the internal table name
    # or "Observation" itself.
    assert pulse.domain_label == "Vital Sign"
    assert "vitals" not in pulse.display_label
    assert "Observation" not in pulse.display_label
    assert "(over time)" not in pulse.display_label

    wbc = _find(catalog, "WBC", "per_patient_aggregate")
    assert wbc.domain_label == "Lab Result"
    mrss = _find(catalog, "MRSS", "per_patient_aggregate")
    assert mrss.domain_label == "MRSS"
    scl70 = _find(catalog, "scl70", "per_patient_aggregate")
    assert scl70.domain_label == "Antibody"


def test_no_catalog_entry_is_a_longitudinal_series(conn: sqlite3.Connection) -> None:
    catalog = list_compare_variables(conn)
    levels = {v.level for v in catalog}
    assert levels == {"demographic", "per_patient_aggregate"}
    assert all("(over time)" not in v.display_label for v in catalog)


# --- infer_dtype ---------------------------------------------------------------


def test_infer_dtype_numeric_column() -> None:
    assert infer_dtype(pd.Series([1.0, 2.0, None, 3.5])) == "numeric"


def test_infer_dtype_numeric_strings_from_sqlite_roundtrip() -> None:
    # WBC's own value column comes back as a str/float mix (see data/compare.py
    # module docstring) -- confirm the real thing classifies as numeric, not
    # just a hand-built numeric Series.
    assert infer_dtype(pd.Series(["4.2", "5.1", 6.0, None])) == "numeric"


def test_infer_dtype_categorical_column() -> None:
    assert infer_dtype(pd.Series(["negative", "positive", "borderline"])) == "categorical"


def test_infer_dtype_all_null_is_categorical_not_an_error() -> None:
    assert infer_dtype(pd.Series([None, None])) == "categorical"


# --- choose_chart_type ---------------------------------------------------------


@pytest.mark.parametrize(
    ("x_dtype", "y_dtype", "expected"),
    [
        ("numeric", "numeric", "scatter"),
        ("categorical", "numeric", "box"),
        ("numeric", "categorical", "box"),
        ("categorical", "categorical", "heatmap"),
    ],
)
def test_choose_chart_type_matches_ticket_rules(
    x_dtype: str, y_dtype: str, expected: str
) -> None:
    assert choose_chart_type(x_dtype, y_dtype) == expected  # type: ignore[arg-type]


# --- resolve_compare_variable ---------------------------------------------------


def test_resolve_demographic_variable_is_one_row_per_subject(conn: sqlite3.Connection) -> None:
    catalog = list_compare_variables(conn)
    gender = _find(catalog, "gender", "demographic")
    resolved = resolve_compare_variable(conn, gender)
    assert list(resolved.columns) == ["subject_id", "value"]
    assert len(resolved) == 1500  # Registry-only field


def test_resolve_numeric_aggregate_averages_across_visits(conn: sqlite3.Connection) -> None:
    catalog = list_compare_variables(conn)
    pulse_aggregate = _find(catalog, "PULSE", "per_patient_aggregate")
    resolved = resolve_compare_variable(conn, pulse_aggregate)
    assert list(resolved.columns) == ["subject_id", "value"]
    assert resolved["subject_id"].is_unique
    assert pd.api.types.is_numeric_dtype(resolved["value"])


def test_resolve_categorical_aggregate_takes_most_recent_value(conn: sqlite3.Connection) -> None:
    catalog = list_compare_variables(conn)
    scl70_aggregate = _find(catalog, "scl70", "per_patient_aggregate")
    resolved = resolve_compare_variable(conn, scl70_aggregate)
    assert resolved["subject_id"].is_unique
    assert set(resolved["value"].dropna()).issubset(
        {"negative", "positive", "borderline", "indeterminate"}
    )


# --- build_comparison / control_overlay_available -------------------------------


def test_two_demographic_variables_pair_into_a_box_chart(conn: sqlite3.Connection) -> None:
    catalog = list_compare_variables(conn)
    gender = _find(catalog, "gender", "demographic")
    height = _find(catalog, "height", "demographic")
    result = build_comparison(conn, gender, height)
    assert result.chart_type == "box"
    assert {"subject_id", "cohort", "x", "y"}.issubset(result.data.columns)
    # No Control Subject has a demographics row at all (CONTEXT.md) -- the
    # overlay toggle must come back unavailable for this pairing.
    assert control_overlay_available(result.data) is False


def test_two_numeric_demographic_variables_pair_into_a_scatter(conn: sqlite3.Connection) -> None:
    catalog = list_compare_variables(conn)
    height = _find(catalog, "height", "demographic")
    weight = _find(catalog, "weight", "demographic")
    result = build_comparison(conn, height, weight)
    assert result.chart_type == "scatter"


def test_categorical_pair_is_a_heatmap(conn: sqlite3.Connection) -> None:
    catalog = list_compare_variables(conn)
    gender = _find(catalog, "gender", "demographic")
    ethnicity = _find(catalog, "ethnicity", "demographic")
    result = build_comparison(conn, gender, ethnicity)
    assert result.chart_type == "heatmap"


def test_two_per_patient_aggregate_variables_pair_into_a_scatter(
    conn: sqlite3.Connection,
) -> None:
    catalog = list_compare_variables(conn)
    pulse = _find(catalog, "PULSE", "per_patient_aggregate")
    mrss = _find(catalog, "MRSS", "per_patient_aggregate")
    result = build_comparison(conn, pulse, mrss)
    assert result.chart_type == "scatter"
    assert not result.data.empty
    # 3 of the 4 Control Subjects have both vitals and mrss records.
    assert control_overlay_available(result.data) is True


def test_lab_result_pairing_never_has_a_control_overlay(conn: sqlite3.Connection) -> None:
    # No Control Subject has any lab_report record (CONTEXT.md) -- the
    # overlay toggle must be unavailable no matter what it's paired with.
    catalog = list_compare_variables(conn)
    wbc = _find(catalog, "WBC", "per_patient_aggregate")
    gender = _find(catalog, "gender", "demographic")
    result = build_comparison(conn, wbc, gender)
    assert control_overlay_available(result.data) is False


# --- build_comparison color-by (ticket 03, round 3) ------------------------------


def test_build_comparison_without_color_leaves_color_label_none(
    conn: sqlite3.Connection,
) -> None:
    catalog = list_compare_variables(conn)
    pulse = _find(catalog, "PULSE", "per_patient_aggregate")
    mrss = _find(catalog, "MRSS", "per_patient_aggregate")
    result = build_comparison(conn, pulse, mrss)
    assert result.color_label is None
    assert "color" not in result.data.columns


def test_build_comparison_with_color_merges_the_third_variables_values(
    conn: sqlite3.Connection,
) -> None:
    catalog = list_compare_variables(conn)
    pulse = _find(catalog, "PULSE", "per_patient_aggregate")
    mrss = _find(catalog, "MRSS", "per_patient_aggregate")
    ssc_subtype = _find(catalog, "ssc_subtype", "demographic")
    result = build_comparison(conn, pulse, mrss, color=ssc_subtype)
    assert result.color_label == ssc_subtype.display_label
    assert "color" in result.data.columns
    assert set(result.data["color"].dropna()).issubset({"dcSSc", "lcSSc"})
