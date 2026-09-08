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
from typing import Protocol

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st
from matplotlib.figure import Figure

from data.access import get_variable, list_subjects, table_coverage
from data.auth import log_event, verify_credentials
from data.dictionary import describe_all_tables
from data.store import build_encrypted_store, open_store

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
    rerun (User Story 6 / ADR 0002)."""
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
        "Every table in the built Subject/Cohort store (ADR 0005), with live row/column "
        "counts and a plain-language description of each field, informed by the QC "
        "investigation ([full QC report](docs/qc_report.md))."
    )
    for entry in describe_all_tables(conn):
        label = f"**{entry.table}** -- {entry.row_count:,} rows x {entry.column_count} columns"
        with st.expander(label):
            st.write(entry.description)
            if entry.suppressed_pii_columns:
                st.caption(
                    f"{len(entry.suppressed_pii_columns)} PII column(s) suppressed from this "
                    "view (subject_id + derived fields only, spec \"PII handling\")."
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
        "which is excluded everywhere as PII (spec \"PII handling\"). state is capped to its "
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
        "Population-level structure across the Registry and its 4 Control Subjects (spec "
        "\"Cohort Overview\", User Story 23) -- demographic distributions, SSc subtype "
        "breakdown, and how many Subjects have at least one record in each clinical table."
    )

    subjects = list_subjects(conn)
    _render_cohort_composition(subjects)
    _render_subtype_breakdown(subjects[subjects["cohort"] == "ssc_patient"])
    _render_demographic_distributions(conn)
    _render_table_coverage(conn)


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
        st.info("Compare & Discover is coming in a later ticket (08).")
    with tabs[3]:
        st.info("Patient Trajectory is coming in a later ticket (09).")


if __name__ == "__main__":
    main()
