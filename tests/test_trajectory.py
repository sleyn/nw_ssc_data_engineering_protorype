"""Tests target the Patient Trajectory tab's support module's external
behavior -- the coercion/reshaping pieces behind Tab 4, kept independently
testable even though the Streamlit rendering itself is out of scope for
testing (spec "No UI/visual testing of the Streamlit app"). `domain_series`
is exercised against hand-built fixtures (its own logic doesn't depend on
the store) plus once against the real store via `get_subject_record`, to
catch any drift between this module's column-name assumptions and
`data.access`'s actual output shape."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from data.access import get_subject_record
from data.ingest import DEFAULT_CSV_DIR, build_store
from data.trajectory import (
    MeasureSeries,
    apply_disease_duration_axis,
    apply_disease_duration_to_medications,
    combine_medication_timelines,
    combine_subject_series,
    domain_series,
    medication_timeline,
    shared_date_range,
)

# subject_2005 has labs, vitals, PFT, and medications records but no MRSS
# (confirmed against the real data, same subject test_access.py uses).
A_SUBJECT_WITH_MOST_DOMAINS = "subject_2005"


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path_factory.mktemp("store") / "ssc.db"
    build_store(db_path=db_path, csv_dir=DEFAULT_CSV_DIR)
    connection = sqlite3.connect(Path(db_path))
    yield connection
    connection.close()


# --- domain_series, hand-built fixtures -----------------------------------------


def test_empty_frame_returns_no_series() -> None:
    empty = pd.DataFrame(columns=["component_name", "value", "date"])
    result = domain_series(empty, value_col="value", date_col="date", measure_col="component_name")
    assert result == []


def test_splits_into_one_series_per_measure_sorted_by_measure_name() -> None:
    df = pd.DataFrame(
        {
            "component_name": ["WBC", "WBC", "HEMOGLOBIN"],
            "value": ["4.2", "5.1", "13.0"],
            "date": ["2020-01-01", "2020-02-01", "2020-01-01"],
        }
    )
    result = domain_series(df, value_col="value", date_col="date", measure_col="component_name")
    assert [series.measure for series in result] == ["HEMOGLOBIN", "WBC"]
    wbc = result[1]
    assert list(wbc.series.columns) == ["date", "value"]
    assert list(wbc.series["value"]) == [4.2, 5.1]
    assert wbc.title == "WBC"  # no title_col given -- falls back to the measure itself


def test_series_within_a_measure_is_sorted_by_date() -> None:
    df = pd.DataFrame(
        {
            "component_name": ["WBC", "WBC"],
            "value": ["5.1", "4.2"],
            "date": ["2020-02-01", "2020-01-01"],
        }
    )
    result = domain_series(df, value_col="value", date_col="date", measure_col="component_name")
    assert list(result[0].series["value"]) == [4.2, 5.1]


def test_non_numeric_and_undated_rows_are_dropped_not_errors() -> None:
    df = pd.DataFrame(
        {
            "component_name": ["WBC", "WBC", "WBC"],
            "value": ["4.2", "Automated", "5.1"],
            "date": ["2020-01-01", "2020-02-01", None],
        }
    )
    result = domain_series(df, value_col="value", date_col="date", measure_col="component_name")
    assert len(result) == 1
    assert list(result[0].series["value"]) == [4.2]


def test_all_unplottable_rows_returns_no_series() -> None:
    df = pd.DataFrame({"component_name": ["WBC"], "value": ["Automated"], "date": ["2020-01-01"]})
    assert domain_series(df, value_col="value", date_col="date", measure_col="component_name") == []


def test_title_col_supplies_a_friendlier_title_than_the_measure_code() -> None:
    df = pd.DataFrame(
        {
            "NAME": ["FVC"],
            "DESCRIPTION": ["Forced Vital Capacity (% predicted)"],
            "ORD_VALUE": ["85"],
            "date": ["2020-01-01"],
        }
    )
    result = domain_series(
        df, value_col="ORD_VALUE", date_col="date", measure_col="NAME", title_col="DESCRIPTION",
    )
    assert result[0].measure == "FVC"
    assert result[0].title == "Forced Vital Capacity (% predicted)"


def test_fixed_measure_treats_every_row_as_the_one_named_measure() -> None:
    df = pd.DataFrame({"mrss_score": ["10", "12"], "date": ["2020-01-01", "2020-02-01"]})
    result = domain_series(df, value_col="mrss_score", date_col="date", fixed_measure="MRSS")
    assert len(result) == 1
    assert result[0].measure == "MRSS"
    assert list(result[0].series["value"]) == [10.0, 12.0]


def test_neither_measure_col_nor_fixed_measure_raises() -> None:
    df = pd.DataFrame({"value": ["1"], "date": ["2020-01-01"]})
    with pytest.raises(ValueError, match="exactly one"):
        domain_series(df, value_col="value", date_col="date")


def test_both_measure_col_and_fixed_measure_raises() -> None:
    df = pd.DataFrame({"c": ["x"], "value": ["1"], "date": ["2020-01-01"]})
    with pytest.raises(ValueError, match="exactly one"):
        domain_series(df, value_col="value", date_col="date", measure_col="c", fixed_measure="MRSS")


# --- domain_series against the real store ---------------------------------------


def test_domain_series_against_the_real_subject_record(conn: sqlite3.Connection) -> None:
    record = get_subject_record(conn, A_SUBJECT_WITH_MOST_DOMAINS)
    labs = domain_series(
        record.labs, value_col="value", date_col="date", measure_col="component_name",
    )
    assert len(labs) > 0
    assert all(not series.series.empty for series in labs)

    mrss = domain_series(record.mrss, value_col="mrss_score", date_col="date", fixed_measure="MRSS")
    assert mrss == []  # this Subject has no MRSS records at all


# --- combine_subject_series -------------------------------------------------------


def _series(measure: str, title: str, dates: list[str], values: list[float]) -> MeasureSeries:
    return MeasureSeries(
        measure=measure, title=title,
        series=pd.DataFrame({"date": pd.to_datetime(dates), "value": values}),
    )


def test_combine_subject_series_tags_each_subjects_rows() -> None:
    per_subject = {
        "subject_1": [_series("WBC", "WBC", ["2020-01-01"], [4.2])],
        "subject_2": [_series("WBC", "WBC", ["2020-01-02"], [5.1])],
    }
    result = combine_subject_series(per_subject)
    assert [series.measure for series in result] == ["WBC"]
    wbc = result[0].series
    assert list(wbc.columns) == ["date", "value", "subject_id"]
    assert set(wbc["subject_id"]) == {"subject_1", "subject_2"}
    assert len(wbc) == 2


def test_combine_subject_series_a_subject_missing_a_measure_contributes_no_rows() -> None:
    per_subject = {
        "subject_1": [_series("WBC", "WBC", ["2020-01-01"], [4.2])],
        "subject_2": [_series("HEMOGLOBIN", "HEMOGLOBIN", ["2020-01-01"], [13.0])],
    }
    result = combine_subject_series(per_subject)
    assert [series.measure for series in result] == ["HEMOGLOBIN", "WBC"]
    wbc = next(series for series in result if series.measure == "WBC")
    assert list(wbc.series["subject_id"]) == ["subject_1"]


def test_combine_subject_series_empty_input_returns_no_series() -> None:
    assert combine_subject_series({}) == []


def test_combine_subject_series_uses_the_first_subjects_title_for_a_measure() -> None:
    per_subject = {
        "subject_1": [_series("FVC", "Forced Vital Capacity (% predicted)", ["2020-01-01"], [85])],
        "subject_2": [_series("FVC", "Forced Vital Capacity (% predicted)", ["2020-01-02"], [90])],
    }
    result = combine_subject_series(per_subject)
    assert result[0].title == "Forced Vital Capacity (% predicted)"


# --- medication_timeline ---------------------------------------------------------


def test_medication_timeline_sorts_by_date() -> None:
    df = pd.DataFrame(
        {
            "date": ["2020-02-01", "2020-01-01"],
            "medication": ["mycophenolate mofetil", "prednisone"],
        }
    )
    result = medication_timeline(df)
    assert list(result["medication"]) == ["prednisone", "mycophenolate mofetil"]


def test_medication_timeline_drops_undated_rows() -> None:
    df = pd.DataFrame({"date": ["2020-01-01", None], "medication": ["prednisone", "aspirin"]})
    result = medication_timeline(df)
    assert list(result["medication"]) == ["prednisone"]


def test_medication_timeline_empty_input_stays_empty() -> None:
    empty = pd.DataFrame(columns=["date", "medication"])
    assert medication_timeline(empty).empty


# --- combine_medication_timelines --------------------------------------------------


def _timeline(dates: list[str], medications: list[str]) -> pd.DataFrame:
    return medication_timeline(pd.DataFrame({"date": dates, "medication": medications}))


def test_combine_medication_timelines_labels_by_subject_and_drug() -> None:
    per_subject = {
        "subject_1": _timeline(["2020-01-01"], ["methotrexate"]),
        "subject_2": _timeline(["2020-01-02"], ["methotrexate"]),
    }
    result = combine_medication_timelines(per_subject)
    assert set(result["label"]) == {"subject_1: methotrexate", "subject_2: methotrexate"}
    assert list(result["subject_id"]) == ["subject_1", "subject_2"]


def test_combine_medication_timelines_sorts_by_date_across_subjects() -> None:
    per_subject = {
        "subject_1": _timeline(["2020-02-01"], ["prednisone"]),
        "subject_2": _timeline(["2020-01-01"], ["aspirin"]),
    }
    result = combine_medication_timelines(per_subject)
    assert list(result["subject_id"]) == ["subject_2", "subject_1"]


def test_combine_medication_timelines_single_subject_label_is_subject_prefixed() -> None:
    per_subject = {"subject_1": _timeline(["2020-01-01"], ["prednisone"])}
    result = combine_medication_timelines(per_subject)
    assert list(result["label"]) == ["subject_1: prednisone"]


def test_combine_medication_timelines_subject_with_no_medications_contributes_nothing() -> None:
    per_subject = {
        "subject_1": _timeline(["2020-01-01"], ["prednisone"]),
        "subject_2": medication_timeline(pd.DataFrame(columns=["date", "medication"])),
    }
    result = combine_medication_timelines(per_subject)
    assert list(result["subject_id"]) == ["subject_1"]


def test_combine_medication_timelines_all_empty_stays_empty() -> None:
    per_subject = {"subject_1": medication_timeline(pd.DataFrame(columns=["date", "medication"]))}
    result = combine_medication_timelines(per_subject)
    assert result.empty
    assert {"subject_id", "label"} <= set(result.columns)


# --- shared_date_range -------------------------------------------------------------


def test_shared_date_range_spans_every_domain_and_medications() -> None:
    labs = combine_subject_series(
        {"subject_1": [_series("WBC", "WBC", ["2020-03-01"], [4.2])]}
    )
    vitals = combine_subject_series(
        {"subject_1": [_series("HR", "HR", ["2020-01-01"], [70])]}
    )
    medications = _timeline(["2020-06-01"], ["prednisone"])
    result = shared_date_range([labs, vitals], medications)
    assert result == (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-01"))


def test_shared_date_range_ignores_empty_domains() -> None:
    labs = combine_subject_series(
        {"subject_1": [_series("WBC", "WBC", ["2020-03-01"], [4.2])]}
    )
    empty_domain: list[MeasureSeries] = []
    result = shared_date_range([labs, empty_domain], pd.DataFrame(columns=["date"]))
    assert result == (pd.Timestamp("2020-03-01"), pd.Timestamp("2020-03-01"))


def test_shared_date_range_no_data_anywhere_returns_none() -> None:
    result = shared_date_range([[], []], pd.DataFrame(columns=["date"]))
    assert result is None


def test_shared_date_range_medications_only() -> None:
    medications = _timeline(["2020-01-01", "2020-02-01"], ["prednisone", "aspirin"])
    result = shared_date_range([[]], medications)
    assert result == (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01"))


# --- apply_disease_duration_axis / apply_disease_duration_to_medications -----------


def test_apply_disease_duration_axis_reexpresses_date_as_years_since_onset() -> None:
    series = combine_subject_series(
        {"subject_1": [_series("WBC", "WBC", ["2021-01-01"], [4.2])]}
    )
    onset_by_subject = {"subject_1": pd.Timestamp("2020-01-01")}
    result = apply_disease_duration_axis(series, onset_by_subject)
    assert len(result) == 1
    assert result[0].series["date"].iloc[0] == pytest.approx(1.0, abs=0.01)
    assert result[0].series["value"].iloc[0] == 4.2


def test_apply_disease_duration_axis_drops_subjects_missing_onset() -> None:
    series = combine_subject_series(
        {
            "subject_1": [_series("WBC", "WBC", ["2021-01-01"], [4.2])],
            "subject_2": [_series("WBC", "WBC", ["2021-01-01"], [5.0])],
        }
    )
    onset_by_subject = {"subject_1": pd.Timestamp("2020-01-01")}  # subject_2 has no onset
    result = apply_disease_duration_axis(series, onset_by_subject)
    assert len(result) == 1
    assert set(result[0].series["subject_id"]) == {"subject_1"}


def test_apply_disease_duration_axis_drops_a_measure_left_with_no_rows() -> None:
    series = combine_subject_series(
        {"subject_1": [_series("WBC", "WBC", ["2021-01-01"], [4.2])]}
    )
    result = apply_disease_duration_axis(series, onset_by_subject={})  # no known onsets at all
    assert result == []


def test_apply_disease_duration_to_medications_reexpresses_date() -> None:
    medications = combine_medication_timelines(
        {"subject_1": _timeline(["2021-01-01"], ["prednisone"])}
    )
    onset_by_subject = {"subject_1": pd.Timestamp("2019-01-01")}
    result = apply_disease_duration_to_medications(medications, onset_by_subject)
    assert result["date"].iloc[0] == pytest.approx(2.0, abs=0.01)


def test_apply_disease_duration_to_medications_drops_subjects_missing_onset() -> None:
    medications = combine_medication_timelines(
        {
            "subject_1": _timeline(["2021-01-01"], ["prednisone"]),
            "subject_2": _timeline(["2021-01-01"], ["aspirin"]),
        }
    )
    onset_by_subject = {"subject_1": pd.Timestamp("2020-01-01")}
    result = apply_disease_duration_to_medications(medications, onset_by_subject)
    assert list(result["subject_id"]) == ["subject_1"]


def test_apply_disease_duration_to_medications_empty_input_stays_empty() -> None:
    empty = pd.DataFrame(columns=["date", "medication", "subject_id", "label"])
    result = apply_disease_duration_to_medications(empty, {})
    assert result.empty
