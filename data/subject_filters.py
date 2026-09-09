"""Support for the Patient Trajectory tab's Subject Filters panel (ticket 08)
-- narrows the pool of Subjects the tab's multi-select offers, without
plotting anything itself. Kept separate from the Streamlit rendering in
app.py for the same reason `data.compare`/`data.trajectory` are (see those
modules' docstrings).

The filter catalog (`list_filter_fields`) spans 5 kinds of filter, each
backed by a different table (or, for Time, several):

- "categorical": an exact-match multi-select against a fixed set of options
  (demographics' gender/ethnicity/races/state/diagnosis; the Antibody Test
  filter, whose options are `"{test}: {result}"` pairs -- antibody values
  are always one of negative/positive/borderline/indeterminate, never
  numeric, confirmed against the real data).
- "range": a numeric slider (demographics' height/weight; one filter per
  Lab Report component, since a component's normal range differs entirely
  from another's).
- "existence": whether a Subject has any qualifying record at all, not a
  value comparison -- Medication (options = canonical drug names a Subject
  was "ever prescribed", `data.normalize.add_canonical_medication_columns`)
  and BAL (`options=None`, a single yes/any toggle with no sub-options).
- "date_range": a date slider, matching a Subject with a qualifying dated
  record in *any* of the 5 domains the Patient Trajectory page plots --
  Vitals, Lab Report, MRSS, PFT, Medications (`_TIME_SOURCES`) -- unlike
  "range", which reads one column of one table.

Selected values *within* one filter combine with OR (e.g. 2 genders
selected -- either matches); separate filters combine with AND (`filter_subjects`
intersects each filter's matching `subject_id` set). Each filter kind's
"neutral" value (an empty multi-select, a range set to its own full bounds,
an unchecked toggle) is a deliberate no-op -- `filter_subjects` narrows
nothing for it -- so a caller can always pass every filter's current widget
state without first checking whether it was actually touched.

Medications and BAL are filter-only here: neither is a pickable variable in
Compare & Discover's catalog (`data.compare`) or `data.access._OBSERVATION_SOURCES`
-- unaffected by this module.
"""

import datetime
import sqlite3
from typing import Literal, NamedTuple

import pandas as pd

from data.normalize import add_canonical_medication_columns

FilterKind = Literal["categorical", "range", "existence", "date_range"]

# A categorical/existence selection is the list of chosen option values
# (OR'd together); a range selection is its (low, high) inclusive bounds; a
# date_range selection is its (low, high) inclusive date bounds; an
# option-less existence selection (BAL) is a plain on/off toggle.
FilterValue = list[str] | tuple[float, float] | tuple[datetime.date, datetime.date] | bool


class FilterField(NamedTuple):
    """One entry in the Subject Filters catalog. `key` is the stable
    identifier `filter_subjects`' `selections` dict is keyed by; `category`/
    `label` are what the panel displays. A `"range"` field populates
    `min_value`/`max_value`, a `"date_range"` field populates `min_date`/
    `max_date` (both leave `options` `None`); every other kind populates
    `options` instead -- `None` only for BAL's option-less existence
    toggle."""

    key: str
    category: str
    label: str
    kind: FilterKind
    options: tuple[str, ...] | None = None
    min_value: float | None = None
    max_value: float | None = None
    min_date: datetime.date | None = None
    max_date: datetime.date | None = None


_DEMOGRAPHIC_CATEGORICAL: tuple[str, ...] = ("gender", "ethnicity", "races", "state", "diagnosis")
_DEMOGRAPHIC_RANGE: tuple[str, ...] = ("height", "weight")


def _demographic_fields(conn: sqlite3.Connection) -> list[FilterField]:
    columns = ", ".join(f'"{c}"' for c in (*_DEMOGRAPHIC_CATEGORICAL, *_DEMOGRAPHIC_RANGE))
    demo = pd.read_sql(f"SELECT {columns} FROM demographics", conn)
    fields: list[FilterField] = []
    for column in _DEMOGRAPHIC_CATEGORICAL:
        options = tuple(sorted(demo[column].dropna().unique()))
        fields.append(
            FilterField(
                f"demographic:{column}", "Demographics", column.capitalize(),
                "categorical", options=options,
            )
        )
    for column in _DEMOGRAPHIC_RANGE:
        values = pd.to_numeric(demo[column], errors="coerce").dropna()
        fields.append(
            FilterField(
                f"demographic:{column}", "Demographics", column.capitalize(), "range",
                min_value=float(values.min()), max_value=float(values.max()),
            )
        )
    return fields


