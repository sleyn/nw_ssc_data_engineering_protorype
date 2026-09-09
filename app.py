"""Streamlit app entry point (spec "Interactive application"), the shell
every later tab ticket (07-09) builds on. Login-gated with the published demo
credentials (User Story 28); every login attempt is audit-logged
(User Story 30, `data.auth`). The store is (re)built and decrypted once per
process (ADR 0002), never per rerun, and read only through the shared
access/dictionary layers -- never raw SQL of its own (spec "Data access
pattern").

Run locally with `uv sync` then `uv run streamlit run app.py`.
"""

import itertools
import sqlite3
from typing import Protocol

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from data.access import (
    SubjectRecord,
    get_subject_record,
    get_variable,
    list_subjects,
    table_coverage,
)
from data.auth import log_event, verify_credentials
from data.compare import (
    CompareVariable,
    ComparisonFrame,
    build_comparison,
    control_overlay_available,
    list_compare_variables,
)
from data.dictionary import describe_all_tables
from data.store import build_encrypted_store, open_store
from data.trajectory import MeasureSeries, domain_series, medication_timeline

sns.set_theme(style="whitegrid")

# Same 4 categorical demographic fields the EDA notebook plots (ticket 05) --
# kept in sync so the app and notebook show the same population shape.
_DEMOGRAPHIC_FIELDS: tuple[str, ...] = ("gender", "ethnicity", "races", "state")

st.set_page_config(page_title="NW SSc Data Explorer", layout="wide")

TAB_NAMES = ["Data & Dictionary", "Cohort Overview", "Compare & Discover", "Patient Trajectory"]


@st.cache_resource
def _get_connection() -> sqlite3.Connection:
    """Build the encrypted store and open one decrypted connection, cached
    process-wide so this only happens once per app process, not once per
    rerun."""
    build_encrypted_store()
    return open_store()


def _render_login_form() -> str | None:
    """Render the login form and return the logged-in username once
    authenticated this session, or None while still on the login screen."""
    st.title("NW SSc Data Explorer")
    st.caption(
        "Demo credentials are published in the README -- this is a "
        "literal-but-lightweight HIPAA-style demonstration (login, "
        "encryption at rest, audit logging), not a real access-control "
        "boundary (docs/spec.md)."
    )
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if not submitted:
        return None

    if verify_credentials(username, password):
        log_event(username, "login_success")
        st.session_state["username"] = username
        st.rerun()
    else:
        log_event(username or "(blank)", "login_failure")
        st.error("Incorrect username or password.")
    return None


def _render_data_dictionary_tab(conn: sqlite3.Connection) -> None:
    st.header("Data & Dictionary")
    st.write(
        "Every table in the built Subject/Cohort store, with live row/column counts "
        " and a plain-language description of each field, informed by the QC investigation."
    )
    for entry in describe_all_tables(conn):
        label = f"**{entry.table}** -- {entry.row_count:,} rows x {entry.column_count} columns"
        with st.expander(label):
            st.write(entry.description)
            if entry.suppressed_pii_columns:
                st.caption(
                    f"{len(entry.suppressed_pii_columns)} PII column(s) suppressed from this "
                    "view (subject_id + derived fields only)."
                )
            st.dataframe(entry.fields, hide_index=True)


class _PyplotContainer(Protocol):
    """Either the top-level `st` module or one `st.columns()` slot -- both
    expose `.pyplot`, which is all `_show_fig` needs."""

    def pyplot(self, fig: Figure) -> object: ...


def _show_fig(container: _PyplotContainer, fig: Figure) -> None:
    container.pyplot(fig)
    plt.close(fig)


def _render_cohort_composition(subjects: pd.DataFrame) -> None:
    cohort_counts = subjects["cohort"].value_counts()
    col1, col2 = st.columns(2)
    col1.metric("Registry patients (ssc_patient)", int(cohort_counts.get("ssc_patient", 0)))
    col2.metric("Control Subjects", int(cohort_counts.get("control", 0)))


def _render_subtype_breakdown(ssc_patients: pd.DataFrame) -> None:
    st.subheader("SSc subtype")
    subtype_counts = ssc_patients["ssc_subtype"].value_counts()
    fig, ax = plt.subplots(figsize=(5, 3))
    sns.barplot(x=subtype_counts.index, y=subtype_counts.values, ax=ax)
    ax.set_title(f"dcSSc / lcSSc split (n={len(ssc_patients):,} Registry patients)")
    ax.set_xlabel("")
    ax.set_ylabel("Patients")
    _show_fig(st, fig)


