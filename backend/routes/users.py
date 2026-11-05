"""
Users blueprint -- Sprint 4, task 4.1 (user profile management).

    GET  /api/users/me             view my profile              users:view
    PUT  /api/users/me             update my profile            users:edit
    POST /api/users/me/password    change my password           users:edit

Every role (patient, doctor, nurse) may view and edit their OWN account, so
these routes never take a user id: the account is always the one the token
belongs to. That makes it impossible to reach someone else's profile by
changing a number in the URL.

What a profile contains:

    everyone   name, email (role is shown but cannot be changed)
    patient    + date of birth, phone, insurance   (same rules as patients.py)
    provider   + specialty                         (doctor or nurse)

The PUT is a partial update: send only the fields you want to change. Fields
that do not belong to the caller's role are refused, not ignored, so a typo
or a role mix-up is visible instead of silently doing nothing.

Login tokens carry only the user id and role, so changing an email or a
password does not invalidate a token that was already issued. That is a
limitation of the current login design, not of this file.
"""

import re
import sqlite3

from flask import Blueprint, g, jsonify, request
from routes.patients import EDITABLE_FIELDS as PATIENT_FIELDS
from routes.patients import _validate_patient_update
from routes.permissions import PATIENT, get_db, require_permission
from werkzeug.security import check_password_hash, generate_password_hash

users_bp = Blueprint("users", __name__)

USER_FIELDS = ("name", "email")
PROVIDER_FIELDS = ("specialty",)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NAME_MAX = 100
EMAIL_MAX = 254
SPECIALTY_MAX = 100
PASSWORD_MIN = 8
PASSWORD_MAX = 128  # stops someone making the server hash a megabyte string


def _conn():
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _error(message, status=400):
    return jsonify({"error": message}), status


# ---------------------------------------------------------------------------
# Reading a profile
# ---------------------------------------------------------------------------


def _load_profile(conn, user_id, role):
    """The caller's account plus the role-specific details, or None."""
    user = conn.execute(
        "SELECT id, name, email, role FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if user is None:
        return None
    profile = dict(user)

    if role == PATIENT:
        row = conn.execute(
            """SELECT id, date_of_birth, phone, insurance_info
               FROM patients WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        profile["patient"] = dict(row) if row else None
    else:
        row = conn.execute(
            """SELECT id, role_type, specialty, can_prescribe
               FROM providers WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        profile["provider"] = dict(row) if row else None
    return profile


@users_bp.route("/me", methods=["GET"])
@require_permission("users", "view")
def get_me():
    conn = _conn()
    try:
        profile = _load_profile(conn, g.auth["user_id"], g.auth["role"])
    finally:
        conn.close()
    if profile is None:
        return _error("Account not found", 404)
    return jsonify(profile)


# ---------------------------------------------------------------------------
# Updating a profile
# ---------------------------------------------------------------------------


def _validate_profile_update(data, role):
    """Return (user_fields, detail_fields, error). On error the first two are None."""
    if not isinstance(data, dict) or not data:
        return None, None, "Send a JSON object with at least one field to update"

    detail_allowed = PATIENT_FIELDS if role == PATIENT else PROVIDER_FIELDS
    allowed = set(USER_FIELDS) | set(detail_allowed)
    unknown = sorted(set(data) - allowed)
    if unknown:
        return (
            None,
            None,
            (
                f"Cannot edit: {unknown}. Editable fields for a {role} are {sorted(allowed)}"
            ),
        )

    user_fields = {}
    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not name.strip():
            return None, None, "name is required"
        name = name.strip()
        if len(name) > NAME_MAX:
            return None, None, f"name must be {NAME_MAX} characters or fewer"
        user_fields["name"] = name

    if "email" in data:
        email = data["email"]
        if not isinstance(email, str) or not email.strip():
            return None, None, "email is required"
        email = email.strip().lower()  # registration lowercases too
        if len(email) > EMAIL_MAX or not EMAIL_RE.match(email):
            return None, None, "email must look like name@example.com"
        user_fields["email"] = email

    detail_fields = {}
    if role == PATIENT:
        patient_part = {k: v for k, v in data.items() if k in PATIENT_FIELDS}
        if patient_part:
            detail_fields, problem = _validate_patient_update(patient_part)
            if problem:
                return None, None, problem
    elif "specialty" in data:
        specialty = data["specialty"]
        if specialty is None:
            detail_fields["specialty"] = None
        elif not isinstance(specialty, str):
            return None, None, "specialty must be text"
        else:
            specialty = specialty.strip()
            if len(specialty) > SPECIALTY_MAX:
                return (
                    None,
                    None,
                    f"specialty must be {SPECIALTY_MAX} characters or fewer",
                )
            detail_fields["specialty"] = specialty or None

    return user_fields, detail_fields, None


def _set_clause(fields):
    # Column names come from the fixed field whitelists checked in validation;
    # only the values are bound parameters.
    return ", ".join(f"{column} = ?" for column in fields)


@users_bp.route("/me", methods=["PUT"])
@require_permission("users", "edit")
def update_me():
    user_id, role = g.auth["user_id"], g.auth["role"]
    user_fields, detail_fields, problem = _validate_profile_update(
        request.get_json(silent=True), role
    )
    if problem:
        return _error(problem)

    conn = _conn()
    try:
        # One transaction: either every change is saved or none is.
        try:
            if user_fields:
                conn.execute(
                    f"UPDATE users SET {_set_clause(user_fields)} WHERE id = ?",
                    (*user_fields.values(), user_id),
                )
            if detail_fields:
                table = "patients" if role == PATIENT else "providers"
                conn.execute(
                    f"UPDATE {table} SET {_set_clause(detail_fields)} WHERE user_id = ?",
                    (*detail_fields.values(), user_id),
                )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            return _error("That email is already in use", 409)
        profile = _load_profile(conn, user_id, role)
    finally:
        conn.close()
    if profile is None:
        return _error("Account not found", 404)
    return jsonify(profile)


# ---------------------------------------------------------------------------
# Changing the password
# ---------------------------------------------------------------------------


@users_bp.route("/me/password", methods=["POST"])
@require_permission("users", "edit")
def change_password():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Send current_password and new_password")
    current, new = data.get("current_password"), data.get("new_password")
    if not isinstance(current, str) or not current:
        return _error("current_password is required")
    if not isinstance(new, str) or not new:
        return _error("new_password is required")
    if len(new) < PASSWORD_MIN:
        return _error(f"new_password must be at least {PASSWORD_MIN} characters")
    if len(new) > PASSWORD_MAX:
        return _error(f"new_password must be {PASSWORD_MAX} characters or fewer")
    if new == current:
        return _error("new_password must be different from the current password")

    conn = _conn()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (g.auth["user_id"],)
        ).fetchone()
        if row is None:
            return _error("Account not found", 404)
        # 403, not 401: the token is fine, the extra proof of identity is wrong,
        # and the frontend treats 401 as "session expired".
        if not check_password_hash(row["password_hash"], current):
            return _error("Current password is incorrect", 403)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new), g.auth["user_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"message": "Password changed"})
