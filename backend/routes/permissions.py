"""Role-based access control for MedLink.

Roles are patient, doctor and nurse. There is no admin role; see
docs/roles-and-permissions.md for what replaces it.

This module consumes the JWT issued by routes/auth.py. That token is signed
HS256 with JWT_SECRET and carries:

    {"userId": <int>, "role": <str>, "exp": <unix timestamp>}

Nothing here issues tokens. Login stays the single place that does that.

Usage:

    from routes.permissions import require_auth, require_role, require_permission

    @bp.route("/records", methods=["POST"])
    @require_permission("records:write")
    def create_record():
        g.current_user["userId"]  # set by the decorator
"""

import os
from functools import wraps

import jwt
from flask import g, jsonify, request

# Must match routes/auth.py or tokens will not validate across the two modules.
JWT_SECRET = os.environ.get("JWT_SECRET", "medlink-development-secret")
JWT_ALGORITHM = "HS256"

PATIENT = "patient"
NURSE = "nurse"
DOCTOR = "doctor"

ROLES = (PATIENT, NURSE, DOCTOR)

# What each role may do. Keeping this as data rather than scattered role
# checks means a permission change is a one-line edit here.
#
#   appointments:book        create an appointment for yourself
#   appointments:read:own    see your own appointments
#   appointments:read:all    see any patient's appointments
#   appointments:manage      reschedule or cancel any appointment
#   records:read:own         see your own medical records
#   records:read:all         see any patient's medical records
#   records:write            add a diagnosis or clinical note
#   prescriptions:write      add a prescription
#   profile:read:own         see your own profile
PERMISSIONS = {
    PATIENT: {
        "appointments:book",
        "appointments:read:own",
        "records:read:own",
        "profile:read:own",
    },
    NURSE: {
        "appointments:read:all",
        "appointments:manage",
        "records:read:all",
        "records:write",
        "profile:read:own",
    },
    DOCTOR: {
        "appointments:read:all",
        "appointments:manage",
        "records:read:all",
        "records:write",
        "prescriptions:write",
        "profile:read:own",
    },
}


class TokenError(Exception):
    """Raised when a bearer token is absent, malformed or expired."""

    def __init__(self, message, status=401):
        super().__init__(message)
        self.message = message
        self.status = status


def extract_token(req):
    """Pull the bearer token out of the Authorization header."""
    header = req.headers.get("Authorization", "")

    if not header:
        raise TokenError("Authorization header is required")

    parts = header.split()

    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise TokenError("Authorization header must be 'Bearer <token>'")

    return parts[1]


def decode_token(token):
    """Verify a token's signature and expiry and return its payload."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise TokenError("Token has expired")
    except jwt.InvalidTokenError:
        raise TokenError("Token is invalid")

    if "userId" not in payload or "role" not in payload:
        raise TokenError("Token payload is missing userId or role")

    if payload["role"] not in ROLES:
        raise TokenError("Token carries an unrecognised role", status=403)

    return payload


def authenticate():
    """Resolve the caller from the request and stash them on flask.g."""
    payload = decode_token(extract_token(request))
    g.current_user = payload
    return payload


def current_user():
    """The authenticated caller, or None outside an authenticated request."""
    return getattr(g, "current_user", None)


def has_permission(role, permission):
    return permission in PERMISSIONS.get(role, set())


def require_auth(view):
    """Reject the request unless it carries a valid token."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            authenticate()
        except TokenError as exc:
            return jsonify({"error": exc.message}), exc.status
        return view(*args, **kwargs)

    return wrapper


def require_role(*allowed_roles):
    """Reject the request unless the caller holds one of these roles."""
    for role in allowed_roles:
        if role not in ROLES:
            raise ValueError("Unknown role: {}".format(role))

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            try:
                payload = authenticate()
            except TokenError as exc:
                return jsonify({"error": exc.message}), exc.status

            if payload["role"] not in allowed_roles:
                return jsonify({
                    "error": "This action requires one of: {}".format(
                        ", ".join(sorted(allowed_roles))
                    )
                }), 403

            return view(*args, **kwargs)

        return wrapper

    return decorator


def require_permission(permission):
    """Reject the request unless the caller's role grants this permission."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            try:
                payload = authenticate()
            except TokenError as exc:
                return jsonify({"error": exc.message}), exc.status

            if not has_permission(payload["role"], permission):
                return jsonify({
                    "error": "Your role does not allow: {}".format(permission)
                }), 403

            return view(*args, **kwargs)

        return wrapper

    return decorator


def owns_or_can_read_all(patient_user_id):
    """True if the caller may read this patient's data.

    Patients reach their own data only. Clinical staff reach any patient's.
    Call this inside a view after require_auth to enforce the 'own' half of
    the read permissions, which a decorator cannot check on its own.
    """
    user = current_user()

    if user is None:
        return False

    if has_permission(user["role"], "records:read:all"):
        return True

    return user["userId"] == patient_user_id
