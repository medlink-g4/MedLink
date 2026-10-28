"""Tests for appointment management (task 4.2): changing and cancelling.

Real SQLite database built from the project's own init_db.py, real tokens
minted the way login mints them, real blueprints on a Flask app. Users are
registered through /api/auth/register; appointments are inserted with SQL so
tests can set up states the booking route refuses (a nurse who is already
assigned, a completed visit, a visit in the past).
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
from routes.appointments import appointments_bp
from routes.auth import auth_bp
from routes.permissions import JWT_ALGORITHM, JWT_SECRET

REPO_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "password123"
DAY = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
YESTERDAY = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def at(hhmm, day=DAY):
    return f"{day}T{hhmm}"


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
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(appointments_bp, url_prefix="/api/appointments")
    c = app.test_client()
    c.db_file = tmp_path / "medlink.db"
    return c


def register(client, name, email, role):
    """Create an account and return its user id.

    Patients sign up through the real route. Doctors and nurses cannot
    self-register (the route refuses them), so they are created directly in
    the test database with the same rows the route would create.
    """
    if role == "patient":
        r = client.post(
            "/api/auth/register",
            json={"name": name, "email": email, "password": PASSWORD, "role": role},
        )
        assert r.status_code == 201, r.get_json()
        return r.get_json()["userId"]
    conn = sqlite3.connect(client.db_file)
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, generate_password_hash(PASSWORD), role),
        )
        conn.execute(
            "INSERT INTO providers (user_id, role_type, specialty, can_prescribe) "
            "VALUES (?, ?, NULL, ?)",
            (cur.lastrowid, role, 1 if role == "doctor" else 0),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def token_for(user_id, role):
    return jwt.encode(
        {
            "userId": user_id,
            "role": role,
            "exp": datetime.now().astimezone() + timedelta(hours=2),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def sql(client, query, args=()):
    conn = sqlite3.connect(client.db_file)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, args).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


@pytest.fixture()
def world(client):
    """Two patients, two doctors, two nurses; ids for each plus auth headers."""
    spec = [
        ("pat", "Pat Patient", "patient"),
        ("pat2", "Other Patient", "patient"),
        ("doc", "Dr Smith", "doctor"),
        ("doc2", "Dr Jones", "doctor"),
        ("nurse", "Nancy Nurse", "nurse"),
        ("nurse2", "Nick Nurse", "nurse"),
    ]
    w = {}
    for key, name, role in spec:
        uid = register(client, name, f"{key}@x.com", role)
        table = "patients" if role == "patient" else "providers"
        row = sql(client, f"SELECT id FROM {table} WHERE user_id = ?", (uid,))[0]
        w[key] = {
            "user": uid,
            "id": row["id"],
            "role": role,
            "h": {"Authorization": f"Bearer {token_for(uid, role)}"},
        }
    return w


def seed(
    client,
    w,
    when,
    patient="pat",
    doctor="doc",
    nurse="nurse",
    status="scheduled",
    reason="checkup",
):
    end = datetime.strptime(when, "%Y-%m-%dT%H:%M") + timedelta(minutes=30)
    rows = sql(
        client,
        """INSERT INTO appointments
        (patient_id, provider_id, assisting_nurse_id, appointment_time,
         end_appointment_time, reason, status, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
        (
            w[patient]["id"],
            w[doctor]["id"],
            w[nurse]["id"] if nurse else None,
            when,
            end.strftime("%Y-%m-%dT%H:%M"),
            reason,
            status,
            w[patient]["user"],
        ),
    )
    return rows[0]["id"]


def row(client, appt_id):
    return dict(sql(client, "SELECT * FROM appointments WHERE id = ?", (appt_id,))[0])


def put(client, who, appt_id, body):
    return client.put(f"/api/appointments/{appt_id}", json=body, headers=who["h"])


def cancel(client, who, appt_id):
    return client.post(f"/api/appointments/{appt_id}/cancel", headers=who["h"])


# --- changing: who may -----------------------------------------------------


