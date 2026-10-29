# Sprint 4 — password reset (4.4) and audit logging (4.5)

Alex Schrader. Backend for both tasks.

## 4.4 Self-service password reset

MedLink has no admin role, so there is nobody to call when a password is
forgotten. This replaces that: the account holder proves they control the
registered address and sets a new password themselves.

### Endpoints

| Method | Path | Who | Purpose |
| --- | --- | --- | --- |
| POST | `/api/auth/password-reset/request` | anyone | ask for a reset link |
| POST | `/api/auth/password-reset/confirm` | anyone with a token | set a new password |
| POST | `/api/auth/password-change` | signed in | change your own password |

### How a token reaches the user

There is no mail server in this project and sending email was out of scope
for the sprint, so the token is written to the application log:

```
2026-10-29 01:43:43 INFO routes.password_reset: Password reset token for
user_id=1 (expires 2026-10-29T02:13:43+00:00): 75_LD5IdDoSOSS6VZ0K2OP...
```

Copy it from there. For local work and for the tests, setting
`MEDLINK_SHOW_RESET_TOKEN=1` also returns the token in the response body,
which is convenient but must never be switched on anywhere real — with it
on, anyone who can name an address can take over that account. The default
is off, and a test asserts the default.

### What the implementation is careful about

**It does not reveal who has an account.** A request for an unregistered
address returns the same message, the same status code, and writes no row.
For a hospital, the list of who is a patient is itself private, so an
endpoint that answers "no such account" is a lookup tool.

**Only the hash of a token is stored,** for the same reason `users` holds a
`password_hash`. A copy of `password_reset_tokens` cannot be used to reset
anybody's password. A plain SHA-256 is correct here rather than a slow
password hash: the input is 32 random bytes, so there is no dictionary to
attack, and the lookup runs on every confirm.

**A token works once and expires in 30 minutes.** Unknown, already used and
expired all return the same message on purpose — they are the same thing to
the person holding the link, and distinguishing them would confirm that a
token once existed.

**Changing a password invalidates every outstanding link.** By any route:
requesting a new link, using one, or changing the password while signed in.
Someone who requested a reset last week does not still hold a key.

**The signed-in change still asks for the current password,** because a
bearer token can be left behind on a shared machine and the point of that
endpoint is to prove it is still the account holder.

## 4.5 Activity and audit logging

HIPAA's audit requirement is about accountability, not content: who reached
which patient's information, when, and whether it was allowed — including
the attempts that were refused.

### Where the entries come from

`require_permission()` in `permissions.py` already sits in front of every
protected route, so it is the one place that sees every access, allowed and
denied alike. Hooking it there means no route has to remember to log, and a
route added next sprint is audited the day it is written. Authentication
events — logins, failures, resets — are recorded from the auth routes.

An audit write can never fail a request. If the table is missing or the
write errors, the failure goes to the application log and the request
carries on; a test drops the table and asserts the endpoint still returns
200. Auditing is a record of the system working, not a part of it.

### What it deliberately does not store

No diagnosis, prescription, message body or set of vitals. An audit table
full of clinical detail is a second copy of the data you are protecting,
with the same disclosure risk and none of the access controls. Every row is
who, what resource, which patient, allowed or denied, and a short reason. A
test seeds a distinctive diagnosis, reads the record through the API, and
asserts the string appears nowhere in the log.

A failed login for an unregistered address records no user id and not the
submitted address either, so the log does not accumulate the emails of
people who do not have accounts.

### Reading it back

Reading the log is access to patient information, so it goes through the
same permission layer as everything else. There is no admin role and no
endpoint that returns the whole table.

| Method | Path | Who | Returns |
| --- | --- | --- | --- |
| GET | `/api/audit/me` | patient | who has reached their record |
| GET | `/api/audit/me` | doctor, nurse | their own activity |
| GET | `/api/audit/patient/<id>` | assigned staff, or the patient | that patient's access history |

A patient reading `/api/audit/me` is the accounting of disclosures they are
entitled to. A patient cannot read anyone else's, and an unassigned doctor
cannot either — both return 403, and both are tested.

### Sample output

```
time      uid  role     action                    resource         pat  outcome
01:43:00  3    doctor   login_succeeded                                 allowed
01:43:00  3    doctor   view                      medical_records  1    allowed
01:43:01  2    patient  password_reset_requested                        allowed
01:43:01  -    -        password_reset_rejected                         denied
01:43:01  2    patient  view                      audit            1    denied
```

## Schema added

`password_reset_tokens` (user, token hash, created, expires, used) and
`audit_log` (when, who, role, action, resource, patient, outcome, detail,
ip), with indexes on the columns the read endpoints filter by. Both use
`CREATE TABLE IF NOT EXISTS`, so re-running `init_db.py` on an existing
database adds them without disturbing anything.

## Testing

| | |
| --- | --- |
| `test_password_reset.py` | 16 tests |
| `test_audit.py` | 14 tests |
| whole suite | 95 passing, up from 65 |
| `demo/integration_check.py` | 53 live cases, up from 34 |

The suite was also checked against ten deliberate breakages — replaying a
spent token, storing the token in the clear, answering differently for an
unknown address, accepting an expired token, leaving old links alive after a
password change, accepting short passwords, not logging denials, not logging
allowed access, and letting patients or unassigned staff read anyone's audit
trail. All ten were caught. A test suite that passes while the rule it
describes is broken is not evidence of anything.

## One fix that came out of building this

`app.py` had no logging configuration, so the root logger sat at WARNING and
every `log.info()` in the project was discarded — including the line that
carries the reset token, which is the only way to obtain one when the
development flag is off. The feature was unusable as shipped until that was
set. Configured at the entry point rather than inside a module, so importing
a blueprint does not reconfigure logging for everyone.
