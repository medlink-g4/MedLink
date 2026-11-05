# Sprint 4 integration test report — task 4.6

Alex Schrader. Tested on 2026-11-05, before any Sprint 4 pull request was
merged.

## Why this was run before the merge rather than after

Last sprint a conflict resolution in `frontend/script.js` produced a file
git accepted and the browser could not parse, and `main` sat with a
completely dead frontend until someone happened to open the page. The same
file is contested again this sprint: Mackenzie's branch and Laura's branch
both rewrite the same navigation handler, and neither branch contains the
Sprint 3 fix to it.

So this run combined all four branches in a local worktree first, resolved
the conflicts there, and tested the result. Nothing was pushed. The point
is to know what the merge produces before `main` has to live with it.

## Branches combined

| Branch | Task | Result |
| --- | --- | --- |
| `s4-johns-4.1,4.2` | profile and appointment management | conflict in `script.js` |
| `sprint4-laura-reports` | reports | conflicts in `script.js` and `app.py` |
| `asma-sprint4-security-role-permissions-review` | security review | merged clean |
| `sprint4-alex-reset-audit` | audit logging, password reset | merged clean |

### The conflicts, and how they resolve

**`backend/app.py`** — three branches each add blueprint imports and
registrations in the same two places. Every side is additive; the
resolution is simply all of them, with `reports`, `providers` and `users`
registered alongside the existing ones. No logic is lost either way.

**`frontend/script.js`, Mackenzie's merge** — one blank line. Trivial.

**`frontend/script.js`, Laura's merge** — the real one, and the same
navigation handler that broke last sprint. Laura's side adds the Reports
page handling and a `backToDashboardBtn` listener but carries the older,
un-nested shape of the block; the current `main` has the corrected shape.
Taking either side wholesale loses something: Laura's side loses the Sprint
3 fix, `main`'s side loses Reports entirely.

The resolution keeps the corrected structure and folds Laura's Reports
branch into it. The staff-only check now runs before navigating rather than
after, so a patient never lands on the page and gets bounced off it, and
the `backToDashboardBtn` listener is guarded with a null check — if that
element is ever absent, an unguarded `addEventListener` throws during page
load and kills the whole script, which is exactly the failure mode from
last sprint.

## Results on the combined code

| Check | Result |
| --- | --- |
| `node --check` on all four frontend scripts | clean |
| `python -m pytest backend/tests -q` | **205 passed** |
| `demo/rbac_demo.py` | 9 of 9 |
| `demo/integration_check.py` against a live server | 49 of 49 |
| Browser pass, all three roles, every page | no JavaScript errors |
| API error responses during the browser pass | none |

The only console message is a missing favicon.

### Browser pass

Patient, doctor and nurse were each logged in and every sidebar page
opened. Patients land on the patient dashboard; doctors and nurses land on
the provider dashboard. Medical History, Messages and Profile work for all
three. Reports is not shown to patients at all, and the link is absent from
their sidebar rather than merely refused on click.

### Scope checks on the new features

Task 4.3, reports, was checked directly against the API because scoping is
the part a screenshot cannot show:

* the nurse, who is assigned only to Jordan, receives only Jordan in all
  three report sections
* the doctor, who is assigned to both patients, receives both
* a patient receives 403
* no token receives 401

Task 4.4 and 4.5, my own, are covered by the 49-case live check: password
reset issues, confirms, refuses replay, refuses expiry and does not reveal
whether an address is registered; the audit log records allowed and refused
access, holds no clinical text, and is readable only within the caller's
own scope.

## Recommended merge order

1. `asma-sprint4-security-role-permissions-review` — documentation only
2. `sprint4-alex-reset-audit` — merges clean against current `main`
3. `s4-johns-4.1,4.2` — one trivial conflict
4. `sprint4-laura-reports` — the real conflict, resolved last so it is
   resolved against everything else rather than twice

Whoever takes step 4 should run `node --check frontend/script.js` before
committing the resolution. It takes a second and it is the exact check that
would have caught last sprint's failure.

## Open items, not defects

**Medical History renders empty for doctors and nurses.** The page is in
the shared sidebar but only loads data for patients, so staff see the
placeholder text. Cosmetic, and arguably the link should be hidden for
staff the way Reports is hidden for patients.

**Provider assignment is still derived from appointments.** Raised
independently in Asma's security review. A past uncancelled appointment
grants access indefinitely and assignment cannot exist before the first
booking. Agreed for the Sprint 5 backlog.

## Conclusion

All four Sprint 4 branches combine into a working application: 205 unit
tests, 9 of 9 permission cases, 49 of 49 live integration cases, and a
clean browser pass across all three roles. The merge is safe to perform in
the order above, provided the `script.js` conflict is resolved as described
rather than by taking one side.
