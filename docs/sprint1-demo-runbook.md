# Sprint 1 Review — role-based access demo

Task 1.4. Two things to show, about four minutes total.

## Before the meeting

```bash
git checkout sprint1-alex-rbac
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
```

Then run both commands once to make sure they work on your machine:

```bash
python demo/rbac_demo.py
cd backend && python -m pytest tests/ -q && cd ..
```

Neither touches your real database. The demo builds a throwaway one in a temp
directory and deletes it on exit, so it is safe to run repeatedly on camera.

Have the terminal at a readable font size before you share your screen.

## What to run, and what to say

**1. The demo.** `python demo/rbac_demo.py`

It prints who is in the database first. Say that Dr. Johnson and Nurse Mike
both have an appointment with John, so they are assigned to him, and Dr. Chen
does not.

Then walk the four sections as they scroll:

- **Patient scope.** John reads his own record and gets it. He asks for
  Maria's and gets 403. A patient can only ever see themselves.
- **Nurse limits.** Nurse Mike records vitals for John and it works. He tries
  to change John's diagnosis and gets 403. This is the interesting one: the
  nurse is assigned to that patient, so the denial is about the action, not
  the patient. Nurses record vitals, doctors diagnose.
- **Doctor assignment.** Dr. Johnson updates John's medications, allowed,
  because she is assigned. Dr. Chen asks for the same record and gets 403.
  Same role, same patient, different answer, because assignment differs.
- **Token checks.** No token, expired token, and a token edited to claim
  doctor all return 401. The edited one is worth pausing on: changing the
  role inside the token breaks its signature, so the server rejects it before
  it ever looks at permissions.

Close with the line the script prints: enforcement is server-side, so hiding
a button in the interface would not have done this.

**2. The tests.** `cd backend && python -m pytest tests/ -q`

Ten passing. Nine are the required cases, the tenth covers a nurse who is not
recorded as assisting on any appointment, which gets logged as a data problem
rather than looking like a blanket denial.

Worth saying out loud: passing tests do not prove much on their own, so the
layer was checked by deliberately breaking it three ways. Granting every scope
as `all` fails four tests, forcing assignment to always succeed fails two, and
disabling signature and expiry checks fails two. The tests notice when the
thing they test stops working.

## If someone asks

**Where are the real endpoints?** The patient, record and appointment
endpoints are Sprint 2 and 3 work owned by other people. Building them now
would take their tasks and cause merge conflicts. The routes in the demo and
tests are a harness. The same decorator applies unchanged when the real
endpoints land, one line above the function.

**How does it know who is assigned?** From non-cancelled appointments.
Doctors match on `provider_id`, nurses on `assisting_nurse_id`. There is no
assignment table in the schema, which is why this is an interim. All of that
logic lives in one function, `is_assigned()`, with one caller, so Sprint 3
swaps it for a real table by editing that function and nothing else.

**Why no admin role?** Removed in Sprint 1. The two things admin would have
done, creating staff accounts and resetting passwords, are Sprint 4 tasks.

**What still needs doing?** Two things. The token carries no provider
identifier, so provider identity is looked up per request; adding `providerId`
at login in task 1.3 removes that. And nothing is merged to `main` yet, so the
demo runs from this branch.

## Fallback

If the demo will not run in the moment, run the tests instead. They cover the
same nine cases and need no setup beyond the install. If neither runs, open
[pull request #34](https://github.com/medlink-g4/MedLink/pull/34) and walk the
table in the description.
