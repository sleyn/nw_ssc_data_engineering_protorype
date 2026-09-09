"""Streamlit app entry point (spec "Interactive application"), the shell
every later tab ticket (07-09) builds on. Login-gated with the published demo
credentials (User Story 28); every login attempt is audit-logged
(User Story 30, `data.auth`). The store is (re)built and decrypted once per
process (ADR 0002), never per rerun, and read only through the shared
access/dictionary layers -- never raw SQL of its own (spec "Data access
pattern").

Run locally with `uv sync` then `uv run streamlit run app.py`.
"""

import sqlite3
from collections.abc import Iterable, Sequence
from typing import Literal, Protocol

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

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
from data.qc import generate_report
from data.store import build_encrypted_store, open_store
from data.subject_filters import FilterField, FilterValue, filter_subjects, list_filter_fields
from data.trajectory import (
    MeasureSeries,
    combine_medication_timelines,
    combine_subject_series,
    domain_series,
    medication_timeline,
    shared_date_range,
)

# Same 4 categorical demographic fields the EDA notebook plots (ticket 05) --
# kept in sync so the app and notebook show the same population shape.
_DEMOGRAPHIC_FIELDS: tuple[str, ...] = ("gender", "ethnicity", "races", "state")

st.set_page_config(page_title="NW SSc Data Explorer", layout="wide")


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


