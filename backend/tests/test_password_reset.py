"""Tests for self-service password reset (task 4.4).

The happy path is the least interesting part. What these mostly check is
that the endpoint does not leak who has an account, that a token cannot be
replayed or used after it expires, and that changing a password by any route
kills every link that was outstanding at the time.
"""

import importlib
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[2]

EMAIL = "resetme@medlink.test"
OLD_PASSWORD = "oldpassword1"
NEW_PASSWORD = "newpassword1"


def fresh_db(tmp_path):
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "database" / "init_db.py")],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path / "medlink.db"


@pytest.fixture()
def db(tmp_path):
    return fresh_db(tmp_path)


@pytest.fixture()
def client(db):
    """An app carrying the auth routes and the task 4.4 routes together."""
    os.environ["MEDLINK_SHOW_RESET_TOKEN"] = "1"

    import routes.auth as auth_module
    import routes.password_reset as reset_module
    importlib.reload(auth_module)
    importlib.reload(reset_module)

    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)
    app.register_blueprint(auth_module.auth_bp, url_prefix="/api/auth")
    app.register_blueprint(reset_module.password_reset_bp, url_prefix="/api/auth")

    test_client = app.test_client()
    test_client.post("/api/auth/register", json={
        "name": "Reset Me", "email": EMAIL,
        "password": OLD_PASSWORD, "role": "patient",
    })
    test_client._db = str(db)
    return test_client


def ask_for_token(client, email=EMAIL):
    return client.post("/api/auth/password-reset/request", json={"email": email})


def get_token(client):
    return ask_for_token(client).get_json()["reset_token"]


def can_log_in(client, password, email=EMAIL):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return r.status_code == 200


# --- account enumeration ---------------------------------------------------

def test_unknown_address_gets_the_same_reply_as_a_known_one(client):
    """Otherwise the endpoint is a way to find out who is a patient here."""
    known = ask_for_token(client)
    unknown = ask_for_token(client, "nobody@medlink.test")

    assert known.status_code == unknown.status_code == 200
    assert known.get_json()["message"] == unknown.get_json()["message"]


def test_no_token_is_issued_for_an_unknown_address(client):
    ask_for_token(client, "nobody@medlink.test")
    conn = sqlite3.connect(client._db)
    count = conn.execute("SELECT COUNT(*) FROM password_reset_tokens").fetchone()[0]
    conn.close()
    assert count == 0


def test_missing_email_is_rejected(client):
    r = client.post("/api/auth/password-reset/request", json={})
    assert r.status_code == 400


# --- the token itself ------------------------------------------------------

def test_the_raw_token_is_never_stored(client):
    token = get_token(client)
    conn = sqlite3.connect(client._db)
    stored = conn.execute("SELECT token_hash FROM password_reset_tokens").fetchone()[0]
    conn.close()
    assert token not in stored
    assert len(stored) == 64, "a sha256 hex digest, not the token"


def test_reset_changes_the_password(client):
    token = get_token(client)
    r = client.post("/api/auth/password-reset/confirm",
                    json={"token": token, "new_password": NEW_PASSWORD})
    assert r.status_code == 200
    assert can_log_in(client, NEW_PASSWORD)
    assert not can_log_in(client, OLD_PASSWORD)


def test_a_token_cannot_be_used_twice(client):
    token = get_token(client)
    client.post("/api/auth/password-reset/confirm",
                json={"token": token, "new_password": NEW_PASSWORD})

    again = client.post("/api/auth/password-reset/confirm",
                        json={"token": token, "new_password": "thirdpassword1"})
    assert again.status_code == 400
    assert can_log_in(client, NEW_PASSWORD), "the second attempt changed nothing"


def test_an_expired_token_is_refused(client):
    token = get_token(client)

    conn = sqlite3.connect(client._db)
    conn.execute(
        "UPDATE password_reset_tokens SET expires_at = ?",
        ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),),
    )
    conn.commit()
    conn.close()

    r = client.post("/api/auth/password-reset/confirm",
                    json={"token": token, "new_password": NEW_PASSWORD})
    assert r.status_code == 400
    assert can_log_in(client, OLD_PASSWORD), "the password was not changed"


