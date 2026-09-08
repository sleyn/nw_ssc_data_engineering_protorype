"""Tests target the encrypted store's external behavior (spec Testing
Decisions): can it be built, decrypted with the right key, and does it
resist being opened as SQLite without one."""

import sqlite3
import tomllib
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

from data.ingest import DEFAULT_CSV_DIR
from data.store import DEFAULT_SECRETS_PATH, build_encrypted_store, open_store

REGISTRY_SIZE = 1500
CONTROL_SIZE = 4

SQLITE_MAGIC = b"SQLite format 3\x00"


def _write_secrets(path: Path, key: bytes) -> None:
    path.write_text(f'encryption_key = "{key.decode()}"\n')


@pytest.fixture
def secrets_path(tmp_path: Path) -> Path:
    path = tmp_path / "secrets.toml"
    _write_secrets(path, Fernet.generate_key())
    return path


@pytest.fixture
def encrypted_path(tmp_path: Path, secrets_path: Path) -> Path:
    path = tmp_path / "ssc.db.enc"
    build_encrypted_store(
        encrypted_db_path=path, csv_dir=DEFAULT_CSV_DIR, secrets_path=secrets_path
    )
    return path


def test_build_encrypted_store_round_trips_through_open_store(
    encrypted_path: Path, secrets_path: Path
) -> None:
    conn = open_store(encrypted_db_path=encrypted_path, secrets_path=secrets_path)
    try:
        counts = dict(conn.execute("SELECT cohort, COUNT(*) FROM subjects GROUP BY cohort"))
        assert counts == {"ssc_patient": REGISTRY_SIZE, "control": CONTROL_SIZE}
    finally:
        conn.close()


def test_encrypted_artifact_is_not_openable_as_sqlite_directly(encrypted_path: Path) -> None:
    assert encrypted_path.read_bytes()[: len(SQLITE_MAGIC)] != SQLITE_MAGIC

    with pytest.raises(sqlite3.DatabaseError):
        with sqlite3.connect(encrypted_path) as conn:
            conn.execute("SELECT * FROM subjects").fetchall()


def test_open_store_fails_with_the_wrong_key(encrypted_path: Path, tmp_path: Path) -> None:
    wrong_key_path = tmp_path / "wrong_secrets.toml"
    _write_secrets(wrong_key_path, Fernet.generate_key())

    with pytest.raises(InvalidToken):
        open_store(encrypted_db_path=encrypted_path, secrets_path=wrong_key_path)


def test_build_encrypted_store_rejects_a_secrets_file_missing_the_key(
    tmp_path: Path,
) -> None:
    encrypted_path = tmp_path / "ssc.db.enc"
    empty_secrets_path = tmp_path / "secrets.toml"
    empty_secrets_path.write_text("")

    with pytest.raises(RuntimeError, match="encryption_key"):
        build_encrypted_store(
            encrypted_db_path=encrypted_path,
            csv_dir=DEFAULT_CSV_DIR,
            secrets_path=empty_secrets_path,
        )


def test_committed_secrets_file_has_a_usable_encryption_key() -> None:
    """Guards the actual committed .streamlit/secrets.toml (ADR 0004), not a
    fixture, so drift between it and this module is caught."""
    with DEFAULT_SECRETS_PATH.open("rb") as f:
        key = tomllib.load(f)["encryption_key"]
    Fernet(key.encode())  # raises if not a valid Fernet key
