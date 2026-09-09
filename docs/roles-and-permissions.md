# Roles and permissions

MedLink has three roles: **patient**, **doctor**, **nurse**. The admin role was
removed to keep the base application small. This document records what each
role may do and where the responsibilities admin used to hold have gone.

Implementation lives in `backend/routes/permissions.py`. Tests are in
`backend/tests/test_permissions.py`.

## Permission matrix

| Permission | Patient | Nurse | Doctor |
|---|:--:|:--:|:--:|
| `appointments:book` (book for yourself) | yes | no | no |
| `appointments:read:own` | yes | no | no |
| `appointments:read:all` | no | yes | yes |
| `appointments:manage` (reschedule, cancel any) | no | yes | yes |
| `records:read:own` | yes | no | no |
| `records:read:all` | no | yes | yes |
| `records:write` (diagnosis, clinical note) | no | yes | yes |
| `prescriptions:write` | no | no | yes |
| `profile:read:own` | yes | yes | yes |

Prescribing is the one clinical action that separates doctor from nurse. This
matches the `providers.can_prescribe` column already in the schema.

Patients hold no write permission over clinical data. A patient books and
cancels their own appointments and reads their own records, nothing further.

## How the layer is used

Three decorators, applied to a route:

```python
from routes.permissions import require_auth, require_role, require_permission

@bp.route("/records", methods=["POST"])
@require_permission("records:write")     # preferred: gate on the action
def create_record():
    ...

@bp.route("/staff/queue")
@require_role("doctor", "nurse")         # when the gate really is about role
def queue():
    ...

@bp.route("/profile")
@require_auth                            # any signed-in user
def profile():
    ...
```

Gate on a permission rather than a role wherever possible. When the rules
change, the matrix above is the only thing that needs editing.

A decorator cannot tell whether a patient is asking for *their own* record, so
routes serving per-patient data must also call `owns_or_can_read_all(...)`
after the decorator runs. Clinical staff pass it for anyone; a patient passes
it only for themselves.

Responses are `401` for a missing, malformed, expired or badly signed token,
and `403` for a valid token whose role lacks the permission.

## Token contract

The layer verifies the token that `routes/auth.py` issues at login. Neither
this module nor any route may mint one.

```
{"userId": <int>, "role": "patient" | "nurse" | "doctor", "exp": <unix ts>}
```

Signed HS256 with `JWT_SECRET`, valid for two hours. Both modules read the same
environment variable and must keep the same fallback, or tokens minted by one
will not verify in the other.

A token presenting any role outside the three above is rejected with `403`,
including `admin`. If the role is ever reinstated it must be added to `ROLES`
and to the matrix, not merely issued at login.

## What replaced the admin role

Dropping admin removed a real capability, not just a screen. Two gaps follow
and each needs an owner.

**Creating staff accounts.** With no admin, nothing creates doctor and nurse
logins. Registration currently accepts a `role` field from the request body,
so anyone reaching the endpoint can register themselves as a doctor. That is
acceptable for a class demo and unacceptable beyond it. The near-term fix is to
let self-registration create patients only, and seed staff accounts through a
script run against the database.

**User management.** Deactivating a departed clinician, correcting a name, or
resetting a password has no home. For the scope we are building, password
reset is the only piece that genuinely matters, and it belongs to the patient
themselves rather than to an administrator.

These two replace the admin-related items in the Sprint 4 backlog:

- Restrict self-registration to the patient role; add a seed script for staff.
- Self-service password reset.
