"""Tests for appointment scheduling and cancellation (tasks 2.4 and 2.5).

Written the same way as the task 1.4 suite: a real SQLite database built from
the project's own schema script, real tokens minted exactly as login mints
them, and the real blueprint mounted on a Flask app. No mocking.

Unlike the 1.4 suite these are not harness routes. `appointments_bp` is the
shipped blueprint, so these tests exercise the real endpoints.
"""

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import jwt
import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.appointments import appointments_bp  # noqa: E402
from routes.permissions import JWT_ALGORITHM, JWT_SECRET  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

PATIENT_A_USER, PATIENT_B_USER, DOCTOR_USER, NURSE_USER = 1, 2, 3, 4
PATIENT_A, PATIENT_B = 1, 2
DOCTOR_PROVIDER, NURSE_PROVIDER = 1, 2


def a_future_date():
    """A date comfortably in the future, so 'past' tests stay meaningful."""
    return (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")


def slot(hhmm, date=None):
    return f"{date or a_future_date()}T{hhmm}"


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
            (1, 'Patient A', 'a@x', 'h', 'patient'),
            (2, 'Patient B', 'b@x', 'h', 'patient'),
            (3, 'Doctor',    'd@x', 'h', 'doctor'),
            (4, 'Nurse',     'n@x', 'h', 'nurse');
        INSERT INTO patients (id, user_id) VALUES (1, 1), (2, 2);
        INSERT INTO providers (id, user_id, role_type) VALUES
            (1, 3, 'doctor'), (2, 4, 'nurse');
        """
    )
    # The nurse must already be assigned to patient A to act for them. With
    # assignment derived from appointments, that means an existing booking.
    # A past appointment is used so it never collides with slots under test.
    conn.execute(
        """INSERT INTO appointments
           (patient_id, provider_id, assisting_nurse_id,
            start_time, end_time, reason, status, created_by)
           VALUES (1, 1, 2, '2026-01-05T09:00', '2026-01-05T09:30',
                   'Initial visit', 'completed', 1)"""
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def client(db):
    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)
    app.register_blueprint(appointments_bp, url_prefix="/api/appointments")
    return app.test_client()


def token_for(user_id, role, expires_in=timedelta(hours=2)):
    return jwt.encode(
        {"userId": user_id, "role": role,
         "exp": datetime.now(tz=None).astimezone() + expires_in},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )


def auth(token):
    return {"Authorization": f"Bearer {token}"}


PATIENT_A_TOKEN = lambda: token_for(PATIENT_A_USER, "patient")   # noqa: E731
PATIENT_B_TOKEN = lambda: token_for(PATIENT_B_USER, "patient")   # noqa: E731
DOCTOR_TOKEN = lambda: token_for(DOCTOR_USER, "doctor")          # noqa: E731
NURSE_TOKEN = lambda: token_for(NURSE_USER, "nurse")             # noqa: E731


def book(client, token, patient_id=PATIENT_A, provider_id=DOCTOR_PROVIDER,
         start_time=None, **extra):
    body = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "start_time": start_time or slot("09:00"),
    }
    body.update(extra)
    return client.post("/api/appointments", json=body, headers=auth(token))


# --- 1. booking -----------------------------------------------------------
def test_patient_books_their_own_appointment(client):
    r = book(client, PATIENT_A_TOKEN(), reason="Annual checkup")
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["status"] == "scheduled"
    assert body["start_time"].endswith("T09:00")
    assert body["end_time"].endswith("T09:30"), "a slot is 30 minutes"


# --- 2. double booking ----------------------------------------------------
def test_double_booking_the_same_provider_slot_is_rejected(client):
    assert book(client, PATIENT_A_TOKEN(), start_time=slot("10:00")).status_code == 201
    second = book(client, PATIENT_B_TOKEN(), patient_id=PATIENT_B,
                  start_time=slot("10:00"))
    assert second.status_code == 409
    assert "already booked" in second.get_json()["error"]


# --- 3. past time ---------------------------------------------------------
def test_booking_in_the_past_is_rejected(client):
    r = book(client, PATIENT_A_TOKEN(), start_time="2020-01-06T09:00")
    assert r.status_code == 400
    assert "past" in r.get_json()["error"].lower()


# --- 4. off slot ----------------------------------------------------------
def test_time_not_on_a_half_hour_boundary_is_rejected(client):
    r = book(client, PATIENT_A_TOKEN(), start_time=slot("10:15"))
    assert r.status_code == 400
    assert "half hour" in r.get_json()["error"]


# --- 5. after hours -------------------------------------------------------
@pytest.mark.parametrize("hhmm", ["07:30", "17:00", "18:30"])
def test_outside_clinic_hours_is_rejected(client, hhmm):
    r = book(client, PATIENT_A_TOKEN(), start_time=slot(hhmm))
    assert r.status_code == 400
    assert "clinic hours" in r.get_json()["error"]


def test_last_slot_of_the_day_is_bookable(client):
    """16:30 to 17:00 is the final slot and must still be allowed."""
    assert book(client, PATIENT_A_TOKEN(), start_time=slot("16:30")).status_code == 201


# --- 6. doctor cannot book ------------------------------------------------
def test_doctor_cannot_book(client):
    r = book(client, DOCTOR_TOKEN())
    assert r.status_code == 403
    assert "may not create appointments" in r.get_json()["error"]


# --- 7. patient cannot book for someone else ------------------------------
def test_patient_cannot_book_for_another_patient(client):
    r = book(client, PATIENT_A_TOKEN(), patient_id=PATIENT_B)
    assert r.status_code == 403


# --- 8. nurse can book for a patient --------------------------------------
def test_nurse_can_book_for_an_assigned_patient(client):
    r = book(client, NURSE_TOKEN(), patient_id=PATIENT_A, start_time=slot("11:00"))
    assert r.status_code == 201, r.get_json()


def test_nurse_cannot_book_for_an_unassigned_patient(client):
    r = book(client, NURSE_TOKEN(), patient_id=PATIENT_B, start_time=slot("11:30"))
    assert r.status_code == 403


# --- 9. availability ------------------------------------------------------
def test_availability_lists_free_slots_and_excludes_booked_ones(client):
    date = a_future_date()
    assert book(client, PATIENT_A_TOKEN(), start_time=f"{date}T13:00").status_code == 201

    r = client.get(
        f"/api/appointments/availability?provider_id={DOCTOR_PROVIDER}&date={date}",
        headers=auth(PATIENT_A_TOKEN()),
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["slot_minutes"] == 30
    assert f"{date}T13:00" in body["booked"]
    assert f"{date}T13:00" not in body["available"]
    assert f"{date}T13:30" in body["available"]
    # 08:00 through 16:30 inclusive is 18 half-hour slots; one is now taken.
    assert len(body["available"]) == 17


def test_cancelling_frees_the_slot_again(client):
    date = a_future_date()
    created = book(client, PATIENT_A_TOKEN(), start_time=f"{date}T14:00")
    appointment_id = created.get_json()["id"]
    client.post(f"/api/appointments/{appointment_id}/cancel",
                headers=auth(PATIENT_A_TOKEN()))
    r = client.get(
        f"/api/appointments/availability?provider_id={DOCTOR_PROVIDER}&date={date}",
        headers=auth(PATIENT_A_TOKEN()),
    )
    assert f"{date}T14:00" in r.get_json()["available"]


# --- 10. cancel your own --------------------------------------------------
def test_patient_cancels_their_own_appointment(client):
    appointment_id = book(client, PATIENT_A_TOKEN()).get_json()["id"]
    r = client.post(f"/api/appointments/{appointment_id}/cancel",
                    headers=auth(PATIENT_A_TOKEN()))
    assert r.status_code == 200
    assert r.get_json()["status"] == "cancelled"


# --- 11. cannot cancel someone else's -------------------------------------
def test_patient_cannot_cancel_another_patients_appointment(client):
    appointment_id = book(client, PATIENT_A_TOKEN()).get_json()["id"]
    r = client.post(f"/api/appointments/{appointment_id}/cancel",
                    headers=auth(PATIENT_B_TOKEN()))
    assert r.status_code == 403


# --- 12. cannot cancel twice ----------------------------------------------
def test_cancelling_twice_is_rejected(client):
    appointment_id = book(client, PATIENT_A_TOKEN()).get_json()["id"]
    assert client.post(f"/api/appointments/{appointment_id}/cancel",
                       headers=auth(PATIENT_A_TOKEN())).status_code == 200
    second = client.post(f"/api/appointments/{appointment_id}/cancel",
                         headers=auth(PATIENT_A_TOKEN()))
    assert second.status_code == 409
    assert "already cancelled" in second.get_json()["error"]


# --- auth, consistent with task 1.4 ---------------------------------------
def test_booking_without_a_token_is_unauthorized(client):
    r = client.post("/api/appointments", json={
        "patient_id": PATIENT_A, "provider_id": DOCTOR_PROVIDER,
        "start_time": slot("09:00"),
    })
    assert r.status_code == 401


def test_doctor_can_still_view_appointments(client):
    """Doctors lost create and cancel, but keep view."""
    book(client, PATIENT_A_TOKEN())
    r = client.get("/api/appointments", headers=auth(DOCTOR_TOKEN()))
    assert r.status_code == 200
    assert len(r.get_json()) >= 1
