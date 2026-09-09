"""Support for the "Compare & Discover" tab (Tab 3, ticket 08; spec User
Stories 24, 25, 27) — a free-form variable picker that lets a reviewer find
structure in the data themselves, rather than being limited to fixed
summary charts (Tabs 1/2).

Kept separate from the Streamlit rendering in app.py so the actual picking/
merging/chart-type logic is plain pandas and directly unit-testable — the
spec explicitly puts "UI/visual testing of the Streamlit app itself" out of
scope, but that's a reason to keep this logic out of app.py, not a reason to
leave it untested.

A variable can be picked at either of 2 levels (User Story 24's own
wording, minus the 3rd -- see ADR 0006):

- "demographic": a static, one-value-per-Subject field (`subjects` /
  `demographics` / `ssc_subtype`) — inherently one row per Subject already.
- "per_patient_aggregate": a longitudinal Observation field (Vital Sign /
  Lab Result / MRSS / PFT / Antibody — CONTEXT.md's "Observation" concept,
  see `data.access`), collapsed to one value per Subject so it can be
  compared against a demographic field or another aggregate on equal
  footing. Numeric fields aggregate by mean; non-numeric fields (e.g. an
  Antibody result of "negative"/"positive") aggregate by the most recent
  recorded value instead — there is no numeric "average" of a category.

ADR 0006 removed the 3rd level ("longitudinal_series", the same Observation
field kept as its raw per-visit `(date, value)` rows) and the `date`/`line`/
`unsupported` machinery it required: 2 of its 3 pairings were broken (a
categorical pairing fell back to a plain table; two series paired together
degenerated into a near-empty heatmap via a sparse same-day join), and the
one working pairing still required a user to correctly guess which pairing
was safe. Patient Trajectory's own per-measure line charts (`data.trajectory`)
are a separate code path, untouched by that removal.

Every catalog entry carries a domain-vocabulary label (Vital Sign / Lab
Result / MRSS / PFT / Antibody / Demographic / Disease Classification) — the
internal "Observation" term (`data.access`, CONTEXT.md) never reaches this
module's public output (User Story 27).
"""

import sqlite3
from typing import Literal, NamedTuple

import pandas as pd

from data.access import get_variable, list_subjects, list_variables

Level = Literal["demographic", "per_patient_aggregate"]
Dtype = Literal["numeric", "categorical"]
ChartType = Literal["scatter", "box", "heatmap"]

# A value column counts as numeric if at least this fraction of its non-null
# values coerce to a number — sqlite/pandas round-tripping leaves some
# genuinely-numeric columns (e.g. WBC) as a str/float mix rather than a
# clean float64 dtype, so a strict dtype check alone would misclassify them.
_NUMERIC_COERCION_THRESHOLD = 0.95

# Domain-vocabulary label per source table (CONTEXT.md) — the one place
# this mapping lives, so every label the Compare & Discover picker shows
# comes from here rather than the internal table/"Observation" name
# (User Story 27, ticket 08's 4th bullet).
TABLE_DOMAIN_LABELS: dict[str, str] = {
    "subjects": "Demographic",
    "demographics": "Demographic",
    "ssc_subtype": "Disease Classification",
    "vitals": "Vital Sign",
    "lab_report": "Lab Result",
    "mrss": "MRSS",
    "pft": "PFT",
    "antibodies": "Antibody",
}


class CompareVariable(NamedTuple):
    """One entry in the Compare & Discover picker. `field_name` is the
    canonical name `data.access.get_variable` resolves; `display_label` is
    what the picker shows the user (domain vocabulary, plus the level for
    Observation fields — see module docstring)."""

    field_name: str
    table: str
    domain_label: str
    level: Level
    display_label: str


def list_compare_variables(conn: sqlite3.Connection) -> list[CompareVariable]:
    """Every variable pickable in the Compare & Discover picker, sorted for
    display: each demographic field once, each longitudinal Observation
    field once, collapsed to its per-patient aggregate (ADR 0006)."""
    catalog: list[CompareVariable] = []
    for _, row in list_variables(conn).iterrows():
        field_name, level, table = str(row["field_name"]), str(row["level"]), str(row["table"])
        domain_label = TABLE_DOMAIN_LABELS.get(table, table)
        if level == "demographic":
            catalog.append(
                CompareVariable(
                    field_name, table, domain_label, "demographic",
                    f"{domain_label}: {field_name}",
                )
            )
        else:
            catalog.append(
                CompareVariable(
                    field_name, table, domain_label, "per_patient_aggregate",
                    f"{domain_label}: {field_name} (per-patient summary)",
                )
            )
    return sorted(catalog, key=lambda v: v.display_label)