def _data_dictionary_page() -> None:
    conn = _get_connection()
    st.header("Data & Dictionary")
    st.write(
        "Every table in the built Subject/Cohort store, with live row/column counts, "
        "a plain-language description of each field informed by the QC investigation, "
        "and up to 3 real example values pulled live from the store."
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


def _qc_report_page() -> None:
    conn = _get_connection()
    st.header("QC Report")
    st.write(
        "Every data-quality check run against the built Subject/Cohort store -- key linkage, "
        "cross-table consistency (e.g. demographics weight vs. vitals), constant-value and "
        "guideline-range outliers, and medication name/dose parsing gaps. Regenerated fresh "
        "from the current store on every view, not cached, so it always reflects what's "
        "actually in the store right now."
    )
    st.markdown(generate_report(conn))


_CHART_WIDTH = 500
# The matplotlib medications-timeline height formula was `figsize` inches at
# matplotlib's ~100 dpi default; this converts that same formula directly to
# Plotly's pixel-based `height` (see `_render_medications_timeline`).
_MEDICATION_TIMELINE_DPI = 100


class _PlotlyContainer(Protocol):
    """Either the top-level `st` module or one `st.columns()` slot -- both
    expose `.plotly_chart`/`.dataframe`, which is all `_show_plotly_fig`/
    `_show_dataframe` need."""

    # Keyword params are typed to match Streamlit's own (narrower-than-`str`)
    # overloaded `plotly_chart` exactly -- a broader `**kwargs: object`
    # doesn't structurally match an overloaded implementation under strict
    # mypy.
    def plotly_chart(
        self,
        fig: go.Figure,
        /,
        *,
        theme: Literal["streamlit"] | None = ...,
        use_container_width: bool | None = ...,
    ) -> object: ...

    def dataframe(self, data: object, /, *, hide_index: bool | None = ...) -> object: ...


def _show_plotly_fig(container: _PlotlyContainer, fig: go.Figure) -> None:
    """Render one Plotly figure at the app's fixed chart width, using
    Streamlit's built-in theme sync (`theme="streamlit"`) so it follows the
    viewer's light/dark setting. `use_container_width=False` is required --
    otherwise Streamlit stretches the figure to fill its container and the
    fixed width has no effect."""
    fig.update_layout(width=_CHART_WIDTH)
    container.plotly_chart(fig, theme="streamlit", use_container_width=False)


def _show_dataframe(container: _PlotlyContainer, data: pd.DataFrame) -> None:
    container.dataframe(data, hide_index=True)


# Spacer:content:spacer ratio for `_centered`/`_centered_columns` -- a 1:2:1
# split puts a fixed-width chart (or a `st.columns(2)` grid of them) in the
# middle half of the page instead of flush against the left edge, without
# touching `_CHART_WIDTH` or `use_container_width` (ticket 03).
_CENTER_RATIO = (1, 2, 1)


def _centered() -> _PlotlyContainer:
    """A single spacer-wrapped container, horizontally centered on the
    page -- for one chart that isn't part of a side-by-side grid."""
    _, center, _ = st.columns(_CENTER_RATIO)
    return center


def _centered_columns(n: int) -> Sequence[_PlotlyContainer]:
    """`n` side-by-side columns, nested inside a centered spacer -- the grid
    as a whole is centered, not each chart re-centered within its own grid
    cell (ticket 03)."""
    _, center, _ = st.columns(_CENTER_RATIO)
    return center.columns(n)


def _render_cohort_composition(subjects: pd.DataFrame) -> None:
    cohort_counts = subjects["cohort"].value_counts()
    col1, col2 = st.columns(2)
    col1.metric("Registry patients (ssc_patient)", int(cohort_counts.get("ssc_patient", 0)))
    col2.metric("Control Subjects", int(cohort_counts.get("control", 0)))


def _render_subtype_breakdown(ssc_patients: pd.DataFrame) -> None:
    st.subheader("SSc subtype")
    subtype_counts = ssc_patients["ssc_subtype"].value_counts()
    fig = px.bar(
        x=subtype_counts.index,
        y=subtype_counts.values,
        labels={"x": "", "y": "Patients"},
        title=f"dcSSc / lcSSc split (n={len(ssc_patients):,} Registry patients)",
    )
    _show_plotly_fig(_centered(), fig)


def _render_demographic_distributions(conn: sqlite3.Connection) -> None:
    st.subheader("Demographic distributions")
    st.caption(
        "Age is not shown: the raw data carries no age/age-at-event field, only birth date, "
        "which is excluded everywhere as PII. state is capped to its "
        "10 most common values for readability."
    )
    columns = _centered_columns(2)
    for i, field in enumerate(_DEMOGRAPHIC_FIELDS):
        counts = get_variable(conn, field)["value"].dropna().value_counts()
        title = field
        if len(counts) > 10:
            counts = counts.head(10)
            title = f"{field} (top 10)"
        fig = px.bar(
            x=counts.values,
            y=counts.index,
            orientation="h",
            labels={"x": "Subjects", "y": ""},
            title=title,
        )
        fig.update_yaxes(categoryorder="total ascending")
        _show_plotly_fig(columns[i % 2], fig)

    height = pd.to_numeric(get_variable(conn, "height")["value"], errors="coerce").dropna()
    weight = pd.to_numeric(get_variable(conn, "weight")["value"], errors="coerce").dropna()
    columns = _centered_columns(2)
    _render_histogram(columns[0], height, 30, "inches", "Height, inches (ingest-normalized)")
    _render_histogram(columns[1], weight, 40, "lbs", "Weight, lbs")


def _render_histogram(
    container: _PlotlyContainer, values: pd.Series, nbins: int, xlabel: str, title: str
) -> None:
    fig = px.histogram(x=values, nbins=nbins, labels={"x": xlabel}, title=title)
    fig.update_yaxes(title="Count")
    _show_plotly_fig(container, fig)


_COVERAGE_SHARE_LABEL = "Share of Subjects"


def _render_table_coverage(conn: sqlite3.Connection) -> None:
    st.subheader("Per-table coverage")
    st.write(
        "Share of all Subjects with at least one record in each clinical/molecular table "
        "-- coverage ranges from a handful of Subjects with a skin biopsy to nearly all of "
        "them with a vitals record."
    )
    coverage = table_coverage(conn).sort_values("subject_coverage", ascending=False)

    row_labels = [
        f"{row.distinct_subjects:,} / {row.rows:,} rows" for row in coverage.itertuples()
    ]
    fig = px.bar(
        coverage,
        x="subject_coverage",
        y="table",
        orientation="h",
        text=row_labels,
        labels={"subject_coverage": "Share of Subjects with >=1 record", "table": ""},
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_xaxes(range=[0, 1.3])
    fig.update_yaxes(categoryorder="total ascending")
    _show_plotly_fig(_centered(), fig)

    display_coverage = coverage.rename(columns={"subject_coverage": _COVERAGE_SHARE_LABEL}).copy()
    display_coverage[_COVERAGE_SHARE_LABEL] = display_coverage[_COVERAGE_SHARE_LABEL].map(
        lambda share: f"{share:.1%}"
    )
    st.dataframe(display_coverage, hide_index=True)


def _cohort_overview_page() -> None:
    conn = _get_connection()
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


_NO_VARIABLE_SELECTED = "-- select a variable --"

# Control Subject overlay color, shared by every panel chart type -- matches
# the black style `_add_control_overlay_scatter` used to draw in matplotlib
# (User Story 25).
_CONTROL_OVERLAY_COLOR = "black"
_CONTROL_OVERLAY_MARKER = dict(symbol="diamond", color=_CONTROL_OVERLAY_COLOR, size=10)


def _panel_key(panel_id: int, suffix: str) -> str:
    """The `st.session_state` key for one widget/flag belonging to one
    comparison panel -- stable across reruns because it's derived from the
    panel's own never-reused id, not its position in the list (see module
    docstring "Panel state design")."""
    return f"compare-panel-{panel_id}-{suffix}"


def _apply_pending_panel_rotation(panel_id: int) -> None:
    """If this panel's "rotate" button was clicked last run, swap its X/Y
    picks now -- before this run's X/Y selectboxes are instantiated below.
    Writing to `st.session_state[x_key]`/`[y_key]` after those widgets exist
    for this run would raise (Streamlit forbids mutating a key its own
    widget already claimed this run); doing it here, one run later, avoids
    that entirely."""
    flag_key = _panel_key(panel_id, "rotate-pending")
    if not st.session_state.get(flag_key):
        return
    x_key, y_key = _panel_key(panel_id, "x"), _panel_key(panel_id, "y")
    current_x = st.session_state.get(x_key, _NO_VARIABLE_SELECTED)
    current_y = st.session_state.get(y_key, _NO_VARIABLE_SELECTED)
    st.session_state[x_key], st.session_state[y_key] = current_y, current_x
    st.session_state[flag_key] = False


def _split_control_overlay(
    data: pd.DataFrame, show_overlay: bool
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`(base, control_rows)` -- `control_rows` only non-empty when the
    toggle is on, shared by both chart-drawing functions below."""
    if show_overlay:
        return data[data["cohort"] != "control"], data[data["cohort"] == "control"]
    return data, data.iloc[0:0]


def _add_control_overlay(
    fig: go.Figure, control_rows: pd.DataFrame, x_col: str, y_col: str
) -> None:
    if control_rows.empty:
        return
    fig.add_scatter(
        x=control_rows[x_col], y=control_rows[y_col], mode="markers",
        marker=_CONTROL_OVERLAY_MARKER, name="Control Subject",
        customdata=control_rows[["subject_id"]],
        hovertemplate="Subject: %{customdata[0]}<extra></extra>",
    )


def _render_panel_table(
    container: _PlotlyContainer, result: ComparisonFrame, data: pd.DataFrame
) -> None:
    """The exact rows one panel's chart was built from -- `subject_id`, the
    2 selected variables (under their display labels), and `cohort` (ticket
    02's 4th bullet)."""
    table = data[["subject_id", "x", "y", "cohort"]].rename(
        columns={"x": result.x_label, "y": result.y_label, "cohort": "Cohort"}
    )
    _show_dataframe(container, table)


def _render_panel_scatter(
    container: _PlotlyContainer, result: ComparisonFrame, data: pd.DataFrame, show_overlay: bool
) -> None:
    base, control_rows = _split_control_overlay(data, show_overlay)
    fig = px.scatter(base, x="x", y="y", opacity=0.6, hover_data={"subject_id": True})
    fig.update_layout(xaxis_title=result.x_label, yaxis_title=result.y_label)
    _add_control_overlay(fig, control_rows, "x", "y")
    _show_plotly_fig(container, fig)


def _render_panel_box(
    container: _PlotlyContainer, result: ComparisonFrame, data: pd.DataFrame, show_overlay: bool
) -> None:
    base, control_rows = _split_control_overlay(data, show_overlay)

    # Whichever axis is the categorical one becomes the box grouping -- the
    # ticket's rule is order-independent ("categorical-numeric"), but a box
    # plot itself needs a fixed x/y assignment.
    cat_col, cat_label, num_col, num_label = (
        ("x", result.x_label, "y", result.y_label)
        if result.x_dtype == "categorical"
        else ("y", result.y_label, "x", result.x_label)
    )
    # `points="outliers"` + `hover_data` only affects the individual outlier
    # markers' hover -- the box body's own hover (quartiles/median) is
    # unaffected, and no permanent on-chart label is added either way
    # (ticket 02's 3rd bullet).
    fig = px.box(base, x=cat_col, y=num_col, points="outliers", hover_data={"subject_id": True})
    # Matches the matplotlib box plot's `ax.tick_params(axis="x", rotation=30)`
    # -- category labels can be long enough to overlap unrotated.
    fig.update_layout(xaxis_title=cat_label, yaxis_title=num_label, xaxis_tickangle=-30)
    _add_control_overlay(fig, control_rows, cat_col, num_col)
    _show_plotly_fig(container, fig)


def _render_panel_heatmap(
    container: _PlotlyContainer, result: ComparisonFrame, data: pd.DataFrame
) -> None:
    # Both axes categorical: a count crosstab is the natural chart. No
    # Control Subject overlay here -- no Control Subject has categorical
    # data on both axes a heatmap pairing can reach (matches the matplotlib
    # version, which never rendered the overlay for this chart_type either).
    # No per-point Subject hover either -- a heatmap cell is an aggregate
    # count, not a single Subject's data point (ticket 02's 4th bullet).
    counts = pd.crosstab(data["x"], data["y"])
    fig = px.imshow(
        counts, text_auto=True, color_continuous_scale="Blues",
        labels={"x": result.y_label, "y": result.x_label, "color": "Count"},
    )
    fig.update_xaxes(tickangle=-30)
    _show_plotly_fig(container, fig)


def _render_panel_comparison(
    panel_id: int, conn: sqlite3.Connection, a: CompareVariable, b: CompareVariable
) -> None:
    result = build_comparison(conn, a, b)
    data = result.data.dropna(subset=["x", "y"])
    if data.empty:
        st.warning("No Subjects have data for both of these variables.")
        return

    show_overlay = False
    # Not offered for "heatmap" (both axes categorical -- no Control Subject
    # reaches one) -- hidden entirely (not just disabled) when it wouldn't
    # be meaningful (User Story 25), same as it always was for a pairing no
    # Control Subject has data on both sides of.
    if result.chart_type in ("scatter", "box") and control_overlay_available(data):
        show_overlay = st.toggle(
            "Highlight the 4 Control Subjects", key=_panel_key(panel_id, "overlay")
        )

    # Chart and its companion data table render as one centered horizontal
    # block, not as two independently-positioned elements (ticket 02's 6th
    # bullet).
    chart_col, table_col = _centered_columns(2)
    if result.chart_type == "scatter":
        _render_panel_scatter(chart_col, result, data, show_overlay)
    elif result.chart_type == "box":
        _render_panel_box(chart_col, result, data, show_overlay)
    else:
        _render_panel_heatmap(chart_col, result, data)
    _render_panel_table(table_col, result, data)


_PanelAction = Literal["remove", "rotate"]


def _render_compare_panel(
    conn: sqlite3.Connection,
    panel_id: int,
    panel_number: int,
    catalog_labels: list[str],
    by_label: dict[str, CompareVariable],
) -> _PanelAction | None:
    """Render one panel and return the action its Remove/Rotate button
    requested this run, if any -- the caller applies it (mutating
    `session_state` and calling `st.rerun()`) only after every panel has
    been rendered, never from inside this function. Calling `st.rerun()`
    here, mid-loop, would cut this script run short before later panels'
    own widgets are reached; Streamlit then treats those un-instantiated
    widget keys as orphaned and clears their `session_state` entries at the
    end of the run, silently wiping the picks of every panel after the one
    whose button was clicked. Deferring the rerun until after the full loop
    guarantees every panel's widgets are instantiated at least once this
    run before any rerun can happen."""
    _apply_pending_panel_rotation(panel_id)
    action: _PanelAction | None = None

    with st.container(border=True):
        title_col, remove_col = st.columns([5, 1])
        title_col.markdown(f"**Panel {panel_number}**")
        if remove_col.button("Remove", key=_panel_key(panel_id, "remove")):
            action = "remove"

        x_col, y_col, rotate_col = st.columns([3, 3, 1])
        x_selected = x_col.selectbox(
            "X variable",
            options=[_NO_VARIABLE_SELECTED, *catalog_labels],
            key=_panel_key(panel_id, "x"),
        )
        y_selected = y_col.selectbox(
            "Y variable",
            options=[_NO_VARIABLE_SELECTED, *catalog_labels],
            key=_panel_key(panel_id, "y"),
        )
        rotate_col.markdown("&nbsp;")  # aligns the button with the selectboxes, not their labels
        if rotate_col.button("Rotate", key=_panel_key(panel_id, "rotate"), help="Swap X and Y"):
            action = "rotate"

        if action is not None:
            return action

        if x_selected == _NO_VARIABLE_SELECTED or y_selected == _NO_VARIABLE_SELECTED:
            st.info("Pick both an X and a Y variable to compare.")
            return None
        if x_selected == y_selected:
            st.warning("X and Y are the same variable -- pick two different variables to compare.")
            return None

        a, b = by_label[x_selected], by_label[y_selected]
        _render_panel_comparison(panel_id, conn, a, b)
    return None


def _compare_discover_page() -> None:
    conn = _get_connection()
    st.header("Compare & Discover")
    st.write(
        "Add one comparison panel per pair of variables you want to see -- pick an X and a Y "
        "independently in each panel, rotate to swap them, and get the chart type that fits "
        "what you picked automatically: a scatter for two numeric measures, a box plot for a "
        "numeric measure grouped by a category, or a heatmap for two categorical fields."
    )

    st.session_state.setdefault("compare_panels", [{"id": 0}])
    st.session_state.setdefault("compare_panel_next_id", 1)

    catalog = list_compare_variables(conn)
    by_label = {variable.display_label: variable for variable in catalog}
    catalog_labels = [variable.display_label for variable in catalog]

    pending_action: tuple[int, _PanelAction] | None = None
    for i, panel in enumerate(st.session_state["compare_panels"]):
        action = _render_compare_panel(conn, panel["id"], i + 1, catalog_labels, by_label)
        if action is not None:
            pending_action = (panel["id"], action)

    # Applied only after every panel above has had a chance to render its
    # own widgets this run -- see `_render_compare_panel`'s docstring for
    # why the rerun can't happen from inside the loop.
    if pending_action is not None:
        panel_id, action = pending_action
        if action == "remove":
            st.session_state["compare_panels"] = [
                panel for panel in st.session_state["compare_panels"] if panel["id"] != panel_id
            ]
            for suffix in ("x", "y", "overlay", "rotate-pending"):
                st.session_state.pop(_panel_key(panel_id, suffix), None)
        else:  # rotate
            st.session_state[_panel_key(panel_id, "rotate-pending")] = True
        st.rerun()

    if st.button("Add comparison panel"):
        next_id = st.session_state["compare_panel_next_id"]
        st.session_state["compare_panels"].append({"id": next_id})
        st.session_state["compare_panel_next_id"] = next_id + 1
        st.rerun()


_MAX_TRAJECTORY_SUBJECTS = 8
# Uniform opacity for every Subject's line, at 1 Subject same as at many
# (ticket 05's "equivalent to today's view, at the same reduced opacity").
_TRAJECTORY_LINE_OPACITY = 0.7


def _apply_shared_x_range(
    fig: go.Figure, date_range: tuple[pd.Timestamp, pd.Timestamp] | None
) -> None:
    """Pin `fig`'s x-axis to `date_range` (see `shared_date_range`, ticket
    07) -- only the range itself is fixed, tick spacing stays Plotly's
    default for it."""
    if date_range is not None:
        fig.update_xaxes(range=list(date_range))


def _plot_measure_series(
    container: _PlotlyContainer,
    series: MeasureSeries,
    date_range: tuple[pd.Timestamp, pd.Timestamp] | None,
    subject_colors: dict[str, str],
) -> None:
    """One measure's chart -- one colored line per Subject present in
    `series.series` (`color="subject_id"`), all at the same reduced
    opacity, with no cohort-average/baseline line mixed in. `subject_colors`
    fixes each Subject's color across every chart on the page -- without it,
    Plotly assigns colors by first-appearance order within each chart's own
    (possibly smaller) Subject subset, so the same Subject could get
    different colors on different measures."""
    fig = px.line(
        series.series, x="date", y="value", color="subject_id", markers=True,
        color_discrete_map=subject_colors,
    )
    fig.update_traces(opacity=_TRAJECTORY_LINE_OPACITY)
    fig.update_layout(
        title=series.title,
        xaxis_title="",
        yaxis_title="",
        height=300,
        legend_title_text="Subject",
    )
    fig.update_xaxes(tickangle=-30)
    _apply_shared_x_range(fig, date_range)
    _show_plotly_fig(container, fig)


def _render_domain_small_multiples(
    series_list: list[MeasureSeries],
    domain_label: str,
    date_range: tuple[pd.Timestamp, pd.Timestamp] | None,
    subject_colors: dict[str, str],
) -> None:
    """One small-multiple line chart per `MeasureSeries` (e.g. one per lab
    component, one per vital sign) -- per-Subject measure counts stay small
    enough (a handful to ~15) that this reads better than a single overlaid
    chart. Centered as a whole grid, matching this round's convention
    (ticket 03)."""
    if not series_list:
        st.caption(
            f"No plottable (numeric, dated) {domain_label} records for the selected Subjects."
        )
        return
    columns = _centered_columns(2)
    for i, series in enumerate(series_list):
        _plot_measure_series(columns[i % 2], series, date_range, subject_colors)


def _render_medications_timeline(
    combined: pd.DataFrame,
    subject_count: int,
    date_range: tuple[pd.Timestamp, pd.Timestamp] | None,
) -> None:
    """Medication events plotted over time (ticket 09's 5th domain) -- a
    scatter timeline rather than a line chart, since a medication event is a
    (drug, dose) pair on a date, not a numeric measure with a trend. With
    multiple Subjects selected, every Subject's events render on one
    combined chart, y-axis rows labeled `"{subject_id}: {medication}"` so 2
    Subjects on the same drug don't collide on one row; with exactly 1
    Subject, rows stay labeled by drug alone -- visually unchanged from the
    single-Subject view (ticket 06). The table underneath surfaces the
    parsed dose (`data.normalize`) the chart itself has no room to show."""
    if combined.empty:
        st.caption("No dated medication records for the selected Subjects.")
        return

    row_col = "medication" if subject_count == 1 else "label"

    # Same "taller for more distinct medications" scaling as the matplotlib
    # version -- see `_MEDICATION_TIMELINE_DPI`.
    height = int(_MEDICATION_TIMELINE_DPI * max(2.0, 0.4 * combined[row_col].nunique() + 1))
    fig = go.Figure(
        go.Scatter(
            x=combined["date"],
            y=combined[row_col],
            mode="markers",
            marker=dict(size=10),
        )
    )
    fig.update_layout(xaxis_title="", yaxis_title="", height=height, showlegend=False)
    fig.update_xaxes(tickangle=-30)
    _apply_shared_x_range(fig, date_range)
    _show_plotly_fig(_centered(), fig)

    detail_columns = [
        "subject_id", "date", "medication", "medication_as_recorded", "dose",
        "dose_value", "dose_unit", "dose_frequency",
    ]
    st.dataframe(combined[detail_columns], hide_index=True)


def _combined_domain_series(
    records: dict[str, SubjectRecord],
    domain: Literal["labs", "vitals", "mrss", "pft"],
    *,
    value_col: str,
    date_col: str,
    measure_col: str | None = None,
    fixed_measure: str | None = None,
    title_col: str | None = None,
) -> list[MeasureSeries]:
    """One domain's `combine_subject_series` result across every selected
    Subject -- the shared shape behind each of `_render_trajectory`'s 4
    domain blocks, differing only in which columns that domain's frame
    uses."""
    return combine_subject_series({
        subject_id: domain_series(
            getattr(record, domain), value_col=value_col, date_col=date_col,
            measure_col=measure_col, fixed_measure=fixed_measure, title_col=title_col,
        )
        for subject_id, record in records.items()
    })


def _subject_color_map(subject_ids: Iterable[str]) -> dict[str, str]:
    """Fix one color per Subject, shared across every chart on the
    Trajectory page. Without this, each chart independently colors Subjects
    by first-appearance order in `px.line`'s default palette -- so a
    Subject missing from one domain's data (e.g. no labs but has vitals)
    shifts every later Subject's color on that chart, making the same
    Subject look different color to color."""
    palette = px.colors.qualitative.Plotly
    return {
        subject_id: palette[i % len(palette)]
        for i, subject_id in enumerate(sorted(subject_ids))
    }


def _render_trajectory(records: dict[str, SubjectRecord]) -> None:
    subject_colors = _subject_color_map(records.keys())
    labs = _combined_domain_series(
        records, "labs", value_col="value", date_col="date", measure_col="component_name",
    )
    vitals = _combined_domain_series(
        records, "vitals", value_col="vital_value", date_col="date",
        measure_col="vital_type_name_category",
    )
    mrss = _combined_domain_series(
        records, "mrss", value_col="mrss_score", date_col="date", fixed_measure="MRSS",
    )
    pft = _combined_domain_series(
        records, "pft", value_col="ORD_VALUE", date_col="date", measure_col="NAME",
        title_col="DESCRIPTION",
    )
    medications = combine_medication_timelines({
        subject_id: medication_timeline(record.medications)
        for subject_id, record in records.items()
    })
    # See `shared_date_range` (ticket 07) -- shared by every chart below.
    date_range = shared_date_range([labs, vitals, mrss, pft], medications)

    st.subheader("Labs")
    _render_domain_small_multiples(labs, "lab", date_range, subject_colors)
    st.subheader("Vitals")
    _render_domain_small_multiples(vitals, "vitals", date_range, subject_colors)
    st.subheader("MRSS")
    _render_domain_small_multiples(mrss, "MRSS", date_range, subject_colors)
    st.subheader("PFT")
    _render_domain_small_multiples(pft, "PFT", date_range, subject_colors)
    st.subheader("Medications")
    _render_medications_timeline(medications, len(records), date_range)


def _log_patient_views_once(username: str, subject_ids: list[str]) -> None:
    """Write one `view_patient_record` audit-log entry per newly-added
    Subject -- not re-logged on every Streamlit rerun for Subjects already
    logged this session. Every tab's render function runs on every rerun
    regardless of which tab is on screen, so logging unconditionally here
    would log a view on every unrelated widget interaction elsewhere in the
    app, not just on an actual new selection."""
    logged = st.session_state.setdefault("logged_patient_views", set())
    for subject_id in subject_ids:
        if subject_id not in logged:
            log_event(username, "view_patient_record", detail=subject_id)
            logged.add(subject_id)


def _filter_widget_key(field: FilterField) -> str:
    return f"subject-filter-{field.key}"


def _render_filter_field(field: FilterField) -> FilterValue:
    """One filter's widget, returning its current selection in the shape
    `data.subject_filters.filter_subjects` expects for that `kind` -- a
    `list[str]` for categorical/existence-with-options, a `(low, high)`
    tuple for range, a `bool` for an option-less existence toggle (BAL)."""
    key = _filter_widget_key(field)
    if field.kind == "range":
        assert field.min_value is not None and field.max_value is not None
        return st.slider(
            field.label, min_value=field.min_value, max_value=field.max_value,
            value=(field.min_value, field.max_value), key=key,
        )
    if field.options is not None:
        return st.multiselect(field.label, options=list(field.options), key=key)
    return st.checkbox(field.label, key=key)


def _render_subject_filters_panel(conn: sqlite3.Connection) -> list[str]:
    """The Subject Filters panel (ticket 08): every filter in
    `list_filter_fields`, grouped by category, narrowing the Subject pool
    the trajectory multi-select below offers. Lab Report gets its own
    collapsed expander -- one filter per component makes for a long list a
    reviewer usually isn't touching."""
    st.subheader("Subject Filters")
    st.caption(
        "Selected values within one filter combine with OR (e.g. picking 2 genders shows "
        "Subjects matching either); separate filters combine with AND (e.g. a gender filter "
        "plus BAL performed narrows to Subjects matching both)."
    )
    fields = list_filter_fields(conn)
    by_category: dict[str, list[FilterField]] = {}
    for field in fields:
        by_category.setdefault(field.category, []).append(field)

    selections: dict[str, FilterValue] = {}
    for category, category_fields in by_category.items():
        if category == "Lab Report":
            with st.expander(f"{category} ({len(category_fields)} components)"):
                for field in category_fields:
                    selections[field.key] = _render_filter_field(field)
        else:
            st.markdown(f"**{category}**")
            for field in category_fields:
                selections[field.key] = _render_filter_field(field)

    return filter_subjects(conn, selections)


def _patient_trajectory_page() -> None:
    conn = _get_connection()
    username = st.session_state["username"]
    st.header("Patient Trajectory")
    st.write(
        f"Select up to {_MAX_TRAJECTORY_SUBJECTS} Subjects by `subject_id` to see their "
        "longitudinal records overlaid -- labs, vitals, MRSS, PFT, and medications plotted "
        "over time. Patient name and birth date are never shown here or anywhere else in "
        "this app."
    )
    subject_ids = _render_subject_filters_panel(conn)
    selected = st.multiselect(
        "subject_id",
        options=subject_ids,
        max_selections=_MAX_TRAJECTORY_SUBJECTS,
        help=f"Select up to {_MAX_TRAJECTORY_SUBJECTS} Subjects to overlay on the same charts.",
    )
    if not selected:
        st.info("Select a subject_id above to view that Subject's record.")
        return

    _log_patient_views_once(username, selected)
    records = {subject_id: get_subject_record(conn, subject_id) for subject_id in selected}
    _render_trajectory(records)


def main() -> None:
    if "username" not in st.session_state:
        _render_login_form()
        return

    username = st.session_state["username"]
    st.sidebar.success(f"Logged in as {username}")

    pages = [
        st.Page(_data_dictionary_page, title="Data & Dictionary"),
        st.Page(_cohort_overview_page, title="Cohort Overview"),
        st.Page(_compare_discover_page, title="Compare & Discover"),
        st.Page(_patient_trajectory_page, title="Patient Trajectory"),
        st.Page(_qc_report_page, title="QC Report"),
    ]
    st.navigation(pages).run()


if __name__ == "__main__":
    main()
