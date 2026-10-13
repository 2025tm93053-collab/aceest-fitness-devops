"""Weekly adherence, body metrics and workouts."""
import db
from tests.conftest import VALID_CLIENT, create_client, post


# -------------------------------------------------------------- adherence
def test_log_progress_updates_summary_and_chart(auth_client, client_id):
    for value in ("80", "90"):
        assert post(auth_client, f"/clients/{client_id}/progress",
                    {"adherence": value}).status_code == 302
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "Weeks logged" in page and "85.0%" in page
    assert "<svg" in page and "Weekly adherence" in page and "Week 40 - 2026" in page


def test_progress_rejects_invalid_values(auth_client, client_id, app):
    for bad in ("", "abc", "101", "-5"):
        response = post(auth_client, f"/clients/{client_id}/progress", {"adherence": bad})
        assert response.status_code == 400, bad
    conn = db.connect(app.config["DATABASE"])
    assert db.progress_stats(conn, client_id) == (0, 0)
    conn.close()


def test_charts_show_empty_state_before_any_data(auth_client, client_id):
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "<svg" not in page
    assert "Log weekly adherence to see the adherence chart." in page


# ---------------------------------------------------------------- metrics
def test_log_metrics_shows_last_entry_and_weight_chart(auth_client, client_id):
    post(auth_client, f"/clients/{client_id}/metrics",
         {"date": "2026-10-01", "weight": "61", "waist": "80", "bodyfat": "24"})
    post(auth_client, f"/clients/{client_id}/metrics", {"weight": "59.5"})
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "2026-10-08: 59.5 kg" in page
    assert "Weight trend" in page and page.count('class="chart-dot"') == 2


def test_metrics_without_weight_do_not_plot_weight(auth_client, client_id):
    post(auth_client, f"/clients/{client_id}/metrics", {"waist": "80"})
    page = auth_client.get(f"/clients/{client_id}").get_data(as_text=True)
    assert "waist 80 cm" in page and "Weight trend" not in page


def test_metrics_validation(auth_client, client_id):
    cases = [{}, {"weight": "abc"}, {"bodyfat": "99"}, {"weight": "60", "date": "nope"}]
    for data in cases:
        response = post(auth_client, f"/clients/{client_id}/metrics", data)
        assert response.status_code == 400, data


# --------------------------------------------------------------- workouts
def test_workouts_page_empty_state(auth_client, client_id):
    html = auth_client.get(f"/clients/{client_id}/workouts").get_data(as_text=True)
    assert "No workouts logged yet" in html and "2026-10-08" in html


def test_log_workout_with_exercise_and_list_it(auth_client, client_id):
    response = post(auth_client, f"/clients/{client_id}/workouts", {
        "date": "2026-10-07", "workout_type": "Strength", "duration_min": "50",
        "notes": "Heavy day", "exercise_name": "Back Squat", "sets": "5", "reps": "5",
        "exercise_weight": "80"})
    assert response.status_code == 302
    html = auth_client.get(f"/clients/{client_id}/workouts").get_data(as_text=True)
    assert "2026-10-07" in html and "Strength" in html and "Heavy day" in html
    assert "Back Squat 5 x 5 @ 80 kg" in html


def test_log_workout_without_exercise(auth_client, client_id):
    post(auth_client, f"/clients/{client_id}/workouts", {"workout_type": "Mobility"})
    html = auth_client.get(f"/clients/{client_id}/workouts").get_data(as_text=True)
    assert "Mobility" in html and "No workouts logged yet" not in html


def test_workouts_listed_newest_first(auth_client, client_id):
    for day in ("2026-10-01", "2026-10-05", "2026-10-03"):
        post(auth_client, f"/clients/{client_id}/workouts",
             {"date": day, "workout_type": "Mixed"})
    html = auth_client.get(f"/clients/{client_id}/workouts").get_data(as_text=True)
    assert html.index("2026-10-05") < html.index("2026-10-03") < html.index("2026-10-01")


def test_workout_validation_errors_keep_input(auth_client, client_id, app):
    response = post(auth_client, f"/clients/{client_id}/workouts", {
        "workout_type": "Yoga", "duration_min": "0", "exercise_name": "Squat", "notes": "keep me"})
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Choose a workout type from the list." in html and "Duration (min) must be" in html
    assert 'value="keep me"' in html
    conn = db.connect(app.config["DATABASE"])
    assert db.list_workouts(conn, client_id) == []
    conn.close()


def test_workouts_are_isolated_per_client(auth_client, client_id):
    other = create_client(auth_client, name="Ben Other")
    post(auth_client, f"/clients/{client_id}/workouts",
         {"workout_type": "Strength", "notes": "only asha"})
    assert "only asha" not in auth_client.get(f"/clients/{other}/workouts").get_data(as_text=True)


def test_progress_and_metrics_are_isolated_per_client(auth_client, client_id):
    other = create_client(auth_client, name="Ben Other")
    post(auth_client, f"/clients/{client_id}/progress", {"adherence": "70"})
    page = auth_client.get(f"/clients/{other}").get_data(as_text=True)
    assert "<svg" not in page


def test_tracking_requires_csrf_token(auth_client, client_id):
    assert auth_client.post(f"/clients/{client_id}/progress",
                            data={"adherence": "70"}).status_code == 400
    assert auth_client.post(f"/clients/{client_id}/workouts",
                            data={"workout_type": "Mixed"}).status_code == 400


def test_valid_client_fixture_is_consistent():
    assert VALID_CLIENT["program"] == "fl3"
