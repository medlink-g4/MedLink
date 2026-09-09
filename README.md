# MedLink

A patient portal for a small clinic. Patients book appointments and read their
own records. Doctors and nurses see their patients, write clinical notes, and
manage appointments. Doctors can also prescribe.

Course group project, Group 4.

## Stack

As built today:

| Layer | What we're using |
|---|---|
| Backend | Python 3 with Flask |
| Database | SQLite |
| Auth | JWT via PyJWT, password hashing via Werkzeug |
| Frontend | HTML, CSS and plain JavaScript |
| Tests | pytest |

**Open decision.** The Project Plan document describes React, Node/Express and
MySQL. The code is Python, Flask and SQLite. One of the two has to change
before we submit. See the team thread. Until that is settled, this file
describes what actually runs.

## Layout

```
backend/
  app.py                  Flask entry point, registers blueprints
  requirements.txt
  routes/
    auth.py               register and login, issues the JWT
    permissions.py        role and permission decorators
  tests/
    test_permissions.py
database/
  init_db.py              creates the schema
frontend/
  index.html              login, dashboards, appointment scheduling
  style.css
  script.js               navigation, currently on mock data
docs/
  roles-and-permissions.md
```

## Setup

Python 3.8 or newer.

```bash
git clone https://github.com/medlink-g4/MedLink.git
cd MedLink

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install Flask PyJWT pytest
```

Create the database. **Run this from the repository root, not from inside
`database/`.** The app looks for `medlink.db` at the root, and the script
writes it to whatever directory you are standing in.

```bash
python database/init_db.py
```

Start the API:

```bash
cd backend
python app.py
```

It serves on `http://localhost:5000`. Check it with `curl http://localhost:5000/`,
which should return `{"message": "MedLink API is running"}`.

The database file is gitignored, so everyone creates their own. It is not
shared and it does not get committed.

For the frontend, open `frontend/index.html` in a browser. It runs on mock data
and is not wired to the API yet.

## Tests

```bash
cd backend
python -m pytest tests/ -q
```

## API

| Method | Route | Body | Returns |
|---|---|---|---|
| GET | `/` | | health check |
| POST | `/api/auth/register` | `name`, `email`, `password`, `role` | `userId`, `role` |
| POST | `/api/auth/login` | `email`, `password` | `token`, `userId`, `role` |

Protected routes expect the token in a header:

```
Authorization: Bearer <token>
```

The token is signed HS256 with `JWT_SECRET` and carries
`{"userId": ..., "role": ..., "exp": ...}`, valid for two hours. Set
`JWT_SECRET` in your environment; there is a development fallback in the code
that must not be used for anything real.

## Roles

Three roles: patient, doctor, nurse. Patients reach only their own data.
Nurses and doctors reach any patient's. Prescribing is doctor only.

Gate a route with a decorator:

```python
from routes.permissions import require_permission

@bp.route("/records", methods=["POST"])
@require_permission("records:write")
def create_record():
    ...
```

Full matrix and the reasoning are in `docs/roles-and-permissions.md`.

## Branches

Branch off `main` as `sprint1-<yourname>-<feature>`, for example
`sprint1-laura-authentication`. Open a pull request rather than pushing to
`main`.

## Known issues

Things to fix before the sprint review, tracked here so nobody rediscovers
them:

- `init_db.py` writes `medlink.db` relative to the current directory, but
  `routes/auth.py` resolves it to the repository root. Running the script from
  `database/` makes every request fail with a 500 and
  `no such table: users`. Both should resolve the path the same way.
- Registration inserts a row into `users` only. It never creates the matching
  `providers` or `patients` row, so a newly registered doctor cannot be booked
  for an appointment, because `appointments.provider_id` is a foreign key into
  `providers`.
- Registration takes `role` straight from the request body, so anyone can sign
  themselves up as a doctor. Acceptable for the demo, not beyond it.
- `requirements.txt` needs `pytest` added once the feature branches merge.
- The frontend login is mock only and does not call `/api/auth/login` yet.
