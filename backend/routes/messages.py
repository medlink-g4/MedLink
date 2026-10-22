from flask import Blueprint, request, g, jsonify

from routes.permissions import (
    get_db,
    require_permission,
    resolve_patient_id,
    resolve_provider_id,
    is_assigned,
    PATIENT,
    DOCTOR,
    NURSE,
)

messages_bp = Blueprint("messages", __name__)


def can_communicate(conn, caller_user_id, caller_role, other_user_id):
    """Allow communication only between a patient and their assigned staff."""
    other = conn.execute(
        "SELECT id, role FROM users WHERE id = ?",
        (other_user_id,),
    ).fetchone()

    if not other:
        return False

    other_role = other["role"]

    # Patients can message only doctors or nurses assigned to them.
    if caller_role == PATIENT:
        if other_role not in (DOCTOR, NURSE):
            return False

        patient_id = resolve_patient_id(caller_user_id)
        provider_id = resolve_provider_id(other_user_id)

        if patient_id is None or provider_id is None:
            return False

        return is_assigned(provider_id, patient_id, other_role)

    # Doctors and nurses can message only patients assigned to them.
    if caller_role in (DOCTOR, NURSE):
        if other_role != PATIENT:
            return False

        patient_id = resolve_patient_id(other_user_id)
        provider_id = resolve_provider_id(caller_user_id)

        if patient_id is None or provider_id is None:
            return False

        return is_assigned(provider_id, patient_id, caller_role)

    return False


@messages_bp.route("/contacts", methods=["GET"])
@require_permission("messages", "view")
def get_contacts():
    caller_user_id = g.auth["user_id"]
    caller_role = g.auth["role"]

    conn = get_db()
    try:
        contacts = conn.execute(
            "SELECT id, role FROM users WHERE id != ?",
            (caller_user_id,),
        ).fetchall()

        result = []
        for contact in contacts:
            if can_communicate(
                conn, caller_user_id, caller_role, contact["id"]
            ):
                result.append({
                    "id": contact["id"],
                    "role": contact["role"],
                })

        return jsonify(result), 200
    finally:
        conn.close()
@messages_bp.route("", methods=["GET"])
@require_permission("messages", "view")
def get_messages():
    other_user_id = request.args.get("with_user_id", type=int)

    if not other_user_id:
        return jsonify({"error": "with_user_id is required"}), 400

    caller_user_id = g.auth["user_id"]
    caller_role = g.auth["role"]

    conn = get_db()
    try:
        if not can_communicate(
            conn, caller_user_id, caller_role, other_user_id
        ):
            return jsonify({"error": "You cannot access this conversation"}), 403

        rows = conn.execute(
            """
            SELECT id, sender_id, recipient_id, message, sent_at
            FROM messages
            WHERE (sender_id = ? AND recipient_id = ?)
               OR (sender_id = ? AND recipient_id = ?)
            ORDER BY sent_at ASC, id ASC
            """,
            (
                caller_user_id,
                other_user_id,
                other_user_id,
                caller_user_id,
            ),
        ).fetchall()

        return jsonify([dict(row) for row in rows]), 200
    finally:
        conn.close()


@messages_bp.route("", methods=["POST"])
@require_permission("messages", "create")
def send_message():
    data = request.get_json(silent=True) or {}
    recipient_id = data.get("recipient_id")
    message = data.get("message")

    if not isinstance(recipient_id, int) or isinstance(recipient_id, bool):
        return jsonify({"error": "recipient_id must be an integer"}), 400

    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "message cannot be empty"}), 400

    message = message.strip()
    if len(message) > 5000:
        return jsonify({"error": "message cannot exceed 5000 characters"}), 400

    caller_user_id = g.auth["user_id"]
    caller_role = g.auth["role"]

    conn = get_db()
    try:
        if not can_communicate(
            conn, caller_user_id, caller_role, recipient_id
        ):
            return jsonify({"error": "You cannot message this user"}), 403

        cursor = conn.execute(
            """
            INSERT INTO messages (sender_id, recipient_id, message)
            VALUES (?, ?, ?)
            """,
            (caller_user_id, recipient_id, message),
        )
        conn.commit()

        row = conn.execute(
            """
            SELECT id, sender_id, recipient_id, message, sent_at
            FROM messages
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

        return jsonify(dict(row)), 201
    finally:
        conn.close()