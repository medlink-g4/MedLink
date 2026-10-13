"""Tests for medical records and medications (tasks 3.1 and 3.2).

Same shape as the task 1.4 and 2.4 suites: a real SQLite database built from
the project's own schema script, tokens minted exactly as login mints them,
and the real blueprint mounted on a Flask app.
"""

import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.medical_records import medical_records_bp  # noqa: E402
from routes.permissions import JWT_ALGORITHM, JWT_SECRET  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

PATIENT_A_USER, PATIENT_B_USER = 1, 2
DOCTOR_USER, NURSE_USER, OTHER_DOCTOR_USER = 3, 4, 5
PATIENT_A, PATIENT_B = 1, 2


@pytest.fixture()
def db(tmp_path):
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "database" / "init_db.py")],
        cwd=tmp_path, check=True, capture_output=True,
    )
    path = tmp_path / "medlink.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        INSERT INTO users (id, name, email, password_hash, role) VALUES
            (1, 'Patient A',  'a@x', 'h', 'patient'),
            (2, 'Patient B',  'b@x', 'h', 'patient'),
            (3, 'Dr. Who',    'd@x', 'h', 'doctor'),
            (4, 'Nurse Nina', 'n@x', 'h', 'nurse'),
            (5, 'Dr. Other',  'o@x', 'h', 'doctor');
        INSERT INTO patients (id, user_id) VALUES (1, 1), (2, 2);
        INSERT INTO providers (id, user_id, role_type) VALUES
            (1, 3, 'doctor'), (2, 4, 'nurse'), (3, 5, 'doctor');

        -- Assignment is derived from non-cancelled appointments, so doctor 1
        -- and nurse 2 are assigned to patient A. Nobody is assigned to B.
        INSERT INTO appointments
            (patient_id, provider_id, assisting_nurse_id,
             appointment_time, end_appointment_time, reason, status, created_by)
        VALUES (1, 1, 2, '2026-01-05T09:00', '2026-01-05T09:30',
                'Initial visit', 'completed', 1);

        INSERT INTO medical_records
            (patient_id, provider_id, diagnosis, prescription, record_date)
        VALUES
            (1, 1, 'Hypertension', 'Lisinopril 10mg', '2026-09-01'),
            (1, 1, 'Seasonal allergies', NULL,        '2026-09-20'),
            (2, 3, 'Migraine', 'Sumatriptan 50mg',    '2026-09-15');
        """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def client(db):
    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)
    app.register_blueprint(medical_records_bp, url_prefix="/api/medical-records")
    return app.test_client()


def token_for(user_id, role, expires_in=timedelta(hours=2)):
    return jwt.encode(
        {"userId": user_id, "role": role,
         "exp": datetime.now(timezone.utc) + expires_in},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )


def auth(user_id, role):
    return {"Authorization": f"Bearer {token_for(user_id, role)}"}


PATIENT_A_AUTH = lambda: auth(PATIENT_A_USER, "patient")        # noqa: E731
PATIENT_B_AUTH = lambda: auth(PATIENT_B_USER, "patient")        # noqa: E731
DOCTOR_AUTH = lambda: auth(DOCTOR_USER, "doctor")               # noqa: E731
OTHER_DOCTOR_AUTH = lambda: auth(OTHER_DOCTOR_USER, "doctor")   # noqa: E731
NURSE_AUTH = lambda: auth(NURSE_USER, "nurse")                  # noqa: E731

RECORDS = "/api/medical-records"


# --- viewing history ------------------------------------------------------
def test_patient_sees_own_history_newest_first(client):
    r = client.get(f"{RECORDS}/patient/{PATIENT_A}", headers=PATIENT_A_AUTH())
    assert r.status_code == 200
    body = r.get_json()
    assert len(body) == 2
    assert body[0]["record_date"] == "2026-09-20", "newest first"
    assert body[0]["provider_name"] == "Dr. Who", "provider resolved to a name"


def test_patient_cannot_see_another_patients_history(client):
    r = client.get(f"{RECORDS}/patient/{PATIENT_B}", headers=PATIENT_A_AUTH())
    assert r.status_code == 403


def test_assigned_doctor_sees_the_history(client):
    r = client.get(f"{RECORDS}/patient/{PATIENT_A}", headers=DOCTOR_AUTH())
    assert r.status_code == 200
    assert len(r.get_json()) == 2


def test_unassigned_doctor_is_refused(client):
    """Patient A is assigned, just not to this doctor."""
    r = client.get(f"{RECORDS}/patient/{PATIENT_A}", headers=OTHER_DOCTOR_AUTH())
    assert r.status_code == 403


def test_assigned_nurse_can_view_history(client):
    r = client.get(f"{RECORDS}/patient/{PATIENT_A}", headers=NURSE_AUTH())
    assert r.status_code == 200


# --- medications ----------------------------------------------------------
def test_medications_returns_only_records_with_a_prescription(client):
    r = client.get(f"{RECORDS}/patient/{PATIENT_A}/medications",
                   headers=PATIENT_A_AUTH())
    assert r.status_code == 200
    meds = r.get_json()
    assert len(meds) == 1, "the allergies record has no prescription"
    assert meds[0]["medication"] == "Lisinopril 10mg"
    assert meds[0]["prescribed_for"] == "Hypertension"
    assert meds[0]["prescribed_by"] == "Dr. Who"


def test_medications_respects_the_same_scope_as_records(client):
    r = client.get(f"{RECORDS}/patient/{PATIENT_B}/medications",
                   headers=PATIENT_A_AUTH())
    assert r.status_code == 403


# --- creating -------------------------------------------------------------
def test_doctor_creates_a_record_for_an_assigned_patient(client):
    r = client.post(RECORDS, json={
        "patient_id": PATIENT_A, "diagnosis": "Sprained ankle",
        "prescription": "Ibuprofen 400mg", "record_date": "2026-10-01",
    }, headers=DOCTOR_AUTH())
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["provider_id"] == 1

    listed = client.get(f"{RECORDS}/patient/{PATIENT_A}", headers=DOCTOR_AUTH())
    assert len(listed.get_json()) == 3


def test_record_is_attributed_to_the_caller_not_the_request_body(client):
    """A doctor cannot file a record under another provider's name."""
    r = client.post(RECORDS, json={
        "patient_id": PATIENT_A, "diagnosis": "Checkup",
        "provider_id": 3,  # Dr. Other, should be ignored
    }, headers=DOCTOR_AUTH())
    assert r.status_code == 201
    assert r.get_json()["provider_id"] == 1


