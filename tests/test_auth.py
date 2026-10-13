"""Authentication, CSRF, security headers, bootstrap credentials and the CLI."""
import pytest

import app as app_module
import db
from tests.conftest import PASSWORD, USERNAME, extract_csrf, post


def login(client, username=USERNAME, password=PASSWORD, next_url=None):
    page = client.get("/login")
    token = extract_csrf(page.get_data(as_text=True))
    url = "/login" + (f"?next={next_url}" if next_url else "")
    return client.post(url, data={"csrf_token": token, "username": username, "password": password})


def test_app_is_a_flask_application(app):
    from flask import Flask
    assert isinstance(app, Flask)
    legacy_gui_module = "tk" + "inter"  # the old desktop UI toolkit must not be used
    assert legacy_gui_module not in open(app_module.__file__, encoding="utf-8").read().lower()


def test_health_endpoint_needs_no_login(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.get_json() == {"status": "ok"}


def test_index_redirects_anonymous_users_to_login(client):
    response = client.get("/")
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")


@pytest.mark.parametrize("url", ["/dashboard", "/clients/new", "/clients/1",
                                 "/clients/1/edit", "/clients/1/workouts",
                                 "/clients/1/report.pdf"])
def test_protected_pages_redirect_to_login(client, url):
    response = client.get(url)
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_login_page_renders_form_with_csrf_token(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'name="username"' in html and 'name="password"' in html
    assert len(extract_csrf(html)) == 64


def test_login_success_redirects_to_dashboard_and_shows_user(client):
    response = login(client)
    assert response.status_code == 302 and response.headers["Location"].endswith("/dashboard")
    page = client.get("/dashboard")
    assert page.status_code == 200 and USERNAME in page.get_data(as_text=True)


def test_login_wrong_password_is_rejected(client):
    response = login(client, password="wrong-password")
    assert response.status_code == 401
    assert "Invalid username or password" in response.get_data(as_text=True)
    assert client.get("/dashboard").status_code == 302


def test_login_unknown_user_is_rejected(client):
    assert login(client, username="nobody").status_code == 401


def test_no_default_admin_account_exists(client):
    assert login(client, "admin", "admin").status_code == 401


def test_login_without_csrf_token_is_rejected(client):
    client.get("/login")
    response = client.post("/login", data={"username": USERNAME, "password": PASSWORD})
    assert response.status_code == 400


def test_login_with_wrong_csrf_token_is_rejected(client):
    client.get("/login")
    response = client.post("/login", data={"csrf_token": "0" * 64, "username": USERNAME,
                                           "password": PASSWORD})
    assert response.status_code == 400


def test_login_honours_safe_next_and_blocks_open_redirects(client):
    response = login(client, next_url="/clients/new")
    assert response.headers["Location"].endswith("/clients/new")
    post(client, "/logout")
    for evil in ("//evil.example", "https://evil.example", "/\\evil.example"):
        other = login(client, next_url=evil)
        assert other.headers["Location"].endswith("/dashboard"), evil
        post(client, "/logout")


def test_logout_requires_post_and_csrf_and_clears_session(auth_client):
    assert auth_client.get("/logout").status_code == 405
    assert auth_client.post("/logout").status_code == 400
    assert post(auth_client, "/logout").status_code == 302
    assert auth_client.get("/dashboard").status_code == 302


def test_passwords_are_stored_hashed(app):
    conn = db.connect(app.config["DATABASE"])
    stored = db.get_user_by_username(conn, USERNAME)["password_hash"]
    conn.close()
    assert stored != PASSWORD and PASSWORD not in stored and ":" in stored


def test_state_changing_requests_need_csrf(auth_client):
    response = auth_client.post("/clients/new", data={"name": "X", "program": "bg"})
    assert response.status_code == 400
    assert "form session expired" in response.get_data(as_text=True)


def test_security_headers_are_set(client):
    headers = client.get("/login").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in headers["Content-Security-Policy"]


def test_unknown_page_returns_friendly_404(auth_client):
    response = auth_client.get("/nope")
    assert response.status_code == 404 and "could not find" in response.get_data(as_text=True)


def test_session_for_deleted_user_is_discarded(app, auth_client):
    conn = db.connect(app.config["DATABASE"])
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    assert auth_client.get("/dashboard").status_code == 302


# ------------------------------------------------- bootstrap and CLI
def make_app(tmp_path, **config):
    return app_module.create_app({
        "TESTING": True, "SECRET_KEY": "k", "DATABASE": str(tmp_path / "boot.db"),
        "BOOTSTRAP_ADMIN_USERNAME": None, "BOOTSTRAP_ADMIN_PASSWORD": None, **config})


def test_bootstrap_admin_from_configuration(tmp_path):
    application = make_app(tmp_path, BOOTSTRAP_ADMIN_USERNAME="owner",
                           BOOTSTRAP_ADMIN_PASSWORD="a-long-password")
    conn = db.connect(application.config["DATABASE"])
    user = db.get_user_by_username(conn, "owner")
    conn.close()
    assert user["role"] == "Admin" and user["password_hash"] != "a-long-password"
    assert application.config["BOOTSTRAP_ADMIN_PASSWORD"] is None
    assert login(application.test_client(), "owner", "a-long-password").status_code == 302


def test_bootstrap_does_not_overwrite_existing_user(tmp_path):
    make_app(tmp_path, BOOTSTRAP_ADMIN_USERNAME="owner", BOOTSTRAP_ADMIN_PASSWORD="first-password")
    again = make_app(tmp_path, BOOTSTRAP_ADMIN_USERNAME="owner",
                     BOOTSTRAP_ADMIN_PASSWORD="second-password")
    assert login(again.test_client(), "owner", "first-password").status_code == 302
    assert login(again.test_client(), "owner", "second-password").status_code == 401


def test_bootstrap_skips_short_password(tmp_path):
    application = make_app(tmp_path, BOOTSTRAP_ADMIN_USERNAME="owner",
                           BOOTSTRAP_ADMIN_PASSWORD="short")
    conn = db.connect(application.config["DATABASE"])
    assert db.get_user_by_username(conn, "owner") is None
    conn.close()


def test_bootstrap_requires_both_values(tmp_path):
    application = make_app(tmp_path, BOOTSTRAP_ADMIN_USERNAME="owner")
    conn = db.connect(application.config["DATABASE"])
    assert db.get_user_by_username(conn, "owner") is None
    conn.close()


def test_create_user_cli_creates_hashed_user_that_can_log_in(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["create-user", "newcoach", "--role", "coach"],
                           input="long-enough-pw\nlong-enough-pw\n")
    assert result.exit_code == 0, result.output
    assert "Created Coach user 'newcoach'" in result.output
    conn = db.connect(app.config["DATABASE"])
    user = db.get_user_by_username(conn, "newcoach")
    conn.close()
    assert user["role"] == "Coach" and "long-enough-pw" not in user["password_hash"]
    assert login(app.test_client(), "newcoach", "long-enough-pw").status_code == 302


def test_create_user_cli_rejects_duplicates_and_weak_input(app):
    runner = app.test_cli_runner()
    duplicate = runner.invoke(args=["create-user", USERNAME, "--password", "long-enough-pw"])
    assert duplicate.exit_code != 0 and "already exists" in duplicate.output
    short = runner.invoke(args=["create-user", "someone", "--password", "short"])
    assert short.exit_code != 0 and "at least 8" in short.output
    bad_name = runner.invoke(args=["create-user", "a b", "--password", "long-enough-pw"])
    assert bad_name.exit_code != 0 and "Username" in bad_name.output