def test_patient_can_move_own_appointment(client, world):
    a = seed(client, world, at("09:00"))
    r = put(client, world["pat"], a, {"appointment_time": at("10:30")})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["appointment_time"] == at("10:30")
    assert body["end_appointment_time"] == at("11:00")
    assert body["patient_name"] == "Pat Patient" and body["provider_name"] == "Dr Smith"
    saved = row(client, a)
    assert (saved["appointment_time"], saved["end_appointment_time"]) == (
        at("10:30"),
        at("11:00"),
    )
    assert saved["status"] == "scheduled"


def test_moving_frees_the_old_slot_for_someone_else(client, world):
    a = seed(client, world, at("09:00"))
    assert (
        put(client, world["pat"], a, {"appointment_time": at("10:00")}).status_code
        == 200
    )
    r = client.post(
        "/api/appointments",
        headers=world["pat2"]["h"],
        json={
            "patient_id": world["pat2"]["id"],
            "provider_id": world["doc"]["id"],
            "appointment_time": at("09:00"),
        },
    )
    assert r.status_code == 201, r.get_json()


def test_patient_cannot_change_someone_elses_appointment(client, world):
    a = seed(client, world, at("09:00"))
    r = put(client, world["pat2"], a, {"appointment_time": at("10:00")})
    assert r.status_code == 403
    assert row(client, a)["appointment_time"] == at("09:00")


def test_doctor_cannot_change_even_an_assigned_appointment(client, world):
    a = seed(client, world, at("09:00"))
    r = put(client, world["doc"], a, {"appointment_time": at("10:00")})
    assert r.status_code == 403
    assert row(client, a)["appointment_time"] == at("09:00")


def test_assigned_nurse_can_change_and_unassigned_nurse_cannot(client, world):
    a = seed(client, world, at("09:00"))
    assert put(client, world["nurse2"], a, {"reason": "x"}).status_code == 403
    assert row(client, a)["reason"] == "checkup"
    r = put(
        client,
        world["nurse"],
        a,
        {"appointment_time": at("14:00"), "reason": "follow-up"},
    )
    assert r.status_code == 200, r.get_json()
    assert (row(client, a)["appointment_time"], row(client, a)["reason"]) == (
        at("14:00"),
        "follow-up",
    )


def test_missing_bad_and_expired_tokens_are_unauthorized(client, world):
    a = seed(client, world, at("09:00"))
    body = {"reason": "x"}
    assert client.put(f"/api/appointments/{a}", json=body).status_code == 401
    assert (
        client.put(
            f"/api/appointments/{a}",
            json=body,
            headers={"Authorization": "Bearer x.y.z"},
        ).status_code
        == 401
    )
    expired = jwt.encode(
        {
            "userId": world["pat"]["user"],
            "role": "patient",
            "exp": datetime.now().astimezone() - timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    assert (
        client.put(
            f"/api/appointments/{a}",
            json=body,
            headers={"Authorization": f"Bearer {expired}"},
        ).status_code
        == 401
    )


def test_unknown_appointment_is_404(client, world):
    assert put(client, world["pat"], 999, {"reason": "x"}).status_code == 404


# --- changing: input -------------------------------------------------------


@pytest.mark.parametrize("body", [{}, [], "text", None])
def test_body_must_be_a_non_empty_object(client, world, body):
    a = seed(client, world, at("09:00"))
    r = client.put(f"/api/appointments/{a}", headers=world["pat"]["h"], json=body)
    assert r.status_code == 400


def test_non_json_body_is_400(client, world):
    a = seed(client, world, at("09:00"))
    r = client.put(f"/api/appointments/{a}", headers=world["pat"]["h"], data="not json")
    assert r.status_code == 400


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "completed"),
        ("patient_id", 2),
        ("assisting_nurse_id", 1),
        ("created_by", 1),
        ("id", 77),
        ("end_appointment_time", at("12:00")),
    ],
)
def test_fields_outside_the_whitelist_are_refused(client, world, field, value):
    a = seed(client, world, at("09:00"))
    before = row(client, a)
    r = put(client, world["pat"], a, {field: value})
    assert r.status_code == 400 and field in r.get_json()["error"]
    assert row(client, a) == before


