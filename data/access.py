"""Shared read-only data-access layer over the built Subject/Cohort store
(ADR 0005). The one place the EDA notebook and the Streamlit app both read
through, so neither ever re-parses the raw CSVs or grows hand-written
per-view SQL of its own (spec "Data access pattern").

Every function here takes a live ``sqlite3.Connection`` — callers get one
from ``data.store.open_store()`` (the decrypt-to-temp-path store, ADR 0002)
and own its lifetime; this module never opens a store itself. Query results
already reflect the QC normalizations baked into the store and applied here:
canonical ``subject_id`` and inch-normalized ``height`` are baked in at
ingest (``data.ingest``), and canonical medication name / parsed dose are
applied on read (``data.normalize``) to every ``SubjectRecord.medications``.

Three read shapes, matching how the app and notebook actually need the data:

- ``list_subjects``: the full Subject roster with cohort/SSc-subtype.
- ``get_subject_record``: one Subject's full longitudinal record (labs,
  vitals, MRSS, PFT, medications).
- ``get_variable`` / ``list_variables``: a generic picker that resolves any
  canonical field name — a demographic column or an Observation measure
  (ADR 0003: vitals/lab_report/mrss/pft share one component-name-plus-value
  shape internally) — to its source table, without the caller needing to
  know which table a field lives in. Deliberately does not cover
  ``medications``: a medication event is a (drug, dose) pair, not a single
  named measure's value, so it does not fit this shape — it stays reachable
  only through ``get_subject_record``.
"""

import sqlite3
from dataclasses import dataclass
from typing import NamedTuple

import pandas as pd

from data.normalize import add_canonical_medication_columns, parse_dose

# Demographic-level fields, by source table. PII (name, birth date) is
# deliberately excluded from this registry — spec "PII handling": every
# downstream view/output gets subject_id + derived fields only, never raw
# identity columns — so no function in this module can ever return them.
_DEMOGRAPHIC_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("subjects", ("cohort",)),
    (
        "demographics",
        ("study", "ethnicity", "gender", "races", "diagnosis", "state", "height", "weight"),
    ),
    (
        "ssc_subtype",
        (
            "ssc_subtype",
            "other_dx",
            "raynaud_date",
            "nonraynaud_date",
            "nonraynaud_sx",
            "diagnosis_date",
        ),
    ),
)


@dataclass(frozen=True)
class _ObservationSource:
    """One Observation-shaped table (ADR 0003). Either `measure_col` names
    the column holding each row's measure (vitals/lab_report/pft, which mix
    many measures in one table) or `fixed_measure` names the single measure
    every row in the table already is (mrss, which has no measure column of
    its own — every row is an MRSS score)."""

    table: str
    value_col: str
    date_col: str
    measure_col: str | None = None
    fixed_measure: str | None = None


_OBSERVATION_SOURCES: tuple[_ObservationSource, ...] = (
    _ObservationSource("vitals", "vital_value", "date", measure_col="vital_type_name_category"),
    _ObservationSource("lab_report", "value", "order_date", measure_col="component_name"),
    _ObservationSource("mrss", "mrss_score", "date", fixed_measure="MRSS"),
    _ObservationSource("pft", "ORD_VALUE", "PFT_dts", measure_col="NAME"),
)


class SubjectRecord(NamedTuple):
    """One Subject's full longitudinal record. Any table a Subject has no
    records in (e.g. a Control Subject's labs/medications) comes back as an
    empty, correctly-shaped DataFrame, not an error — only an unknown
    subject_id itself is an error (see `get_subject_record`)."""

    labs: pd.DataFrame
    vitals: pd.DataFrame
    mrss: pd.DataFrame
    pft: pd.DataFrame
    medications: pd.DataFrame


