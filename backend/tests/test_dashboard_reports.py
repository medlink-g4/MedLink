"""Doctor/nurse dashboard and reports routes (Sprint 5, tasks 5.2/5.3).

Neither route had tests. Both are built the same way (token -> provider id ->
appointments assigned to that provider), so every check runs against both.

Uses the database and token helpers from test_appointments: patient A has a
completed appointment with the doctor and the nurse; patient B has none.
"""

import sqlite3

import sys
from pathlib import Path

# Without this the module only imports when another test file has already
# put backend/ on the path, so running this file on its own fails with
# "No module named 'routes'". Every other test file does the same.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import timedelta

import pytest
from flask import Flask
from routes.dr_nr_dashboard import dashboard_bp
from routes.reports import reports_bp
from test_appointments import (  # noqa: F401
    DOCTOR_PROVIDER,
    DOCTOR_TOKEN,
    NURSE_PROVIDER,
    NURSE_TOKEN,
    PATIENT_A,
    PATIENT_A_TOKEN,
    PATIENT_B,
    PATIENT_B_TOKEN,
    auth,
    db,
    token_for,
)

URLS = ["/api/dashboard/", "/api/reports/"]


@pytest.fixture()
def client(db):
    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
    app.register_blueprint(reports_bp, url_prefix="/api/reports")
    return app.test_client()


def run(db, sql, args=()):
    conn = sqlite3.connect(db)
    conn.execute(sql, args)
    conn.commit()
    conn.close()


def add_record(db, patient_id, diagnosis, date="2026-02-01"):
    run(
        db,
        "INSERT INTO medical_records (patient_id, provider_id, diagnosis, "
        "prescription, record_date) VALUES (?, 1, ?, 'x', ?)",
        (patient_id, diagnosis, date),
    )


def add_appointment(db, patient_id, time, status="scheduled", doctor=1, nurse=None):
    run(
        db,
        "INSERT INTO appointments (patient_id, provider_id, assisting_nurse_id, "
        "appointment_time, end_appointment_time, status, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (patient_id, doctor, nurse, time, time[:-2] + "30", status),
    )


def get(client, url, token):
    return client.get(url, headers=auth(token))


def names(rows, key="patient_name"):
    return {row[key] for row in rows}


# --- who may call ----------------------------------------------------------
@pytest.mark.parametrize("url", URLS)
def test_no_token_is_401(client, url):
    assert client.get(url).status_code == 401


@pytest.mark.parametrize("url", URLS)
def test_garbage_and_expired_tokens_are_401(client, url):
    assert get(client, url, "not.a.token").status_code == 401
    expired = token_for(3, "doctor", expires_in=timedelta(hours=-1))
    assert get(client, url, expired).status_code == 401


@pytest.mark.parametrize("url", URLS)
def test_patients_are_turned_away(client, url):
    assert get(client, url, PATIENT_A_TOKEN()).status_code == 403
    assert get(client, url, PATIENT_B_TOKEN()).status_code == 403


@pytest.mark.parametrize("url", URLS)
def test_staff_without_a_provider_profile_get_404(client, db, url):
    run(
        db,
        "INSERT INTO users (id,name,email,password_hash,role) "
        "VALUES (9,'Ghost','g@x','h','doctor')",
    )
    assert get(client, url, token_for(9, "doctor")).status_code == 404


# --- what they see ---------------------------------------------------------
@pytest.mark.parametrize("url", URLS)
def test_response_has_the_three_lists(client, url):
    body = get(client, url, DOCTOR_TOKEN()).get_json()
    assert set(body) == {"appointments", "patients", "medical_records"}


@pytest.mark.parametrize("url", URLS)
@pytest.mark.parametrize("token", [DOCTOR_TOKEN, NURSE_TOKEN])
def test_assigned_staff_see_their_patient_and_not_others(client, db, url, token):
    add_record(db, PATIENT_A, "Allergies")
    add_record(db, PATIENT_B, "Secret B diagnosis")
    body = get(client, url, token()).get_json()
    assert [p["name"] for p in body["patients"]] == ["Patient A"]
    assert names(body["appointments"]) == {"Patient A"}
    assert [r["diagnosis"] for r in body["medical_records"]] == ["Allergies"]
    assert "Secret B" not in str(body)


@pytest.mark.parametrize("url", URLS)
def test_an_unassigned_doctor_sees_nothing(client, db, url):
    run(
        db,
        "INSERT INTO users (id,name,email,password_hash,role) "
        "VALUES (9,'Doc2','d2@x','h','doctor')",
    )
    run(db, "INSERT INTO providers (id,user_id,role_type) VALUES (3,9,'doctor')")
    add_record(db, PATIENT_A, "Allergies")
    body = get(client, url, token_for(9, "doctor")).get_json()
    assert body == {"appointments": [], "patients": [], "medical_records": []}


@pytest.mark.parametrize("url", URLS)
def test_a_nurse_only_sees_patients_she_assists(client, db, url):
    # Patient B sees the doctor, but no nurse is on the appointment.
    add_appointment(db, PATIENT_B, "2026-12-01T10:00", doctor=DOCTOR_PROVIDER)
    nurse_body = get(client, url, NURSE_TOKEN()).get_json()
    doctor_body = get(client, url, DOCTOR_TOKEN()).get_json()
    assert names(nurse_body["appointments"]) == {"Patient A"}
    assert names(doctor_body["appointments"]) == {"Patient A", "Patient B"}


@pytest.mark.parametrize("url", URLS)
def test_cancelled_appointments_grant_nothing(client, db, url):
    add_appointment(
        db,
        PATIENT_B,
        "2026-12-01T10:00",
        status="cancelled",
        doctor=DOCTOR_PROVIDER,
        nurse=NURSE_PROVIDER,
    )
    add_record(db, PATIENT_B, "Secret B diagnosis")
    body = get(client, url, DOCTOR_TOKEN()).get_json()
    assert "Patient B" not in str(body)


@pytest.mark.parametrize("url", URLS)
def test_a_patient_with_two_appointments_is_listed_once(client, db, url):
    add_appointment(db, PATIENT_A, "2026-12-01T10:00", doctor=DOCTOR_PROVIDER)
    body = get(client, url, DOCTOR_TOKEN()).get_json()
    assert len(body["patients"]) == 1
    assert len(body["appointments"]) == 2


# --- the two routes differ in order and limit -------------------------------
def test_dashboard_lists_appointments_soonest_first(client, db):
    add_appointment(db, PATIENT_A, "2026-12-01T10:00")
    times = [
        a["appointment_time"]
        for a in get(client, "/api/dashboard/", DOCTOR_TOKEN()).get_json()[
            "appointments"
        ]
    ]
    assert times == sorted(times)


def test_reports_list_appointments_latest_first(client, db):
    add_appointment(db, PATIENT_A, "2026-12-01T10:00")
    times = [
        a["appointment_time"]
        for a in get(client, "/api/reports/", DOCTOR_TOKEN()).get_json()["appointments"]
    ]
    assert times == sorted(times, reverse=True)


def test_dashboard_shows_only_ten_recent_records_but_reports_show_all(client, db):
    for day in range(1, 13):
        add_record(db, PATIENT_A, f"Visit {day}", date=f"2026-03-{day:02d}")
    dash = get(client, "/api/dashboard/", DOCTOR_TOKEN()).get_json()["medical_records"]
    full = get(client, "/api/reports/", DOCTOR_TOKEN()).get_json()["medical_records"]
    assert len(dash) == 10 and len(full) == 12
    assert dash[0]["diagnosis"] == "Visit 12"  # newest first
