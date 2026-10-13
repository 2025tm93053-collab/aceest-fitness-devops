"""Shared fixtures: isolated temporary database, fixed clock, seeded randomness."""
import re
from datetime import date

import pytest
from werkzeug.security import generate_password_hash

import app as app_module
import db

TODAY = date(2026, 10, 8)
USERNAME = "coach_test"
PASSWORD = "correct-horse-battery"


@pytest.fixture
def app(tmp_path):
    database = str(tmp_path / "test.db")
    application = app_module.create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key",
        "DATABASE": database,
        "BOOTSTRAP_ADMIN_USERNAME": None,
        "BOOTSTRAP_ADMIN_PASSWORD": None,
        "PROGRAM_RNG_SEED": 1234,
        "TODAY_FUNC": lambda: TODAY,
    })
    conn = db.connect(database)
    db.create_user(conn, USERNAME, generate_password_hash(PASSWORD), "Admin")
    conn.close()
    return application


@pytest.fixture
def client(app):
    """Anonymous test client."""
    return app.test_client()


@pytest.fixture
def auth_client(app):
    """Test client already signed in (session set directly for speed)."""
    test_client = app.test_client()
    conn = db.connect(app.config["DATABASE"])
    user_id = db.get_user_by_username(conn, USERNAME)["id"]
    conn.close()
    with test_client.session_transaction() as session:
        session["user_id"] = user_id
        session["csrf_token"] = "test-csrf-token"
    return test_client


def post(test_client, url, data=None, **kwargs):
    """POST a form including the session's CSRF token."""
    with test_client.session_transaction() as session:
        token = session.setdefault("csrf_token", "test-csrf-token")
    payload = {"csrf_token": token, **(data or {})}
    return test_client.post(url, data=payload, **kwargs)


def extract_csrf(html):
    return re.search(r'name="csrf_token" value="([0-9a-f]+)"', html).group(1)


VALID_CLIENT = {
    "name": "Asha Rao", "age": "29", "height": "165", "weight": "60",
    "program": "fl3", "target_weight": "55", "target_adherence": "90",
    "membership_status": "Active", "membership_end": "2027-01-31",
}


def create_client(test_client, **overrides):
    """Create a client through the web form and return its id."""
    response = post(test_client, "/clients/new", {**VALID_CLIENT, **overrides})
    assert response.status_code == 302, response.get_data(as_text=True)
    return int(response.headers["Location"].rstrip("/").split("/")[-1])


@pytest.fixture
def client_id(auth_client):
    return create_client(auth_client)