# The 5 dated domains the Patient Trajectory page plots (`app.py`'s
# `_render_trajectory`) -- each `(table, date_column)` pair the Time filter
# checks a Subject against, OR'd together.
_TIME_SOURCES: tuple[tuple[str, str], ...] = (
    ("vitals", "date"),
    ("lab_report", "order_date"),
    ("mrss", "date"),
    ("pft", "PFT_dts"),
    ("medications", "date"),
)


def _all_time_dates(conn: sqlite3.Connection) -> pd.Series:
    parsed = [
        pd.to_datetime(
            pd.read_sql(f'SELECT "{column}" FROM {table}', conn)[column], errors="coerce"
        )
        for table, column in _TIME_SOURCES
    ]
    return pd.concat(parsed, ignore_index=True).dropna()


def _time_field(conn: sqlite3.Connection) -> FilterField:
    dates = _all_time_dates(conn)
    return FilterField(
        "time", "Time", "Visit date", "date_range",
        min_date=dates.min().date(), max_date=dates.max().date(),
    )


def _medication_field(conn: sqlite3.Connection) -> FilterField:
    meds = add_canonical_medication_columns(pd.read_sql("SELECT medication FROM medications", conn))
    options = tuple(sorted(meds["medication"].dropna().unique()))
    return FilterField("medication", "Medication", "Ever prescribed", "existence", options=options)


def _antibody_field(conn: sqlite3.Connection) -> FilterField:
    antibodies = pd.read_sql("SELECT DISTINCT test, value FROM antibodies", conn)
    options = tuple(sorted(f"{row.test}: {row.value}" for row in antibodies.itertuples()))
    return FilterField("antibody", "Antibody Test", "Test result", "categorical", options=options)


def _bal_field() -> FilterField:
    return FilterField("bal", "BAL", "BAL performed", "existence", options=None)


def _lab_report_fields(conn: sqlite3.Connection) -> list[FilterField]:
    lab = pd.read_sql("SELECT component_name, value FROM lab_report", conn)
    fields: list[FilterField] = []
    for component in sorted(lab["component_name"].dropna().unique()):
        component_values = lab.loc[lab["component_name"] == component, "value"]
        values = pd.to_numeric(component_values, errors="coerce").dropna()
        if values.empty:
            continue
        fields.append(
            FilterField(
                f"lab:{component}", "Lab Report", component, "range",
                min_value=float(values.min()), max_value=float(values.max()),
            )
        )
    return fields


def list_filter_fields(conn: sqlite3.Connection) -> list[FilterField]:
    """The full Subject Filters catalog -- every filter the panel can render,
    in display order (Demographics, Time, Medication, Antibody Test, BAL,
    then one entry per Lab Report component)."""
    return [
        *_demographic_fields(conn),
        _time_field(conn),
        _medication_field(conn),
        _antibody_field(conn),
        _bal_field(),
        *_lab_report_fields(conn),
    ]


