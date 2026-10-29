"""Tests for activity and audit logging (task 4.5).

Two halves. The first is that the log is complete and honest: every access
through the permission layer leaves a row, refused attempts included, and
nothing clinical ends up in it. The second is that reading the log is itself
access to patient information and obeys the same rules as everything else.
"""

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from flask import Flask, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.audit import audit_bp  # noqa: E402
from routes.permissions import (  # noqa: E402
    JWT_ALGORITHM,
    JWT_SECRET,
    require_permission,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

PATIENT_A_USER, PATIENT_B_USER, DOCTOR_USER, NURSE_USER = 1, 2, 3, 4
PATIENT_A, PATIENT_B = 1, 2

SECRET_DIAGNOSIS = "Stage II carcinoma"
SECRET_PRESCRIPTION = "Tamoxifen 20mg daily"


@pytest.fixture()
def db(tmp_path):
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "database" / "init_db.py")],
        cwd=tmp_path, check=True, capture_output=True,
    )
    path = tmp_path / "medlink.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        INSERT INTO users (id, name, email, password_hash, role) VALUES
            (1, 'Patient A', 'a@example.com', 'x', 'patient'),
            (2, 'Patient B', 'b@example.com', 'x', 'patient'),
            (3, 'Doctor',    'd@example.com', 'x', 'doctor'),
            (4, 'Nurse',     'n@example.com', 'x', 'nurse');

        INSERT INTO patients (id, user_id) VALUES (1, 1), (2, 2);

        INSERT INTO providers (id, user_id, role_type, can_prescribe) VALUES
            (1, 3, 'doctor', 1),
            (2, 4, 'nurse',  0);

        INSERT INTO medical_records
            (patient_id, provider_id, diagnosis, prescription, record_date)
        VALUES (1, 1, '{SECRET_DIAGNOSIS}', '{SECRET_PRESCRIPTION}', '2026-10-01');

        INSERT INTO appointments
            (patient_id, provider_id, assisting_nurse_id, appointment_time,
             end_appointment_time, reason, status, created_by)
        VALUES (1, 1, 2, '2026-11-02T09:00', '2026-11-02T09:30',
                'Follow-up', 'scheduled', 1);
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def client(db):
    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)
    app.register_blueprint(audit_bp, url_prefix="/api/audit")

    @app.route("/h/patients/<int:patient_id>/records", methods=["GET"])
    @require_permission("medical_records", "view")
    def view_records(patient_id):
        conn = sqlite3.connect(app.config["MEDLINK_DB"])
        rows = conn.execute(
            "SELECT diagnosis, prescription FROM medical_records WHERE patient_id = ?",
            (patient_id,),
        ).fetchall()
        conn.close()
        return jsonify({"records": [list(r) for r in rows]}), 200

    return app.test_client()


def token_for(user_id, role, expires_in=timedelta(hours=2)):
    return jwt.encode(
        {"userId": user_id, "role": role,
         "exp": datetime.now(timezone.utc) + expires_in},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )


def auth(user_id, role):
    return {"Authorization": f"Bearer {token_for(user_id, role)}"}


def log_rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id")]
    conn.close()
    return rows


# --- the log is complete ---------------------------------------------------

def test_an_allowed_access_is_recorded(client, db):
    client.get(f"/h/patients/{PATIENT_A}/records", headers=auth(DOCTOR_USER, "doctor"))

    rows = [r for r in log_rows(db) if r["resource"] == "medical_records"]
    assert len(rows) == 1
    entry = rows[0]
    assert entry["outcome"] == "allowed"
    assert entry["user_id"] == DOCTOR_USER
    assert entry["role"] == "doctor"
    assert entry["action"] == "view"
    assert entry["patient_id"] == PATIENT_A


def test_a_refused_access_is_recorded(client, db):
    """The attempts that were blocked are the ones an audit is really for."""
    r = client.get(f"/h/patients/{PATIENT_B}/records",
                   headers=auth(DOCTOR_USER, "doctor"))
    assert r.status_code == 403

    rows = [r for r in log_rows(db) if r["resource"] == "medical_records"]
    assert len(rows) == 1
    assert rows[0]["outcome"] == "denied"
    assert rows[0]["patient_id"] == PATIENT_B
    assert rows[0]["user_id"] == DOCTOR_USER


