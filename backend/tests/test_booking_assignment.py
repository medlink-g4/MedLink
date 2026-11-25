"""Booking an appointment must create the provider's assignment.

The patient_provider_assignments table replaced deriving assignment from
appointment history. The backfill in init_db.py only covers appointments
that existed when it ran, so without the booking routes writing to the
table too, a provider booked with a new patient has no access to them at
all -- the appointment exists and every record request is refused.

Patient B starts with no assignments at all, which is what makes these
meaningful: if the booking route did nothing, the "before" and "after"
states would be identical and the access checks would stay refused.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_appointments import (  # noqa: E402,F401
    DOCTOR_PROVIDER,
    DOCTOR_TOKEN,
    PATIENT_A_TOKEN,
    NURSE_PROVIDER,
    NURSE_TOKEN,
    PATIENT_A,
    PATIENT_B,
    PATIENT_B_TOKEN,
    a_future_date,
    auth,
    book,
    client,
    db,
    slot,
)


def assignments(db, patient_id):
    """Active provider ids for this patient, read straight from the table."""
    conn = sqlite3.connect(db)
    try:
        return {
            r[0]
            for r in conn.execute(
                """SELECT provider_id FROM patient_provider_assignments
                   WHERE patient_id = ? AND is_active = 1""",
                (patient_id,),
            )
        }
    finally:
        conn.close()


def end_assignment(db, patient_id, provider_id):
    conn = sqlite3.connect(db)
    conn.execute(
        """UPDATE patient_provider_assignments
           SET is_active = 0, ended_at = datetime('now')
           WHERE patient_id = ? AND provider_id = ?""",
        (patient_id, provider_id),
    )
    conn.commit()
    conn.close()


# --- booking creates the assignment ----------------------------------------

def test_patient_b_starts_with_no_assignments(db):
    """The premise. If this ever fails the rest of the file proves nothing."""
    assert assignments(db, PATIENT_B) == set()


def test_booking_assigns_the_doctor(client, db):
    r = book(client, PATIENT_B_TOKEN(), patient_id=PATIENT_B,
             appointment_time=slot("09:00"))
    assert r.status_code == 201
    assert DOCTOR_PROVIDER in assignments(db, PATIENT_B)


def test_booking_assigns_the_assisting_nurse(client, db):
    r = book(client, PATIENT_B_TOKEN(), patient_id=PATIENT_B,
             appointment_time=slot("09:30"),
             assisting_nurse_id=NURSE_PROVIDER)
    assert r.status_code == 201
    assert assignments(db, PATIENT_B) == {DOCTOR_PROVIDER, NURSE_PROVIDER}


def test_booking_without_a_nurse_assigns_only_the_doctor(client, db):
    book(client, PATIENT_B_TOKEN(), patient_id=PATIENT_B,
         appointment_time=slot("10:00"))
    assert assignments(db, PATIENT_B) == {DOCTOR_PROVIDER}


def test_the_booking_is_what_grants_access(client, db):
    """The point of the whole change: refused before the booking, allowed
    after it, asked through the real permission function both times."""
    import flask
    from routes.permissions import is_assigned

    app = flask.Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)

    with app.app_context():
        assert is_assigned(DOCTOR_PROVIDER, PATIENT_B, "doctor") is False

    assert book(client, PATIENT_B_TOKEN(), patient_id=PATIENT_B,
                appointment_time=slot("11:00")).status_code == 201

    with app.app_context():
        assert is_assigned(DOCTOR_PROVIDER, PATIENT_B, "doctor") is True


def test_booking_twice_does_not_duplicate_the_assignment(client, db):
    book(client, PATIENT_B_TOKEN(), patient_id=PATIENT_B,
         appointment_time=slot("13:00"))
    book(client, PATIENT_B_TOKEN(), patient_id=PATIENT_B,
         appointment_time=slot("14:00"))

    conn = sqlite3.connect(db)
    count = conn.execute(
        """SELECT COUNT(*) FROM patient_provider_assignments
           WHERE patient_id = ? AND provider_id = ?""",
        (PATIENT_B, DOCTOR_PROVIDER),
    ).fetchone()[0]
    conn.close()
    assert count == 1, "the table is unique on the pair, not one row per booking"


def test_booking_reactivates_an_assignment_that_was_ended(client, db):
    """The reason this uses an upsert rather than INSERT OR IGNORE.

    A pair whose assignment was ended still has a row, so a plain ignore
    would quietly do nothing and leave the provider locked out of a patient
    they were just booked with.
    """
    end_assignment(db, PATIENT_A, DOCTOR_PROVIDER)
    assert DOCTOR_PROVIDER not in assignments(db, PATIENT_A)

    # Patient A books themselves, because doctors have no create permission
    # on appointments -- booking is done by the patient or by a nurse.
    r = book(client, PATIENT_A_TOKEN(), patient_id=PATIENT_A,
             appointment_time=slot("15:00"))
    assert r.status_code == 201, r.get_json()
    assert DOCTOR_PROVIDER in assignments(db, PATIENT_A)

    conn = sqlite3.connect(db)
    ended = conn.execute(
        """SELECT ended_at FROM patient_provider_assignments
           WHERE patient_id = ? AND provider_id = ?""",
        (PATIENT_A, DOCTOR_PROVIDER),
    ).fetchone()[0]
    conn.close()
    assert ended is None, "reactivating should clear ended_at"


# --- a failed booking must not leave an assignment behind -------------------

def test_a_rejected_booking_creates_no_assignment(client, db):
    """Double-booked, so the appointment is refused. The assignment must not
    survive the refusal -- access would be granted for a visit that does not
    exist."""
    book(client, PATIENT_B_TOKEN(), patient_id=PATIENT_B,
         appointment_time=slot("09:00"))

    conn = sqlite3.connect(db)
    conn.execute(
        """UPDATE patient_provider_assignments SET is_active = 0
           WHERE patient_id = ? AND provider_id = ?""",
        (PATIENT_B, DOCTOR_PROVIDER),
    )
    conn.commit()
    conn.close()

    clash = book(client, PATIENT_B_TOKEN(), patient_id=PATIENT_B,
                 appointment_time=slot("09:00"))
    assert clash.status_code == 409
    assert DOCTOR_PROVIDER not in assignments(db, PATIENT_B), (
        "a refused booking reactivated the assignment anyway"
    )


def test_an_invalid_booking_creates_no_assignment(client, db):
    r = book(client, PATIENT_B_TOKEN(), patient_id=PATIENT_B,
             appointment_time=slot("07:00"))
    assert r.status_code == 400
    assert assignments(db, PATIENT_B) == set()


# --- moving an appointment to another doctor assigns them too --------------

SECOND_DOCTOR_USER, SECOND_DOCTOR_PROVIDER = 5, 3


def add_second_doctor(db):
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        INSERT INTO users (id, name, email, password_hash, role)
        VALUES (5, 'Second Doctor', 'd2@x', 'h', 'doctor');
        INSERT INTO providers (id, user_id, role_type) VALUES (3, 5, 'doctor');
        """
    )
    conn.commit()
    conn.close()


