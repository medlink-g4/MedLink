"""
Patients blueprint -- Sprint 3, tasks 3.3 and 3.4.

    GET  /api/patients/<id>          view patient info          patients:view
    PUT  /api/patients/<id>          update patient info        patients:edit
    GET  /api/patients/<id>/vitals   vitals history             medical_records:view
    POST /api/patients/<id>/vitals   record a vitals reading    medical_records:update_vitals

Who may do what is NOT decided in this file. Every route sits behind
require_permission(), so the PERMISSIONS matrix in permissions.py stays the
single source of truth. Today that matrix means:

    doctor   view + edit assigned patients, view + record vitals
    nurse    view + edit assigned patients, view + record vitals
    patient  view + edit own info, view own vitals, cannot record vitals

Every route takes a patient_id URL parameter, so the decorator also enforces
the own / assigned scope automatically before the view runs.

Vitals are append-only readings (one row per measurement session), not a single
row that gets overwritten. "Updating vitals" means recording a new reading; the
latest one is what shows as current and the older ones stay as history.
"""

import re
import sqlite3
from datetime import date, datetime, timezone

from flask import Blueprint, g, jsonify, request
from routes.permissions import ForbiddenError, get_db, require_permission

patients_bp = Blueprint("patients", __name__)

# Patient fields a PUT may change. name/email live on the user's own account
# (users:edit is own-only), so they are deliberately not editable here.
EDITABLE_FIELDS = ("date_of_birth", "phone", "insurance_info")
PHONE_RE = re.compile(r"^[0-9+().\-\s]{7,30}$")

# field: (type, minimum, maximum) -- plausibility bounds that catch typos
# (a heart rate of 720, a temperature of 986) without second-guessing real
# clinical extremes.
VITAL_LIMITS = {
    "temperature_f": (float, 80.0, 115.0),
    "systolic_bp": (int, 50, 260),
    "diastolic_bp": (int, 30, 160),
    "heart_rate": (int, 20, 250),
    "respiratory_rate": (int, 4, 80),
    "oxygen_saturation": (int, 50, 100),
    "weight_lb": (float, 1.0, 1500.0),
    "height_in": (float, 10.0, 100.0),
}
VITAL_COLUMNS = tuple(VITAL_LIMITS)  # fixed whitelist -> safe to put in SQL


def _conn():
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _error(message, status=400):
    return jsonify({"error": message}), status


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_patient_update(data):
    """Return (clean_fields, error_message). Exactly one of them is None."""
    if not isinstance(data, dict) or not data:
        return None, "Send a JSON object with at least one field to update"

    unknown = sorted(set(data) - set(EDITABLE_FIELDS))
    if unknown:
        return None, (
            f"Cannot edit: {unknown}. Editable fields are {list(EDITABLE_FIELDS)}"
        )

    clean = {}
    for field, value in data.items():
        if value is None:
            clean[field] = None  # explicit null clears the field
            continue
        if not isinstance(value, str):
            return None, f"{field} must be text"
        value = value.strip()
        if value == "":
            clean[field] = None
            continue

        if field == "date_of_birth":
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                return None, "date_of_birth must be a real date in YYYY-MM-DD format"
            if parsed > date.today():
                return None, "date_of_birth cannot be in the future"
            clean[field] = parsed.isoformat()
        elif field == "phone":
            if not PHONE_RE.match(value):
                return (
                    None,
                    "phone may only contain digits, spaces and + ( ) . - (7-30 characters)",
                )
            clean[field] = value
        elif field == "insurance_info":
            if len(value) > 200:
                return None, "insurance_info must be 200 characters or fewer"
            clean[field] = value
    return clean, None


def _validate_vitals(data):
    """Return (clean_fields, error_message). Exactly one of them is None."""
    if not isinstance(data, dict) or not data:
        return None, "Send a JSON object with at least one measurement"

    unknown = sorted(set(data) - set(VITAL_COLUMNS) - {"notes"})
    if unknown:
        return None, f"Unknown fields: {unknown}"

    clean = {}
    for field, (kind, low, high) in VITAL_LIMITS.items():
        value = data.get(field)
        if value is None:
            continue
        # bool is a subclass of int in Python, so reject it explicitly
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"{field} must be a number"
        if kind is int:
            if isinstance(value, float) and not value.is_integer():
                return None, f"{field} must be a whole number"
            value = int(value)
        else:
            value = float(value)
        # written this way round so NaN fails the check too
        if not (low <= value <= high):
            return None, f"{field} must be between {low} and {high}"
        clean[field] = value

    notes = data.get("notes")
    if notes is not None:
        if not isinstance(notes, str):
            return None, "notes must be text"
        notes = notes.strip()
        if len(notes) > 500:
            return None, "notes must be 500 characters or fewer"
        clean["notes"] = notes or None

    if not any(field in clean for field in VITAL_COLUMNS):
        return None, "Provide at least one measurement"

    systolic, diastolic = clean.get("systolic_bp"), clean.get("diastolic_bp")
    if (systolic is None) != (diastolic is None):
        return None, "systolic_bp and diastolic_bp must be given together"
    if systolic is not None and systolic <= diastolic:
        return None, "systolic_bp must be higher than diastolic_bp"

    return clean, None