def _subject_exists(conn: sqlite3.Connection, subject_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM subjects WHERE subject_id = ?", (subject_id,)).fetchone()
    return row is not None


def _add_parsed_dose_columns(medications: pd.DataFrame) -> pd.DataFrame:
    """Attach dose_value/dose_unit/dose_frequency (`data.normalize.parse_dose`)
    alongside the original `dose` string, for every row including blanks."""
    result = medications.copy()
    raw_doses = result["dose"].where(result["dose"].notna(), None)
    parsed = [parse_dose(dose) for dose in raw_doses]
    result["dose_value"] = [p.value for p in parsed]
    result["dose_unit"] = [p.unit for p in parsed]
    result["dose_frequency"] = [p.frequency for p in parsed]
    return result


def list_subjects(conn: sqlite3.Connection) -> pd.DataFrame:
    """The full Subject roster: subject_id, cohort, and — for SSc Patients —
    their SSc-subtype fields (NULL for Control Subjects, who have no
    ssc_subtype row)."""
    return pd.read_sql(
        """
        SELECT
            s.subject_id,
            s.cohort,
            t.ssc_subtype,
            t.other_dx,
            t.raynaud_date,
            t.nonraynaud_date,
            t.nonraynaud_sx,
            t.diagnosis_date
        FROM subjects s
        LEFT JOIN ssc_subtype t ON s.subject_id = t.subject_id
        ORDER BY s.subject_id
        """,
        conn,
    )


def get_subject_record(conn: sqlite3.Connection, subject_id: str) -> SubjectRecord:
    """Pull one Subject's full longitudinal record. Raises `ValueError` if
    subject_id is not a known Subject at all — a real distinction from a
    known Subject who simply has no records in a given domain."""
    if not _subject_exists(conn, subject_id):
        raise ValueError(f"{subject_id!r} is not a known subject_id")

    labs = pd.read_sql(
        'SELECT order_date AS date, component_name, value FROM lab_report WHERE subject_id = ?',
        conn,
        params=(subject_id,),
    )
    vitals = pd.read_sql(
        "SELECT date, vital_type_name_category, vital_value FROM vitals WHERE subject_id = ?",
        conn,
        params=(subject_id,),
    )
    mrss = pd.read_sql(
        'SELECT date, mrss_score, "ENTRY_USER_NAME" FROM mrss WHERE subject_id = ?',
        conn,
        params=(subject_id,),
    )
    pft = pd.read_sql(
        'SELECT "PFT_dts" AS date, "DESCRIPTION", "NAME", "ORD_VALUE" FROM pft '
        "WHERE subject_id = ?",
        conn,
        params=(subject_id,),
    )
    medications = pd.read_sql(
        "SELECT date, medication, dose FROM medications WHERE subject_id = ?",
        conn,
        params=(subject_id,),
    )
    medications = add_canonical_medication_columns(medications)
    medications = _add_parsed_dose_columns(medications)

    return SubjectRecord(labs=labs, vitals=vitals, mrss=mrss, pft=pft, medications=medications)


def _measures(conn: sqlite3.Connection, source: _ObservationSource) -> list[str]:
    if source.fixed_measure is not None:
        return [source.fixed_measure]
    rows = conn.execute(f'SELECT DISTINCT "{source.measure_col}" FROM {source.table}').fetchall()
    return [row[0] for row in rows]


def list_variables(conn: sqlite3.Connection) -> pd.DataFrame:
    """Every canonical field name `get_variable` can resolve, with its level
    (demographic or observation) and source table — so a caller can discover
    valid names instead of guessing them."""
    rows: list[tuple[str, str, str]] = []
    for table, columns in _DEMOGRAPHIC_TABLES:
        rows.extend((column, "demographic", table) for column in columns)
    for source in _OBSERVATION_SOURCES:
        rows.extend((measure, "observation", source.table) for measure in _measures(conn, source))
    return pd.DataFrame(rows, columns=["field_name", "level", "table"]).sort_values(
        "field_name", ignore_index=True
    )


def _fetch_demographic(
    conn: sqlite3.Connection, table: str, column: str, subject_id: str | None
) -> pd.DataFrame:
    sql = f'SELECT subject_id, "{column}" AS value FROM {table}'
    params: list[str] = []
    if subject_id is not None:
        sql += " WHERE subject_id = ?"
        params.append(subject_id)
    result = pd.read_sql(sql, conn, params=params)
    result["date"] = pd.NaT
    return result[["subject_id", "date", "value"]]


def _fetch_observation(
    conn: sqlite3.Connection,
    source: _ObservationSource,
    field_name: str,
    subject_id: str | None,
) -> pd.DataFrame:
    sql = (
        f'SELECT subject_id, "{source.date_col}" AS date, "{source.value_col}" AS value '
        f"FROM {source.table}"
    )
    conditions: list[str] = []
    params: list[str] = []
    if source.measure_col is not None:
        conditions.append(f'"{source.measure_col}" = ?')
        params.append(field_name)
    if subject_id is not None:
        conditions.append("subject_id = ?")
        params.append(subject_id)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    return pd.read_sql(sql, conn, params=params)


def get_variable(
    conn: sqlite3.Connection, field_name: str, *, subject_id: str | None = None
) -> pd.DataFrame:
    """Resolve `field_name` — a demographic column or an Observation measure
    (any of vitals/lab_report/mrss/pft) — to a `subject_id, date, value`
    DataFrame, without the caller needing to know which table it lives in.
    `date` is `NaT` for demographic-level fields (one value per Subject, not
    per visit). Optionally restrict to one Subject. Raises `ValueError` for
    an unrecognized field_name — call `list_variables` for the known set.
    """
    for table, columns in _DEMOGRAPHIC_TABLES:
        if field_name in columns:
            return _fetch_demographic(conn, table, field_name, subject_id)
    for source in _OBSERVATION_SOURCES:
        if field_name in _measures(conn, source):
            return _fetch_observation(conn, source, field_name, subject_id)
    raise ValueError(f"{field_name!r} is not a known field — call list_variables() for the options")


if __name__ == "__main__":
    from data.store import build_encrypted_store, open_store

    build_encrypted_store()
    store_conn = open_store()
    try:
        subjects = list_subjects(store_conn)
        print(f"list_subjects: {subjects.shape[0]} rows, columns={list(subjects.columns)}")

        variables = list_variables(store_conn)
        print(f"list_variables: {variables.shape[0]} fields")

        an_ssc_patient = subjects.loc[subjects["cohort"] == "ssc_patient", "subject_id"].iloc[0]
        record = get_subject_record(store_conn, an_ssc_patient)
        print(
            f"get_subject_record({an_ssc_patient!r}): "
            f"labs={record.labs.shape}, vitals={record.vitals.shape}, "
            f"mrss={record.mrss.shape}, pft={record.pft.shape}, "
            f"medications={record.medications.shape}"
        )

        demographic_sample = get_variable(store_conn, "gender")
        print(f"get_variable('gender'): {demographic_sample.shape[0]} rows")

        observation_sample = get_variable(store_conn, "WBC", subject_id=an_ssc_patient)
        print(
            f"get_variable('WBC', subject_id={an_ssc_patient!r}): "
            f"{observation_sample.shape[0]} rows"
        )
    finally:
        store_conn.close()
