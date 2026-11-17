"""Creates the demo accounts and sample data, so nobody has to type curl loops.

Usage, from the repository root, after `python database/init_db.py`:

    python demo/seed_demo_data.py

It uses the same database as the app: the file named by MEDLINK_DB, or
medlink.db in the current folder. Running it twice is safe; accounts that
already exist are left alone.

All four accounts use the password  demo1234 :

    patient@medlink.test   Pat Patient    patient, sees the doctor and the nurse
    patient2@medlink.test  Sam Second     patient, sees the doctor only
    doctor@medlink.test    Dr. Sam Avery  doctor
    nurse@medlink.test     Nia Nurse      nurse

Patient 2 exists so access checks mean something: "refused" can only be told
apart from "never tried" when there is a patient the staff member is NOT
assigned to. demo/integration_check.py relies on these exact accounts, and on
them being the first four users in a fresh database (ids 1 to 4).

This is demo data with a public password. Never run it against a real system.
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

PASSWORD = "demo1234"
DB_FILE = os.environ.get("MEDLINK_DB", "medlink.db")

USERS = [
    ("Pat Patient", "patient@medlink.test", "patient"),
    ("Sam Second", "patient2@medlink.test", "patient"),
    ("Dr. Sam Avery", "doctor@medlink.test", "doctor"),
    ("Nia Nurse", "nurse@medlink.test", "nurse"),
]


def main():
    if not os.path.exists(DB_FILE):
        sys.exit(f"{DB_FILE} not found. Run  python database/init_db.py  first.")

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "users" not in tables:
            sys.exit(
                f"{DB_FILE} has no tables. Run  python database/init_db.py  first."
            )

        ids = {}
        created = 0
        for name, email, role in USERS:
            row = conn.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if row:
                ids[email] = row["id"]
                continue
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                (name, email, generate_password_hash(PASSWORD), role),
            )
            ids[email] = cur.lastrowid
            created += 1
            if role == "patient":
                conn.execute(
                    "INSERT INTO patients (user_id) VALUES (?)", (cur.lastrowid,)
                )
            else:
                conn.execute(
                    "INSERT INTO providers (user_id, role_type, specialty, can_prescribe) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        cur.lastrowid,
                        role,
                        "General Practice" if role == "doctor" else None,
                        1 if role == "doctor" else 0,
                    ),
                )

        if created == 0:
            print("Demo accounts already exist; nothing to add.")
        else:
            patient = patient_id(conn, ids["patient@medlink.test"])
            patient2 = patient_id(conn, ids["patient2@medlink.test"])
            doctor = provider_id(conn, ids["doctor@medlink.test"])
            nurse = provider_id(conn, ids["nurse@medlink.test"])
            add_sample_data(conn, patient, patient2, doctor, nurse)
            conn.commit()
            print(f"Created {created} account(s) and sample data in {DB_FILE}.")

        warn_if_ids_differ(ids)
    finally:
        conn.close()

    print("\nLog in with password  " + PASSWORD + "  as:")
    for name, email, role in USERS:
        print(f"  {role:8} {email}")


def patient_id(conn, user_id):
    return conn.execute(
        "SELECT id FROM patients WHERE user_id = ?", (user_id,)
    ).fetchone()["id"]


def provider_id(conn, user_id):
    return conn.execute(
        "SELECT id FROM providers WHERE user_id = ?", (user_id,)
    ).fetchone()["id"]


def add_sample_data(conn, patient, patient2, doctor, nurse):
    today = datetime.now().date()
    last_month = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    next_week = (today + timedelta(days=7)).strftime("%Y-%m-%d")

    def appointment(patient_id, nurse_id, day, start, end, reason, status):
        conn.execute(
            "INSERT INTO appointments (patient_id, provider_id, assisting_nurse_id, "
            "appointment_time, end_appointment_time, reason, status, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                patient_id,
                doctor,
                nurse_id,
                f"{day}T{start}",
                f"{day}T{end}",
                reason,
                status,
                patient_id,
            ),
        )

    # Patient 1 sees the doctor and the nurse; patient 2 only the doctor.
    appointment(
        patient, nurse, last_month, "09:00", "09:30", "Initial visit", "completed"
    )
    appointment(patient, nurse, next_week, "10:00", "10:30", "Follow-up", "scheduled")
    appointment(
        patient2, None, next_week, "11:00", "11:30", "Annual checkup", "scheduled"
    )

    for diagnosis, prescription, day in [
        ("Seasonal allergies", "Cetirizine 10mg daily", last_month),
        ("Mild hypertension", "Lisinopril 10mg daily", last_month),
    ]:
        conn.execute(
            "INSERT INTO medical_records (patient_id, provider_id, diagnosis, "
            "prescription, record_date) VALUES (?, ?, ?, ?, ?)",
            (patient, doctor, diagnosis, prescription, day),
        )


def warn_if_ids_differ(ids):
    expected = {
        "patient@medlink.test": 1,
        "patient2@medlink.test": 2,
        "doctor@medlink.test": 3,
        "nurse@medlink.test": 4,
    }
    if any(ids[e] != n for e, n in expected.items()):
        print(
            "\nNote: these accounts do not have user ids 1 to 4 (the database already "
            "had other users).\nThe site works fine; only demo/integration_check.py "
            "assumes those ids."
        )


if __name__ == "__main__":
    main()
