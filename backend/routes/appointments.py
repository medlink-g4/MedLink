"""Appointment scheduling, cancellation and changes (tasks 2.4, 2.5 and 4.2).

Booking rules:

    Slots are 30 minutes, on the half hour, from 08:00 to 17:00. The last
    bookable slot therefore starts at 16:30. A slot in the past cannot be
    booked, and a provider or a patient cannot be double booked.

Changing an appointment (task 4.2, PUT /<id>):

    Only a 'scheduled' appointment that has not started yet can be changed.
    It may be moved to a new slot, given to a different provider, or have its
    reason edited. A move follows the same slot and double-booking rules as a
    new booking, except that the appointment does not clash with itself.
    Cancelling and completed appointments are final.

Who may do what comes from the task 1.4 permission matrix, not from here:

    patient   books, changes and cancels their own appointments
    nurse     books, changes and cancels for patients they are assigned to
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
REASON_MAX = 500
UPDATABLE_FIELDS = ("appointment_time", "provider_id", "reason")

# Appointment rows plus the two names a screen needs to show them. LEFT JOINs
# so a row with a missing detail record is still listed instead of vanishing.
APPOINTMENT_SELECT = """
    SELECT a.*, pu.name AS patient_name, du.name AS provider_name
    FROM appointments a
    LEFT JOIN patients p ON p.id = a.patient_id
    LEFT JOIN users pu ON pu.id = p.user_id
    LEFT JOIN providers d ON d.id = a.provider_id
    LEFT JOIN users du ON du.id = d.user_id
"""


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


def taken(conn, column, who, start, exclude_id=None):
    """Is this provider or patient already booked at this time?

    exclude_id lets an appointment being moved ignore its own current row.
    """
    row = conn.execute(
        f"""SELECT 1 FROM appointments
            WHERE {column} = ? AND appointment_time = ? AND status != 'cancelled'
              AND id IS NOT ?
            LIMIT 1""",
        (who, fmt(start), exclude_id),
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
            if (
                conn.execute(
                    "SELECT 1 FROM providers WHERE id = ?", (provider_id,)
                ).fetchone()
                is None
            ):
                _bad(f"No provider with id {provider_id}")
            if (
                conn.execute(
                    "SELECT 1 FROM patients WHERE id = ?", (patient_id,)
                ).fetchone()
                is None
            ):
                _bad(f"No patient with id {patient_id}")

            if taken(conn, "provider_id", provider_id, start):
                return jsonify(
                    {
                        "error": f"Provider {provider_id} is already booked at {fmt(start)}"
                    }
                ), 409
            if taken(conn, "patient_id", patient_id, start):
                return jsonify(
                    {
                        "error": f"Patient {patient_id} already has an appointment at {fmt(start)}"
                    }
                ), 409

            cur = conn.execute(
                """INSERT INTO appointments
                   (patient_id, provider_id, assisting_nurse_id,
                    appointment_time, end_appointment_time, reason, status, created_by)
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

    return jsonify(
        {
            "id": appointment_id,
            "patient_id": patient_id,
            "provider_id": provider_id,
            "appointment_time": fmt(start),
            "end_appointment_time": fmt(end),
            "status": "scheduled",
        }
    ), 201


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
            return jsonify(
                {"error": f"Appointment {appointment_id} is already cancelled"}
            ), 409
        if appt["status"] != "scheduled":
            # A completed visit is a record of something that happened.
            return jsonify(
                {"error": f"A {appt['status']} appointment cannot be cancelled"}
            ), 409

        conn.execute(
            "UPDATE appointments SET status = 'cancelled' WHERE id = ?",
            (appointment_id,),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"id": appointment_id, "status": "cancelled"}), 200


def _validate_changes(data):
    """Check an update body. Returns {column: value}; raises ValidationError."""
    if not isinstance(data, dict) or not data:
        _bad("Send a JSON object with at least one field to change")
    unknown = sorted(set(data) - set(UPDATABLE_FIELDS))
    if unknown:
        _bad(
            f"Cannot change {unknown}. Changeable fields are {sorted(UPDATABLE_FIELDS)}"
        )

    changes = {}
    if "appointment_time" in data:
        changes["appointment_time"] = parse_slot(data["appointment_time"])
    if "provider_id" in data:
        pid = data["provider_id"]
        if not isinstance(pid, int) or isinstance(pid, bool):
            _bad("provider_id must be a whole number")
        changes["provider_id"] = pid
    if "reason" in data:
        reason = data["reason"]
        if reason is not None:
            if not isinstance(reason, str):
                _bad("reason must be text")
            reason = reason.strip() or None
            if reason is not None and len(reason) > REASON_MAX:
                _bad(f"reason must be {REASON_MAX} characters or fewer")
        changes["reason"] = reason
    return changes