def infer_dtype(values: pd.Series) -> Dtype:
    """"numeric" if (nearly) every non-null value coerces to a number, else
    "categorical"."""
    non_null = values.dropna()
    if non_null.empty:
        return "categorical"
    if pd.api.types.is_numeric_dtype(non_null):
        return "numeric"
    coerced = pd.to_numeric(non_null, errors="coerce")
    if coerced.notna().mean() >= _NUMERIC_COERCION_THRESHOLD:
        return "numeric"
    return "categorical"


def choose_chart_type(x_dtype: Dtype, y_dtype: Dtype) -> ChartType:
    """The 2 remaining auto-chart rules (numeric-numeric -> scatter,
    categorical-numeric -> box), plus a 3rd this module adds for the one
    remaining common case: categorical-categorical -> heatmap (a count
    crosstab is a real chart, not the plain table a "no rule" fallback would
    otherwise leave a reviewer with)."""
    dtypes = {x_dtype, y_dtype}
    if dtypes == {"numeric"}:
        return "scatter"
    if dtypes == {"numeric", "categorical"}:
        return "box"
    return "heatmap"


def _aggregate_per_subject(raw: pd.DataFrame) -> pd.DataFrame:
    """Collapse a `(subject_id, date, value)` longitudinal frame to one row
    per Subject — see module docstring for the mean-vs-most-recent choice."""
    if infer_dtype(raw["value"]) == "numeric":
        numeric = raw.assign(value=pd.to_numeric(raw["value"], errors="coerce"))
        return numeric.groupby("subject_id", as_index=False)[["value"]].mean()
    dated = raw.dropna(subset=["date"]).assign(date=pd.to_datetime(raw["date"], errors="coerce"))
    dated = dated.dropna(subset=["date"]).sort_values("date")
    latest = dated.groupby("subject_id", as_index=False).last()
    return latest[["subject_id", "value"]]


def resolve_compare_variable(conn: sqlite3.Connection, variable: CompareVariable) -> pd.DataFrame:
    """Resolve one catalog entry to its comparison-ready frame: `subject_id,
    value` (one row per Subject)."""
    raw = get_variable(conn, variable.field_name)
    if variable.level == "demographic":
        return raw[["subject_id", "value"]]
    return _aggregate_per_subject(raw)


class ComparisonFrame(NamedTuple):
    """The merged, chart-ready result of pairing two `CompareVariable`s.
    `data` always carries `subject_id`, `cohort` (for the Control Subject
    overlay, User Story 25), `x`, and `y`."""

    data: pd.DataFrame
    x_label: str
    y_label: str
    x_dtype: Dtype
    y_dtype: Dtype
    chart_type: ChartType


def control_overlay_available(frame: pd.DataFrame) -> bool:
    """Whether the Control Subject overlay toggle (User Story 25) is
    meaningful for this comparison: at least one of the 4 Control Subjects
    survived the merge with data for both selected variables. Many pairings
    (any Registry-only demographic/disease-classification field, or a
    domain like Lab Report / Antibody that no Control Subject has any
    records in — CONTEXT.md) always come back empty here, which is exactly
    when the ticket says the toggle should be hidden or disabled rather than
    forced into a view too thin to be useful."""
    return bool((frame["cohort"] == "control").any())


def build_comparison(
    conn: sqlite3.Connection, a: CompareVariable, b: CompareVariable
) -> ComparisonFrame:
    """Merge 2 selected variables into one chart-ready `ComparisonFrame`,
    joined on `subject_id`."""
    subjects = list_subjects(conn)[["subject_id", "cohort"]]
    a_frame = resolve_compare_variable(conn, a)
    b_frame = resolve_compare_variable(conn, b)
    merged = a_frame.merge(b_frame, on="subject_id", suffixes=("_a", "_b"))
    merged = merged.rename(columns={"value_a": "x", "value_b": "y"})
    merged = merged.merge(subjects, on="subject_id", how="left")
    x_dtype, y_dtype = infer_dtype(merged["x"]), infer_dtype(merged["y"])
    chart_type = choose_chart_type(x_dtype, y_dtype)
    return ComparisonFrame(merged, a.display_label, b.display_label, x_dtype, y_dtype, chart_type)