# ---------------------------------------------------------------------------
# Patient information (task 3.3)
# ---------------------------------------------------------------------------


def _fetch_patient(conn, patient_id):
    row = conn.execute(
        """
        SELECT p.id, u.name, u.email, p.date_of_birth, p.phone, p.insurance_info
        FROM patients p
        JOIN users u ON p.user_id = u.id
        WHERE p.id = ?
        """,
        (patient_id,),
    ).fetchone()
    return dict(row) if row else None


@patients_bp.route("/<int:patient_id>", methods=["GET"])
@require_permission("patients", "view")
def get_patient(patient_id):
    conn = _conn()
    try:
        patient = _fetch_patient(conn, patient_id)
    finally:
        conn.close()
    if patient is None:
        return _error("Patient not found", 404)
    return jsonify(patient)


@patients_bp.route("/<int:patient_id>", methods=["PUT"])
@require_permission("patients", "edit")
def update_patient(patient_id):
    clean, problem = _validate_patient_update(request.get_json(silent=True))
    if problem:
        return _error(problem)

    # Column names come from the fixed EDITABLE_FIELDS whitelist (validation
    # above rejects anything else); only the values are bound parameters.
    assignments = ", ".join(f"{field} = ?" for field in clean)
    conn = _conn()
    try:
        cursor = conn.execute(
            f"UPDATE patients SET {assignments} WHERE id = ?",
            (*clean.values(), patient_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return _error("Patient not found", 404)
        patient = _fetch_patient(conn, patient_id)
    finally:
        conn.close()
    return jsonify(patient)


# ---------------------------------------------------------------------------
# Vitals (task 3.4)
# ---------------------------------------------------------------------------

_VITALS_SELECT = """
    SELECT v.id, v.patient_id, v.recorded_at,
           v.temperature_f, v.systolic_bp, v.diastolic_bp, v.heart_rate,
           v.respiratory_rate, v.oxygen_saturation, v.weight_lb, v.height_in,
           v.notes,
           pr.role_type AS recorded_by_role, u.name AS recorded_by_name
    FROM vitals v
    JOIN providers pr ON v.recorded_by = pr.id
    JOIN users u ON pr.user_id = u.id
"""


@patients_bp.route("/<int:patient_id>/vitals", methods=["GET"])
@require_permission("medical_records", "view")
def get_vitals(patient_id):
    conn = _conn()
    try:
        rows = conn.execute(
            _VITALS_SELECT
            + " WHERE v.patient_id = ? ORDER BY v.recorded_at DESC, v.id DESC LIMIT 50",
            (patient_id,),
        ).fetchall()
    finally:
        conn.close()
    history = [dict(row) for row in rows]
    return jsonify({"latest": history[0] if history else None, "history": history})


@patients_bp.route("/<int:patient_id>/vitals", methods=["POST"])
@require_permission("medical_records", "update_vitals")
def record_vitals(patient_id):
    clean, problem = _validate_vitals(request.get_json(silent=True))
    if problem:
        return _error(problem)

    provider_id = g.auth.get("provider_id")
    if provider_id is None:
        raise ForbiddenError("Only a provider can record vitals")

    columns = ["patient_id", "recorded_by", "recorded_at", *clean]
    values = [
        patient_id,
        provider_id,
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        *clean.values(),
    ]
    conn = _conn()
    try:
        try:
            cursor = conn.execute(
                f"INSERT INTO vitals ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' * len(columns))})",
                values,
            )
        except sqlite3.IntegrityError:
            return _error("Patient not found", 404)
        conn.commit()
        created = conn.execute(
            _VITALS_SELECT + " WHERE v.id = ?", (cursor.lastrowid,)
        ).fetchone()
    finally:
        conn.close()
    return jsonify(dict(created)), 201
