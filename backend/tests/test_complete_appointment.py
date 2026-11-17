"""Marking an appointment completed (Sprint 5, task 5.2)."""

import sqlite3

import pytest
from test_appointments import (  # noqa: F401
    DOCTOR_PROVIDER,
    DOCTOR_TOKEN,
    NURSE_TOKEN,
    PATIENT_A,
    PATIENT_A_TOKEN,
    PATIENT_B_TOKEN,
    auth,
    client,
    db,
    token_for,
)


def add(db, time, status="scheduled", doctor=DOCTOR_PROVIDER):
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "INSERT INTO appointments (patient_id, provider_id, assisting_nurse_id, "
        "appointment_time, end_appointment_time, status, created_by) "
        "VALUES (?, ?, 2, ?, ?, ?, 1)",
        (PATIENT_A, doctor, time, time[:-2] + "30", status),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def status_of(db, appointment_id):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT status FROM appointments WHERE id = ?", (appointment_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def complete(client, token, appointment_id):
    return client.post(
        f"/api/appointments/{appointment_id}/complete", headers=auth(token)
    )


def test_doctor_completes_a_visit_that_has_started(client, db):
    appt = add(db, "2026-01-10T09:00")
    r = complete(client, DOCTOR_TOKEN(), appt)
    assert r.status_code == 200 and r.get_json()["status"] == "completed"
    assert status_of(db, appt) == "completed"


def test_cannot_complete_a_future_visit(client, db):
    appt = add(db, "2999-01-01T09:00")
    r = complete(client, DOCTOR_TOKEN(), appt)
    assert r.status_code == 409 and "not started" in r.get_json()["error"]
    assert status_of(db, appt) == "scheduled"


@pytest.mark.parametrize("status", ["cancelled", "completed"])
def test_cannot_complete_a_cancelled_or_completed_visit(client, db, status):
    appt = add(db, "2026-01-10T09:00", status=status)
    assert complete(client, DOCTOR_TOKEN(), appt).status_code == 409
    assert status_of(db, appt) == status


def test_unknown_appointment_is_404(client):
    assert complete(client, DOCTOR_TOKEN(), 9999).status_code == 404


@pytest.mark.parametrize("token", [PATIENT_A_TOKEN, PATIENT_B_TOKEN, NURSE_TOKEN])
def test_patients_and_nurses_cannot_complete(client, db, token):
    appt = add(db, "2026-01-10T09:00")
    assert complete(client, token(), appt).status_code == 403
    assert status_of(db, appt) == "scheduled"


def test_no_token_is_401(client, db):
    appt = add(db, "2026-01-10T09:00")
    assert client.post(f"/api/appointments/{appt}/complete").status_code == 401


def test_another_doctor_cannot_complete_it_even_when_assigned_to_the_patient(
    client, db
):
    # Doctor 2 also treats patient A (a separate appointment), so is_assigned
    # is true for them. The visit still belongs to doctor 1.
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO users (id,name,email,password_hash,role) "
        "VALUES (9,'Doc2','d2@x','h','doctor')"
    )
    conn.execute("INSERT INTO providers (id,user_id,role_type) VALUES (3,9,'doctor')")
    conn.commit()
    conn.close()
    add(db, "2026-01-11T09:00", doctor=3)
    appt = add(db, "2026-01-10T09:00", doctor=DOCTOR_PROVIDER)
    r = complete(client, token_for(9, "doctor"), appt)
    assert r.status_code == 403
    assert status_of(db, appt) == "scheduled"


def test_a_completed_visit_cannot_then_be_cancelled(client, db):
    appt = add(db, "2026-01-10T09:00")
    complete(client, DOCTOR_TOKEN(), appt)
    r = client.post(f"/api/appointments/{appt}/cancel", headers=auth(PATIENT_A_TOKEN()))
    assert r.status_code == 409
