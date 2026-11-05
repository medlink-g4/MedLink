# Sprint 3 test report — task 3.6

Testing of the medical record and communication features on the integrated
`main` branch, after all four Sprint 3 pull requests were merged.

Tested at commit `f350b71`. Alex Schrader.

## What was tested and how

Three layers, because each catches a different kind of mistake.

**1. Automated unit tests — 65 passing.**

    python -m pytest backend/tests -q

| File | Tests | Covers |
| --- | --- | --- |
| `test_rbac.py` | 10 | the permission matrix and token handling |
| `test_appointments.py` | 19 | booking, cancelling, slot conflicts |
| `test_medical_records.py` | 26 | records and medications, read and write |
| `test_auth.py` | 8 | login, registration, role assignment |
| `test_messages.py` | 2 | sending and reading messages |

**2. Access control demo — 9 of 9 cases correct.**

    python demo/rbac_demo.py

Walks through a patient reading their own records and being refused
someone else's, a nurse reading for an assigned patient and being refused an
unassigned one, a doctor writing a record and a patient being refused the
same write, plus a missing token, an expired token and a token edited to
claim a higher role.

**3. Live integration check — 34 of 34 cases correct.**

    python demo/integration_check.py

The pytest suite runs each blueprint against a throwaway database. This runs
against a real server over HTTP, which is the only way to catch mistakes in
`app.py` wiring or in how the features behave together rather than alone. It
covers the record history, the medication list, writing and amending
records, the messaging contact list, sending and reading a thread from both
sides, and appointments still working after the merge — each with the
negative case alongside it.

**4. Manual check in the browser.** Chromium against the running stack, all
three roles, with screenshots taken for the review document.

## Defects found

### 1. `frontend/script.js` did not parse — whole application dead (fixed)

The entire frontend was broken on `main`. `script.js` had a JavaScript
syntax error, so the browser discarded the whole file: no login, no
navigation, no dashboards. The page rendered and did nothing.

It came from the conflict resolution in `b3a678b`, "Merge branch 'main' into
sprint3-laura-communication", which merged the Messages navigation handler
with the Medical History one and left behind a duplicated `showPage(pageId)`
and one extra `});`. Git reported the conflict resolved; the result was not
valid JavaScript. Checking the four Sprint 3 merge commits in order shows
`main` parsing correctly through PR #42 and PR #41, and breaking at that
merge.

Fixed in this branch by removing the duplicated lines. `node --check` now
passes on both frontend scripts.

This is worth a habit rather than just a fix: a conflict inside a function
body resolves cleanly in git and still produces a file that cannot run.
Opening the page once after resolving a conflict would have caught it.

### 2. Messaging navigation bug — resolved by the same fix

Laura reported that sending a message returned the user to the Appointments
page. It does not reproduce after fix 1. In the browser the page stays on
Messages, the thread refreshes with the new message, and the status line
reads "Message sent successfully." `sendMessage()` itself was always
correct — it calls `event.preventDefault()`. The navigation symptom came
from the broken file, not from the messaging code.

### 3. `database/init_db.py` ignored `MEDLINK_DB` (fixed)

The schema script had its database hardcoded as `sqlite3.connect("medlink.db")`,
relative to whatever directory it was run from, while every other module
honours the `MEDLINK_DB` environment variable. Running it from anywhere but
the repository root created a second, empty database, and the application
then failed with "no such table". This is the same defect class as the one
fixed in `auth.py` last sprint.

Fixed. The default is unchanged, so nothing anyone currently does breaks.
Its summary line also listed the tables it creates and omitted `messages`;
that is corrected too.

## Open items, not fixed

**Contacts show a role and an ID instead of a name.** The messaging contact
list renders "doctor (User ID: 3)" because `GET /api/messages/contacts`
returns only `id` and `role`. The name is already in the `users` row the
endpoint reads, so adding it is a one-line change — but it is in Laura's
feature, so flagging rather than editing.

**No automated coverage of the frontend.** All three defects above were in
or caused by frontend code, and nothing in the test suite would have caught
any of them. A `node --check` on the two script files is close to free and
would have caught the one that mattered most.

## Result

With the two fixes in this branch, every layer passes: 65 unit tests, 9 of 9
access control cases, 34 of 34 live integration cases, and a manual pass
through all three roles in the browser. Patient records, medications, doctor
and nurse views and patient/staff messaging all behave as specified, and the
permission boundaries hold at every one of them.
