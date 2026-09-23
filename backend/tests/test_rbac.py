"""Tests for the task 1.4 role-based access control layer.

The protected routes below are a TEST HARNESS, not application code. The
patient, medical record and appointment endpoints belong to Sprint 2 and 3 and
are owned by other people, so this suite defines the minimum routes needed to
exercise the real decorators against a real database without claiming that
work. When those endpoints land, the same decorators apply to them unchanged.

No test here knows how assignment is derived. Assignment is set up purely by
inserting appointment rows, and if Sprint 3 swaps the derivation inside
is_assigned() these tests still describe the same behaviour.
"""

import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from flask import Flask, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.permissions import (  # noqa: E402
    JWT_ALGORITHM,
    JWT_SECRET,
    require_permission,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Seeded identities.
PATIENT_A_USER, PATIENT_B_USER = 1, 2
DOCTOR_USER, NURSE_USER, OTHER_DOCTOR_USER = 3, 4, 5
PATIENT_A, PATIENT_B = 1, 2


def make_assigned(conn, doctor_provider_id, nurse_provider_id, patient_id):
    """Put the database into a state where these providers reach this patient.

    Test setup has to create assignment state somehow, so this helper is the
    single place in the suite that knows how. Sprint 3's assignment table
    therefore needs exactly two edits: the body of is_assigned() and the body
    of this helper. No individual test touches the derivation.
    """
    conn.execute(
        """
        INSERT INTO appointments
            (patient_id, provider_id, assisting_nurse_id, appointment_time, status)
        VALUES (?, ?, ?, '2026-09-21T10:00', 'scheduled')
        """,
        (patient_id, doctor_provider_id, nurse_provider_id),
    )


def unassign_nurse_everywhere(conn):
    """Remove every nurse assignment, leaving doctor assignments intact."""
    conn.execute("UPDATE appointments SET assisting_nurse_id = NULL")


@pytest.fixture()
def db(tmp_path):
    """A real SQLite database built from the project's own schema script."""
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "database" / "init_db.py")],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    path = tmp_path / "medlink.db"

    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript(
        """
        INSERT INTO users (id, name, email, password_hash, role) VALUES
            (1, 'Patient A', 'a@example.com', 'x', 'patient'),
            (2, 'Patient B', 'b@example.com', 'x', 'patient'),
            (3, 'Doctor',    'd@example.com', 'x', 'doctor'),
            (4, 'Nurse',     'n@example.com', 'x', 'nurse'),
            (5, 'Other Doc', 'o@example.com', 'x', 'doctor');

        INSERT INTO patients (id, user_id) VALUES (1, 1), (2, 2);

        INSERT INTO providers (id, user_id, role_type, can_prescribe) VALUES
            (1, 3, 'doctor', 1),
            (2, 4, 'nurse',  0),
            (3, 5, 'doctor', 1);

        INSERT INTO medical_records
            (patient_id, provider_id, diagnosis, prescription, record_date)
        VALUES (1, 1, 'Stable', 'None', '2026-09-21');
        """
    )
    # Doctor provider 1 and nurse provider 2 both reach patient 1.
    # Nobody reaches patient 2.
    make_assigned(conn, doctor_provider_id=1, nurse_provider_id=2, patient_id=1)
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def client(db):
    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)

    @app.route("/h/patients/<int:patient_id>/records", methods=["GET"])
    @require_permission("medical_records", "view")
    def view_records(patient_id):
        return jsonify({"patient_id": patient_id, "records": []}), 200

    @app.route("/h/patients/<int:patient_id>/records/diagnosis", methods=["PUT"])
    @require_permission("medical_records", "update")
    def update_diagnosis(patient_id):
        return jsonify({"patient_id": patient_id, "updated": "diagnosis"}), 200

    @app.route("/h/patients/<int:patient_id>/records/medications", methods=["PUT"])
    @require_permission("medical_records", "update")
    def update_medications(patient_id):
        return jsonify({"patient_id": patient_id, "updated": "medications"}), 200

    @app.route("/h/patients/<int:patient_id>/records/vitals", methods=["PUT"])
    @require_permission("medical_records", "update_vitals")
    def update_vitals(patient_id):
        return jsonify({"patient_id": patient_id, "updated": "vitals"}), 200

    return app.test_client()


