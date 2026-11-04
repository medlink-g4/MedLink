"""Reports for doctors and nurses (task 4.3)."""

from flask import Blueprint, jsonify, request

from routes.permissions import (
    DOCTOR,
    NURSE,
    AuthError,
    decode_token,
    get_db,
    resolve_provider_id,
)

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/", methods=["GET"])
def get_reports():
    # Validate the logged-in user.
    try:
        payload = decode_token(request.headers.get("Authorization"))
    except AuthError as exc:
        return jsonify({"error": str(exc)}), 401

    role = payload["role"]

    # Reports are available only to doctors and nurses.
    if role not in (DOCTOR, NURSE):
        return jsonify({
            "error": "Only doctors and nurses may view reports"
        }), 403

    provider_id = resolve_provider_id(payload["userId"])

    if provider_id is None:
        return jsonify({
            "error": "No provider profile found for this account"
        }), 404

    # Use the same assignment rules as the provider dashboard.
    my_column = (
        "provider_id" if role == DOCTOR else "assisting_nurse_id"
    )

    conn = get_db()

    try:
        # Appointment Report
        appointments = conn.execute(
            f"""
            SELECT a.id, a.patient_id, u.name AS patient_name,
                   a.appointment_time, a.status, a.reason
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE a.{my_column} = ?
              AND a.status != 'cancelled'
            ORDER BY a.appointment_time DESC
            """,
            (provider_id,),
        ).fetchall()

        # Patient Report
        patients = conn.execute(
            f"""
            SELECT DISTINCT p.id AS patient_id,
                   u.name, u.email, p.phone
            FROM appointments a
            JOIN patients p ON a.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE a.{my_column} = ?
              AND a.status != 'cancelled'
            ORDER BY u.name ASC
            """,
            (provider_id,),
        ).fetchall()

        # Medical Records Report
        records = conn.execute(
            f"""
            SELECT mr.id, mr.patient_id,
                   u.name AS patient_name,
                   mr.diagnosis, mr.prescription,
                   mr.record_date
            FROM medical_records mr
            JOIN patients p ON mr.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE mr.patient_id IN (
                SELECT DISTINCT patient_id
                FROM appointments
                WHERE {my_column} = ?
                  AND status != 'cancelled'
            )
            ORDER BY mr.record_date DESC
            """,
            (provider_id,),
        ).fetchall()

    finally:
        conn.close()

    return jsonify({
        "appointments": [dict(row) for row in appointments],
        "patients": [dict(row) for row in patients],
        "medical_records": [dict(row) for row in records]
    }), 200