def test_nurse_cannot_create_a_record(client):
    r = client.post(RECORDS, json={
        "patient_id": PATIENT_A, "diagnosis": "Checkup",
    }, headers=NURSE_AUTH())
    assert r.status_code == 403


def test_patient_cannot_create_a_record(client):
    r = client.post(RECORDS, json={
        "patient_id": PATIENT_A, "diagnosis": "I feel fine",
    }, headers=PATIENT_A_AUTH())
    assert r.status_code == 403


def test_doctor_cannot_create_for_an_unassigned_patient(client):
    r = client.post(RECORDS, json={
        "patient_id": PATIENT_A, "diagnosis": "Checkup",
    }, headers=OTHER_DOCTOR_AUTH())
    assert r.status_code == 403


def test_empty_record_is_rejected(client):
    r = client.post(RECORDS, json={"patient_id": PATIENT_A},
                    headers=DOCTOR_AUTH())
    assert r.status_code == 400
    assert "diagnosis or a prescription" in r.get_json()["error"]


def test_future_record_date_is_rejected(client):
    future = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
    r = client.post(RECORDS, json={
        "patient_id": PATIENT_A, "diagnosis": "Time travel",
        "record_date": future,
    }, headers=DOCTOR_AUTH())
    assert r.status_code == 400
    assert "future" in r.get_json()["error"]


def test_record_date_defaults_to_today(client):
    r = client.post(RECORDS, json={
        "patient_id": PATIENT_A, "diagnosis": "Flu",
    }, headers=DOCTOR_AUTH())
    assert r.status_code == 201
    assert r.get_json()["record_date"] == date.today().strftime("%Y-%m-%d")


# --- updating -------------------------------------------------------------
def test_doctor_updates_a_prescription(client):
    r = client.put(f"{RECORDS}/1", json={"prescription": "Lisinopril 20mg"},
                   headers=DOCTOR_AUTH())
    assert r.status_code == 200
    assert r.get_json()["prescription"] == "Lisinopril 20mg"
    assert r.get_json()["diagnosis"] == "Hypertension", "untouched field kept"


def test_nurse_cannot_update_a_record(client):
    r = client.put(f"{RECORDS}/1", json={"prescription": "Something else"},
                   headers=NURSE_AUTH())
    assert r.status_code == 403


def test_doctor_cannot_update_an_unassigned_patients_record(client):
    r = client.put(f"{RECORDS}/3", json={"prescription": "Changed"},
                   headers=DOCTOR_AUTH())
    assert r.status_code == 403, "record 3 belongs to patient B"


def test_updating_a_missing_record_is_404(client):
    r = client.put(f"{RECORDS}/999", json={"diagnosis": "Nothing"},
                   headers=DOCTOR_AUTH())
    assert r.status_code == 404


# --- auth, consistent with the other suites -------------------------------
def test_no_token_is_unauthorized(client):
    assert client.get(f"{RECORDS}/patient/{PATIENT_A}").status_code == 401


def test_expired_token_is_unauthorized(client):
    bad = {"Authorization":
           f"Bearer {token_for(PATIENT_A_USER, 'patient', timedelta(seconds=-60))}"}
    assert client.get(f"{RECORDS}/patient/{PATIENT_A}", headers=bad).status_code == 401
