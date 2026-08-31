"""SQLite-backed storage for ForMed user accounts and authentication.

Why SQLite: it ships with Python (no extra dependency), gives us a real
schema with a UNIQUE constraint on email, and handles concurrent access from
multiple Gunicorn workers far better than a hand-rolled JSON file would.
Passwords are never stored in the clear -- only a salted hash via Werkzeug.
"""

import os
import re
import sqlite3
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = os.environ.get(
    "AUTH_DB_PATH", os.path.join(os.path.dirname(__file__), "users.db")
)

VALID_ROLES = ("student", "author", "admin")

# Extra security code required to register for / sign in to a privileged role.
ROLE_SECURITY_CODES = {
    "author": "1111",
    "admin": "2222",
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the users table if it does not exist yet. Safe to call on boot."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                role          TEXT NOT NULL CHECK (role IN ('student', 'author', 'admin')),
                first_name    TEXT NOT NULL,
                last_name     TEXT NOT NULL,
                email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
                phone         TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL
            )
            """
        )


def _valid_email(email):
    return bool(_EMAIL_RE.match(email))


def _valid_phone(phone):
    digits = re.sub(r"\D", "", phone)
    return 7 <= len(digits) <= 15


def _check_security_code(role, security_code):
    """Return an error string if the code is wrong for the role, else None."""
    required = ROLE_SECURITY_CODES.get(role)
    if required is None:
        return None
    if (security_code or "").strip() != required:
        return "Incorrect security code for this role."
    return None


def create_user(role, first_name, last_name, email, phone, password, security_code=None):
    """Validate and insert a new account. Returns {"ok": bool, "error"?: str}."""
    role = (role or "").strip().lower()
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    email = (email or "").strip()
    phone = (phone or "").strip()
    password = password or ""

    if role not in VALID_ROLES:
        return {"ok": False, "error": "Please choose a valid role."}
    if not first_name or not last_name:
        return {"ok": False, "error": "First and last name are both required."}
    if not _valid_email(email):
        return {"ok": False, "error": "Please enter a valid email address."}
    if not _valid_phone(phone):
        return {"ok": False, "error": "Please enter a valid phone number."}
    if len(password) < 8:
        return {"ok": False, "error": "Password must be at least 8 characters."}

    code_error = _check_security_code(role, security_code)
    if code_error:
        return {"ok": False, "error": code_error}

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users
                    (role, first_name, last_name, email, phone, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    role,
                    first_name,
                    last_name,
                    email,
                    phone,
                    generate_password_hash(password),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "An account with that email already exists."}

    return {"ok": True}


def authenticate(role, email, password, security_code=None):
    """Verify credentials. Returns {"ok": bool, "user"?: dict, "error"?: str}."""
    role = (role or "").strip().lower()
    email = (email or "").strip()
    password = password or ""

    if role not in VALID_ROLES:
        return {"ok": False, "error": "Please choose a valid role."}

    code_error = _check_security_code(role, security_code)
    if code_error:
        return {"ok": False, "error": code_error}

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()

    # Same message for "no such user" and "wrong password" so we don't leak
    # which emails have accounts.
    if row is None or not check_password_hash(row["password_hash"], password):
        return {"ok": False, "error": "Invalid email or password."}

    if row["role"] != role:
        return {
            "ok": False,
            "error": "This account is not registered under the selected role.",
        }

    return {"ok": True, "user": _public_user(row)}


def get_user_by_id(user_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return _public_user(row) if row else None


def get_user_by_email(email):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", ((email or "").strip(),)
        ).fetchone()
    return _public_user(row) if row else None


def _public_user(row):
    """Shape a DB row into the fields safe to hand back to the browser."""
    return {
        "id": row["id"],
        "role": row["role"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "email": row["email"],
        "phone": row["phone"],
    }
