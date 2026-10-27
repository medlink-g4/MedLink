"""Tests for the two authentication defects fixed in Sprint 3.

Both were logged during Sprint 1 review and carried through two sprints:
the database path was pinned to the repository root and ignored any
configured path, and the signup form took the role straight from the
request body so anyone could register themselves as a doctor.
"""

import importlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[2]


def fresh_db(tmp_path):
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "database" / "init_db.py")],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path / "medlink.db"


def make_client(db, allow_staff=False):
    """Reload auth so the module-level staff-signup flag is re-read."""
    if allow_staff:
        os.environ["MEDLINK_ALLOW_STAFF_SIGNUP"] = "1"
    else:
        os.environ.pop("MEDLINK_ALLOW_STAFF_SIGNUP", None)
    import routes.auth as auth_module
    importlib.reload(auth_module)

    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)
    app.register_blueprint(auth_module.auth_bp, url_prefix="/api/auth")
    return app.test_client()


@pytest.fixture()
def db(tmp_path):
    return fresh_db(tmp_path)


def signup(client, role, email="new@x.test"):
    return client.post("/api/auth/register", json={
        "name": "New Person", "email": email,
        "password": "pw12345", "role": role,
    })


# --- the database path is configurable ------------------------------------
def test_auth_uses_the_configured_database_not_the_repo_root(db):
    """The whole point of the fix: writes land in the configured file."""
    client = make_client(db)
    assert signup(client, "patient").status_code == 201

    conn = sqlite3.connect(db)
    found = conn.execute(
        "SELECT email FROM users WHERE email = ?", ("new@x.test",)
    ).fetchone()
    conn.close()
    assert found is not None, "user was written to the configured database"


def test_login_works_against_the_configured_database(db):
    client = make_client(db)
    signup(client, "patient")
    r = client.post("/api/auth/login",
                    json={"email": "new@x.test", "password": "pw12345"})
    assert r.status_code == 200
    assert "token" in r.get_json()


# --- self-registration cannot create staff --------------------------------
@pytest.mark.parametrize("role", ["doctor", "nurse"])
def test_cannot_self_register_as_staff(db, role):
    r = signup(make_client(db), role)
    assert r.status_code == 403
    assert "Cannot self-register" in r.get_json()["error"]


def test_patients_can_still_self_register(db):
    r = signup(make_client(db), "patient")
    assert r.status_code == 201
    assert r.get_json()["role"] == "patient"


def test_unknown_role_is_still_a_400(db):
    r = signup(make_client(db), "admin")
    assert r.status_code == 400
    assert r.get_json()["error"] == "Invalid role"


def test_staff_signup_can_be_enabled_for_local_development(db):
    r = signup(make_client(db, allow_staff=True), "doctor")
    assert r.status_code == 201
    make_client(db)  # restore the secure default for later tests


# --- the detail row is still created (Mackenzie's Sprint 2 fix) -----------
def test_registering_a_patient_creates_the_patients_row(db):
    client = make_client(db)
    user_id = signup(client, "patient").get_json()["userId"]
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT 1 FROM patients WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    assert row is not None