@pytest.mark.parametrize(
    "when",
    [
        at("09:15"),
        at("07:30"),
        at("17:00"),
        at("12:00", YESTERDAY),
        "tomorrow",
        "2026-13-40T09:00",
        None,
        "",
        900,
    ],
)
def test_bad_times_are_400_and_change_nothing(client, world, when):
    a = seed(client, world, at("09:00"))
    r = put(client, world["pat"], a, {"appointment_time": when})
    assert r.status_code == 400, (when, r.get_json())
    assert row(client, a)["appointment_time"] == at("09:00")


def test_last_slot_of_the_day_is_allowed(client, world):
    a = seed(client, world, at("09:00"))
    assert (
        put(client, world["pat"], a, {"appointment_time": at("16:30")}).status_code
        == 200
    )


@pytest.mark.parametrize("pid", ["2", True, 1.5, [1], None, 999])
def test_bad_provider_ids_are_400(client, world, pid):
    a = seed(client, world, at("09:00"))
    r = put(client, world["pat"], a, {"provider_id": pid})
    assert r.status_code == 400, (pid, r.get_json())
    assert row(client, a)["provider_id"] == world["doc"]["id"]


def test_reason_rules(client, world):
    a = seed(client, world, at("09:00"))
    assert (
        put(client, world["pat"], a, {"reason": "  sore knee  "}).get_json()["reason"]
        == "sore knee"
    )
    assert put(client, world["pat"], a, {"reason": "   "}).get_json()["reason"] is None
    assert put(client, world["pat"], a, {"reason": "again"}).status_code == 200
    assert put(client, world["pat"], a, {"reason": None}).get_json()["reason"] is None
    assert put(client, world["pat"], a, {"reason": "x" * 501}).status_code == 400
    assert put(client, world["pat"], a, {"reason": 5}).status_code == 400
    assert put(client, world["pat"], a, {"reason": "x" * 500}).status_code == 200


def test_reason_only_edit_leaves_the_time_alone(client, world):
    a = seed(client, world, at("09:00"))
    before = row(client, a)
    assert put(client, world["pat"], a, {"reason": "new"}).status_code == 200
    after = row(client, a)
    assert after["reason"] == "new"
    assert {k: v for k, v in after.items() if k != "reason"} == {
        k: v for k, v in before.items() if k != "reason"
    }


# --- changing: double booking ---------------------------------------------


def test_cannot_move_onto_the_providers_other_appointment(client, world):
    a = seed(client, world, at("09:00"))
    seed(client, world, at("10:00"), patient="pat2")
    r = put(client, world["pat"], a, {"appointment_time": at("10:00")})
    assert r.status_code == 409
    assert row(client, a)["appointment_time"] == at("09:00")


def test_cannot_move_onto_the_patients_other_appointment(client, world):
    a = seed(client, world, at("09:00"))
    seed(client, world, at("10:00"), doctor="doc2")
    assert (
        put(client, world["pat"], a, {"appointment_time": at("10:00")}).status_code
        == 409
    )


def test_a_cancelled_appointment_does_not_block_a_move(client, world):
    a = seed(client, world, at("09:00"))
    seed(client, world, at("10:00"), patient="pat2", status="cancelled")
    assert (
        put(client, world["pat"], a, {"appointment_time": at("10:00")}).status_code
        == 200
    )


def test_setting_the_same_time_again_is_not_a_clash_with_itself(client, world):
    a = seed(client, world, at("09:00"))
    assert (
        put(client, world["pat"], a, {"appointment_time": at("09:00")}).status_code
        == 200
    )


def test_switching_provider_at_the_same_time_works_when_free(client, world):
    a = seed(client, world, at("09:00"))
    r = put(client, world["pat"], a, {"provider_id": world["doc2"]["id"]})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["provider_name"] == "Dr Jones"
    # the old doctor no longer sees it, the new doctor does
    assert client.get("/api/appointments", headers=world["doc"]["h"]).get_json() == []
    assert (
        len(client.get("/api/appointments", headers=world["doc2"]["h"]).get_json()) == 1
    )


