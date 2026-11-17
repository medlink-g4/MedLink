"""Sprint 5 (task 5.2): who can be messaged, and readable error messages.

Reuses the database and token helpers from test_appointments: patient A has an
appointment with the doctor and the nurse, so those three are connected.
"""

import sqlite3

import pytest
from flask import Flask
from routes.messages import messages_bp
from routes.patients import _validate_patient_update, _validate_vitals
from test_appointments import (  # noqa: F401
    DOCTOR_TOKEN,
    NURSE_TOKEN,
    PATIENT_A_TOKEN,
    PATIENT_B_TOKEN,
    auth,
    db,
)


@pytest.fixture()
def msg_client(db):
    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)
    app.register_blueprint(messages_bp, url_prefix="/api/messages")
    return app.test_client()


def contacts(client, token):
    r = client.get("/api/messages/contacts", headers=auth(token))
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def send(client, token, to, text="hello"):
    return client.post(
        "/api/messages", json={"recipient_id": to, "message": text}, headers=auth(token)
    )


# fixture users: patients 1, 2; doctor 3; nurse 4
def test_contacts_include_names(msg_client):
    got = contacts(msg_client, PATIENT_A_TOKEN())
    assert {c["name"] for c in got} == {"Doctor", "Nurse"}
    assert all({"id", "name", "role"} <= set(c) for c in got)


def test_doctor_sees_patient_and_assigned_nurse(msg_client):
    got = {c["role"]: c["name"] for c in contacts(msg_client, DOCTOR_TOKEN())}
    assert got == {"patient": "Patient A", "nurse": "Nurse"}


def test_nurse_sees_the_doctor_too(msg_client):
    assert {c["role"] for c in contacts(msg_client, NURSE_TOKEN())} == {
        "patient",
        "doctor",
    }


def test_doctor_and_nurse_can_exchange_messages(msg_client):
    assert send(msg_client, DOCTOR_TOKEN(), 4, "Please take vitals").status_code == 201
    r = msg_client.get("/api/messages?with_user_id=3", headers=auth(NURSE_TOKEN()))
    assert r.status_code == 200
    assert [m["message"] for m in r.get_json()] == ["Please take vitals"]


def test_doctor_cannot_message_a_nurse_they_share_no_appointment_with(msg_client, db):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO users (id,name,email,password_hash,role) "
        "VALUES (8,'Other Nurse','on@x','h','nurse')"
    )
    conn.execute("INSERT INTO providers (id,user_id,role_type) VALUES (5,8,'nurse')")
    conn.commit()
    conn.close()
    assert send(msg_client, DOCTOR_TOKEN(), 8).status_code == 403
    assert 8 not in {c["id"] for c in contacts(msg_client, DOCTOR_TOKEN())}


def test_cancelled_appointment_no_longer_connects_doctor_and_nurse(msg_client, db):
    conn = sqlite3.connect(db)
    conn.execute("UPDATE appointments SET status = 'cancelled'")
    conn.commit()
    conn.close()
    assert send(msg_client, DOCTOR_TOKEN(), 4).status_code == 403


def test_patient_still_cannot_message_unrelated_patient(msg_client):
    assert send(msg_client, PATIENT_A_TOKEN(), 2).status_code == 403


# --- readable wording ---------------------------------------------------
@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"temperature_f": 50}, "Temperature must be between 80 and 115 °F"),
        ({"heart_rate": 500}, "Heart rate must be between 20 and 250 bpm"),
        ({"weight_lb": "x"}, "Weight must be a number"),
        ({"heart_rate": 70.5}, "Heart rate must be a whole number"),
        (
            {"systolic_bp": 120},
            "Systolic and diastolic blood pressure must be entered together",
        ),
    ],
)
def test_vitals_errors_use_plain_names(payload, expected):
    clean, error = _validate_vitals(payload)
    assert clean is None and error == expected


def test_no_raw_column_names_in_vitals_errors():
    for field in (
        "temperature_f",
        "systolic_bp",
        "diastolic_bp",
        "heart_rate",
        "respiratory_rate",
        "oxygen_saturation",
        "weight_lb",
        "height_in",
    ):
        _, error = _validate_vitals({field: 99999})
        assert "_" not in error, error


def test_date_of_birth_errors_use_plain_names():
    _, error = _validate_patient_update({"date_of_birth": "2999-01-01"})
    assert error == "Date of birth cannot be in the future"
    _, error = _validate_patient_update({"date_of_birth": "nope"})
    assert error == "Date of birth must be a real date"
