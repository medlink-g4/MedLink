import os
import sqlite3

# Everything else in the project reads MEDLINK_DB when it is set, so the
# schema script has to honour it too. Without this it always wrote to
# medlink.db in whatever directory you happened to run it from, which is
# how you end up with a second empty database and a "no such table" error.
DB_PATH = os.environ.get("MEDLINK_DB", "medlink.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys = ON")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('patient', 'nurse', 'doctor'))
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        date_of_birth TEXT,
        phone TEXT,
        insurance_info TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS providers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        role_type TEXT NOT NULL CHECK (role_type IN ('nurse', 'doctor')),
        specialty TEXT,
        can_prescribe INTEGER NOT NULL DEFAULT 0,  -- 0 = false, 1 = true
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL,
        provider_id INTEGER NOT NULL,        -- the doctor
        assisting_nurse_id INTEGER,          -- optional nurse, can be NULL
        appointment_time TEXT NOT NULL,      -- start, ISO 8601 e.g. 2026-10-15T11:00
        end_appointment_time TEXT NOT NULL,
        reason TEXT,
        status TEXT NOT NULL DEFAULT 'scheduled'
            CHECK (status IN ('scheduled', 'completed', 'cancelled')),
        created_by INTEGER NOT NULL,         -- patient or provider who booked
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (patient_id) REFERENCES patients(id),
        FOREIGN KEY (provider_id) REFERENCES providers(id),
        FOREIGN KEY (assisting_nurse_id) REFERENCES providers(id),
        FOREIGN KEY (created_by) REFERENCES users(id)
    )
""")

# Appointment lookups are always "whose, and when", so index both directions.
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_appt_provider_time
        ON appointments (provider_id, appointment_time)
""")
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_appt_patient_time
        ON appointments (patient_id, appointment_time)
""")
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_appt_nurse_time
        ON appointments (assisting_nurse_id, appointment_time)
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS medical_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL,
        provider_id INTEGER NOT NULL,
        diagnosis TEXT,
        prescription TEXT,
        record_date TEXT NOT NULL,
        FOREIGN KEY (patient_id) REFERENCES patients(id),
        FOREIGN KEY (provider_id) REFERENCES providers(id)
    )
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        recipient_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        sent_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (sender_id) REFERENCES users(id),
        FOREIGN KEY (recipient_id) REFERENCES users(id),
        CHECK (sender_id != recipient_id)
    )
""")

cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_messages_sender_recipient
    ON messages (sender_id, recipient_id, sent_at)
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS vitals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL,
        recorded_by INTEGER NOT NULL,
        recorded_at TEXT NOT NULL,
        temperature_f REAL,
        systolic_bp INTEGER,
        diastolic_bp INTEGER,
        heart_rate INTEGER,
        respiratory_rate INTEGER,
        oxygen_saturation INTEGER,
        weight_lb REAL,
        height_in REAL,
        notes TEXT,
        FOREIGN KEY (patient_id) REFERENCES patients(id),
        FOREIGN KEY (recorded_by) REFERENCES providers(id)
    )
""")

# --- Task 4.4: self-service password reset ---------------------------------
# Only the hash of a reset token is stored. If this table leaks, the rows in
# it cannot be used to reset anyone's password, the same reason users holds a
# password_hash rather than a password.
cursor.execute("""
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
""")

cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_reset_tokens_user
    ON password_reset_tokens(user_id)
""")

# --- Task 4.5: activity and audit logging ----------------------------------
# HIPAA requires a record of who reached which patient's information and when,
# including the attempts that were refused. It does NOT require, and this
# table deliberately does not hold, the information itself: no diagnosis,
# prescription or message text is ever written here. Only who, what resource,
# which patient, and whether it was allowed.
cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at TEXT NOT NULL,
        user_id INTEGER,
        role TEXT,
        action TEXT NOT NULL,
        resource TEXT,
        patient_id INTEGER,
        outcome TEXT NOT NULL,
        detail TEXT,
        ip_address TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
""")

cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_audit_log_patient
    ON audit_log(patient_id, occurred_at)
""")

cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_audit_log_user
    ON audit_log(user_id, occurred_at)
""")

conn.commit()
conn.close()
print(
    f"{DB_PATH} created with tables: users, patients, providers, "
    "appointments, medical_records, messages, vitals, "
    "password_reset_tokens, audit_log"
)