def test_switching_to_a_busy_provider_is_409(client, world):
    a = seed(client, world, at("09:00"))
    seed(client, world, at("09:00"), patient="pat2", doctor="doc2")
    assert (
        put(client, world["pat"], a, {"provider_id": world["doc2"]["id"]}).status_code
        == 409
    )
    assert row(client, a)["provider_id"] == world["doc"]["id"]


def test_time_and_provider_can_change_together(client, world):
    a = seed(client, world, at("09:00"))
    seed(client, world, at("09:00"), patient="pat2", doctor="doc2")
    r = put(
        client,
        world["pat"],
        a,
        {"provider_id": world["doc2"]["id"], "appointment_time": at("11:00")},
    )
    assert r.status_code == 200, r.get_json()


# --- changing: state --------------------------------------------------------


@pytest.mark.parametrize("status", ["cancelled", "completed"])
def test_finished_appointments_cannot_be_changed(client, world, status):
    a = seed(client, world, at("09:00"), status=status)
    r = put(client, world["pat"], a, {"reason": "x"})
    assert r.status_code == 409 and status in r.get_json()["error"]
    assert row(client, a)["reason"] == "checkup"


def test_an_appointment_that_already_started_cannot_be_changed(client, world):
    a = seed(client, world, at("09:00", YESTERDAY))
    assert put(client, world["pat"], a, {"reason": "x"}).status_code == 409
    assert row(client, a)["reason"] == "checkup"


def test_authorization_is_checked_before_the_body(client, world):
    a = seed(client, world, at("09:00"))
    assert put(client, world["pat2"], a, {"status": "completed"}).status_code == 403


# --- cancelling -------------------------------------------------------------


def test_patient_cancels_own_appointment_and_slot_is_freed(client, world):
    a = seed(client, world, at("09:00"))
    r = cancel(client, world["pat"], a)
    assert r.status_code == 200 and r.get_json()["status"] == "cancelled"
    assert row(client, a)["status"] == "cancelled"
    assert cancel(client, world["pat"], a).status_code == 409
    free = client.get(
        f"/api/appointments/availability?provider_id={world['doc']['id']}&date={DAY}",
        headers=world["pat2"]["h"],
    ).get_json()
    assert at("09:00") in free["available"]


def test_only_the_right_people_can_cancel(client, world):
    a = seed(client, world, at("09:00"))
    assert cancel(client, world["pat2"], a).status_code == 403
    assert cancel(client, world["doc"], a).status_code == 403
    assert cancel(client, world["nurse2"], a).status_code == 403
    assert row(client, a)["status"] == "scheduled"
    assert cancel(client, world["nurse"], a).status_code == 200
    assert row(client, a)["status"] == "cancelled"


def test_a_completed_appointment_cannot_be_cancelled(client, world):
    a = seed(client, world, at("09:00"), status="completed")
    r = cancel(client, world["pat"], a)
    assert r.status_code == 409
    assert row(client, a)["status"] == "completed"


def test_cancel_unknown_appointment_is_404(client, world):
    assert cancel(client, world["pat"], 999).status_code == 404


# --- listing ----------------------------------------------------------------


def test_list_carries_names_and_stays_scoped(client, world):
    seed(client, world, at("09:00"))
    seed(client, world, at("10:00"), patient="pat2", doctor="doc2", nurse="nurse2")
    mine = client.get("/api/appointments", headers=world["pat"]["h"]).get_json()
    assert [(m["patient_name"], m["provider_name"]) for m in mine] == [
        ("Pat Patient", "Dr Smith")
    ]
    nurse = client.get("/api/appointments", headers=world["nurse"]["h"]).get_json()
    assert [m["patient_name"] for m in nurse] == ["Pat Patient"]
    doc2 = client.get("/api/appointments", headers=world["doc2"]["h"]).get_json()
    assert [m["patient_name"] for m in doc2] == ["Other Patient"]
