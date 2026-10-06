"""Appointment scheduling and cancellation (tasks 2.4 and 2.5).

Booking rules:

    Slots are 30 minutes, on the half hour, from 08:00 to 17:00. The last
    bookable slot therefore starts at 16:30. A slot in the past cannot be
    booked, and a provider or a patient cannot be double booked.

Who may do what comes from the task 1.4 permission matrix, not from here:

    patient   books and cancels their own appointments
    nurse     books and cancels for patients they are assigned to
    doctor    view only

Every route is gated by require_permission. Routes that take the patient from
the request body rather than the URL call enforce_patient_scope themselves,
which raises ForbiddenError and surfaces as 403.
"""

import sqlite3
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from routes.permissions import (
    ALL,
    ASSIGNED,
    OWN,
    enforce_patient_scope,
    get_db,
    require_permission,
)

appointments_bp = Blueprint("appointments", __name__)

SLOT_MINUTES = 30
DAY_START_HOUR = 8
DAY_END_HOUR = 17  # exclusive: the last slot runs 16:30 to 17:00
TIME_FORMAT = "%Y-%m-%dT%H:%M"


class ValidationError(Exception):
    """Bad input from the caller. Surfaces as 400."""


def parse_slot(raw):
    """Parse an ISO start time and check it is a bookable slot."""
    if not raw:
        return _bad("appointment_time is required")
    try:
        start = datetime.strptime(str(raw)[:16], TIME_FORMAT)
    except ValueError:
        return _bad(f"appointment_time must look like 2026-10-15T09:30, got {raw!r}")

    if start.minute % SLOT_MINUTES or start.second:
        _bad(
            f"Appointments start on the hour or half hour; {start.strftime('%H:%M')} "
            "is not a valid slot"
        )
    if start.hour < DAY_START_HOUR or start >= start.replace(
        hour=DAY_END_HOUR, minute=0
    ):
        _bad(
            f"Appointments run from {DAY_START_HOUR:02d}:00 to {DAY_END_HOUR:02d}:00; "
            f"{start.strftime('%H:%M')} is outside clinic hours"
        )
    if start < datetime.now():
        _bad("Cannot book an appointment in the past")
    return start


def _bad(message):
    raise ValidationError(message)


def slot_end(start):
    return start + timedelta(minutes=SLOT_MINUTES)


def fmt(dt):
    return dt.strftime(TIME_FORMAT)


def day_slots(date_str):
    """Every bookable start time on one date, as strings."""
    day = datetime.strptime(date_str, "%Y-%m-%d")
    slots, cur = [], day.replace(hour=DAY_START_HOUR, minute=0)
    end = day.replace(hour=DAY_END_HOUR, minute=0)
    while cur < end:
        slots.append(fmt(cur))
        cur += timedelta(minutes=SLOT_MINUTES)
    return slots


def taken(conn, column, who, start):
    """Is this provider or patient already booked at this time?"""
    row = conn.execute(
        f"""SELECT 1 FROM appointments
            WHERE {column} = ? AND appointment_time = ? AND status != 'cancelled'
            LIMIT 1""",
        (who, fmt(start)),
    ).fetchone()
    return row is not None


