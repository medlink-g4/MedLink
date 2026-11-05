"""The application must not start with a published signing key (task 4.5).

Raised in Asma's Sprint 4 security and role permissions review. Both auth.py
and permissions.py used to fall back to a fixed string when JWT_SECRET was
unset. This repository is public, so that string is readable by anyone, and
any deployment that forgot the environment variable would accept tokens
forged with it -- a token claiming the doctor role for any user id, which
walks past every scope rule in the permission matrix.

These run in subprocesses because the check happens when the module is
imported, and a test process has already imported it.
"""

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

PROBE = (
    "import json, sys;"
    "sys.path.insert(0, %r);"
    "import routes.permissions as p;"
    "print(json.dumps({'secret': p.JWT_SECRET}))"
) % str(BACKEND)


def run(env_overrides):
    """Import the permission layer in a clean process with this environment."""
    import os
    env = {k: v for k, v in os.environ.items()
           if k not in ("JWT_SECRET", "MEDLINK_DEV")}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True, text=True, env=env,
    )


def test_a_configured_secret_is_used():
    r = run({"JWT_SECRET": "a-real-deployment-secret"})
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["secret"] == "a-real-deployment-secret"


def test_the_app_refuses_to_start_with_no_secret():
    """The whole point. Silently downgrading to a published key is worse
    than not starting at all."""
    r = run({})
    assert r.returncode != 0, "importing without a secret should fail"
    assert "JWT_SECRET is not set" in r.stderr


def test_the_failure_says_how_to_fix_it():
    r = run({})
    assert "MEDLINK_DEV=1" in r.stderr, "an error nobody can act on is a dead end"


def test_development_mode_still_works_without_setup():
    r = run({"MEDLINK_DEV": "1"})
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["secret"] == "medlink-development-secret"


def test_development_mode_warns_that_the_key_is_published():
    r = run({"MEDLINK_DEV": "1"})
    assert "development" in r.stderr.lower()
    assert "never run this way" in r.stderr.lower()


def test_a_configured_secret_wins_over_development_mode():
    r = run({"JWT_SECRET": "the-real-one", "MEDLINK_DEV": "1"})
    assert json.loads(r.stdout)["secret"] == "the-real-one"


def test_auth_and_permissions_agree_on_the_key():
    """They used to hold separate copies of the same literal, which could
    drift. A login signed with one key and checked against another fails
    every request with a token that looks valid."""
    probe = (
        "import json, sys;"
        "sys.path.insert(0, %r);"
        "import routes.auth as a, routes.permissions as p;"
        "print(json.dumps({'same': a.JWT_SECRET == p.JWT_SECRET}))"
    ) % str(BACKEND)
    import os
    env = {k: v for k, v in os.environ.items() if k != "MEDLINK_DEV"}
    env["JWT_SECRET"] = "shared-secret-value"
    r = subprocess.run([sys.executable, "-c", probe],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["same"] is True
