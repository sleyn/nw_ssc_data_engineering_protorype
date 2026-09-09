"""Support for the "Patient Trajectory" tab (Tab 4, ticket 09; spec User
Story 26) -- the coercion/reshaping logic behind plotting one Subject's
longitudinal record over time, kept separate from the Streamlit rendering in
app.py for the same reason `data.compare` is (see that module's docstring):
the spec puts "UI/visual testing of the Streamlit app itself" out of scope,
but that's a reason to keep this logic out of app.py, not a reason to leave
it untested.

`domain_series` reshapes one of the 4 Observation-shaped domains
`data.access.get_subject_record` returns (labs/vitals/MRSS/PFT) into
independently-plottable per-measure series. It takes `measure_col`/
`fixed_measure` the same either/or way `data.access._ObservationSource`
does, and for the same reason (MRSS has no measure column of its own -- every
row already is one) -- but is not that same type, since this module reshapes
an already-fetched per-Subject frame for charting, not a SQL source a
canonical field name resolves to.
"""

from typing import NamedTuple

import pandas as pd


class MeasureSeries(NamedTuple):
    """One measure's plottable time series within a domain -- e.g. one lab
    component, one vital sign, or the (single, fixed) MRSS score. `series`
    carries only `date`/`value`, already numeric-coerced, dated, and sorted."""

    measure: str
    title: str
    series: pd.DataFrame


def domain_series(
    df: pd.DataFrame,
    *,
    value_col: str,
    date_col: str,
    measure_col: str | None = None,
    fixed_measure: str | None = None,
    title_col: str | None = None,
) -> list[MeasureSeries]:
    """Split one Subject's Observation-shaped domain frame into its
    per-measure plottable series, sorted by measure name. Rows with an
    unparseable date or non-numeric value are dropped (e.g. `lab_report`'s
    rare qualitative "Automated" result) rather than erroring, since a
    handful of unplottable rows is a real, expected shape of this data, not
    a bug. `title_col`, when given, supplies a friendlier chart title than
    the measure code itself (e.g. PFT's NAME "FVC" vs. its DESCRIPTION
    "Forced Vital Capacity (% predicted)")."""
    if (measure_col is None) == (fixed_measure is None):
        raise ValueError("exactly one of measure_col or fixed_measure must be given")
    if df.empty:
        return []

    working = df.copy()
    working[date_col] = pd.to_datetime(working[date_col], errors="coerce")
    working[value_col] = pd.to_numeric(working[value_col], errors="coerce")
    working = working.dropna(subset=[date_col, value_col])
    if working.empty:
        return []

    if measure_col is None:
        assert fixed_measure is not None  # guaranteed by the XOR check above
        groups: list[tuple[str, pd.DataFrame]] = [(fixed_measure, working)]
    else:
        groups = [
            (str(measure), working[working[measure_col] == measure])
            for measure in sorted(working[measure_col].dropna().unique())
        ]

    result: list[MeasureSeries] = []
    for measure, group in groups:
        subset = group.sort_values(date_col)
        title = measure
        if title_col is not None:
            label = subset[title_col].iloc[0]
            if pd.notna(label):
                title = str(label)
        series = subset.rename(columns={date_col: "date", value_col: "value"})[["date", "value"]]
        result.append(MeasureSeries(measure=measure, title=title, series=series))
    return result


def medication_timeline(medications: pd.DataFrame) -> pd.DataFrame:
    """One Subject's medication events, dated rows only, sorted by date --
    the shared shape the timeline chart and its detail table both read.
    Returns `medications` unchanged (still empty) when there's nothing to
    show."""
    if medications.empty:
        return medications
    working = medications.copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    return working.dropna(subset=["date"]).sort_values("date")
