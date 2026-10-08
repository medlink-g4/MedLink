import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = Path(__file__).resolve().parents[2] / "medlink.db"
JWT_SECRET = os.environ.get("JWT_SECRET", "medlink-development-secret")
auth_bp = Blueprint("auth", __name__)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body is required"}), 400

    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    role = data.get("role")

    if not name or not email or not password or not role:
        return jsonify({"error": "Name, email, password, and role are required"}), 400

    email = email.strip().lower()
    role = role.strip().lower()

    allowed_roles = ["patient", "nurse", "doctor"]

    if role not in allowed_roles:
        return jsonify({"error": "Invalid role"}), 400

    password_hash = generate_password_hash(password)

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO users (name, email, password_hash, role)
            VALUES (?, ?, ?, ?)
            """,
            (name, email, password_hash, role),
        )
        user_id = cursor.lastrowid

        # Registration also creates the role-specific detail row.
        # Without this, resolve_patient_id()/resolve_provider_id() in
        # permissions.py return None for a brand-new user, and every
        # scoped permission check fails -- even for that user's own data.
        if role == "patient":
            cursor.execute(
                """
                INSERT INTO patients (user_id, date_of_birth, phone, insurance_info)
                VALUES (?, NULL, NULL, NULL)
                """,
                (user_id,),
            )
        else:  # 'doctor' or 'nurse'
            can_prescribe = 1 if role == "doctor" else 0
            cursor.execute(
                """
                INSERT INTO providers (user_id, role_type, specialty, can_prescribe)
                VALUES (?, ?, NULL, ?)
                """,
                (user_id, role, can_prescribe),
            )

        conn.commit()

        return jsonify(
            {"message": "User registered successfully", "userId": user_id, "role": role}
        ), 201

    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({"error": "Email already exists"}), 409

    finally:
        conn.close()


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body is required"}), 400

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    email = email.strip().lower()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, name, email, password_hash, role
        FROM users
        WHERE email = ?
        """,
        (email,),
    )

    user = cursor.fetchone()
    conn.close()

    if user is None:
        return jsonify({"error": "Invalid email or password"}), 401

    if not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    payload = {
        "userId": user["id"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=2),
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    return jsonify(
        {
            "message": "Login successful",
            "token": token,
            "userId": user["id"],
            "role": user["role"],
        }
    ), 200
