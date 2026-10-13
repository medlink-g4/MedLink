"""Patient medical records and medications (tasks 3.1 and 3.2).

Both features read the same `medical_records` table. A record carries a
diagnosis, a prescription and a date, so medications are not a separate
store: they are the prescription column of the records that have one. That
is why one module serves both, with a records endpoint for the full history
and a medications endpoint for the prescribing subset.

Who may do what comes from the task 1.4 permission matrix, not from here:

    patient   view their own records
    nurse     view records for patients they are assigned to
    doctor    view, create and update records for assigned patients

Mounted at /api/medical-records so it does not collide with the
/api/patients blueprint.
"""

import sqlite3
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request

from routes.permissions import (
    enforce_patient_scope,
    get_db,
    require_permission,
)

medical_records_bp = Blueprint("medical_records", __name__)

DATE_FORMAT = "%Y-%m-%d"


class ValidationError(Exception):
    """Bad input from the caller. Surfaces as 400."""


def _bad(message):
    raise ValidationError(message)


def parse_record_date(raw):
    """Default to today. Reject anything unparseable or in the future."""
    if raw in (None, ""):
        return date.today().strftime(DATE_FORMAT)
    try:
        parsed = datetime.strptime(str(raw)[:10], DATE_FORMAT).date()
    except ValueError:
        _bad(f"record_date must look like 2026-10-13, got {raw!r}")
    if parsed > date.today():
        _bad("record_date cannot be in the future")
    return parsed.strftime(DATE_FORMAT)


def row_to_record(row):
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "provider_id": row["provider_id"],
        "provider_name": row["provider_name"],
        "diagnosis": row["diagnosis"],
        "prescription": row["prescription"],
        "record_date": row["record_date"],
    }


RECORD_SELECT = """
    SELECT r.id, r.patient_id, r.provider_id, r.diagnosis,
           r.prescription, r.record_date, u.name AS provider_name
    FROM medical_records r
    JOIN providers p ON p.id = r.provider_id
    JOIN users u     ON u.id = p.user_id
"""


@medical_records_bp.route("/patient/<int:patient_id>", methods=["GET"])
@require_permission("medical_records", "view")
def list_records(patient_id):
    """Full medical history for one patient, newest first."""
    conn = get_db()
    try:
        rows = conn.execute(
            RECORD_SELECT + " WHERE r.patient_id = ? ORDER BY r.record_date DESC, r.id DESC",
            (patient_id,),
        ).fetchall()
    finally:
        conn.close()
    return jsonify([row_to_record(r) for r in rows]), 200


@medical_records_bp.route("/patient/<int:patient_id>/medications", methods=["GET"])
@require_permission("medical_records", "view")
def list_medications(patient_id):
    """The prescribing subset of the same records, newest first.

    Medications are not stored separately. This returns only records whose
    prescription is set, with the diagnosis it was prescribed for.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            RECORD_SELECT
            + """ WHERE r.patient_id = ?
                    AND r.prescription IS NOT NULL
                    AND TRIM(r.prescription) != ''
                  ORDER BY r.record_date DESC, r.id DESC""",
            (patient_id,),
        ).fetchall()
    finally:
        conn.close()
    return jsonify([
        {
            "record_id": r["id"],
            "patient_id": r["patient_id"],
            "medication": r["prescription"],
            "prescribed_for": r["diagnosis"],
            "prescribed_by": r["provider_name"],
            "prescribed_on": r["record_date"],
        }
        for r in rows
    ]), 200


@medical_records_bp.route("", methods=["POST"])
@medical_records_bp.route("/", methods=["POST"])
@require_permission("medical_records", "create")
def create_record():
    """Add a record. Doctors only, per the permission matrix."""
    data = request.get_json(silent=True) or {}
    try:
        patient_id = data.get("patient_id")
        if patient_id is None:
            _bad("patient_id is required")

        enforce_patient_scope(patient_id)

        diagnosis = (data.get("diagnosis") or "").strip() or None
        prescription = (data.get("prescription") or "").strip() or None
        if diagnosis is None and prescription is None:
            _bad("a record needs at least a diagnosis or a prescription")

        record_date = parse_record_date(data.get("record_date"))

        # The author is the authenticated provider, never a value from the
        # request body, so a record cannot be attributed to someone else.
        provider_id = g.auth.get("provider_id")
        if provider_id is None:
            return jsonify({"error": "No provider profile for this account"}), 403

        conn = get_db()
        try:
            if conn.execute(
                "SELECT 1 FROM patients WHERE id = ?", (patient_id,)
            ).fetchone() is None:
                _bad(f"No patient with id {patient_id}")
            cur = conn.execute(
                """INSERT INTO medical_records
                   (patient_id, provider_id, diagnosis, prescription, record_date)
                   VALUES (?, ?, ?, ?, ?)""",
                (patient_id, provider_id, diagnosis, prescription, record_date),
            )
            conn.commit()
            record_id = cur.lastrowid
        except sqlite3.IntegrityError as exc:
            return jsonify({"error": f"Could not save record: {exc}"}), 400
        finally:
            conn.close()
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "id": record_id,
        "patient_id": patient_id,
        "provider_id": provider_id,
        "diagnosis": diagnosis,
        "prescription": prescription,
        "record_date": record_date,
    }), 201


@medical_records_bp.route("/<int:record_id>", methods=["PUT"])
@require_permission("medical_records", "update")
def update_record(record_id):
    """Amend a record. Doctors only, and only for assigned patients."""
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id, patient_id, diagnosis, prescription, record_date"
            " FROM medical_records WHERE id = ?",
            (record_id,),
        ).fetchone()
        if existing is None:
            return jsonify({"error": f"No record with id {record_id}"}), 404

        # Scope is decided by the patient the record belongs to.
        enforce_patient_scope(existing["patient_id"])

        try:
            diagnosis = (
                (data.get("diagnosis") or "").strip() or None
                if "diagnosis" in data else existing["diagnosis"]
            )
            prescription = (
                (data.get("prescription") or "").strip() or None
                if "prescription" in data else existing["prescription"]
            )
            if diagnosis is None and prescription is None:
                _bad("a record needs at least a diagnosis or a prescription")
            record_date = (
                parse_record_date(data.get("record_date"))
                if "record_date" in data else existing["record_date"]
            )
        except ValidationError as exc:
            return jsonify({"error": str(exc)}), 400

        conn.execute(
            """UPDATE medical_records
               SET diagnosis = ?, prescription = ?, record_date = ?
               WHERE id = ?""",
            (diagnosis, prescription, record_date, record_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        "id": record_id,
        "patient_id": existing["patient_id"],
        "diagnosis": diagnosis,
        "prescription": prescription,
        "record_date": record_date,
    }), 200
