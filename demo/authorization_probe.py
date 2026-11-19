#!/usr/bin/env python3
"""Task 5.1 - authorization probes against the running system.

The test suite proves each route behaves correctly in isolation and the
integration check proves the features work together. Neither answers the
question a reviewer actually asks about a medical system: can someone see
data that is not theirs?

Screenshots cannot answer it either. A report that returns too many
patients looks exactly like one that returns the right number. So these
probes ask the running server directly, as each role, and compare what
comes back against what the database says that role should reach.

Usage:

    python backend/app.py            # in one terminal, with demo accounts
    python demo/authorization_probe.py

Every expectation is derived from the database rather than hardcoded, so
this keeps working when the seed data changes. Exits non-zero on failure.
"""

import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
DB = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("medlink.db")
PASSWORD = "demo1234"

passed, failed = [], []


def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except ValueError:
            return e.code, {}


def check(label, got, want):
    good = got in want if isinstance(want, (list, tuple, set)) else got == want
    (passed if good else failed).append(label)
    suffix = "" if good else f" expected {want}"
    print(f"  {'PASS' if good else 'FAIL'}  {label}  ({got}{suffix})")


def login(email):
    return call("POST", "/api/auth/login",
                body={"email": email, "password": PASSWORD})[1].get("token")


def expected_patients_for(conn, provider_id, column):
    """What the database says this provider may reach, derived not assumed."""
    rows = conn.execute(
        f"""
        SELECT DISTINCT u.name
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        JOIN users u ON u.id = p.user_id
        WHERE a.{column} = ? AND a.status != 'cancelled'
        """,
        (provider_id,),
    ).fetchall()
    return {r[0] for r in rows}


patient = login("patient@medlink.test")
patient2 = login("patient2@medlink.test")
doctor = login("doctor@medlink.test")
nurse = login("nurse@medlink.test")

if not all([patient, patient2, doctor, nurse]):
    print("Could not log in as all four demo accounts. Is the server running "
          "with the demo data seeded?")
    sys.exit(1)

print("\n== reports are staff only, and scoped to assigned patients ==")
check("patient refused reports", call("GET", "/api/reports/", patient)[0], 403)
check("anonymous refused reports", call("GET", "/api/reports/")[0], 401)

if DB.exists():
    conn = sqlite3.connect(DB)
    try:
        for role, token, column, provider in (
            ("doctor", doctor, "provider_id", 1),
            ("nurse", nurse, "assisting_nurse_id", 2),
        ):
            status, report = call("GET", "/api/reports/", token)
            check(f"{role} can read reports", status, 200)
            got = {p.get("name") for p in (report.get("patients") or [])}
            want = expected_patients_for(conn, provider, column)
            check(f"{role} report matches their assignments exactly", got, [want])
            print(f"        {sorted(got) or 'none'}")
    finally:
        conn.close()
else:
    print(f"  (skipped scope comparison: no database at {DB})")

print("\n== records reach only the right people ==")
check("patient reads own records",
      call("GET", "/api/medical-records/me", patient)[0], 200)
check("other patient refused patient 1",
      call("GET", "/api/medical-records/patient/1", patient2)[0], 403)
check("assigned doctor reads patient 1",
      call("GET", "/api/medical-records/patient/1", doctor)[0], 200)
check("patient cannot write a record",
      call("POST", "/api/medical-records/", patient,
           {"patient_id": 1, "diagnosis": "x", "prescription": "y"})[0], 403)
check("nurse cannot write a record",
      call("POST", "/api/medical-records/", nurse,
           {"patient_id": 1, "diagnosis": "x", "prescription": "y"})[0], 403)

print("\n== profile and appointments ==")
check("patient reads own profile", call("GET", "/api/users/me", patient)[0], 200)
check("anonymous refused profile", call("GET", "/api/users/me")[0], 401)
check("patient refused another user's record",
      call("GET", "/api/users/2", patient)[0], (401, 403, 404))
check("patient lists own appointments",
      call("GET", "/api/appointments", patient)[0], 200)
check("anonymous refused appointments", call("GET", "/api/appointments")[0], 401)

print("\n== the audit trail is itself access controlled ==")
check("patient reads own access history",
      call("GET", "/api/audit/me", patient)[0], 200)
check("other patient refused patient 1's history",
      call("GET", "/api/audit/patient/1", patient2)[0], 403)
check("anonymous refused audit", call("GET", "/api/audit/me")[0], 401)
trail = json.dumps(call("GET", "/api/audit/me", patient)[1])
check("no clinical text in the audit log",
      not any(w in trail for w in ("Lisinopril", "Hypertension", "Migraine")), True)

print("\n== password reset does not reveal who has an account ==")
status_a, known = call("POST", "/api/auth/password-reset/request",
                       body={"email": "patient2@medlink.test"})
status_b, unknown = call("POST", "/api/auth/password-reset/request",
                         body={"email": "definitely-nobody@medlink.test"})
check("known and unknown addresses answer identically",
      known.get("message") == unknown.get("message") and status_a == status_b == 200,
      True)
check("invented reset token refused",
      call("POST", "/api/auth/password-reset/confirm",
           body={"token": "not-a-real-token", "new_password": "whatever12"})[0], 400)

print("\n== tokens cannot be forged or replayed ==")
check("garbage token refused",
      call("GET", "/api/medical-records/me", "garbage")[0], 401)

import base64  # noqa: E402

header, _, signature = patient.split(".")
forged_payload = base64.urlsafe_b64encode(
    b'{"userId":1,"role":"doctor","exp":9999999999}'
).decode().rstrip("=")
check("token edited to claim the doctor role refused",
      call("GET", "/api/reports/", f"{header}.{forged_payload}.{signature}")[0], 401)

print("\n" + "=" * 58)
print(f"{len(passed)} passed, {len(failed)} failed")
for f in failed:
    print("  FAILED: " + f)
sys.exit(1 if failed else 0)