def test_reassigning_to_another_doctor_assigns_them(client, db):
    """A booking can be moved to a different doctor. If that does not create
    an assignment, the new doctor holds an appointment they cannot see."""
    add_second_doctor(db)
    booked = book(client, PATIENT_A_TOKEN(), patient_id=PATIENT_A,
                  appointment_time=slot("13:30"))
    assert booked.status_code == 201
    appointment_id = booked.get_json()["id"]

    assert SECOND_DOCTOR_PROVIDER not in assignments(db, PATIENT_A)

    moved = client.put(
        f"/api/appointments/{appointment_id}",
        json={"provider_id": SECOND_DOCTOR_PROVIDER},
        headers=auth(PATIENT_A_TOKEN()),
    )
    assert moved.status_code == 200, moved.get_json()
    assert SECOND_DOCTOR_PROVIDER in assignments(db, PATIENT_A)


def test_the_original_doctor_keeps_their_assignment(client, db):
    """They may still have other appointments with this patient. Ending an
    assignment is deliberate, not a side effect of moving one booking."""
    add_second_doctor(db)
    booked = book(client, PATIENT_A_TOKEN(), patient_id=PATIENT_A,
                  appointment_time=slot("14:30"))
    appointment_id = booked.get_json()["id"]

    client.put(
        f"/api/appointments/{appointment_id}",
        json={"provider_id": SECOND_DOCTOR_PROVIDER},
        headers=auth(PATIENT_A_TOKEN()),
    )
    assert DOCTOR_PROVIDER in assignments(db, PATIENT_A)