def _render_demographic_distributions(conn: sqlite3.Connection) -> None:
    st.subheader("Demographic distributions")
    st.caption(
        "Age is not shown: the raw data carries no age/age-at-event field, only birth date, "
        "which is excluded everywhere as PII. state is capped to its "
        "10 most common values for readability -- the Registry spans far more than 10 states, "
        "long-tailed."
    )
    columns = st.columns(2)
    for i, field in enumerate(_DEMOGRAPHIC_FIELDS):
        counts = get_variable(conn, field)["value"].dropna().value_counts()
        title = field
        if len(counts) > 10:
            counts = counts.head(10)
            title = f"{field} (top 10)"
        fig, ax = plt.subplots(figsize=(5, 3.5))
        sns.barplot(x=counts.values, y=counts.index, ax=ax, orient="h")
        ax.set_title(title)
        ax.set_xlabel("Subjects")
        ax.set_ylabel("")
        _show_fig(columns[i % 2], fig)

    height = pd.to_numeric(get_variable(conn, "height")["value"], errors="coerce").dropna()
    weight = pd.to_numeric(get_variable(conn, "weight")["value"], errors="coerce").dropna()
    columns = st.columns(2)
    fig, ax = plt.subplots(figsize=(5, 3.5))
    sns.histplot(height, bins=30, ax=ax)
    ax.set_title("Height, inches (ingest-normalized)")
    ax.set_xlabel("inches")
    _show_fig(columns[0], fig)

    fig, ax = plt.subplots(figsize=(5, 3.5))
    sns.histplot(weight, bins=40, ax=ax)
    ax.set_title("Weight, lbs")
    ax.set_xlabel("lbs")
    _show_fig(columns[1], fig)


def _render_table_coverage(conn: sqlite3.Connection) -> None:
    st.subheader("Per-table coverage")
    st.write(
        "Share of all Subjects with at least one record in each clinical/molecular table "
        "-- coverage ranges from a handful of Subjects with a skin biopsy to nearly all of "
        "them with a vitals record."
    )
    coverage = table_coverage(conn).sort_values("subject_coverage", ascending=False)

    fig, ax = plt.subplots(figsize=(8, 5))
    sns.barplot(x="subject_coverage", y="table", data=coverage, ax=ax, color="steelblue")
    ax.set_xlim(0, 1.15)
    ax.set_xlabel("Share of Subjects with >=1 record")
    ax.set_ylabel("")
    for i, (_, row) in enumerate(coverage.reset_index(drop=True).iterrows()):
        ax.text(
            row["subject_coverage"] + 0.02,
            i,
            f"{row['distinct_subjects']:,} / {row['rows']:,} rows",
            va="center",
            fontsize=9,
        )
    _show_fig(st, fig)

    st.dataframe(coverage, hide_index=True)


def _render_cohort_overview_tab(conn: sqlite3.Connection) -> None:
    st.header("Cohort Overview")
    st.write(
        "Population-level structure across the Registry and its 4 Control Subjects "
        " -- demographic distributions, SSc subtype "
        "breakdown, and how many Subjects have at least one record in each clinical table."
    )

    subjects = list_subjects(conn)
    _render_cohort_composition(subjects)
    _render_subtype_breakdown(subjects[subjects["cohort"] == "ssc_patient"])
    _render_demographic_distributions(conn)
    _render_table_coverage(conn)


_MAX_COMPARISON_PAIRS = 6  # C(4, 2) -- keeps a large selection from rendering dozens of charts


def _add_control_overlay_scatter(ax: Axes, x: pd.Series, y: pd.Series) -> None:
    """The shared marker style for highlighting Control Subject points on
    top of a scatter or box chart (User Story 25) -- factored out since
    scatter and box charts otherwise repeat the identical call."""
    ax.scatter(x, y, color="black", marker="D", s=70, label="Control Subject", zorder=5)


