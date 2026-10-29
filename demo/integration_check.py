"""Task 3.6 - integrated test of the medical record and communication features.

The pytest suite exercises each blueprint in isolation against a throwaway
database. This script does the opposite: it talks to a running server over
HTTP, the way the browser does, so it covers the parts unit tests cannot -
blueprint wiring in app.py, the real database file, and the permission layer
working across features rather than inside one of them.

Usage:

    python backend/app.py                 # in one terminal
    python demo/integration_check.py      # in another

It needs four accounts to exist, all with the password  demo1234 :

    patient@medlink.test   patient, assigned to the doctor and the nurse
    patient2@medlink.test  patient, assigned to the doctor only
    doctor@medlink.test    doctor
    nurse@medlink.test     nurse

The second patient is what makes the negative cases meaningful: without a
patient who is NOT assigned to a given staff member, "access was refused"
can never be distinguished from "access was never attempted". I have a
seed script that creates these four and their sample data - ask me for it
if the team wants it in the repository.

Exits 0 if every case behaved as specified, 1 otherwise.
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5055"
PASSWORD = "demo1234"

def items(payload, key):
    """Endpoints return either a bare list or {key: [...]}; accept both."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get(key, [])
    return []

passed = []
failed = []


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
            return e.code, {"raw": raw.decode()[:200]}


def check(label, got, want):
    if got == want:
        passed.append(label)
        print(f"  PASS  {label}  ({got})")
    else:
        failed.append(f"{label}: expected {want}, got {got}")
        print(f"  FAIL  {label}  expected {want}, got {got}")


def login(email):
    status, body = call("POST", "/api/auth/login",
                        body={"email": email, "password": PASSWORD})
    if status != 200:
        print(f"  FAIL  login {email} -> {status} {body}")
        failed.append(f"login {email}")
        return None
    return body.get("token") or body.get("access_token")


print("\n== Logins ==")
patient = login("patient@medlink.test")
patient2 = login("patient2@medlink.test")
doctor = login("doctor@medlink.test")
nurse = login("nurse@medlink.test")
for name, tok in [("patient", patient), ("patient2", patient2),
                  ("doctor", doctor), ("nurse", nurse)]:
    check(f"{name} can log in", bool(tok), True)

if not all([patient, patient2, doctor, nurse]):
    print("\nCannot continue without all four demo accounts.")
    print("See the note at the top of this file for what they are.")
    sys.exit(1)

print("\n== Medical records (3.1) ==")
s, own = call("GET", "/api/medical-records/me", patient)
check("patient reads own record history", s, 200)
records = items(own, "records")
print(f"        returned {len(records)} record(s)")
check("history is not empty", len(records) > 0, True)

s, _ = call("GET", "/api/medical-records/patient/1", doctor)
check("assigned doctor reads patient 1", s, 200)
s, _ = call("GET", "/api/medical-records/patient/1", nurse)
check("assigned nurse reads patient 1", s, 200)
s, _ = call("GET", "/api/medical-records/patient/1", patient2)
check("other patient blocked from patient 1", s, 403)
s, _ = call("GET", "/api/medical-records/patient/1")
check("no token blocked", s, 401)

print("\n== Medications (3.2) ==")
s, meds = call("GET", "/api/medical-records/me/medications", patient)
check("patient reads own medications", s, 200)
med_list = items(meds, "medications")
print(f"        returned {len(med_list)} medication(s)")
check("medication list is not empty", len(med_list) > 0, True)
s, _ = call("GET", "/api/medical-records/patient/1/medications", doctor)
check("assigned doctor reads medications", s, 200)
s, _ = call("GET", "/api/medical-records/patient/1/medications", patient2)
check("other patient blocked from medications", s, 403)

print("\n== Writing records (3.3) ==")
new = {"patient_id": 1, "diagnosis": "Integration check",
       "prescription": "Ibuprofen 200mg", "notes": "Added by 3.6 test"}
s, created = call("POST", "/api/medical-records/", doctor, new)
check("doctor can add a record", s, 201)
record_id = (created.get("record_id") or created.get("id")) if isinstance(created, dict) else None
s, _ = call("POST", "/api/medical-records/", patient, new)
check("patient cannot add a record", s, 403)
s, _ = call("POST", "/api/medical-records/", nurse, new)
check("nurse cannot add a record", s, 403)
if record_id:
    s, _ = call("PUT", f"/api/medical-records/{record_id}", doctor,
                {"notes": "Amended by 3.6 test"})
    check("doctor can amend a record", s, 200)
    s, _ = call("PUT", f"/api/medical-records/{record_id}", patient,
                {"notes": "nope"})
    check("patient cannot amend a record", s, 403)

print("\n== Messaging (3.5) ==")
s, contacts = call("GET", "/api/messages/contacts", patient)
check("patient can list contacts", s, 200)
clist = items(contacts, "contacts")
print(f"        returned {len(clist)} contact(s)")
check("patient has at least one contact", len(clist) > 0, True)

doctor_user_id = None
for c in clist:
    if c.get("role") == "doctor":
        doctor_user_id = c.get("user_id") or c.get("id")
if doctor_user_id:
    s, _ = call("POST", "/api/messages", patient,
                {"recipient_id": doctor_user_id, "message": "3.6 test message"})
    check("patient can message assigned doctor", s, 201)
    s, thread = call("GET", f"/api/messages?with_user_id={doctor_user_id}", patient)
    check("patient can read the thread back", s, 200)
    msgs = items(thread, "messages")
    check("sent message appears in the thread", len(msgs) > 0, True)
    s, dthread = call("GET", f"/api/messages?with_user_id=1", doctor)
    check("doctor can read the same thread", s, 200)
    check("doctor sees the patient's message", len(items(dthread, "messages")) > 0, True)
    # Patient 2 has an appointment with the doctor but none with the nurse,
    # so the nurse is the genuinely unassigned staff member for them.
    nurse_user_id = None
    s, c2 = call("GET", "/api/messages/contacts", patient2)
    nurse_ids = [c.get("user_id") or c.get("id") for c in items(c2, "contacts")
                 if c.get("role") == "nurse"]
    check("unassigned nurse is not offered as a contact", nurse_ids, [])
    s, _ = call("POST", "/api/messages", patient2,
                {"recipient_id": 4, "message": "should be blocked"})
    check("patient cannot message an unassigned nurse", s, 403)
    s, _ = call("GET", "/api/messages?with_user_id=4", patient2)
    check("patient cannot read an unassigned nurse's thread", s, 403)
    s, _ = call("GET", f"/api/messages?with_user_id={doctor_user_id}")
    check("reading messages with no token is blocked", s, 401)
    s, _ = call("GET", "/api/messages", patient)
    check("missing with_user_id is rejected", s, 400)
else:
    failed.append("no doctor contact returned for the patient")
    print("  FAIL  no doctor contact returned, cannot test sending")

s, _ = call("POST", "/api/messages", patient,
            {"recipient_id": 9999, "message": "nobody"})
check("message to a non-existent user is refused", s in (400, 403, 404), True)

print("\n== Appointments still working after integration (2.4 / 2.5) ==")
s, _ = call("GET", "/api/appointments", patient)
check("patient can list appointments", s, 200)
s, avail = call("GET", "/api/appointments/availability?provider_id=1&date=2026-12-01",
                patient)
check("availability returns slots", s, 200)

print("\n" + "=" * 58)
print(f"{len(passed)} passed, {len(failed)} failed")
for f in failed:
    print("  FAILED: " + f)
sys.exit(1 if failed else 0)
