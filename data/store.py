"""Encrypt-at-rest wrapper around the built SQLite store (ADR 0002).

``data.ingest.build_store`` produces a plaintext SQLite file. This module
wraps that build step so the artifact actually written to disk is a
Fernet-encrypted blob that cannot be opened as SQLite directly, and provides
the matching decrypt-to-temp-path helper every downstream reader (EDA
notebook, QC module, Streamlit app) uses to get a live connection.

The encryption key lives in the committed ``.streamlit/secrets.toml`` (ADR
0004), never hardcoded in source. The encrypted store is rebuilt fresh at
every process start and is never committed to git (``.gitignore``).
"""

import atexit
import os
import sqlite3
import tempfile
import tomllib
from pathlib import Path

from cryptography.fernet import Fernet

from data.ingest import DEFAULT_CSV_DIR, build_store

DEFAULT_ENCRYPTED_DB_PATH = Path(__file__).parent / "ssc.db.enc"
DEFAULT_SECRETS_PATH = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"

SECRETS_ENCRYPTION_KEY = "encryption_key"


def _load_encryption_key(secrets_path: Path) -> bytes:
    with secrets_path.open("rb") as f:
        secrets = tomllib.load(f)
    key = secrets.get(SECRETS_ENCRYPTION_KEY)
    if not isinstance(key, str):
        raise RuntimeError(
            f"{secrets_path} is missing a string '{SECRETS_ENCRYPTION_KEY}' entry "
            "(ADR 0002/0004)"
        )
    return key.encode()


def build_encrypted_store(
    encrypted_db_path: Path = DEFAULT_ENCRYPTED_DB_PATH,
    csv_dir: Path = DEFAULT_CSV_DIR,
    secrets_path: Path = DEFAULT_SECRETS_PATH,
) -> None:
    """Build the store from csv_dir and write it to encrypted_db_path as a
    Fernet-encrypted blob. Safe to re-run, like the plaintext build it wraps.
    """
    fernet = Fernet(_load_encryption_key(secrets_path))

    with tempfile.TemporaryDirectory() as tmp_dir:
        plaintext_path = Path(tmp_dir) / "ssc.db"
        build_store(db_path=plaintext_path, csv_dir=csv_dir)
        ciphertext = fernet.encrypt(plaintext_path.read_bytes())

    encrypted_db_path.parent.mkdir(parents=True, exist_ok=True)
    encrypted_db_path.write_bytes(ciphertext)


def open_store(
    encrypted_db_path: Path = DEFAULT_ENCRYPTED_DB_PATH,
    secrets_path: Path = DEFAULT_SECRETS_PATH,
) -> sqlite3.Connection:
    """Decrypt encrypted_db_path to a temp file and return a live connection
    to it. The temp file is removed when the process exits.
    """
    fernet = Fernet(_load_encryption_key(secrets_path))
    plaintext = fernet.decrypt(encrypted_db_path.read_bytes())

    fd, tmp_path_str = tempfile.mkstemp(suffix=".db", prefix="ssc-")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(plaintext)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    atexit.register(tmp_path.unlink, missing_ok=True)

    return sqlite3.connect(tmp_path)