def _build_comparison_figure(
    result: ComparisonFrame, data: pd.DataFrame, show_control_overlay: bool
) -> Figure:
    """One matplotlib figure for a `ComparisonFrame` whose chart_type is
    scatter/box/line/heatmap -- never called for "unsupported" (the caller
    falls back to a crosstab instead, see `_render_comparison_pair`)."""
    fig, ax = plt.subplots(figsize=(6, 4.5))
    if show_control_overlay:
        base, control_rows = data[data["cohort"] != "control"], data[data["cohort"] == "control"]
    else:
        base, control_rows = data, data.iloc[0:0]

    if result.chart_type == "scatter":
        sns.scatterplot(x="x", y="y", data=base, ax=ax, alpha=0.6)
        if not control_rows.empty:
            _add_control_overlay_scatter(ax, control_rows["x"], control_rows["y"])
        ax.set_xlabel(result.x_label)
        ax.set_ylabel(result.y_label)
    elif result.chart_type == "box":
        # Whichever axis is the categorical one becomes the box grouping --
        # the ticket's rule is order-independent ("categorical-numeric"),
        # but a box plot itself needs a fixed x/y assignment.
        cat_col, cat_label, num_col, num_label = (
            ("x", result.x_label, "y", result.y_label)
            if result.x_dtype == "categorical"
            else ("y", result.y_label, "x", result.x_label)
        )
        sns.boxplot(x=cat_col, y=num_col, data=base, ax=ax)
        if not control_rows.empty:
            _add_control_overlay_scatter(ax, control_rows[cat_col], control_rows[num_col])
        ax.set_xlabel(cat_label)
        ax.set_ylabel(num_label)
        ax.tick_params(axis="x", rotation=30)
    elif result.chart_type == "heatmap":
        # Both axes categorical: a count crosstab is the natural chart. No
        # Control Subject in this dataset has categorical data on either
        # axis a heatmap pairing can reach, so the overlay toggle never
        # actually renders for this chart_type -- `data` here is always
        # every-Subject-is-not-a-Control-Subject already, not just `base`.
        counts = pd.crosstab(data["x"], data["y"])
        sns.heatmap(counts, annot=True, fmt="d", cmap="Blues", ax=ax)
        ax.set_xlabel(result.y_label)
        ax.set_ylabel(result.x_label)
        ax.tick_params(axis="x", rotation=30)
        return fig
    else:  # line -- one side of the pair was picked "over time" (User Story 24)
        hue = "hue" if result.hue_label else None
        sns.lineplot(x="x", y="y", hue=hue, data=base, ax=ax, errorbar=("ci", 95))
        for subject_id, group in control_rows.sort_values("x").groupby("subject_id"):
            ax.plot(
                group["x"], group["y"], color="black", linewidth=2, linestyle="--",
                marker="o", label=f"Control Subject ({subject_id})",
            )
        ax.set_xlabel(result.x_label)
        ax.set_ylabel(result.y_label)
        fig.autofmt_xdate()

    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(fontsize=8)
    return fig


def _render_comparison_pair(
    conn: sqlite3.Connection, a: CompareVariable, b: CompareVariable
) -> None:
    result = build_comparison(conn, a, b)
    data = result.data.dropna(subset=["x", "y"])
    if data.empty:
        st.warning("No Subjects have data for both of these variables.")
        return

    show_control_overlay = False
    if control_overlay_available(data):
        # Hidden entirely (not just disabled) when it wouldn't be
        # meaningful (User Story 25) -- most pairings involving a
        # Registry-only or Lab Result/Antibody field never reach this.
        show_control_overlay = st.toggle(
            "Highlight the 4 Control Subjects",
            key=f"control-overlay-{a.field_name}-{a.level}-{b.field_name}-{b.level}",
        )

    if result.chart_type == "unsupported":
        st.info(
            "A category's trend over time doesn't have an automatic chart rule here -- showing "
            "the raw values instead."
        )
        st.dataframe(data[["subject_id", "x", "y"]])
        return

    fig = _build_comparison_figure(result, data, show_control_overlay)
    _show_fig(st, fig)


def _render_compare_discover_tab(conn: sqlite3.Connection) -> None:
    st.header("Compare & Discover")
    st.write(
        "Pick 2 or more variables from any table, at any level, and get the chart type that "
        "fits what you picked automatically -- a scatter for two numeric measures, a box plot "
        "for a numeric measure grouped by a category, a trend line when one of your picks is a "
        "longitudinal reading followed over time."
    )

    catalog = list_compare_variables(conn)
    by_label = {variable.display_label: variable for variable in catalog}
    selected_labels = st.multiselect(
        "Variables to compare",
        options=[variable.display_label for variable in catalog],
        help=(
            "A demographic field, a per-patient summary of a longitudinal reading (Lab Result / "
            "Vital Sign / MRSS / PFT / Antibody), or that same reading's raw over-time series."
        ),
    )
    if len(selected_labels) < 2:
        st.info("Select at least 2 variables to compare.")
        return

    selected = [by_label[label] for label in selected_labels]
    pairs = list(itertools.combinations(selected, 2))
    if len(pairs) > _MAX_COMPARISON_PAIRS:
        st.caption(
            f"{len(selected)} variables selected -- showing the first {_MAX_COMPARISON_PAIRS} "
            f"of {len(pairs)} possible pairs. Deselect some to see the rest."
        )
        pairs = pairs[:_MAX_COMPARISON_PAIRS]

    for a, b in pairs:
        st.subheader(f"{a.display_label} vs. {b.display_label}")
        _render_comparison_pair(conn, a, b)


_NO_PATIENT_SELECTED = "-- select a subject_id --"


