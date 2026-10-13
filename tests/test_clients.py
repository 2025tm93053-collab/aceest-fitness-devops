"""Client management: list, create, update, validation, detail page."""
import db
from tests.conftest import VALID_CLIENT, create_client, post


def test_dashboard_empty_state(auth_client):
    html = auth_client.get("/dashboard").get_data(as_text=True)
    assert "No clients yet" in html


def test_new_client_form_renders(auth_client):
    response = auth_client.get("/clients/new")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'name="name"' in html and 'name="csrf_token"' in html
    assert "Fat Loss (FL) - 3 day" in html and "Beginner (BG)" in html


def test_create_client_stores_calories_and_lists_client(auth_client):
    client_id = create_client(auth_client)
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "Asha Rao" in page and "1320 kcal/day" in page
    assert "Fat Loss (FL) - 3 day" in page
    dashboard = auth_client.get("/dashboard").get_data(as_text=True)
    assert "Asha Rao" in dashboard and "1320" in dashboard


def test_create_client_with_only_required_fields(auth_client):
    response = post(auth_client, "/clients/new", {"name": "Min", "program": "bg"})
    assert response.status_code == 302
    page = auth_client.get(response.headers["Location"]).get_data(as_text=True)
    assert "Min" in page and "Add height and weight" in page


def test_create_client_requires_name_and_program(auth_client):
    response = post(auth_client, "/clients/new", {"name": "", "program": ""})
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Name is required." in html and "Program is required." in html


def test_create_client_rejects_invalid_numbers_and_keeps_input(auth_client, app):
    response = post(auth_client, "/clients/new",
                    {**VALID_CLIENT, "name": "Bad Input", "age": "abc", "weight": "-5"})
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Age must be a number." in html and "Weight (kg) must be between" in html
    assert 'value="Bad Input"' in html
    conn = db.connect(app.config["DATABASE"])
    assert db.list_clients(conn) == []
    conn.close()


def test_create_client_rejects_unknown_program_and_bad_date(auth_client):
    response = post(auth_client, "/clients/new",
                    {**VALID_CLIENT, "program": "hax", "membership_end": "soon"})
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Choose a program from the list." in html and "YYYY-MM-DD" in html


def test_duplicate_client_name_is_rejected(auth_client):
    create_client(auth_client)
    response = post(auth_client, "/clients/new", {**VALID_CLIENT, "name": "asha rao"})
    assert response.status_code == 400
    assert "already exists" in response.get_data(as_text=True)


def test_edit_form_is_prefilled(auth_client, client_id):
    html = auth_client.get(f"/clients/{client_id}/edit").get_data(as_text=True)
    assert 'value="Asha Rao"' in html and 'value="165.0"' in html
    assert 'value="fl3" selected' in html


def test_update_client_recalculates_calories_and_keeps_goals(auth_client, client_id):
    response = post(auth_client, f"/clients/{client_id}/edit",
                    {**VALID_CLIENT, "weight": "70", "program": "mg-ppl"})
    assert response.status_code == 302
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "2450 kcal/day" in page and "Muscle Gain (MG) - PPL" in page
    assert "55 kg" in page and "90%" in page


def test_update_with_invalid_data_does_not_change_client(auth_client, client_id):
    response = post(auth_client, f"/clients/{client_id}/edit", {**VALID_CLIENT, "age": "500"})
    assert response.status_code == 400
    assert "Age must be between" in response.get_data(as_text=True)
    assert "29" in auth_client.get(f"/clients/{client_id}").get_data(as_text=True)


def test_update_can_keep_the_same_name(auth_client, client_id):
    assert post(auth_client, f"/clients/{client_id}/edit", VALID_CLIENT).status_code == 302


def test_unknown_client_returns_404(auth_client):
    for url in ("/clients/999", "/clients/999/edit", "/clients/999/workouts",
                "/clients/999/report.pdf"):
        assert auth_client.get(url).status_code == 404, url
    for url in ("/clients/999/progress", "/clients/999/metrics", "/clients/999/program",
                "/clients/999/edit"):
        assert post(auth_client, url, {}).status_code == 404, url


def test_client_detail_shows_bmi(auth_client, client_id):
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "22.0" in page and "Normal" in page


def test_client_names_are_html_escaped(auth_client):
    client_id = create_client(auth_client, name="<script>alert(1)</script>")
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_sql_injection_attempt_is_stored_as_plain_text(auth_client, app):
    payload = "x'); DROP TABLE clients;--"
    create_client(auth_client, name=payload)
    conn = db.connect(app.config["DATABASE"])
    assert [c["name"] for c in db.list_clients(conn)] == [payload]
    conn.close()
