"""Activity and audit logging (task 4.5).

HIPAA's audit requirement is about accountability, not content. The record
has to answer "who reached this patient's information, when, and was it
allowed" for every access, including the ones that were refused. It does not
need the information itself, and keeping it out is the point: an audit table
full of diagnoses is a second copy of the data you are trying to protect.

So nothing here ever writes a diagnosis, a prescription, a message body or a
set of vitals. Every row is: who, what resource, which patient, allowed or
denied. The detail column holds a short reason, never clinical content.

Two things write to this table:

  * require_permission() in permissions.py, which already sits in front of
    every protected route and so sees allowed and denied access alike
  * the authentication routes, for logins and password resets

Reading it back is itself access to patient information, so it goes through
the same permission layer as everything else. There is no admin role in
MedLink and no endpoint that returns the whole log: a patient sees the
accesses to their own record, which is the accounting of disclosures they
are entitled to, and staff see their own activity.
"""

import logging
import sqlite3
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from routes.permissions import (
    DOCTOR,
    NURSE,
    PATIENT,
    enforce_patient_scope,
    get_db,
    require_permission,
    resolve_patient_id,
)

log = logging.getLogger(__name__)

audit_bp = Blueprint("audit", __name__)

ALLOWED = "allowed"
DENIED = "denied"

# Authentication actions, which have no resource or patient attached.
LOGIN_SUCCEEDED = "login_succeeded"
LOGIN_FAILED = "login_failed"
PASSWORD_RESET_REQUESTED = "password_reset_requested"
PASSWORD_RESET_COMPLETED = "password_reset_completed"
PASSWORD_RESET_REJECTED = "password_reset_rejected"
PASSWORD_CHANGED = "password_changed"

MAX_PAGE = 200
DEFAULT_PAGE = 50


def _client_ip():
    """Best effort. Behind a proxy this is the proxy unless it sets the header."""
    try:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr
    except RuntimeError:  # outside a request context
        return None


def record(
    action,
    outcome,
    user_id=None,
    role=None,
    resource=None,
    patient_id=None,
    detail=None,
):
    """Write one audit row.

    Never raises. An audit write that fails must not turn a working request
    into a 500 -- the caller is in the middle of serving someone. A failure
    here is logged to the application log so it is not silent, and the
    request carries on.

    Callers must not pass clinical content in `detail`. It is for short
    reasons such as "assigned scope does not reach patient 7".
    """
    try:
        conn = get_db()
        try:
            conn.execute(
                """
                INSERT INTO audit_log (
                    occurred_at, user_id, role, action,
                    resource, patient_id, outcome, detail, ip_address
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    user_id,
                    role,
                    action,
                    resource,
                    patient_id,
                    outcome,
                    detail,
                    _client_ip(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.error("Audit write failed for action=%s outcome=%s: %s",
                  action, outcome, exc)


def _limit():
    try:
        requested = int(request.args.get("limit", DEFAULT_PAGE))
    except (TypeError, ValueError):
        return DEFAULT_PAGE
    return max(1, min(requested, MAX_PAGE))


def _rows_for_patient(patient_id, limit):
    conn = get_db()
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT a.id, a.occurred_at, a.action, a.resource,
                       a.outcome, a.detail, a.role, u.name AS actor_name
                FROM audit_log a
                LEFT JOIN users u ON u.id = a.user_id
                WHERE a.patient_id = ?
                ORDER BY a.occurred_at DESC, a.id DESC
                LIMIT ?
                """,
                (patient_id, limit),
            )
        ]
    finally:
        conn.close()


def _rows_for_user(user_id, limit):
    conn = get_db()
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, occurred_at, action, resource,
                       patient_id, outcome, detail
                FROM audit_log
                WHERE user_id = ?
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
        ]
    finally:
        conn.close()


@audit_bp.route("/me", methods=["GET"])
@require_permission("audit", "view")
def my_audit_trail():
    """A patient's accounting of disclosures; for staff, their own activity.

    For a patient this answers "who has looked at my record", which is the
    right HIPAA gives them. For a doctor or nurse it answers "what did I
    do", which is the half of the log that is theirs to see. Neither can
    read anyone else's.
    """
    limit = _limit()

    if g.auth["role"] == PATIENT:
        patient_id = g.auth.get("patient_id")
        if patient_id is None:
            return jsonify({
                "error": (
                    "No patient record is linked to this account, so there "
                    "is no access history to show."
                )
            }), 400
        return jsonify({
            "patient_id": patient_id,
            "entries": _rows_for_patient(patient_id, limit),
        }), 200

    return jsonify({
        "user_id": g.auth["user_id"],
        "entries": _rows_for_user(g.auth["user_id"], limit),
    }), 200


@audit_bp.route("/patient/<int:patient_id>", methods=["GET"])
@require_permission("audit", "view")
def patient_audit_trail(patient_id):
    """Access history for one patient.

    The decorator has already enforced the caller's scope against this
    patient, so a doctor or nurse reaches it only for someone they are
    assigned to, and a patient only for themselves.
    """
    return jsonify({
        "patient_id": patient_id,
        "entries": _rows_for_patient(patient_id, _limit()),
    }), 200