def _all_subject_ids(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT subject_id FROM subjects")}


def _matching_categorical(
    conn: sqlite3.Connection, table: str, column: str, selected: list[str]
) -> set[str]:
    if not selected:
        return _all_subject_ids(conn)
    placeholders = ",".join("?" * len(selected))
    rows = conn.execute(
        f'SELECT subject_id FROM {table} WHERE "{column}" IN ({placeholders})', selected
    ).fetchall()
    return {row[0] for row in rows}


def _matching_range(
    conn: sqlite3.Connection,
    table: str,
    value_column: str,
    bounds: tuple[float, float],
    *,
    equals: tuple[str, str] | None = None,
) -> set[str]:
    """Subjects whose `value_column` in `table` falls within `bounds`
    (inclusive), optionally restricted to rows matching one `(column,
    value)` equality (`equals`) -- the Lab Report per-component range
    filters share this shape with the demographic ones, differing only in
    that extra row filter (a component name)."""
    lo, hi = bounds
    sql = f'SELECT subject_id, "{value_column}" FROM {table}'
    params: tuple[str, ...] = ()
    if equals is not None:
        equals_column, equals_value = equals
        sql += f' WHERE "{equals_column}" = ?'
        params = (equals_value,)
    frame = pd.read_sql(sql, conn, params=params)
    values = pd.to_numeric(frame[value_column], errors="coerce")
    if equals is not None:
        # Component-scoped (Lab Report) range: at its own full bounds this
        # must be a true no-op, not just "every Subject with a row for this
        # component" -- unlike a demographic range, each Lab Report
        # component scopes to a *different* row subset of the shared
        # `lab_report` table, so leaving ~28 per-component filters at their
        # neutral value would otherwise AND together into an empty Subject
        # pool even though none of them were touched.
        non_null = values.dropna()
        if not non_null.empty and lo <= non_null.min() and hi >= non_null.max():
            return _all_subject_ids(conn)
    return set(frame.loc[values.between(lo, hi), "subject_id"])


def _matching_time(
    conn: sqlite3.Connection, bounds: tuple[datetime.date, datetime.date]
) -> set[str]:
    """Subjects with at least one dated record, in any of `_TIME_SOURCES`
    (Vitals, Lab Report, MRSS, PFT, Medications), within `bounds` (inclusive)
    -- the multi-table analog of `_matching_range` for the Time filter,
    OR'ing across domains instead of reading one column of one table. At its
    own full bounds this must be a true no-op like every other filter's
    neutral value, not just "every Subject with a dated record somewhere" --
    so it falls back to every Subject when `bounds` covers the field's whole
    range, the same guard `_matching_range` uses for Lab Report."""
    all_dates = _all_time_dates(conn)
    lo, hi = pd.Timestamp(bounds[0]), pd.Timestamp(bounds[1])
    if lo <= all_dates.min() and hi >= all_dates.max():
        return _all_subject_ids(conn)

    hi_end_of_day = hi + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    matched: set[str] = set()
    for table, column in _TIME_SOURCES:
        frame = pd.read_sql(f'SELECT subject_id, "{column}" AS date FROM {table}', conn)
        dates = pd.to_datetime(frame["date"], errors="coerce")
        matched |= set(frame.loc[dates.between(lo, hi_end_of_day), "subject_id"])
    return matched


def _matching_medication(conn: sqlite3.Connection, selected: list[str]) -> set[str]:
    if not selected:
        return _all_subject_ids(conn)
    meds = add_canonical_medication_columns(
        pd.read_sql("SELECT subject_id, medication FROM medications", conn)
    )
    return set(meds.loc[meds["medication"].isin(selected), "subject_id"])


def _matching_antibody(conn: sqlite3.Connection, selected: list[str]) -> set[str]:
    if not selected:
        return _all_subject_ids(conn)
    antibodies = pd.read_sql("SELECT subject_id, test, value FROM antibodies", conn)
    combined = antibodies["test"] + ": " + antibodies["value"]
    return set(antibodies.loc[combined.isin(selected), "subject_id"])


def _matching_bal(conn: sqlite3.Connection, performed: bool) -> set[str]:
    if not performed:
        return _all_subject_ids(conn)
    rows = conn.execute("SELECT DISTINCT subject_id FROM bal").fetchall()
    return {row[0] for row in rows}


def filter_subjects(conn: sqlite3.Connection, selections: dict[str, FilterValue]) -> list[str]:
    """The `subject_id` list matching every filter in `selections` --
    selected values within one filter combine with OR, separate filters
    (dict keys) combine with AND (module docstring). A `FilterField.key`
    absent from `selections` is treated as untouched (no-op), same as its
    kind's neutral value would be."""
    matched = _all_subject_ids(conn)
    for key, value in selections.items():
        if key.startswith("demographic:"):
            column = key.split(":", 1)[1]
            if column in _DEMOGRAPHIC_RANGE:
                assert isinstance(value, tuple) and isinstance(value[0], float)
                matched &= _matching_range(conn, "demographics", column, value)
            else:
                assert isinstance(value, list)
                matched &= _matching_categorical(conn, "demographics", column, value)
        elif key == "time":
            assert isinstance(value, tuple) and isinstance(value[0], datetime.date)
            matched &= _matching_time(conn, value)
        elif key == "medication":
            assert isinstance(value, list)
            matched &= _matching_medication(conn, value)
        elif key == "antibody":
            assert isinstance(value, list)
            matched &= _matching_antibody(conn, value)
        elif key == "bal":
            assert isinstance(value, bool)
            matched &= _matching_bal(conn, value)
        elif key.startswith("lab:"):
            component = key.split(":", 1)[1]
            assert isinstance(value, tuple) and isinstance(value[0], float)
            matched &= _matching_range(
                conn, "lab_report", "value", value, equals=("component_name", component)
            )
        else:
            raise ValueError(f"unknown filter key {key!r}")
    return sorted(matched)
