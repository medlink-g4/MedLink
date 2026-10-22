"""Basic tests for the MedLink messaging routes."""

from pathlib import Path
import sys

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.messages import messages_bp


@pytest.fixture()
def client():
    app = Flask(__name__)
    app.register_blueprint(messages_bp, url_prefix="/api/messages")
    return app.test_client()


def test_get_messages_requires_authentication(client):
    response = client.get("/api/messages?with_user_id=6")

    assert response.status_code == 401


def test_send_message_requires_authentication(client):
    response = client.post(
        "/api/messages",
        json={"recipient_id": 6, "message": "Hello"},
    )

    assert response.status_code == 401