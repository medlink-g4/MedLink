# MedLink

A hospital management web application. CSC289 Programming Capstone, Team G4.

Three roles: patient, doctor and nurse. Patients book and cancel their own
appointments, read their own records and medications, and message the staff
assigned to them. Doctors and nurses see only the patients they are assigned
to. Every one of those rules is enforced on the server.

## Running it locally

```bash
python database/init_db.py          # creates medlink.db
MEDLINK_DEV=1 python backend/app.py # starts the API on port 5000
```

Then open `frontend/index.html`, or serve the folder:

```bash
cd frontend && python -m http.server 8080
```

### Environment variables

| Variable | Needed | What it does |
| --- | --- | --- |
| `JWT_SECRET` | yes, unless `MEDLINK_DEV=1` | The key every access token is signed with. |
| `MEDLINK_DEV` | local work only | Uses a built-in development key so local setup takes no steps. |
| `MEDLINK_DB` | no | Points the app at a different database file. |
| `MEDLINK_SHOW_RESET_TOKEN` | local work only | Returns password reset tokens in the response instead of only the log. |
| `MEDLINK_ALLOW_STAFF_SIGNUP` | local work only | Lets the signup form create doctor and nurse accounts. |

**The app will not start without `JWT_SECRET` or `MEDLINK_DEV=1`, on purpose.**
It used to fall back to a fixed key when neither was set. That key is written
in this repository, which is public, so anyone could use it to sign a token
claiming any role for any user and read every patient record. Refusing to
start is better than quietly accepting forged tokens. For anything real, set
`JWT_SECRET` to a long random value and leave `MEDLINK_DEV` unset.

The three `local work only` variables all weaken something deliberately. None
of them should ever be set outside your own machine.

## Checking it works

```bash
python -m pytest backend/tests -q   # the unit suite
python demo/rbac_demo.py            # the permission rules, live, in 10 seconds
python demo/integration_check.py    # end to end against a running server
```

`integration_check.py` needs the server up and a set of demo accounts; the
file says which.

## Layout

```
backend/routes/     the API: auth, permissions, appointments, records,
                    messages, dashboards, password reset, audit
backend/tests/      the test suite
database/init_db.py the schema
demo/               runnable demonstrations and the integration check
docs/               per-task write-ups and test reports
frontend/           the interface
```
