"""Tests target auth.py's external behavior (spec Testing Decisions):
credential verification against a secrets file, and audit-log entries as
read back from disk -- not internal hashing details."""

import hashlib
import json
from pathlib import Path

import pytest

from data.auth import DEFAULT_SECRETS_PATH, log_event, verify_credentials

# The real committed demo credentials (README / .streamlit/secrets.toml).
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "SscDemo2026!"


@pytest.fixture
def secrets_path(tmp_path: Path) -> Path:
    path = tmp_path / "secrets.toml"
    password_hash = hashlib.sha256(b"correct horse").hexdigest()
    path.write_text(f'demo_username = "someuser"\ndemo_password_hash = "{password_hash}"\n')
    return path


# --- verify_credentials against the real committed secrets file -------------


def test_verify_credentials_accepts_the_real_published_demo_credentials() -> None:
    assert DEFAULT_SECRETS_PATH.exists(), "committed .streamlit/secrets.toml is missing"
    assert verify_credentials(DEMO_USERNAME, DEMO_PASSWORD) is True


def test_verify_credentials_rejects_wrong_password() -> None:
    assert verify_credentials(DEMO_USERNAME, "not the password") is False


def test_verify_credentials_rejects_wrong_username() -> None:
    assert verify_credentials("not-demo", DEMO_PASSWORD) is False


# --- verify_credentials against a fixture secrets file -----------------------


def test_verify_credentials_accepts_matching_username_and_password(secrets_path: Path) -> None:
    assert verify_credentials("someuser", "correct horse", secrets_path=secrets_path) is True


def test_verify_credentials_rejects_mismatched_password(secrets_path: Path) -> None:
    assert verify_credentials("someuser", "wrong", secrets_path=secrets_path) is False


def test_verify_credentials_raises_for_malformed_secrets_file(tmp_path: Path) -> None:
    bad_secrets = tmp_path / "secrets.toml"
    bad_secrets.write_text('encryption_key = "unrelated"\n')
    with pytest.raises(RuntimeError, match="demo_username"):
        verify_credentials("anyone", "anything", secrets_path=bad_secrets)


# --- log_event ----------------------------------------------------------------


def test_log_event_appends_one_json_line_with_timestamp_user_action(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.log"
    log_event("demo", "login_success", audit_log_path=log_path)

    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["user"] == "demo"
    assert entry["action"] == "login_success"
    assert entry["detail"] == ""
    assert "timestamp" in entry and entry["timestamp"]


def test_log_event_appends_multiple_events_in_order(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.log"
    log_event("demo", "login_success", audit_log_path=log_path)
    log_event("demo", "view_patient", detail="subject_2005", audit_log_path=log_path)

    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [e["action"] for e in entries] == ["login_success", "view_patient"]
    assert entries[1]["detail"] == "subject_2005"


def test_log_event_creates_parent_directories_if_needed(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "dir" / "audit.log"
    log_event("demo", "login_failure", audit_log_path=log_path)
    assert log_path.exists()
