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

import streamlit as st

from data.auth import log_event, verify_credentials
from data.dictionary import describe_all_tables
from data.store import build_encrypted_store, open_store

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
        st.info("Cohort Overview is coming in a later ticket (07).")
    with tabs[2]:
        st.info("Compare & Discover is coming in a later ticket (08).")
    with tabs[3]:
        st.info("Patient Trajectory is coming in a later ticket (09).")


if __name__ == "__main__":
    main()
