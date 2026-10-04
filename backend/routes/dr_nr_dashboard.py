"""
Doctor/nurse dashboard: one combined endpoint for everything the
dashboard needs on load.

Not built on require_permission, because that decorator gates a single
resource/action pair -- this endpoint spans three resources
(appointments, patients, medical_records) in one response. Instead it
reuses the same token decoding and provider-id resolution fromcd
permissions.py, so it enforces identically to every other route:
same JWT validation, same 401s on a bad/missing token.

Only doctor and nurse may view this dashboard -- patients get the
'own' scope on these resources, which is a single-record concept, not
a dashboard of other people's data, so they're explicitly turned away.
"""

from flask import Blueprint, jsonify, request
from routes.permissions import (
    DOCTOR,
    NURSE,
    AuthError,
    decode_token,
    get_db,
    resolve_provider_id,
)

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/", methods=["GET"])
def get_dashboard():
    try:
        payload = decode_token(request.headers.get("Authorization"))
    except AuthError as exc:
        return jsonify({"error": str(exc)}), 401

    role = payload["role"]
    if role not in (DOCTOR, NURSE):
        return jsonify(
            {"error": f"Role {role} may not view the provider dashboard"}
        ), 403

    provider_id = resolve_provider_id(payload["userId"])
    if provider_id is None:
        return jsonify({"error": "No provider profile found for this account"}), 404

    # Doctors are assigned via appointments.provider_id; nurses via
    # appointments.assisting_nurse_id. Same column distinction permissions.py
    # uses in is_assigned().
    my_column = "provider_id" if role == DOCTOR else "assisting_nurse_id"

    conn = get_db()

    appointments = conn.execute(
        f"""
        SELECT a.id, a.appointment_time, a.status, a.patient_id, u.name AS patient_name
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        JOIN users u ON p.user_id = u.id
        WHERE a.{my_column} = ? AND a.status != 'cancelled'
        ORDER BY a.appointment_time ASC
    """,
        (provider_id,),
    ).fetchall()

    patients = conn.execute(
        f"""
        SELECT DISTINCT p.id, u.name, u.email, p.phone
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        JOIN users u ON p.user_id = u.id
        WHERE a.{my_column} = ? AND a.status != 'cancelled'
        ORDER BY u.name ASC
    """,
        (provider_id,),
    ).fetchall()

    # Scoped to assigned PATIENTS, not to records this provider personally
    # wrote -- a nurse assisting on a visit should see the doctor's notes
    # for that same patient, not just her own entries.
    records = conn.execute(
        f"""
        SELECT mr.id, mr.patient_id, u.name AS patient_name,
               mr.diagnosis, mr.prescription, mr.record_date
        FROM medical_records mr
        JOIN patients p ON mr.patient_id = p.id
        JOIN users u ON p.user_id = u.id
        WHERE mr.patient_id IN (
            SELECT DISTINCT a.patient_id FROM appointments a
            WHERE a.{my_column} = ? AND a.status != 'cancelled'
        )
        ORDER BY mr.record_date DESC
        LIMIT 10
    """,
        (provider_id,),
    ).fetchall()

    conn.close()

    return jsonify(
        {
            "appointments": [dict(r) for r in appointments],
            "patients": [dict(r) for r in patients],
            "medical_records": [dict(r) for r in records],
        }
    )