@appointments_bp.route("/<int:appointment_id>", methods=["PUT"])
@require_permission("appointments", "update")
def update(appointment_id):
    """Move an appointment, change its provider, or edit its reason."""
    data = request.get_json(silent=True)
    conn = get_db()
    try:
        # Take the write lock before reading, so two people changing the same
        # slot at once cannot both pass the double-booking check.
        conn.execute("BEGIN IMMEDIATE")
        appt = conn.execute(
            "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
        ).fetchone()
        if appt is None:
            return jsonify({"error": f"No appointment with id {appointment_id}"}), 404

        enforce_patient_scope(appt["patient_id"])

        try:
            changes = _validate_changes(data)
        except ValidationError as exc:
            return jsonify({"error": str(exc)}), 400

        if appt["status"] != "scheduled":
            return jsonify(
                {"error": f"A {appt['status']} appointment cannot be changed"}
            ), 409
        try:
            old_start = datetime.strptime(appt["appointment_time"][:16], TIME_FORMAT)
        except (TypeError, ValueError):
            old_start = None
        if old_start is not None and old_start < datetime.now():
            return jsonify(
                {"error": "That appointment has already started and cannot be changed"}
            ), 409

        new_start = changes.get("appointment_time")
        new_provider = changes.get("provider_id", appt["provider_id"])
        if (
            "provider_id" in changes
            and conn.execute(
                "SELECT 1 FROM providers WHERE id = ?", (new_provider,)
            ).fetchone()
            is None
        ):
            return jsonify({"error": f"No provider with id {new_provider}"}), 400

        moved = (
            new_start is not None and fmt(new_start) != appt["appointment_time"]
        ) or new_provider != appt["provider_id"]
        if moved:
            when = new_start or datetime.strptime(
                appt["appointment_time"][:16], TIME_FORMAT
            )
            if taken(conn, "provider_id", new_provider, when, appointment_id):
                return jsonify(
                    {
                        "error": f"Provider {new_provider} is already booked at {fmt(when)}"
                    }
                ), 409
            if taken(conn, "patient_id", appt["patient_id"], when, appointment_id):
                return jsonify(
                    {
                        "error": f"Patient {appt['patient_id']} already has an appointment at {fmt(when)}"
                    }
                ), 409

        columns = dict(changes)
        if new_start is not None:
            columns["appointment_time"] = fmt(new_start)
            columns["end_appointment_time"] = fmt(slot_end(new_start))
        if columns:
            # Column names come from the fixed whitelist above; only values
            # are bound parameters.
            assignments = ", ".join(f"{c} = ?" for c in columns)
            conn.execute(
                f"UPDATE appointments SET {assignments} WHERE id = ?",
                (*columns.values(), appointment_id),
            )
        conn.commit()
        row = conn.execute(
            APPOINTMENT_SELECT + " WHERE a.id = ?", (appointment_id,)
        ).fetchone()
    except sqlite3.IntegrityError as exc:
        return jsonify({"error": f"Could not change appointment: {exc}"}), 400
    finally:
        conn.close()

    return jsonify(dict(row)), 200


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
        return jsonify(
            {"error": f"date must look like 2026-10-15, got {date_str!r}"}
        ), 400

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
        s for s in slots if s not in booked and datetime.strptime(s, TIME_FORMAT) >= now
    ]
    return jsonify(
        {
            "provider_id": provider_id,
            "date": date_str,
            "slot_minutes": SLOT_MINUTES,
            "available": free,
            "booked": sorted(booked),
        }
    ), 200


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
                APPOINTMENT_SELECT + " ORDER BY a.appointment_time"
            ).fetchall()
        elif scope == OWN:
            rows = conn.execute(
                APPOINTMENT_SELECT
                + " WHERE a.patient_id = ? ORDER BY a.appointment_time",
                (g.auth.get("patient_id"),),
            ).fetchall()
        elif scope == ASSIGNED:
            pid = g.auth.get("provider_id")
            rows = conn.execute(
                APPOINTMENT_SELECT
                + """ WHERE a.provider_id = ? OR a.assisting_nurse_id = ?
                      ORDER BY a.appointment_time""",
                (pid, pid),
            ).fetchall()
        else:
            rows = []
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows]), 200
