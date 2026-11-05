"""Self-service password reset (task 4.4).

MedLink has no admin role, so there is nobody to telephone when a password is
forgotten. This is the replacement for that: the account holder proves they
control the registered address, and sets a new password themselves.

The flow is the ordinary one:

    POST /api/auth/password-reset/request   {email}
    POST /api/auth/password-reset/confirm   {token, new_password}

and, for someone who is already signed in and simply wants a new password:

    POST /api/auth/password-change          {current_password, new_password}

Four things matter more than the happy path, and each is tested:

  * The request endpoint answers identically whether or not the address is
    registered. If it said "no such account" it would be a way to find out
    who has one, and for a hospital the membership list is itself private.
  * Only a hash of the token is stored, for the same reason users holds a
    password_hash. A copy of this table cannot be used to reset anybody.
  * A token works once and expires. Using one, or changing the password by
    any other route, invalidates every other outstanding token for that
    account, so an attacker who requested one earlier cannot still use it.
  * Every step is written to the audit log from task 4.5.

Delivery. There is no mail server in this project, and emailing the token is
out of scope for the sprint, so the token is written to the application log
for the team to copy during development. Setting MEDLINK_SHOW_RESET_TOKEN=1
also returns it in the response, which is convenient for local work and for
the automated tests. It must stay off anywhere real: with it on, anyone who
can name an address can reset that account. The code refuses to leak it by
default rather than relying on the deployment to remember.
"""

import hashlib
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from routes.audit import (
    ALLOWED,
    DENIED,
    PASSWORD_CHANGED,
    PASSWORD_RESET_COMPLETED,
    PASSWORD_RESET_REJECTED,
    PASSWORD_RESET_REQUESTED,
    record,
)
from routes.permissions import AuthError, decode_token, get_db

log = logging.getLogger(__name__)

password_reset_bp = Blueprint("password_reset", __name__)

TOKEN_TTL_MINUTES = 30
MIN_PASSWORD_LENGTH = 8

# Development convenience only. See the module docstring.
SHOW_TOKEN = os.environ.get("MEDLINK_SHOW_RESET_TOKEN") == "1"

# Deliberately identical for a known and an unknown address.
GENERIC_REQUEST_REPLY = (
    "If that email address has an account, a password reset link has been "
    "sent to it."
)


