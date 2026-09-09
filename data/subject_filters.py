"""Support for the Patient Trajectory tab's Subject Filters panel (ticket 08)
-- narrows the pool of Subjects the tab's multi-select offers, without
plotting anything itself. Kept separate from the Streamlit rendering in
app.py for the same reason `data.compare`/`data.trajectory` are (see those
modules' docstrings).

The filter catalog (`list_filter_fields`) spans 4 kinds of filter, each
backed by a different table:

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

import sqlite3
from typing import Literal, NamedTuple

import pandas as pd

from data.normalize import add_canonical_medication_columns

FilterKind = Literal["categorical", "range", "existence"]

# A categorical/existence selection is the list of chosen option values
# (OR'd together); a range selection is its (low, high) inclusive bounds; an
# option-less existence selection (BAL) is a plain on/off toggle.
FilterValue = list[str] | tuple[float, float] | bool


class FilterField(NamedTuple):
    """One entry in the Subject Filters catalog. `key` is the stable
    identifier `filter_subjects`' `selections` dict is keyed by; `category`/
    `label` are what the panel displays. Exactly one of `options` (categorical
    / existence) or `min_value`+`max_value` (range) is populated, except a
    "range" filter is always the former + the latter — see `kind`."""

    key: str
    category: str
    label: str
    kind: FilterKind
    options: tuple[str, ...] | None = None
    min_value: float | None = None
    max_value: float | None = None


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
    in display order (Demographics, Medication, Antibody Test, BAL, then one
    entry per Lab Report component)."""
    return [
        *_demographic_fields(conn),
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
    conn: sqlite3.Connection, table: str, column: str, bounds: tuple[float, float]
) -> set[str]:
    lo, hi = bounds
    frame = pd.read_sql(f'SELECT subject_id, "{column}" FROM {table}', conn)
    values = pd.to_numeric(frame[column], errors="coerce")
    return set(frame.loc[values.between(lo, hi), "subject_id"])


def _matching_lab_range(
    conn: sqlite3.Connection, component: str, bounds: tuple[float, float]
) -> set[str]:
    lo, hi = bounds
    lab = pd.read_sql(
        "SELECT subject_id, value FROM lab_report WHERE component_name = ?",
        conn, params=(component,),
    )
    values = pd.to_numeric(lab["value"], errors="coerce")
    return set(lab.loc[values.between(lo, hi), "subject_id"])


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
                assert isinstance(value, tuple)
                matched &= _matching_range(conn, "demographics", column, value)
            else:
                assert isinstance(value, list)
                matched &= _matching_categorical(conn, "demographics", column, value)
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
            assert isinstance(value, tuple)
            matched &= _matching_lab_range(conn, component, value)
        else:
            raise ValueError(f"unknown filter key {key!r}")
    return sorted(matched)
