"""Login gate and audit logging for the Streamlit app (spec "Auth" /
"Audit logging", User Stories 28/30, ADR 0001/0004).

``verify_credentials`` checks a submitted username/password against the one
published demo credential pair in the committed secrets file
(``.streamlit/secrets.toml``). The password is stored there as a SHA-256
hash rather than plaintext -- real credential-handling practice, kept even
though the demo password itself is intentionally public (ADR 0001).

``log_event`` appends one audit-log entry (timestamp, user, action) per
line, as a JSON object, to a local append-only file -- covering both login
events (this ticket) and patient-record-view events (ticket 09). The log is
local-filesystem only and does not survive a redeploy/restart under the
chosen ephemeral hosting (spec "Audit logging" / Out of Scope) -- a
documented limitation, not an oversight.
"""

import hashlib
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from data.store import DEFAULT_SECRETS_PATH

DEFAULT_AUDIT_LOG_PATH = Path(__file__).parent.parent / "audit.log"

SECRETS_USERNAME_KEY = "demo_username"
SECRETS_PASSWORD_HASH_KEY = "demo_password_hash"


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_credentials(
    username: str, password: str, *, secrets_path: Path = DEFAULT_SECRETS_PATH
) -> bool:
    """Check a submitted username/password against the one published demo
    credential pair in secrets_path. A wrong username/password is a normal
    `False` result, never an exception; a malformed secrets file (missing
    keys) is a setup bug and raises `RuntimeError`."""
    with secrets_path.open("rb") as f:
        secrets = tomllib.load(f)
    expected_username = secrets.get(SECRETS_USERNAME_KEY)
    expected_password_hash = secrets.get(SECRETS_PASSWORD_HASH_KEY)
    if not isinstance(expected_username, str) or not isinstance(expected_password_hash, str):
        raise RuntimeError(
            f"{secrets_path} is missing a string '{SECRETS_USERNAME_KEY}'/"
            f"'{SECRETS_PASSWORD_HASH_KEY}' entry (ADR 0004)"
        )
    return username == expected_username and _hash_password(password) == expected_password_hash


def log_event(
    user: str,
    action: str,
    *,
    detail: str = "",
    audit_log_path: Path = DEFAULT_AUDIT_LOG_PATH,
) -> None:
    """Append one audit-log entry -- UTC timestamp, user, action, and an
    optional free-text detail -- as a single JSON line."""
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "user": user,
        "action": action,
        "detail": detail,
    }
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