@appointments_bp.route("", methods=["POST"])
@appointments_bp.route("/", methods=["POST"])
@require_permission("appointments", "create")
def book():
    data = request.get_json(silent=True) or {}
    try:
        patient_id = data.get("patient_id")
        provider_id = data.get("provider_id")
        if patient_id is None or provider_id is None:
            _bad("patient_id and provider_id are required")

        # Whose appointment this is decides whether the caller may book it.
        enforce_patient_scope(patient_id)

        start = parse_slot(data.get("appointment_time"))
        end = slot_end(start)

        conn = get_db()
        try:
            if conn.execute(
                "SELECT 1 FROM providers WHERE id = ?", (provider_id,)
            ).fetchone() is None:
                _bad(f"No provider with id {provider_id}")
            if conn.execute(
                "SELECT 1 FROM patients WHERE id = ?", (patient_id,)
            ).fetchone() is None:
                _bad(f"No patient with id {patient_id}")

            if taken(conn, "provider_id", provider_id, start):
                return jsonify({
                    "error": f"Provider {provider_id} is already booked at {fmt(start)}"
                }), 409
            if taken(conn, "patient_id", patient_id, start):
                return jsonify({
                    "error": f"Patient {patient_id} already has an appointment at {fmt(start)}"
                }), 409

            cur = conn.execute(
                """INSERT INTO appointments
                   (patient_id, provider_id, assisting_nurse_id,
                    appointment_time, end_time, reason, status, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?)""",
                (
                    patient_id,
                    provider_id,
                    data.get("assisting_nurse_id"),
                    fmt(start),
                    fmt(end),
                    data.get("reason"),
                    g.auth["user_id"],
                ),
            )
            conn.commit()
            appointment_id = cur.lastrowid
        except sqlite3.IntegrityError as exc:
            return jsonify({"error": f"Could not book: {exc}"}), 400
        finally:
            conn.close()
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "id": appointment_id,
        "patient_id": patient_id,
        "provider_id": provider_id,
        "appointment_time": fmt(start),
        "end_time": fmt(end),
        "status": "scheduled",
    }), 201


@appointments_bp.route("/<int:appointment_id>/cancel", methods=["POST"])
@require_permission("appointments", "cancel")
def cancel(appointment_id):
    conn = get_db()
    try:
        appt = conn.execute(
            "SELECT id, patient_id, status FROM appointments WHERE id = ?",
            (appointment_id,),
        ).fetchone()
        if appt is None:
            return jsonify({"error": f"No appointment with id {appointment_id}"}), 404

        # Cancelling is scoped to the patient the appointment belongs to.
        enforce_patient_scope(appt["patient_id"])

        if appt["status"] == "cancelled":
            return jsonify({
                "error": f"Appointment {appointment_id} is already cancelled"
            }), 409

        conn.execute(
            "UPDATE appointments SET status = 'cancelled' WHERE id = ?",
            (appointment_id,),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"id": appointment_id, "status": "cancelled"}), 200


@appointments_bp.route("/availability", methods=["GET"])
@require_permission("providers", "view")
def availability():
    """Free slots for one provider on one date.

    Gated on viewing providers rather than appointments, because this says
    when a provider is free, not who they are seeing. Every role may read it,
    which is what lets a patient pick a time.
    """
    provider_id = request.args.get("provider_id", type=int)
    date_str = request.args.get("date")
    if provider_id is None or not date_str:
        return jsonify({"error": "provider_id and date are required"}), 400
    try:
        slots = day_slots(date_str)
    except ValueError:
        return jsonify({"error": f"date must look like 2026-10-15, got {date_str!r}"}), 400

    conn = get_db()
    try:
        booked = {
            r["appointment_time"]
            for r in conn.execute(
                """SELECT appointment_time FROM appointments
                   WHERE provider_id = ? AND status != 'cancelled'
                     AND appointment_time LIKE ?""",
                (provider_id, f"{date_str}T%"),
            )
        }
    finally:
        conn.close()

    now = datetime.now()
    free = [
        s for s in slots
        if s not in booked and datetime.strptime(s, TIME_FORMAT) >= now
    ]
    return jsonify({
        "provider_id": provider_id,
        "date": date_str,
        "slot_minutes": SLOT_MINUTES,
        "available": free,
        "booked": sorted(booked),
    }), 200


@appointments_bp.route("", methods=["GET"])
@appointments_bp.route("/", methods=["GET"])
@require_permission("appointments", "view")
def list_appointments():
    """Appointments the caller is allowed to see, narrowed by their scope."""
    scope = g.auth["scope"]
    conn = get_db()
    try:
        if scope == ALL:
            rows = conn.execute(
                "SELECT * FROM appointments ORDER BY appointment_time"
            ).fetchall()
        elif scope == OWN:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE patient_id = ? ORDER BY appointment_time",
                (g.auth.get("patient_id"),),
            ).fetchall()
        elif scope == ASSIGNED:
            pid = g.auth.get("provider_id")
            rows = conn.execute(
                """SELECT * FROM appointments
                   WHERE provider_id = ? OR assisting_nurse_id = ?
                   ORDER BY appointment_time""",
                (pid, pid),
            ).fetchall()
        else:
            rows = []
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows]), 200