def _plot_measure_series(container: _PyplotContainer, series: MeasureSeries) -> None:
    fig, ax = plt.subplots(figsize=(5, 3))
    sns.lineplot(x="date", y="value", data=series.series, marker="o", ax=ax)
    ax.set_title(series.title)
    ax.set_xlabel("")
    ax.set_ylabel("")
    fig.autofmt_xdate()
    _show_fig(container, fig)


def _render_domain_small_multiples(series_list: list[MeasureSeries], domain_label: str) -> None:
    """One small-multiple line chart per `MeasureSeries` (e.g. one per lab
    component, one per vital sign) -- per-Subject measure counts stay small
    enough (a handful to ~15) that this reads better than a single overlaid
    chart."""
    if not series_list:
        st.caption(f"No plottable (numeric, dated) {domain_label} records for this Subject.")
        return
    columns = st.columns(2)
    for i, series in enumerate(series_list):
        _plot_measure_series(columns[i % 2], series)


def _render_medications_timeline(medications: pd.DataFrame) -> None:
    """Medication events plotted over time (ticket 09's 5th domain) -- a
    scatter timeline rather than a line chart, since a medication event is a
    (drug, dose) pair on a date, not a numeric measure with a trend. The
    table underneath surfaces the parsed dose (`data.normalize`) the chart
    itself has no room to show."""
    working = medication_timeline(medications)
    if working.empty:
        st.caption("No dated medication records for this Subject.")
        return

    fig, ax = plt.subplots(figsize=(8, max(2.0, 0.4 * working["medication"].nunique() + 1)))
    sns.scatterplot(x="date", y="medication", data=working, ax=ax, s=80)
    ax.set_xlabel("")
    ax.set_ylabel("")
    fig.autofmt_xdate()
    _show_fig(st, fig)

    detail_columns = [
        "date", "medication", "medication_as_recorded", "dose",
        "dose_value", "dose_unit", "dose_frequency",
    ]
    st.dataframe(working[detail_columns], hide_index=True)


def _render_subject_record(record: SubjectRecord) -> None:
    st.subheader("Labs")
    _render_domain_small_multiples(
        domain_series(
            record.labs, value_col="value", date_col="date", measure_col="component_name",
        ),
        "lab",
    )
    st.subheader("Vitals")
    _render_domain_small_multiples(
        domain_series(
            record.vitals, value_col="vital_value", date_col="date",
            measure_col="vital_type_name_category",
        ),
        "vitals",
    )
    st.subheader("MRSS")
    _render_domain_small_multiples(
        domain_series(
            record.mrss, value_col="mrss_score", date_col="date", fixed_measure="MRSS",
        ),
        "MRSS",
    )
    st.subheader("PFT")
    _render_domain_small_multiples(
        domain_series(
            record.pft, value_col="ORD_VALUE", date_col="date", measure_col="NAME",
            title_col="DESCRIPTION",
        ),
        "PFT",
    )
    st.subheader("Medications")
    _render_medications_timeline(record.medications)


def _log_patient_view_once(username: str, subject_id: str) -> None:
    """Write one `view_patient` audit-log entry per newly-selected Subject
     -- not once per Streamlit rerun. Every tab's render
    function runs on every rerun regardless of which tab is on screen, so
    logging unconditionally here would log a view on every unrelated widget
    interaction elsewhere in the app, not just on an actual new selection."""
    if st.session_state.get("last_viewed_subject") != subject_id:
        log_event(username, "view_patient", detail=subject_id)
        st.session_state["last_viewed_subject"] = subject_id


def _render_patient_trajectory_tab(conn: sqlite3.Connection, username: str) -> None:
    st.header("Patient Trajectory")
    st.write(
        "Select one Subject by `subject_id` to see their longitudinal record -- labs, vitals, "
        "MRSS, PFT, and medications plotted over time."
        "Patient name and birth date are never shown here or anywhere else in this app."
    )
    subject_ids = list_subjects(conn)["subject_id"].tolist()
    subject_id = st.selectbox("subject_id", options=[_NO_PATIENT_SELECTED, *subject_ids])
    if subject_id == _NO_PATIENT_SELECTED:
        st.info("Select a subject_id above to view that Subject's record.")
        return

    _log_patient_view_once(username, subject_id)
    record = get_subject_record(conn, subject_id)
    _render_subject_record(record)


def main() -> None:
    if "username" not in st.session_state:
        _render_login_form()
        return

    username = st.session_state["username"]
    st.sidebar.success(f"Logged in as {username}")
    conn = _get_connection()

    tabs = st.tabs(TAB_NAMES)
    with tabs[0]:
        _render_data_dictionary_tab(conn)
    with tabs[1]:
        _render_cohort_overview_tab(conn)
    with tabs[2]:
        _render_compare_discover_tab(conn)
    with tabs[3]:
        _render_patient_trajectory_tab(conn, username)


if __name__ == "__main__":
    main()
