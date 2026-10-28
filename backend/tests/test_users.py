"""Tests for user profile management (task 4.1).

Same approach as the earlier suites: a real SQLite database built from the
project's own init_db.py, real tokens minted the way login mints them, and the
real blueprints mounted on a Flask app. Registration goes through the real
/api/auth/register route so the detail rows are created exactly as in use.
"""

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import jwt
import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routes.auth import auth_bp
from routes.permissions import JWT_ALGORITHM, JWT_SECRET
from routes.users import users_bp

REPO_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "oldpass123"


@pytest.fixture()
def client(tmp_path):
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "database" / "init_db.py")],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(tmp_path / "medlink.db")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(users_bp, url_prefix="/api/users")
    c = app.test_client()
    c.db_file = tmp_path / "medlink.db"
    return c


def register(client, name, email, role):
    """Create an account and return its user id.

    Patients sign up through the real route. Doctors and nurses cannot
    self-register (the route refuses them), so they are created directly in
    the test database with the same rows the route would create.
    """
    if role == "patient":
        r = client.post(
            "/api/auth/register",
            json={"name": name, "email": email, "password": PASSWORD, "role": role},
        )
        assert r.status_code == 201, r.get_json()
        return r.get_json()["userId"]
    conn = sqlite3.connect(client.db_file)
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, generate_password_hash(PASSWORD), role),
        )
        conn.execute(
            "INSERT INTO providers (user_id, role_type, specialty, can_prescribe) "
            "VALUES (?, ?, NULL, ?)",
            (cur.lastrowid, role, 1 if role == "doctor" else 0),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def token_for(user_id, role, expires_in=timedelta(hours=2)):
    return jwt.encode(
        {
            "userId": user_id,
            "role": role,
            "exp": datetime.now().astimezone() + expires_in,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def people(client):
    """A patient, a second patient, a doctor and a nurse, with tokens."""
    ids = {
        "pat": register(client, "Pat Patient", "pat@x.com", "patient"),
        "pat2": register(client, "Other Patient", "other@x.com", "patient"),
        "doc": register(client, "Dr Smith", "smith@x.com", "doctor"),
        "nurse": register(client, "Nancy Nurse", "nancy@x.com", "nurse"),
    }
    roles = {"pat": "patient", "pat2": "patient", "doc": "doctor", "nurse": "nurse"}
    return {
        k: {"id": v, "role": roles[k], "h": auth(token_for(v, roles[k]))}
        for k, v in ids.items()
    }


# --- viewing ---------------------------------------------------------------


def test_patient_sees_own_profile_with_patient_details(client, people):
    r = client.get("/api/users/me", headers=people["pat"]["h"])
    assert r.status_code == 200
    body = r.get_json()
    assert (body["name"], body["email"], body["role"]) == (
        "Pat Patient",
        "pat@x.com",
        "patient",
    )
    assert set(body["patient"]) == {"id", "date_of_birth", "phone", "insurance_info"}
    assert "provider" not in body
    assert "password_hash" not in str(body)


def test_doctor_and_nurse_see_provider_details(client, people):
    doc = client.get("/api/users/me", headers=people["doc"]["h"]).get_json()
    nurse = client.get("/api/users/me", headers=people["nurse"]["h"]).get_json()
    assert (
        doc["provider"]["role_type"] == "doctor"
        and doc["provider"]["can_prescribe"] == 1
    )
    assert (
        nurse["provider"]["role_type"] == "nurse"
        and nurse["provider"]["can_prescribe"] == 0
    )
    assert "patient" not in doc


def test_profile_always_belongs_to_the_token_holder(client, people):
    a = client.get("/api/users/me", headers=people["pat"]["h"]).get_json()
    b = client.get("/api/users/me", headers=people["pat2"]["h"]).get_json()
    assert a["email"] == "pat@x.com" and b["email"] == "other@x.com"


def test_no_token_and_bad_token_are_unauthorized(client, people):
    assert client.get("/api/users/me").status_code == 401
    assert client.get("/api/users/me", headers=auth("x.y.z")).status_code == 401
    expired = auth(token_for(people["pat"]["id"], "patient", timedelta(hours=-1)))
    assert client.get("/api/users/me", headers=expired).status_code == 401


# --- editing ---------------------------------------------------------------


def test_patient_updates_name_and_patient_details(client, people):
    r = client.put(
        "/api/users/me",
        headers=people["pat"]["h"],
        json={
            "name": "  Patricia Patient ",
            "phone": "(919) 555-0142",
            "date_of_birth": "1990-4-5",
            "insurance_info": "Blue Cross",
        },
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["name"] == "Patricia Patient"
    assert body["patient"]["phone"] == "(919) 555-0142"
    assert body["patient"]["date_of_birth"] == "1990-04-05"
    again = client.get("/api/users/me", headers=people["pat"]["h"]).get_json()
    assert again["patient"]["insurance_info"] == "Blue Cross"


def test_partial_update_leaves_other_fields_alone(client, people):
    client.put("/api/users/me", headers=people["pat"]["h"], json={"phone": "555-0100"})
    r = client.put(
        "/api/users/me", headers=people["pat"]["h"], json={"name": "New Name"}
    )
    body = r.get_json()
    assert body["name"] == "New Name" and body["patient"]["phone"] == "555-0100"
    assert body["email"] == "pat@x.com"


def test_optional_field_can_be_cleared(client, people):
    client.put("/api/users/me", headers=people["pat"]["h"], json={"phone": "555-0100"})
    r = client.put("/api/users/me", headers=people["pat"]["h"], json={"phone": ""})
    assert r.get_json()["patient"]["phone"] is None


def test_provider_updates_specialty(client, people):
    r = client.put(
        "/api/users/me", headers=people["doc"]["h"], json={"specialty": " Cardiology "}
    )
    assert r.status_code == 200
    assert r.get_json()["provider"]["specialty"] == "Cardiology"
    r = client.put(
        "/api/users/me", headers=people["nurse"]["h"], json={"specialty": None}
    )
    assert r.get_json()["provider"]["specialty"] is None


def test_email_change_is_lowercased_and_usable_for_login(client, people):
    r = client.put(
        "/api/users/me", headers=people["pat"]["h"], json={"email": " NEW@Example.COM "}
    )
    assert r.status_code == 200 and r.get_json()["email"] == "new@example.com"
    login = client.post(
        "/api/auth/login", json={"email": "new@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    old = client.post(
        "/api/auth/login", json={"email": "pat@x.com", "password": PASSWORD}
    )
    assert old.status_code == 401


def test_email_already_taken_is_a_conflict_and_changes_nothing(client, people):
    r = client.put(
        "/api/users/me",
        headers=people["pat"]["h"],
        json={"name": "Should Not Save", "phone": "555-0199", "email": "OTHER@x.com"},
    )
    assert r.status_code == 409
    after = client.get("/api/users/me", headers=people["pat"]["h"]).get_json()
    assert after["name"] == "Pat Patient" and after["email"] == "pat@x.com"
    # the patients table must be untouched too, not just the users table
    assert after["patient"]["phone"] is None


def test_keeping_your_own_email_is_not_a_conflict(client, people):
    r = client.put(
        "/api/users/me", headers=people["pat"]["h"], json={"email": "pat@x.com"}
    )
    assert r.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        "text",
        {"name": ""},
        {"name": "   "},
        {"name": None},
        {"name": 5},
        {"name": "x" * 101},
        {"email": ""},
        {"email": "not-an-email"},
        {"email": "a@b"},
        {"email": "a b@c.com"},
        {"email": 5},
        {"phone": "abc"},
        {"date_of_birth": "2999-01-01"},
    ],
)
def test_invalid_input_is_rejected(client, people, body):
    r = client.put("/api/users/me", headers=people["pat"]["h"], json=body)
    assert r.status_code == 400, r.get_json()


def test_atomic_when_one_field_is_invalid(client, people):
    r = client.put(
        "/api/users/me",
        headers=people["pat"]["h"],
        json={"name": "Changed", "phone": "abc"},
    )
    assert r.status_code == 400
    assert (
        client.get("/api/users/me", headers=people["pat"]["h"]).get_json()["name"]
        == "Pat Patient"
    )


def test_cannot_change_role_or_fields_of_another_role(client, people):
    for who, body in [
        ("pat", {"role": "doctor"}),
        ("pat", {"specialty": "Cardiology"}),
        ("pat", {"password_hash": "x"}),
        ("pat", {"id": 99}),
        ("doc", {"role": "patient"}),
        ("doc", {"phone": "555-0100"}),
        ("nurse", {"can_prescribe": 1}),
    ]:
        r = client.put("/api/users/me", headers=people[who]["h"], json=body)
        assert r.status_code == 400, (who, body, r.get_json())
    me = client.get("/api/users/me", headers=people["nurse"]["h"]).get_json()
    assert me["role"] == "nurse" and me["provider"]["can_prescribe"] == 0


def test_cannot_reach_another_users_profile_by_url(client, people):
    # There is no id in the route, so these must simply not exist.
    other = people["pat2"]["id"]
    assert (
        client.get(f"/api/users/{other}", headers=people["pat"]["h"]).status_code == 404
    )
    assert client.put(
        f"/api/users/{other}", headers=people["pat"]["h"], json={"name": "Hacked"}
    ).status_code in (404, 405)


def test_sql_in_a_field_is_stored_as_text(client, people):
    evil = "x'); DROP TABLE users; --"
    r = client.put("/api/users/me", headers=people["pat"]["h"], json={"name": evil})
    assert r.status_code == 200 and r.get_json()["name"] == evil
    assert client.get("/api/users/me", headers=people["pat"]["h"]).status_code == 200


# --- password --------------------------------------------------------------


def change(client, who, current=PASSWORD, new="brandnew99", **extra):
    return client.post(
        "/api/users/me/password",
        headers=who["h"],
        json={"current_password": current, "new_password": new, **extra},
    )


def test_password_change_works_and_old_password_stops_working(client, people):
    assert change(client, people["pat"]).status_code == 200
    ok = client.post(
        "/api/auth/login", json={"email": "pat@x.com", "password": "brandnew99"}
    )
    old = client.post(
        "/api/auth/login", json={"email": "pat@x.com", "password": PASSWORD}
    )
    assert ok.status_code == 200 and old.status_code == 401


def test_wrong_current_password_is_refused(client, people):
    r = change(client, people["pat"], current="wrong-password")
    assert r.status_code == 403
    assert (
        client.post(
            "/api/auth/login", json={"email": "pat@x.com", "password": PASSWORD}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("new", ["short", "", None, 12345678, "x" * 129, PASSWORD])
def test_bad_new_password_is_rejected(client, people, new):
    assert change(client, people["pat"], new=new).status_code == 400


def test_password_change_needs_both_fields_and_a_token(client, people):
    h = people["pat"]["h"]
    assert client.post("/api/users/me/password", headers=h, json={}).status_code == 400
    assert (
        client.post(
            "/api/users/me/password", headers=h, json={"new_password": "brandnew99"}
        ).status_code
        == 400
    )
    assert client.post("/api/users/me/password", headers=h).status_code == 400
    assert (
        client.post(
            "/api/users/me/password",
            json={"current_password": PASSWORD, "new_password": "brandnew99"},
        ).status_code
        == 401
    )


def test_password_change_only_affects_the_token_holder(client, people):
    change(client, people["doc"])
    other = client.post(
        "/api/auth/login", json={"email": "other@x.com", "password": PASSWORD}
    )
    assert other.status_code == 200
