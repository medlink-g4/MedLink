# Deadlines and Open Items

## Next deadline: 9/17/26 — Sprint 1 Status Update #1

Sprint 1 coding and testing happen after the 9/10 backlog deadline, so the
status update on 9/17 is the first checkpoint where the work itself is
reported.

### Blocking: nothing from Sprint 1 is merged

All six Sprint 1 tasks are marked Complete in the backlog, but `main` still
contains an empty `backend/app.py` and none of the feature work. Three branches
are outstanding:

| Branch | Owner | Ahead of main | Pull request |
|---|---|---|---|
| `sprint1-laura-authentication` | Laura | 6 commits | none opened |
| `sprin1-asma-navigation-ui` | Asma | 1 commit | [#31](https://github.com/medlink-g4/MedLink/pull/31), open |
| `sprint1-permissions` | Alex | 2 commits | none opened |

A demo from `main` would currently show nothing. These need review and merge
before the status update.

### Also open

- **Two authentication defects**, both in `backend/routes/auth.py`. The
  database path resolves differently than in `database/init_db.py`, and
  registration never creates the matching `providers` or `patients` row. Both
  are described in the README under Known issues.
- **`requirements.txt` needs `pytest`** once the branches merge.
- **Sprint 2 assignments.** The assignment requires development tasks
  distributed to every team member. Sprints 2 through 5 currently have no
  assignees.

## Settled

- **Stack.** Python, Flask and SQLite, agreed by the team rather than migrating
  to React and Node. The Project Development Plan was corrected and resubmitted
  after the professor reopened the submission.

## Earlier

- 9/10/26 — Project Backlog and Project Development Plan. Submitted late, then
  resubmitted with corrections after the professor reopened the submission.
