# Sprint 5 system test report — task 5.1

Alex Schrader. Tested on 2026-11-19 against `main` at commit `e6d0370`,
from a clean clone and an empty database.

## What was tested

Five layers, because each catches a kind of mistake the others cannot.

**1. Static checks.** Every frontend script parses, every Python file
parses. This is here because the frontend has twice been shipped in a
state where the browser discarded the whole file, and no other check in
this project can see that.

**2. Unit suite — 267 passing** across 15 files.

**3. Permission demo — 9 of 9.** `demo/rbac_demo.py`.

**4. Live integration check — 53 of 53.** `demo/integration_check.py`,
over HTTP against a running server.

**5. Authorization probes — 24 of 24.** New in this sprint; see below.

**6. Manual browser pass.** All three roles, every page reachable from the
sidebar, on the assembled application.

## New in this sprint: `demo/authorization_probe.py`

The existing checks prove each route behaves correctly and that the
features work together. Neither answers the question a reviewer actually
asks about a medical system: can anyone reach data that is not theirs?

Screenshots cannot answer it. A report returning too many patients looks
identical to one returning the right number, which is exactly why this
class of bug survives a demo. So these probes ask the server directly as
each role.

The expectations are derived from the database rather than written into
the script: for each provider it reads which patients they are actually
assigned to, then asserts the API returns that set exactly. A probe with
hardcoded expectations breaks every time the seed data changes, and is
usually "fixed" by loosening the assertion.

Covered: reports are staff-only and scoped; records reach only their owner
or assigned staff; only doctors may write records; profile and appointment
access; the audit trail is itself access controlled and holds no clinical
text; password reset does not reveal who has an account; and tokens that
are absent, garbage, or edited to claim a higher role are refused.

## Defect found and fixed

**Two test files could not run on their own.**
`test_dashboard_reports.py` and `test_messaging_and_wording.py` failed
immediately with `ModuleNotFoundError: No module named 'routes'`. They
only worked when another test file had already put `backend/` on the
import path, so running the whole suite passed while running either file
by itself did not.

That is 39 tests — 25 and 14 — which could not be run in isolation, and
which would have vanished silently from the count had they been collected
in a different order. Fixed by giving both the same three lines every other
test file already has.

Worth noting what this says about the number: a suite reporting 267 passes
is only meaningful if the tests actually run. This one was fine, but it was
fine by accident.

## Verified, not assumed

Scoping was compared against the database rather than eyeballed:

* the doctor is on appointments with both seeded patients, and the reports
  endpoint returns both
* the nurse is the assisting nurse on one patient only, and the reports
  endpoint returns that one
* medical records in each report are limited to the same set

## Closed since Sprint 4

The Medical History page used to appear in the sidebar for doctors and
nurses and render empty, which I raised in the Sprint 4 report. It is now
hidden for staff roles.

## Open items

**Provider assignment is still derived from appointment history,** so a
past appointment grants access indefinitely and no access exists before the
first booking. The replacement assignment table is written but not yet
merged.

**When it is merged, two things need checking.** The implementation report
notes that appointments created after setup do not produce assignment rows,
which would mean a provider gets no access to a newly booked patient. It
also changed five test files; the whole reason assignment lives in a single
function is that swapping it should not require touching tests, so those
diffs are worth reading before the merge rather than after.

**No automated frontend coverage.** All 267 tests are backend. Both
occasions where `main` shipped a dead page passed every test.

## Result

267 unit tests, 9 of 9 permission cases, 53 of 53 integration cases, 24 of
24 authorization probes, and a clean browser pass across all three roles
with no JavaScript errors and no server errors. The application on `main`
works end to end today.
