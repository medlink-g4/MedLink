"""Nurse assignment when booking (Sprint 5, task 5.2).

Before this, a booking made from the website never had a nurse, so nurses saw
an empty dashboard. assisting_nurse_id is now validated, and "any" picks a free
nurse. Reuses the fixtures and helpers from test_appointments.
"""

import sqlite3

import pytest
from test_appointments import (  # noqa: F401
    DOCTOR_PROVIDER,
    NURSE_PROVIDER,
    NURSE_TOKEN,
    PATIENT_A_TOKEN,
    PATIENT_B,
    PATIENT_B_TOKEN,
    auth,
    book,
    client,
    db,
    slot,
)


def nurse_of(db, appointment_id):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT assisting_nurse_id FROM appointments WHERE id = ?",
            (appointment_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def add_second_doctor(db):
    """So two appointments can share a time with only the nurse in common."""
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO users (id,name,email,password_hash,role) "
        "VALUES (9,'Doc2','d2@x','h','doctor')"
    )
    conn.execute("INSERT INTO providers (id,user_id,role_type) VALUES (3,9,'doctor')")
    conn.commit()
    conn.close()
    return 3


def test_no_nurse_requested_means_no_nurse(client, db):
    r = book(client, PATIENT_A_TOKEN())
    assert r.status_code == 201
    assert r.get_json()["assisting_nurse_id"] is None
    assert nurse_of(db, r.get_json()["id"]) is None


def test_specific_nurse_is_attached(client, db):
    r = book(client, PATIENT_A_TOKEN(), assisting_nurse_id=NURSE_PROVIDER)
    assert r.status_code == 201, r.get_json()
    assert nurse_of(db, r.get_json()["id"]) == NURSE_PROVIDER


def test_any_picks_a_free_nurse(client, db):
    r = book(client, PATIENT_A_TOKEN(), assisting_nurse_id="any")
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["assisting_nurse_id"] == NURSE_PROVIDER


def test_any_with_every_nurse_busy_still_books_without_one(client, db):
    first = book(client, PATIENT_A_TOKEN(), assisting_nurse_id=NURSE_PROVIDER)
    assert first.status_code == 201
    doctor2 = add_second_doctor(db)
    r = book(
        client,
        PATIENT_B_TOKEN(),
        patient_id=PATIENT_B,
        provider_id=doctor2,
        assisting_nurse_id="any",
    )
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["assisting_nurse_id"] is None


def test_busy_nurse_requested_by_id_is_409(client, db):
    doctor2 = add_second_doctor(db)
    assert (
        book(client, PATIENT_A_TOKEN(), assisting_nurse_id=NURSE_PROVIDER).status_code
        == 201
    )
    # Different doctor and patient, same time: only the nurse clashes.
    r = book(
        client,
        PATIENT_B_TOKEN(),
        patient_id=PATIENT_B,
        provider_id=doctor2,
        appointment_time=slot("09:00"),
        assisting_nurse_id=NURSE_PROVIDER,
    )
    assert r.status_code == 409
    assert "Nurse" in r.get_json()["error"]


def test_a_doctor_cannot_be_used_as_the_nurse(client):
    r = book(client, PATIENT_A_TOKEN(), assisting_nurse_id=DOCTOR_PROVIDER)
    assert r.status_code == 400


@pytest.mark.parametrize("bad", [999, "abc", True, 1.5, [2]])
def test_junk_nurse_values_are_400(client, bad):
    r = book(client, PATIENT_A_TOKEN(), assisting_nurse_id=bad)
    assert r.status_code == 400, r.get_json()


def test_attached_nurse_now_sees_the_appointment(client):
    book(client, PATIENT_A_TOKEN(), assisting_nurse_id="any")
    r = client.get("/api/appointments", headers=auth(NURSE_TOKEN()))
    assert r.status_code == 200
    assert any(a["appointment_time"] == slot("09:00") for a in r.get_json())
