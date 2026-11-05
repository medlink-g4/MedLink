"""Tests for the provider directory used by the booking form.

Real SQLite database from the project's init_db.py, real tokens, real
blueprints. Doctors and nurses cannot self-register, so they are created
directly in the test database with the rows the register route would create.
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
from routes.permissions import JWT_ALGORITHM, JWT_SECRET
from routes.providers import providers_bp

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    app.register_blueprint(providers_bp, url_prefix="/api/providers")
    c = app.test_client()
    c.db_file = tmp_path / "medlink.db"
    return c


def make_user(client, name, email, role, specialty=None):
    conn = sqlite3.connect(client.db_file)
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, generate_password_hash("password123"), role),
        )
        uid = cur.lastrowid
        if role == "patient":
            conn.execute("INSERT INTO patients (user_id) VALUES (?)", (uid,))
        else:
            conn.execute(
                "INSERT INTO providers (user_id, role_type, specialty, can_prescribe) "
                "VALUES (?, ?, ?, ?)",
                (uid, role, specialty, 1 if role == "doctor" else 0),
            )
        conn.commit()
        return uid
    finally:
        conn.close()


def headers(uid, role):
    token = jwt.encode(
        {
            "userId": uid,
            "role": role,
            "exp": datetime.now().astimezone() + timedelta(hours=2),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def people(client):
    ids = {
        "pat": make_user(client, "Pat Patient", "pat@x.com", "patient"),
        "zed": make_user(client, "Dr Zed", "zed@x.com", "doctor", "Neurology"),
        "amy": make_user(client, "dr amy", "amy@x.com", "doctor", "Cardiology"),
        "nurse": make_user(client, "Nancy Nurse", "nancy@x.com", "nurse"),
    }
    roles = {"pat": "patient", "zed": "doctor", "amy": "doctor", "nurse": "nurse"}
    return {k: headers(v, roles[k]) for k, v in ids.items()}


def test_patient_sees_doctors_sorted_by_name_ignoring_case(client, people):
    r = client.get("/api/providers", headers=people["pat"])
    assert r.status_code == 200
    body = r.get_json()
    assert [d["name"] for d in body] == ["dr amy", "Dr Zed"]
    assert [d["specialty"] for d in body] == ["Cardiology", "Neurology"]
    assert all(d["role_type"] == "doctor" for d in body)


def test_nurses_are_not_listed_unless_asked_for(client, people):
    names = [
        d["name"]
        for d in client.get("/api/providers", headers=people["pat"]).get_json()
    ]
    assert "Nancy Nurse" not in names
    r = client.get("/api/providers?role_type=nurse", headers=people["pat"])
    assert [d["name"] for d in r.get_json()] == ["Nancy Nurse"]


def test_every_role_may_read_the_directory(client, people):
    for who in ("pat", "zed", "nurse"):
        assert client.get("/api/providers", headers=people[who]).status_code == 200


def test_only_id_name_specialty_and_role_type_are_exposed(client, people):
    body = client.get("/api/providers", headers=people["pat"]).get_json()
    assert all(set(d) == {"id", "name", "specialty", "role_type"} for d in body)
    text = str(body)
    assert "@x.com" not in text and "password" not in text and "pbkdf2" not in text


def test_returned_id_is_the_providers_table_id_the_booking_route_expects(
    client, people
):
    conn = sqlite3.connect(client.db_file)
    expected = conn.execute(
        "SELECT p.id FROM providers p JOIN users u ON u.id = p.user_id WHERE u.email = 'amy@x.com'"
    ).fetchone()[0]
    conn.close()
    body = client.get("/api/providers", headers=people["pat"]).get_json()
    assert body[0]["id"] == expected


@pytest.mark.parametrize("value", ["admin", "", "DOCTOR", "doctor' OR 1=1 --"])
def test_unknown_role_type_is_400(client, people, value):
    assert (
        client.get(
            "/api/providers", query_string={"role_type": value}, headers=people["pat"]
        ).status_code
        == 400
    )


def test_a_missing_or_bad_token_is_unauthorized(client, people):
    assert client.get("/api/providers").status_code == 401
    assert (
        client.get(
            "/api/providers", headers={"Authorization": "Bearer x.y.z"}
        ).status_code
        == 401
    )


def test_empty_directory_is_an_empty_list(client):
    uid = make_user(client, "Pat", "p@x.com", "patient")
    r = client.get("/api/providers", headers=headers(uid, "patient"))
    assert r.status_code == 200 and r.get_json() == []
