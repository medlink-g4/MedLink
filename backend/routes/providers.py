"""Provider directory, used by the booking form to list who can be booked.

    GET /api/providers                   doctors, A to Z
    GET /api/providers?role_type=nurse   nurses instead

Gated on the existing providers:view permission, which every role holds, so
a patient can pick a doctor. The response is deliberately small: id, name,
specialty and role type. Emails and account details are never included.
"""

from flask import Blueprint, jsonify, request
from routes.permissions import get_db, require_permission

providers_bp = Blueprint("providers", __name__)

ROLE_TYPES = ("doctor", "nurse")


@providers_bp.route("", methods=["GET"])
@providers_bp.route("/", methods=["GET"])
@require_permission("providers", "view")
def list_providers():
    role_type = request.args.get("role_type", "doctor")
    if role_type not in ROLE_TYPES:
        return jsonify(
            {"error": f"role_type must be one of {list(ROLE_TYPES)}, got {role_type!r}"}
        ), 400

    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT p.id, u.name, p.specialty, p.role_type
               FROM providers p
               JOIN users u ON u.id = p.user_id
               WHERE p.role_type = ?
               ORDER BY u.name COLLATE NOCASE, p.id""",
            (role_type,),
        ).fetchall()
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows]), 200
