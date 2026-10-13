"""Program generation, membership behaviour and the PDF report."""
import json

import db
from tests.conftest import create_client, post


# ------------------------------------------------------------ program
def test_generate_program_stores_and_shows_plan(auth_client, client_id, app):
    response = post(auth_client, f"/clients/{client_id}/program", {"experience": "beginner"})
    assert response.status_code == 302
    conn = db.connect(app.config["DATABASE"])
    stored = json.loads(db.get_client(conn, client_id)["generated_program"])
    conn.close()
    assert stored["experience"] == "beginner" and len(stored["rows"]) == 9
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "Generated for the beginner level." in page and "Monday" in page
    assert "Regenerate program" in page


def test_generate_program_is_reproducible_with_seed(auth_client, app):
    first = create_client(auth_client, name="One")
    second = create_client(auth_client, name="Two")
    for client_id in (first, second):
        post(auth_client, f"/clients/{client_id}/program", {"experience": "advanced"})
    conn = db.connect(app.config["DATABASE"])
    plans = [db.get_client(conn, i)["generated_program"] for i in (first, second)]
    conn.close()
    assert plans[0] == plans[1]
    assert len(json.loads(plans[0])["rows"]) == 20


def test_generate_program_follows_the_clients_program(auth_client, app):
    from services import EXERCISE_POOL
    client_id = create_client(auth_client, name="Gainer", program="mg-ppl")
    post(auth_client, f"/clients/{client_id}/program", {"experience": "intermediate"})
    conn = db.connect(app.config["DATABASE"])
    rows = json.loads(db.get_client(conn, client_id)["generated_program"])["rows"]
    conn.close()
    assert {r["exercise"] for r in rows} <= set(EXERCISE_POOL["Hypertrophy"])


def test_regenerating_replaces_the_plan(auth_client, client_id, app):
    post(auth_client, f"/clients/{client_id}/program", {"experience": "beginner"})
    post(auth_client, f"/clients/{client_id}/program", {"experience": "advanced"})
    conn = db.connect(app.config["DATABASE"])
    stored = json.loads(db.get_client(conn, client_id)["generated_program"])
    conn.close()
    assert stored["experience"] == "advanced"


def test_generate_program_rejects_invalid_experience(auth_client, client_id):
    response = post(auth_client, f"/clients/{client_id}/program", {"experience": "wizard"})
    assert response.status_code == 400
    assert "Choose beginner, intermediate or advanced." in response.get_data(as_text=True)


def test_program_form_empty_state(auth_client, client_id):
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "No program generated yet" in page and "Generate program" in page


# --------------------------------------------------------- membership
def test_membership_active_with_days_left(auth_client):
    client_id = create_client(auth_client, membership_end="2026-10-18")
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "badge-active" in page and "Days left" in page and "2026-10-18" in page


def test_membership_expired_is_derived_from_end_date(auth_client):
    client_id = create_client(auth_client, membership_end="2026-10-01")
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "badge-expired" in page and "Days overdue" in page
    dashboard = auth_client.get("/dashboard").get_data(as_text=True)
    assert "badge-expired" in dashboard


def test_membership_inactive_status(auth_client):
    client_id = create_client(auth_client, membership_status="Inactive", membership_end="")
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "badge-inactive" in page


def test_membership_can_be_renewed_by_editing(auth_client):
    from tests.conftest import VALID_CLIENT
    client_id = create_client(auth_client, membership_end="2026-10-01")
    renewed = {**VALID_CLIENT, "membership_end": "2027-06-30"}
    post(auth_client, f"/clients/{client_id}/edit", renewed)
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "badge-active" in page and "2027-06-30" in page and "badge-expired" not in page


def test_dashboard_lists_membership_state_per_client(auth_client):
    create_client(auth_client, name="Active One", membership_end="2027-01-01")
    create_client(auth_client, name="Expired One", membership_end="2026-01-01")
    html = auth_client.get("/dashboard").get_data(as_text=True)
    assert "badge-active" in html and "badge-expired" in html


# --------------------------------------------------------------- report
def test_pdf_report_download(auth_client, client_id):
    post(auth_client, f"/clients/{client_id}/progress", {"adherence": "80"})
    post(auth_client, f"/clients/{client_id}/program", {"experience": "beginner"})
    response = auth_client.get(f"/clients/{client_id}/report.pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF-")
    assert f"client-{client_id}-report.pdf" in response.headers["Content-Disposition"]


def test_pdf_report_is_reproducible(auth_client, client_id):
    first = auth_client.get(f"/clients/{client_id}/report.pdf").data
    second = auth_client.get(f"/clients/{client_id}/report.pdf").data
    assert first == second


def test_pdf_report_for_client_with_no_optional_data(auth_client):
    response = post(auth_client, "/clients/new", {"name": "Bare", "program": "bg"})
    client_id = int(response.headers["Location"].split("/")[-1])
    assert auth_client.get(f"/clients/{client_id}/report.pdf").data.startswith(b"%PDF-")