def token_for(user_id, role, expires_in=timedelta(hours=2)):
    """Mint a token exactly as task 1.3 does at login."""
    return jwt.encode(
        {
            "userId": user_id,
            "role": role,
            "exp": datetime.now(timezone.utc) + expires_in,
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# --- 1. Patient requests another patient's record -> 403 -------------------
def test_patient_cannot_read_another_patients_record(client):
    r = client.get(
        f"/h/patients/{PATIENT_B}/records",
        headers=auth(token_for(PATIENT_A_USER, "patient")),
    )
    assert r.status_code == 403


# --- 2. Patient requests own record -> 200 ---------------------------------
def test_patient_can_read_own_record(client):
    r = client.get(
        f"/h/patients/{PATIENT_A}/records",
        headers=auth(token_for(PATIENT_A_USER, "patient")),
    )
    assert r.status_code == 200


# --- 3. Nurse attempts to update a diagnosis -> 403 ------------------------
def test_nurse_cannot_update_diagnosis(client):
    r = client.put(
        f"/h/patients/{PATIENT_A}/records/diagnosis",
        headers=auth(token_for(NURSE_USER, "nurse")),
    )
    assert r.status_code == 403


# --- 4. Nurse updates vitals on an assigned patient -> 200 -----------------
def test_nurse_can_update_vitals_for_assigned_patient(client):
    r = client.put(
        f"/h/patients/{PATIENT_A}/records/vitals",
        headers=auth(token_for(NURSE_USER, "nurse")),
    )
    assert r.status_code == 200


# --- 5. Doctor requests an unassigned patient's record -> 403 --------------
def test_doctor_cannot_read_unassigned_patients_record(client):
    """Patient A has an appointment, but with a different doctor.

    Asking about a patient who has no appointments at all would pass even if
    assignment were ignored entirely, so this deliberately targets a patient
    who IS assigned, just not to this caller.
    """
    r = client.get(
        f"/h/patients/{PATIENT_A}/records",
        headers=auth(token_for(OTHER_DOCTOR_USER, "doctor")),
    )
    assert r.status_code == 403

    # And the doctor who is assigned reaches the same patient, proving the
    # denial above is about assignment rather than the route being broken.
    ok = client.get(
        f"/h/patients/{PATIENT_A}/records",
        headers=auth(token_for(DOCTOR_USER, "doctor")),
    )
    assert ok.status_code == 200


# --- 6. Doctor updates an assigned patient's medications -> 200 ------------
def test_doctor_can_update_medications_for_assigned_patient(client):
    r = client.put(
        f"/h/patients/{PATIENT_A}/records/medications",
        headers=auth(token_for(DOCTOR_USER, "doctor")),
    )
    assert r.status_code == 200


# --- 7. Request with no token -> 401 ---------------------------------------
def test_missing_token_is_unauthorized(client):
    r = client.get(f"/h/patients/{PATIENT_A}/records")
    assert r.status_code == 401


# --- 8. Request with an expired token -> 401 -------------------------------
def test_expired_token_is_unauthorized(client):
    expired = token_for(
        PATIENT_A_USER, "patient", expires_in=timedelta(seconds=-60)
    )
    r = client.get(f"/h/patients/{PATIENT_A}/records", headers=auth(expired))
    assert r.status_code == 401


# --- 9. Request with a tampered role claim -> 401 --------------------------
def test_tampered_role_claim_is_unauthorized(client):
    """Rewrite the role to doctor in place, keeping the original signature."""
    original = token_for(PATIENT_A_USER, "patient")
    header_b64, payload_b64, signature_b64 = original.split(".")

    def pad(segment):
        return segment + "=" * (-len(segment) % 4)

    payload = json.loads(base64.urlsafe_b64decode(pad(payload_b64)))
    payload["role"] = "doctor"
    forged_payload = (
        base64.urlsafe_b64encode(json.dumps(payload).encode())
        .decode()
        .rstrip("=")
    )
    tampered = f"{header_b64}.{forged_payload}.{signature_b64}"

    assert tampered != original
    r = client.get(
        f"/h/patients/{PATIENT_B}/records", headers=auth(tampered)
    )
    assert r.status_code == 401


# --- Extra: a nurse with no assisting rows is reported, not silently denied -
def test_nurse_with_no_assisting_rows_is_reported(client, db, caplog):
    import sqlite3

    conn = sqlite3.connect(db)
    unassign_nurse_everywhere(conn)
    conn.commit()
    conn.close()

    with caplog.at_level("WARNING"):
        r = client.put(
            f"/h/patients/{PATIENT_A}/records/vitals",
            headers=auth(token_for(NURSE_USER, "nurse")),
        )

    assert r.status_code == 403
    assert "no assisting_nurse_id rows" in caplog.text
