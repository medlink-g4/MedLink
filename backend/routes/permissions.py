"""Role-based access control for MedLink (task 1.4).

Three roles: patient, doctor, nurse. There is no admin role.

Three scopes decide *which* rows a role may reach once an action is allowed:

    own       only rows belonging to the caller
    assigned  only patients assigned to this provider
    all       every row

Enforcement is server-side. The role is read from the signed JWT issued by
task 1.3, never from a per-request database lookup, so a tampered or expired
token fails signature or expiry validation before any permission is consulted.

This module does not modify task 1.3. It builds on top of it.
"""

import functools
import logging
import os
import sqlite3
from pathlib import Path

import jwt
from flask import current_app, g, jsonify, request

log = logging.getLogger(__name__)

# Mirrors task 1.3 so both halves validate the same tokens.
JWT_SECRET = os.environ.get("JWT_SECRET", "medlink-development-secret")
JWT_ALGORITHM = "HS256"

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "medlink.db"

PATIENT = "patient"
DOCTOR = "doctor"
NURSE = "nurse"
ROLES = (PATIENT, DOCTOR, NURSE)

OWN = "own"
ASSIGNED = "assigned"
ALL = "all"

# Anything absent from this matrix is denied.
PERMISSIONS = {
    PATIENT: {
        "users": {"view": OWN, "edit": OWN},
        "patients": {"view": OWN, "edit": OWN},
        "medical_records": {"view": OWN},
        "appointments": {"view": OWN, "create": OWN, "cancel": OWN},
        "providers": {"view": ALL},
    },
    DOCTOR: {
        "users": {"view": OWN, "edit": OWN},
        "patients": {"view": ASSIGNED, "edit": ASSIGNED},
        "medical_records": {
            "view": ASSIGNED,
            "create": ASSIGNED,
            "update": ASSIGNED,
            "update_vitals": ASSIGNED,
        },
        "appointments": {
            "view": ASSIGNED,
            "create": ASSIGNED,
            "cancel": ASSIGNED,
            "note": ASSIGNED,
        },
        "providers": {"view": ALL, "edit": OWN},
    },
    NURSE: {
        "users": {"view": OWN, "edit": OWN},
        "patients": {"view": ASSIGNED},
        "medical_records": {"view": ASSIGNED, "update_vitals": ASSIGNED},
        "appointments": {
            "view": ASSIGNED,
            "create": ASSIGNED,
            "cancel": ASSIGNED,
            "note": ASSIGNED,
        },
        "providers": {"view": ALL, "edit": OWN},
    },
}


class AuthError(Exception):
    """Raised for an unusable token. Always surfaces as 401."""


class ForbiddenError(Exception):
    """Raised when a valid caller lacks permission. Always surfaces as 403."""


def db_path():
    """Resolve the database file.

    Configurable so tests can point at a temporary database without touching
    the task 1.3 authentication module.
    """
    configured = None
    try:
        configured = current_app.config.get("MEDLINK_DB")
    except RuntimeError:  # outside an application context
        pass
    return Path(configured or os.environ.get("MEDLINK_DB") or DEFAULT_DB_PATH)


def get_db():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def scope_for(role, resource, action):
    """Return the scope granted for this role/resource/action, else None."""
    return PERMISSIONS.get(role, {}).get(resource, {}).get(action)