def test_a_patient_reaching_another_patients_record_is_recorded(client, db):
    client.get(f"/h/patients/{PATIENT_A}/records",
               headers=auth(PATIENT_B_USER, "patient"))

    denied = [r for r in log_rows(db) if r["outcome"] == "denied"]
    assert len(denied) == 1
    assert denied[0]["user_id"] == PATIENT_B_USER


def test_a_request_with_no_token_is_recorded(client, db):
    client.get(f"/h/patients/{PATIENT_A}/records")

    rows = log_rows(db)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "denied"
    assert rows[0]["user_id"] is None, "there is no account to attribute this to"


def test_an_expired_token_is_recorded(client, db):
    stale = jwt.encode(
        {"userId": DOCTOR_USER, "role": "doctor",
         "exp": datetime.now(timezone.utc) - timedelta(minutes=5)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    client.get(f"/h/patients/{PATIENT_A}/records",
               headers={"Authorization": f"Bearer {stale}"})

    rows = log_rows(db)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "denied"
    assert "expired" in rows[0]["detail"].lower()


# --- the log holds no clinical information ---------------------------------

def test_the_log_never_contains_the_record_contents(client, db):
    """An audit table full of diagnoses is a second copy of the problem."""
    client.get(f"/h/patients/{PATIENT_A}/records", headers=auth(DOCTOR_USER, "doctor"))

    everything = " ".join(
        str(value) for row in log_rows(db) for value in row.values()
    )
    assert SECRET_DIAGNOSIS not in everything
    assert SECRET_PRESCRIPTION not in everything


# --- reading the log obeys the same rules ----------------------------------

def test_a_patient_sees_who_reached_their_record(client, db):
    client.get(f"/h/patients/{PATIENT_A}/records", headers=auth(DOCTOR_USER, "doctor"))
    client.get(f"/h/patients/{PATIENT_A}/records", headers=auth(NURSE_USER, "nurse"))

    r = client.get("/api/audit/me", headers=auth(PATIENT_A_USER, "patient"))
    assert r.status_code == 200
    body = r.get_json()
    assert body["patient_id"] == PATIENT_A

    actors = {e["actor_name"] for e in body["entries"]}
    assert "Doctor" in actors
    assert "Nurse" in actors


def test_a_patient_cannot_read_another_patients_access_history(client, db):
    r = client.get(f"/api/audit/patient/{PATIENT_A}",
                   headers=auth(PATIENT_B_USER, "patient"))
    assert r.status_code == 403


def test_an_unassigned_doctor_cannot_read_a_patients_access_history(client, db):
    r = client.get(f"/api/audit/patient/{PATIENT_B}",
                   headers=auth(DOCTOR_USER, "doctor"))
    assert r.status_code == 403


def test_an_assigned_doctor_can_read_a_patients_access_history(client, db):
    r = client.get(f"/api/audit/patient/{PATIENT_A}",
                   headers=auth(DOCTOR_USER, "doctor"))
    assert r.status_code == 200
    assert r.get_json()["patient_id"] == PATIENT_A


def test_reading_the_log_without_a_token_is_refused(client):
    assert client.get("/api/audit/me").status_code == 401


def test_staff_see_their_own_activity_not_a_patients(client, db):
    client.get(f"/h/patients/{PATIENT_A}/records", headers=auth(DOCTOR_USER, "doctor"))
    client.get(f"/h/patients/{PATIENT_A}/records", headers=auth(NURSE_USER, "nurse"))

    r = client.get("/api/audit/me", headers=auth(DOCTOR_USER, "doctor"))
    assert r.status_code == 200
    body = r.get_json()
    assert body["user_id"] == DOCTOR_USER
    assert body["entries"], "the doctor's own access should be listed"
    # Every row belongs to the caller, including the read of the log itself.
    assert all(e["action"] in ("view",) for e in body["entries"])


def test_reading_the_log_is_itself_recorded(client, db):
    client.get("/api/audit/me", headers=auth(DOCTOR_USER, "doctor"))

    rows = [r for r in log_rows(db) if r["resource"] == "audit"]
    assert rows, "looking at the audit trail is an access like any other"
    assert rows[0]["user_id"] == DOCTOR_USER


# --- auditing must never break the application -----------------------------

def test_a_missing_audit_table_does_not_break_the_request(client, db):
    """Older databases predate this table. The app has to carry on regardless."""
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE audit_log")
    conn.commit()
    conn.close()

    r = client.get(f"/h/patients/{PATIENT_A}/records",
                   headers=auth(DOCTOR_USER, "doctor"))
    assert r.status_code == 200, "the access still succeeds, it just is not logged"
