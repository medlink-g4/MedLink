"""Tests for the role-based access control layer.

Run from the backend directory:

    python -m pytest tests/test_permissions.py -v
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routes.permissions import (  # noqa: E402
    JWT_SECRET,
    PERMISSIONS,
    require_auth,
    require_permission,
    require_role,
)


def make_token(user_id=1, role="patient", expires_in_hours=2, secret=JWT_SECRET):
    """Build a token shaped exactly like the one routes/auth.py login issues."""
    payload = {
        "userId": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def client():
    app = Flask(__name__)

    @app.route("/any")
    @require_auth
    def any_user():
        return jsonify({"ok": True})

    @app.route("/doctors-only")
    @require_role("doctor")
    def doctors_only():
        return jsonify({"ok": True})

    @app.route("/clinical")
    @require_role("doctor", "nurse")
    def clinical():
        return jsonify({"ok": True})

    @app.route("/prescribe")
    @require_permission("prescriptions:write")
    def prescribe():
        return jsonify({"ok": True})

    @app.route("/write-record")
    @require_permission("records:write")
    def write_record():
        return jsonify({"ok": True})

    return app.test_client()


def auth(token):
    return {"Authorization": "Bearer {}".format(token)}


# --- authentication ---------------------------------------------------------

def test_valid_token_is_accepted(client):
    assert client.get("/any", headers=auth(make_token())).status_code == 200


def test_missing_header_is_rejected(client):
    response = client.get("/any")
    assert response.status_code == 401
    assert "Authorization header is required" in response.get_json()["error"]


def test_malformed_header_is_rejected(client):
    response = client.get("/any", headers={"Authorization": "token abc"})
    assert response.status_code == 401


def test_expired_token_is_rejected(client):
    token = make_token(expires_in_hours=-1)
    response = client.get("/any", headers=auth(token))
    assert response.status_code == 401
    assert "expired" in response.get_json()["error"].lower()


def test_token_signed_with_wrong_secret_is_rejected(client):
    token = make_token(secret="not-the-real-secret")
    assert client.get("/any", headers=auth(token)).status_code == 401


def test_unknown_role_in_token_is_rejected(client):
    """A token claiming a role we deleted, such as admin, must not pass."""
    token = make_token(role="admin")
    assert client.get("/any", headers=auth(token)).status_code == 403


# --- role gates -------------------------------------------------------------

def test_doctor_reaches_doctor_route(client):
    token = make_token(role="doctor")
    assert client.get("/doctors-only", headers=auth(token)).status_code == 200


def test_nurse_blocked_from_doctor_route(client):
    token = make_token(role="nurse")
    response = client.get("/doctors-only", headers=auth(token))
    assert response.status_code == 403


def test_patient_blocked_from_clinical_route(client):
    token = make_token(role="patient")
    assert client.get("/clinical", headers=auth(token)).status_code == 403


@pytest.mark.parametrize("role", ["doctor", "nurse"])
def test_clinical_staff_reach_clinical_route(client, role):
    token = make_token(role=role)
    assert client.get("/clinical", headers=auth(token)).status_code == 200


# --- permission gates -------------------------------------------------------

def test_only_doctors_may_prescribe(client):
    doctor = client.get("/prescribe", headers=auth(make_token(role="doctor")))
    nurse = client.get("/prescribe", headers=auth(make_token(role="nurse")))
    patient = client.get("/prescribe", headers=auth(make_token(role="patient")))

    assert doctor.status_code == 200
    assert nurse.status_code == 403
    assert patient.status_code == 403


def test_nurses_may_write_records_but_not_prescribe(client):
    token = make_token(role="nurse")
    assert client.get("/write-record", headers=auth(token)).status_code == 200
    assert client.get("/prescribe", headers=auth(token)).status_code == 403


def test_patients_hold_no_write_permissions():
    writes = {p for p in PERMISSIONS["patient"] if p.endswith(":write")}
    assert writes == set()


def test_every_role_in_the_matrix_is_a_real_role():
    assert set(PERMISSIONS) == {"patient", "nurse", "doctor"}