def decode_token(auth_header):
    """Validate a bearer token and return its payload.

    Raises AuthError for anything missing, malformed, expired, or tampered
    with. A tampered role claim breaks the HS256 signature, so it is rejected
    here rather than being trusted downstream.
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        raise AuthError("Missing or malformed Authorization header")

    token = auth_header[len("Bearer "):].strip()
    if not token:
        raise AuthError("Empty bearer token")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthError("Token has expired")
    except jwt.InvalidTokenError:
        raise AuthError("Token is invalid")

    if payload.get("role") not in ROLES or payload.get("userId") is None:
        raise AuthError("Token payload is incomplete")

    return payload


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------
# Task 1.3 issues a token carrying only userId, role and exp. It does not
# carry a provider identifier, so provider identity is resolved here from the
# user id. Adding providerId (and patientId) to the token payload is a
# required change to task 1.3; until then this costs one lookup per request
# that needs provider identity. The role itself still comes from the token.


def resolve_provider_id(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM providers WHERE user_id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    return row["id"] if row else None


def resolve_patient_id(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM patients WHERE user_id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


def is_assigned(provider_id, patient_id, role):
    """Is this provider assigned to this patient?

    THIS FUNCTION IS THE ONLY PLACE THAT KNOWS HOW ASSIGNMENT IS DERIVED.
    No route, decorator, or test may depend on the derivation. Sprint 3 adds a
    real patient/provider assignment table; swapping to it must be a change to
    this function body alone, with nothing else in the codebase touched.

    Current derivation, agreed as an interim: a provider is assigned to a
    patient when a non-cancelled appointment links them. Doctors match on
    appointments.provider_id, nurses on appointments.assisting_nurse_id.

    Known limits of deriving it this way, which the assignment table fixes:
    assignment cannot exist before the first appointment is booked, and a
    single past appointment grants access indefinitely.
    """
    if provider_id is None or patient_id is None:
        return False

    column = {DOCTOR: "provider_id", NURSE: "assisting_nurse_id"}.get(role)
    if column is None:
        return False

    conn = get_db()
    try:
        row = conn.execute(
            f"""
            SELECT 1 FROM appointments
            WHERE {column} = ? AND patient_id = ? AND status != 'cancelled'
            LIMIT 1
            """,
            (provider_id, patient_id),
        ).fetchone()
        if row is not None:
            return True

        # Distinguish "not assigned to this patient" from "this nurse is not
        # recorded as assisting on any appointment at all", which is a data
        # problem rather than a permission decision and would otherwise look
        # like a blanket denial.
        if role == NURSE:
            any_rows = conn.execute(
                "SELECT 1 FROM appointments WHERE assisting_nurse_id = ? LIMIT 1",
                (provider_id,),
            ).fetchone()
            if any_rows is None:
                log.warning(
                    "Nurse provider_id=%s has no assisting_nurse_id rows in "
                    "appointments, so no patient can ever resolve as assigned "
                    "for this nurse. This is an appointment data gap, not a "
                    "permission failure.",
                    provider_id,
                )
    finally:
        conn.close()

    return False


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


def _scope_allows_patient(scope, target_patient_id):
    """Does the granted scope reach this patient, for the current caller?"""
    if scope == ALL:
        return True

    if scope == OWN:
        own = g.auth.get("patient_id")
        return own is not None and int(own) == int(target_patient_id)

    if scope == ASSIGNED:
        return is_assigned(
            g.auth.get("provider_id"), target_patient_id, g.auth["role"]
        )

    return False


def enforce_patient_scope(target_patient_id):
    """Check the caller's granted scope against one patient. Raises on denial.

    Routes that resolve a patient themselves call this directly; routes with a
    patient_id URL parameter get it applied automatically by the decorator.
    """
    if not _scope_allows_patient(g.auth["scope"], target_patient_id):
        raise ForbiddenError(
            f"Role {g.auth['role']} with {g.auth['scope']} scope may not reach "
            f"patient {target_patient_id}"
        )


def require_permission(resource, action, patient_arg="patient_id"):
    """Gate a route on one resource/action pair.

    Rejects an unusable token with 401 and an insufficient permission with
    403. When the view takes a patient_id parameter, the granted scope is
    also enforced against that patient automatically.
    """

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            try:
                payload = decode_token(request.headers.get("Authorization"))
            except AuthError as exc:
                return jsonify({"error": str(exc)}), 401

            role = payload["role"]
            scope = scope_for(role, resource, action)
            if scope is None:
                return (
                    jsonify(
                        {
                            "error": f"Role {role} may not {action} {resource}"
                        }
                    ),
                    403,
                )

            user_id = payload["userId"]
            g.auth = {
                "user_id": user_id,
                "role": role,
                "scope": scope,
                "resource": resource,
                "action": action,
                "patient_id": resolve_patient_id(user_id)
                if role == PATIENT
                else None,
                "provider_id": resolve_provider_id(user_id)
                if role in (DOCTOR, NURSE)
                else None,
            }

            if patient_arg in kwargs:
                try:
                    enforce_patient_scope(kwargs[patient_arg])
                except ForbiddenError as exc:
                    return jsonify({"error": str(exc)}), 403

            try:
                return view(*args, **kwargs)
            except ForbiddenError as exc:
                return jsonify({"error": str(exc)}), 403

        return wrapper

    return decorator