def hash_token(token):
    """Tokens are high-entropy random strings, so a plain SHA-256 is right.

    A slow hash such as the one guarding passwords exists to survive a
    dictionary attack on something a human chose. There is no dictionary for
    32 random bytes, and the lookup happens on every confirm.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_problem(password):
    """Return why this password is unacceptable, or None if it is fine."""
    if not isinstance(password, str) or not password:
        return "A new password is required"
    if len(password) < MIN_PASSWORD_LENGTH:
        return (
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    return None


def invalidate_outstanding_tokens(conn, user_id, now):
    """Spend every unused token for this account.

    Called whenever the password changes, by any route. Without it, a reset
    link requested last week still works after today's change.
    """
    conn.execute(
        """
        UPDATE password_reset_tokens
        SET used_at = ?
        WHERE user_id = ? AND used_at IS NULL
        """,
        (now, user_id),
    )


@password_reset_bp.route("/password-reset/request", methods=["POST"])
def request_reset():
    data = request.get_json(silent=True) or {}
    email = data.get("email")

    if not isinstance(email, str) or not email.strip():
        return jsonify({"error": "Email is required"}), 400

    email = email.strip().lower()
    now = datetime.now(timezone.utc)

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, role FROM users WHERE email = ?", (email,)
        ).fetchone()

        if user is None:
            # Same reply, same status, no row written. The only difference an
            # outsider can observe is timing, which this does not try to hide.
            record(
                PASSWORD_RESET_REQUESTED,
                DENIED,
                detail="no account for the submitted address",
            )
            return jsonify({"message": GENERIC_REQUEST_REPLY}), 200

        token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(minutes=TOKEN_TTL_MINUTES)

        # A fresh request supersedes anything still outstanding.
        invalidate_outstanding_tokens(conn, user["id"], now.isoformat())

        conn.execute(
            """
            INSERT INTO password_reset_tokens
                (user_id, token_hash, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                user["id"],
                hash_token(token),
                now.isoformat(timespec="seconds"),
                expires_at.isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        log.error("Password reset request failed: %s", exc)
        return jsonify({"error": "Could not process the request"}), 500
    finally:
        conn.close()

    record(
        PASSWORD_RESET_REQUESTED,
        ALLOWED,
        user_id=user["id"],
        role=user["role"],
        detail=f"token valid for {TOKEN_TTL_MINUTES} minutes",
    )

    # Stands in for the email this project does not send.
    log.info(
        "Password reset token for user_id=%s (expires %s): %s",
        user["id"],
        expires_at.isoformat(timespec="seconds"),
        token,
    )

    body = {"message": GENERIC_REQUEST_REPLY}
    if SHOW_TOKEN:
        body["reset_token"] = token
        body["expires_at"] = expires_at.isoformat(timespec="seconds")
        body["warning"] = (
            "MEDLINK_SHOW_RESET_TOKEN is set. This is for local development "
            "only and must never be enabled anywhere real."
        )
    return jsonify(body), 200


@password_reset_bp.route("/password-reset/confirm", methods=["POST"])
def confirm_reset():
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    new_password = data.get("new_password")

    if not isinstance(token, str) or not token.strip():
        return jsonify({"error": "A reset token is required"}), 400

    problem = password_problem(new_password)
    if problem:
        return jsonify({"error": problem}), 400

    now = datetime.now(timezone.utc)

    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT t.id, t.user_id, t.expires_at, t.used_at, u.role
            FROM password_reset_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token_hash = ?
            """,
            (hash_token(token.strip()),),
        ).fetchone()

        # Unknown, already spent and expired are one answer on purpose. Each
        # is the same thing to the person holding the link -- it does not
        # work -- and telling them which would confirm a token once existed.
        if row is None or row["used_at"] is not None:
            record(
                PASSWORD_RESET_REJECTED,
                DENIED,
                detail="token is unknown or has already been used",
            )
            return jsonify({"error": "This reset link is no longer valid"}), 400

        if datetime.fromisoformat(row["expires_at"]) <= now:
            record(
                PASSWORD_RESET_REJECTED,
                DENIED,
                user_id=row["user_id"],
                role=row["role"],
                detail="token expired",
            )
            return jsonify({"error": "This reset link is no longer valid"}), 400

        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), row["user_id"]),
        )
        invalidate_outstanding_tokens(
            conn, row["user_id"], now.isoformat(timespec="seconds")
        )
        conn.commit()
    except sqlite3.Error as exc:
        log.error("Password reset confirmation failed: %s", exc)
        return jsonify({"error": "Could not reset the password"}), 500
    finally:
        conn.close()

    record(
        PASSWORD_RESET_COMPLETED,
        ALLOWED,
        user_id=row["user_id"],
        role=row["role"],
        detail="password changed via reset link",
    )

    return jsonify({
        "message": "Your password has been changed. You can now log in."
    }), 200


@password_reset_bp.route("/password-change", methods=["POST"])
def change_password():
    """Change the password of the signed-in account.

    The current password is required even though the caller already holds a
    valid token, because a token can be left behind on a shared machine and
    the point of this endpoint is to prove it is still the account holder.
    """
    try:
        payload = decode_token(request.headers.get("Authorization"))
    except AuthError as exc:
        record(PASSWORD_CHANGED, DENIED, detail=str(exc))
        return jsonify({"error": str(exc)}), 401

    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password")
    new_password = data.get("new_password")

    if not isinstance(current_password, str) or not current_password:
        return jsonify({"error": "Your current password is required"}), 400

    problem = password_problem(new_password)
    if problem:
        return jsonify({"error": problem}), 400

    user_id = payload["userId"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, password_hash, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if user is None or not check_password_hash(
            user["password_hash"], current_password
        ):
            record(
                PASSWORD_CHANGED,
                DENIED,
                user_id=user_id,
                role=payload.get("role"),
                detail="current password did not match",
            )
            return jsonify({"error": "Your current password is incorrect"}), 403

        if check_password_hash(user["password_hash"], new_password):
            return jsonify({
                "error": "The new password must be different from the current one"
            }), 400

        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(new_password), user_id),
        )
        invalidate_outstanding_tokens(conn, user_id, now)
        conn.commit()
    except sqlite3.Error as exc:
        log.error("Password change failed: %s", exc)
        return jsonify({"error": "Could not change the password"}), 500
    finally:
        conn.close()

    record(
        PASSWORD_CHANGED,
        ALLOWED,
        user_id=user_id,
        role=user["role"],
        detail="changed by the account holder while signed in",
    )

    return jsonify({"message": "Your password has been changed."}), 200
