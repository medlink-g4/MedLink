#!/usr/bin/env python3
"""Live demonstration of the MedLink permission layer (task 1.4).

Run it:  python demo/rbac_demo.py

Builds a throwaway database from the project's own schema, seeds four people,
and sends real requests through the real decorators, printing what the server
returns. Nothing here is application code; it exists to show the permission
layer working. The patient, record and appointment endpoints are Sprint 2 and
3 work owned by other people.

Exits non-zero if any case does not return what it should, so it doubles as a
smoke test before the review.
"""

import base64
import json
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# The development JWT secret is short, which PyJWT warns about on every call.
# Keeping the demo output clean; see the README on setting JWT_SECRET.
import warnings  # noqa: E402

warnings.filterwarnings("ignore", message=".*HMAC key.*")

import jwt  # noqa: E402
from flask import Flask, jsonify  # noqa: E402

from routes.permissions import (  # noqa: E402
    JWT_ALGORITHM,
    JWT_SECRET,
    require_permission,
)

BOLD, DIM, GREEN, RED, CYAN, YELLOW, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[36m", "\033[33m", "\033[0m"
)

PEOPLE = {
    "john": (1, "patient", "John Patient"),
    "maria": (2, "patient", "Maria Lopez"),
    "sarah": (3, "doctor", "Dr. Sarah Johnson"),
    "mike": (4, "nurse", "Nurse Mike"),
    "chen": (5, "doctor", "Dr. Mike Chen"),
}
JOHN_RECORD, MARIA_RECORD = 1, 2

failures = []


def build_database(tmpdir):
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "database" / "init_db.py")],
        cwd=tmpdir, check=True, capture_output=True,
    )
    path = Path(tmpdir) / "medlink.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        INSERT INTO users (id, name, email, password_hash, role) VALUES
            (1, 'John Patient',      'john@medlink.test',  'x', 'patient'),
            (2, 'Maria Lopez',       'maria@medlink.test', 'x', 'patient'),
            (3, 'Dr. Sarah Johnson', 'sarah@medlink.test', 'x', 'doctor'),
            (4, 'Nurse Mike',        'mike@medlink.test',  'x', 'nurse'),
            (5, 'Dr. Mike Chen',     'chen@medlink.test',  'x', 'doctor');

        INSERT INTO patients (id, user_id) VALUES (1, 1), (2, 2);

        INSERT INTO providers (id, user_id, role_type, specialty, can_prescribe)
        VALUES (1, 3, 'doctor', 'Cardiology', 1),
               (2, 4, 'nurse',  NULL,         0),
               (3, 5, 'doctor', 'Neurology',  1);

        INSERT INTO appointments
            (patient_id, provider_id, assisting_nurse_id, appointment_time, status)
        VALUES (1, 1, 2, '2026-09-23T10:00', 'scheduled');

        INSERT INTO medical_records
            (patient_id, provider_id, diagnosis, prescription, record_date)
        VALUES (1, 1, 'Hypertension, stable', 'Lisinopril 10mg', '2026-09-20'),
               (2, 3, 'Migraine',             'Sumatriptan',     '2026-09-19');
        """
    )
    conn.commit()
    conn.close()
    return path


def build_app(db):
    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)

    @app.route("/api/patients/<int:patient_id>/records", methods=["GET"])
    @require_permission("medical_records", "view")
    def view_records(patient_id):
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT diagnosis, prescription FROM medical_records WHERE patient_id = ?",
            (patient_id,),
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows]), 200

    @app.route("/api/patients/<int:patient_id>/diagnosis", methods=["PUT"])
    @require_permission("medical_records", "update")
    def update_diagnosis(patient_id):
        return jsonify({"updated": "diagnosis", "patient_id": patient_id}), 200

    @app.route("/api/patients/<int:patient_id>/medications", methods=["PUT"])
    @require_permission("medical_records", "update")
    def update_medications(patient_id):
        return jsonify({"updated": "medications", "patient_id": patient_id}), 200

    @app.route("/api/patients/<int:patient_id>/vitals", methods=["PUT"])
    @require_permission("medical_records", "update_vitals")
    def update_vitals(patient_id):
        return jsonify({"updated": "vitals", "patient_id": patient_id}), 200

    return app.test_client()


def token_for(who, expires_in=timedelta(hours=2)):
    user_id, role, _ = PEOPLE[who]
    return jwt.encode(
        {"userId": user_id, "role": role,
         "exp": datetime.now(timezone.utc) + expires_in},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )


def tamper(token, new_role):
    """Rewrite the role claim in place, keeping the original signature."""
    header, payload_b64, signature = token.split(".")
    pad = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(pad))
    payload["role"] = new_role
    forged = base64.urlsafe_b64encode(
        json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{forged}.{signature}"


def show(client, label, method, path, token, expect, why):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = getattr(client, method.lower())(path, headers=headers)
    ok = response.status_code == expect
    if not ok:
        failures.append(label)

    colour = GREEN if ok else RED
    mark = "OK" if ok else "UNEXPECTED"
    print(f"  {BOLD}{label}{RESET}")
    print(f"    {DIM}{method} {path}{RESET}")
    print(f"    {DIM}Authorization: {'Bearer <token>' if token else '(none)'}{RESET}")
    print(f"    -> {colour}{response.status_code}{RESET}  {why}  {DIM}[{mark}]{RESET}")
    body = response.get_json()
    if response.status_code == 200 and isinstance(body, list) and body:
        for row in body:
            print(f"       {CYAN}{row}{RESET}")
    elif isinstance(body, dict) and "error" in body:
        print(f"       {DIM}{body['error']}{RESET}")
    print()


def section(title):
    print(f"\n{BOLD}{YELLOW}{title}{RESET}")
    print(f"{DIM}{'-' * len(title)}{RESET}\n")


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = build_database(tmpdir)
        client = build_app(db)

        print(f"\n{BOLD}MedLink role-based access control — task 1.4{RESET}")
        print(f"{DIM}Three roles: patient, doctor, nurse. No admin role.{RESET}\n")
        print(f"{BOLD}Who is in the demo database{RESET}")
        print("  John Patient       patient")
        print("  Maria Lopez        patient")
        print("  Dr. Sarah Johnson  doctor, has an appointment with John")
        print("  Nurse Mike         nurse, assisting on that same appointment")
        print("  Dr. Mike Chen      doctor, no appointment with John")
        print(f"\n{DIM}So Sarah and Mike are assigned to John. Chen is not.{RESET}")

        section("1. A patient reaches their own record and nothing else")
        show(client, "John reads his own record",
             "GET", f"/api/patients/{JOHN_RECORD}/records", token_for("john"),
             200, "allowed, own scope")
        show(client, "John tries to read Maria's record",
             "GET", f"/api/patients/{MARIA_RECORD}/records", token_for("john"),
             403, "denied, not his record")

        section("2. A nurse is limited by role, not just by patient")
        show(client, "Nurse Mike updates vitals for John",
             "PUT", f"/api/patients/{JOHN_RECORD}/vitals", token_for("mike"),
             200, "allowed, assigned and nurses may record vitals")
        show(client, "Nurse Mike tries to change John's diagnosis",
             "PUT", f"/api/patients/{JOHN_RECORD}/diagnosis", token_for("mike"),
             403, "denied, diagnosis is a doctor action")

        section("3. A doctor reaches assigned patients only")
        show(client, "Dr. Johnson updates John's medications",
             "PUT", f"/api/patients/{JOHN_RECORD}/medications", token_for("sarah"),
             200, "allowed, she is assigned to John")
        show(client, "Dr. Chen tries to read John's record",
             "GET", f"/api/patients/{JOHN_RECORD}/records", token_for("chen"),
             403, "denied, not assigned to John")

        section("4. The token itself is checked before any permission is")
        show(client, "No token at all",
             "GET", f"/api/patients/{JOHN_RECORD}/records", None,
             401, "rejected, no credentials")
        show(client, "Expired token",
             "GET", f"/api/patients/{JOHN_RECORD}/records",
             token_for("john", expires_in=timedelta(seconds=-60)),
             401, "rejected, expired")
        show(client, "John's token edited to claim doctor",
             "GET", f"/api/patients/{MARIA_RECORD}/records",
             tamper(token_for("john"), "doctor"),
             401, "rejected, signature no longer matches")

        print(f"{BOLD}{'=' * 62}{RESET}")
        if failures:
            print(f"{RED}{BOLD}{len(failures)} case(s) did not behave as expected:{RESET}")
            for f in failures:
                print(f"  - {f}")
            return 1
        print(f"{GREEN}{BOLD}All 9 cases behaved exactly as specified.{RESET}")
        print(f"{DIM}Enforcement is server-side. Hiding a button would not do this.{RESET}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