def test_an_invented_token_is_refused(client):
    r = client.post("/api/auth/password-reset/confirm",
                    json={"token": "not-a-real-token", "new_password": NEW_PASSWORD})
    assert r.status_code == 400
    assert can_log_in(client, OLD_PASSWORD)


def test_requesting_again_invalidates_the_earlier_token(client):
    first = get_token(client)
    second = get_token(client)
    assert first != second

    stale = client.post("/api/auth/password-reset/confirm",
                        json={"token": first, "new_password": NEW_PASSWORD})
    assert stale.status_code == 400

    fresh = client.post("/api/auth/password-reset/confirm",
                        json={"token": second, "new_password": NEW_PASSWORD})
    assert fresh.status_code == 200


def test_a_short_password_is_refused_and_the_token_survives(client):
    token = get_token(client)
    r = client.post("/api/auth/password-reset/confirm",
                    json={"token": token, "new_password": "short"})
    assert r.status_code == 400

    # The attempt failed on validation, so the link should still work.
    retry = client.post("/api/auth/password-reset/confirm",
                        json={"token": token, "new_password": NEW_PASSWORD})
    assert retry.status_code == 200


def test_the_token_is_not_returned_when_the_development_flag_is_off(db):
    os.environ.pop("MEDLINK_SHOW_RESET_TOKEN", None)
    import routes.auth as auth_module
    import routes.password_reset as reset_module
    importlib.reload(auth_module)
    importlib.reload(reset_module)

    app = Flask(__name__)
    app.config["MEDLINK_DB"] = str(db)
    app.register_blueprint(auth_module.auth_bp, url_prefix="/api/auth")
    app.register_blueprint(reset_module.password_reset_bp, url_prefix="/api/auth")
    c = app.test_client()
    c.post("/api/auth/register", json={
        "name": "Reset Me", "email": EMAIL,
        "password": OLD_PASSWORD, "role": "patient",
    })

    body = c.post("/api/auth/password-reset/request",
                  json={"email": EMAIL}).get_json()
    assert "reset_token" not in body, "the token must not be in the response by default"


# --- changing a password while signed in -----------------------------------

def signed_in_token(client):
    return client.post("/api/auth/login", json={
        "email": EMAIL, "password": OLD_PASSWORD,
    }).get_json()["token"]


def test_signed_in_change_requires_the_current_password(client):
    auth = {"Authorization": f"Bearer {signed_in_token(client)}"}
    r = client.post("/api/auth/password-change", headers=auth, json={
        "current_password": "wrongpassword", "new_password": NEW_PASSWORD,
    })
    assert r.status_code == 403
    assert can_log_in(client, OLD_PASSWORD)


def test_signed_in_change_works(client):
    auth = {"Authorization": f"Bearer {signed_in_token(client)}"}
    r = client.post("/api/auth/password-change", headers=auth, json={
        "current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD,
    })
    assert r.status_code == 200
    assert can_log_in(client, NEW_PASSWORD)


def test_signed_in_change_is_refused_without_a_token(client):
    r = client.post("/api/auth/password-change", json={
        "current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD,
    })
    assert r.status_code == 401


def test_changing_the_password_kills_an_outstanding_reset_link(client):
    """Someone who requested a link earlier should not still hold a key."""
    token = get_token(client)

    auth = {"Authorization": f"Bearer {signed_in_token(client)}"}
    assert client.post("/api/auth/password-change", headers=auth, json={
        "current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD,
    }).status_code == 200

    stale = client.post("/api/auth/password-reset/confirm",
                        json={"token": token, "new_password": "attacker12345"})
    assert stale.status_code == 400
    assert can_log_in(client, NEW_PASSWORD)


def test_the_new_password_must_differ_from_the_old_one(client):
    auth = {"Authorization": f"Bearer {signed_in_token(client)}"}
    r = client.post("/api/auth/password-change", headers=auth, json={
        "current_password": OLD_PASSWORD, "new_password": OLD_PASSWORD,
    })
    assert r.status_code == 400
