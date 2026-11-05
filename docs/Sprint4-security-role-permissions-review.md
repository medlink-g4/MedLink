# Sprint 4 Security and Role Permissions Review

## 1. Task scope

This review covered MedLink’s authentication and role-based access control for the patient, doctor, and nurse roles.

The review examined how the application:

- Registers users and authenticates login requests
- Creates and validates JWT access tokens
- Grants permissions based on a user’s role and the requested action
- Restricts patient information to the patient or assigned medical staff
- Protects the doctor and nurse dashboard and related API routes

No application code was changed as part of this review.

## 2. Files reviewed

### Authentication and permissions

- `backend/routes/auth.py` — user registration, login, JWT creation, and the staff self-registration restriction.
- `backend/routes/permissions.py` — the role-permission matrix, token validation, user identity resolution, patient ownership checks, provider assignment checks, and permission enforcement.
- `backend/app.py` — backend blueprint registration.

### Protected backend routes

- `backend/routes/dr_nr_dashboard.py` — access to the doctor and nurse dashboard and its provider-scoped data.
- `backend/routes/medical_records.py` — access to medical records and medications, including record creation and updates.
- `backend/routes/patients.py` — patient profile and vitals routes.
- `backend/routes/appointments.py` — appointment access, booking, cancellation, and availability.
- `backend/routes/messages.py` — contact, conversation, and message access.

### Database, tests, and frontend

- `database/init_db.py` — user roles and relationships between users, patients, providers, appointments, and medical records.
- `backend/tests/test_rbac.py` — the existing RBAC test cases.
- `frontend/script.js` and `frontend/index.html` — how the frontend handles the logged-in role and displays backend data.

## 3. Authentication and token review

The login route in `auth.py` checks the user’s credentials and issues a signed JWT containing the user ID, role, and expiration time. The permission code in `permissions.py` checks for a bearer token and rejects missing, invalid, expired, or tampered tokens before allowing a protected request to continue.

Patient and provider database IDs are resolved from the authenticated user ID. This lets backend routes apply ownership or provider-assignment rules without trusting an ID supplied only by the browser.

Self-registration is limited to patients by default. Staff signup is controlled by the `MEDLINK_ALLOW_STAFF_SIGNUP` environment setting.

## 4. Role-permission review

The permission matrix uses three scopes:

- `own` — the caller’s own data
- `assigned` — patients assigned to the caller
- `all` — all records for the permitted resource

The reviewed matrix generally provides these permissions:

- **Patients** can access their own profile, medical records, appointments, and messages.
- **Doctors** can access assigned patients and their records, create and update medical records for assigned patients, and view assigned appointments.
- **Nurses** can access assigned patients and records, update vitals, and view or manage assigned appointments as specified by the matrix.

The permission decorator returns HTTP 401 for an unusable token and HTTP 403 when an authenticated user lacks the required permission.

## 5. Route and data-scope review

The reviewed backend routes apply role checks through the permission decorator or perform additional checks where needed:

- Appointment booking checks the patient associated with the booking; cancellation checks the appointment’s patient before changing its status.
- Medical-record routes restrict access according to the patient and provider scopes.
- Patient vitals routes use the medical-record permissions and patient scope.
- Messaging routes check that the patient and staff member are assigned to one another before returning or sending conversation data.
- The provider dashboard allows doctors and nurses and returns information scoped to the logged-in provider.

The review also checked the database schema to understand how user IDs, patient IDs, provider IDs, and appointment assignments relate to one another.

## 6. Assignment behavior and configuration notes

Provider assignment is currently derived from appointment data. Doctors are matched through an appointment’s `provider_id`, and nurses through `assisting_nurse_id`.

The follow-up discussion clarified that this approach has limitations: providers may retain access through a past appointment, while a provider may not be considered assigned before an appointment exists. A separate assignment table is suggested by the team membres and will be considered for the Sprint 5 backlog.

The permission matrix allows nurses to edit assigned patient profiles, including date of birth, phone, and insurance information. The discussion clarified that this followed the earlier “update patient information” task while noting that insurance updates may not be appropriate for nurses. The team can decide whether to narrow this permission.

During the review, a development fallback for `JWT_SECRET` was indetified as a security risk. Because the repository is public, the fallback value could be used to forge JWTs and impersonate user roles, potentially exposing patient records. Deployed environments should use a securely configured secret. In a follow-up discussion, Alex explained that `MEDLINK_DEV=1` is intended for local development.

## 7. Testing performed

The RBAC test suite covers patient ownership, provider assignment, role restrictions, missing or expired tokens, and tampered tokens.

The test file uses test-harness routes. The passing result confirms the RBAC cases covered by that suite; it does not verify every application route end to end.

The command `python -m pytest test_rbac.py -q` completed with **10 passed**.

## 8. Separate runtime observation

A local medical-record runtime issue was observed during testing. It was not confirmed as a repository-level defect and was outside the verified RBAC test scope. It should be investigated separately before being reported as an application-wide failure.

## 9. Outcome

The Sprint 4 security and role-permissions review was completed. Authentication, token validation, role scopes, patient ownership, provider assignment, route checks, database relationships, and the RBAC tests were reviewed.

