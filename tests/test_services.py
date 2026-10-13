"""Unit tests for the pure business logic (no Flask, no database)."""
import random
from datetime import date

import pytest

import services as s

TODAY = date(2026, 10, 8)


# ------------------------------------------------------------ calculations
def test_estimate_calories_uses_program_factor():
    assert s.estimate_calories(60, "fl3") == 1320
    assert s.estimate_calories(80, "mg-ppl") == 2800
    assert s.estimate_calories(70.5, "bg") == int(70.5 * 26)


def test_estimate_calories_default_factor_and_missing_weight():
    assert s.estimate_calories(60, "unknown") == 1500
    assert s.estimate_calories(None, "fl3") is None
    assert s.estimate_calories(0, "fl3") is None


@pytest.mark.parametrize("height,weight,category", [
    (180, 55, "Underweight"), (170, 65, "Normal"),
    (170, 80, "Overweight"), (170, 100, "Obese"),
])
def test_bmi_categories(height, weight, category):
    info = s.bmi_info(height, weight)
    assert info["category"] == category
    assert info["bmi"] == round(weight / (height / 100) ** 2, 1)
    assert info["risk"]


def test_bmi_boundaries():
    assert s.bmi_info(100, 18.5)["category"] == "Normal"
    assert s.bmi_info(100, 25)["category"] == "Overweight"
    assert s.bmi_info(100, 30)["category"] == "Obese"


def test_bmi_missing_inputs():
    assert s.bmi_info(None, 60) is None
    assert s.bmi_info(170, None) is None
    assert s.bmi_info(0, 60) is None


def test_week_label():
    assert s.week_label(date(2026, 10, 8)) == "Week 40 - 2026"


# --------------------------------------------------------------- membership
def test_membership_active_without_end_date():
    info = s.membership_status("Active", None, TODAY)
    assert info == {"state": "Active", "end": None, "days_left": None}


def test_membership_active_future_end():
    info = s.membership_status("Active", "2026-10-18", TODAY)
    assert info["state"] == "Active" and info["days_left"] == 10


def test_membership_ends_today_is_still_active():
    info = s.membership_status("Active", "2026-10-08", TODAY)
    assert info["state"] == "Active" and info["days_left"] == 0


def test_membership_expired():
    info = s.membership_status("Active", "2026-10-01", TODAY)
    assert info["state"] == "Expired" and info["days_left"] == -7


def test_membership_inactive_wins_over_dates():
    assert s.membership_status("Inactive", "2030-01-01", TODAY)["state"] == "Inactive"


# ------------------------------------------------------------- validation
def test_validate_client_accepts_valid_input():
    clean, errors = s.validate_client({
        "name": "  Asha Rao ", "age": "29", "height": "165.5", "weight": "60",
        "program": "fl3", "target_weight": "55", "target_adherence": "90",
        "membership_status": "Active", "membership_end": "2027-01-31"})
    assert errors == {}
    assert clean["name"] == "Asha Rao"
    assert clean["age"] == 29 and clean["height"] == 165.5
    assert clean["membership_end"] == "2027-01-31"


def test_validate_client_optional_fields_become_none():
    clean, errors = s.validate_client({"name": "A", "program": "bg"})
    assert errors == {}
    assert clean["age"] is None and clean["weight"] is None
    assert clean["membership_status"] == "Active"
    assert clean["membership_end"] is None


@pytest.mark.parametrize("field,value", [
    ("name", ""), ("name", "x" * 101), ("program", ""), ("program", "nope"),
    ("age", "0"), ("age", "abc"), ("age", "12.5"), ("height", "10"), ("weight", "nan"),
    ("weight", "inf"), ("target_adherence", "101"), ("membership_status", "Frozen"),
    ("membership_end", "31/01/2027"), ("membership_end", "2027-02-30"),
])
def test_validate_client_rejects_bad_values(field, value):
    form = {"name": "Asha", "program": "fl3", field: value}
    _, errors = s.validate_client(form)
    assert field in errors


def test_validate_progress():
    assert s.validate_progress({"adherence": "85"}) == ({"adherence": 85}, {})
    assert "adherence" in s.validate_progress({"adherence": ""})[1]
    assert "adherence" in s.validate_progress({"adherence": "101"})[1]
    assert "adherence" in s.validate_progress({"adherence": "-1"})[1]
    assert s.validate_progress({"adherence": "0"})[1] == {}


def test_validate_metrics_defaults_date_and_requires_a_measurement():
    clean, errors = s.validate_metrics({"weight": "61.5"}, TODAY)
    assert errors == {} and clean["date"] == "2026-10-08" and clean["waist"] is None
    assert "weight" in s.validate_metrics({}, TODAY)[1]
    assert "bodyfat" in s.validate_metrics({"bodyfat": "95"}, TODAY)[1]
    assert "date" in s.validate_metrics({"weight": "60", "date": "yesterday"}, TODAY)[1]


def test_validate_workout_with_and_without_exercise():
    clean, errors = s.validate_workout({"workout_type": "Strength"}, TODAY)
    assert errors == {} and clean["exercise"] is None
    assert clean["workout"]["duration_min"] == 60
    clean, errors = s.validate_workout({
        "workout_type": "Mixed", "duration_min": "45", "exercise_name": "Squat",
        "sets": "5", "reps": "5", "exercise_weight": "100"}, TODAY)
    assert errors == {}
    assert clean["exercise"] == {"name": "Squat", "sets": 5, "reps": 5, "weight": 100.0}


@pytest.mark.parametrize("field,value", [
    ("workout_type", "Yoga"), ("duration_min", "0"), ("duration_min", "601"),
    ("date", "2026-13-01"), ("sets", "0"), ("reps", "x"),
])
def test_validate_workout_rejects_bad_values(field, value):
    form = {"workout_type": "Strength", "exercise_name": "Squat", field: value}
    assert field in s.validate_workout(form, TODAY)[1]


def test_validate_experience():
    assert s.validate_experience({"experience": " Beginner "}) == ("beginner", {})
    assert "experience" in s.validate_experience({"experience": "expert"})[1]


# --------------------------------------------------------------- generator
def test_generator_is_deterministic_for_a_seed():
    a = s.generate_program("mg-ppl", "intermediate", random.Random(7))
    b = s.generate_program("mg-ppl", "intermediate", random.Random(7))
    assert a == b


@pytest.mark.parametrize("level,days,per_day,sets,reps", [
    ("beginner", 3, 3, (2, 3), (8, 12)),
    ("intermediate", 4, 4, (3, 4), (8, 15)),
    ("advanced", 5, 4, (4, 5), (6, 15)),
])
def test_generator_shape_and_ranges(level, days, per_day, sets, reps):
    plan = s.generate_program("bg", level, random.Random(1))
    assert len(plan) == days * per_day
    assert [r["day"] for r in plan][::per_day] == list(s.WEEK_DAYS[:days])
    assert all(sets[0] <= r["sets"] <= sets[1] for r in plan)
    assert all(reps[0] <= r["reps"] <= reps[1] for r in plan)


@pytest.mark.parametrize("program,focus", [
    ("fl3", "Conditioning"), ("fl5", "Conditioning"),
    ("mg-ppl", "Hypertrophy"), ("bg", "Full Body"), (None, "Full Body"),
])
def test_generator_picks_exercises_from_program_focus(program, focus):
    plan = s.generate_program(program, "beginner", random.Random(3))
    assert {r["exercise"] for r in plan} <= set(s.EXERCISE_POOL[focus])


def test_generator_no_repeat_exercises_within_a_day():
    plan = s.generate_program("fl5", "advanced", random.Random(5))
    for day in s.WEEK_DAYS[:5]:
        names = [r["exercise"] for r in plan if r["day"] == day]
        assert len(names) == len(set(names))


def test_generator_rejects_unknown_experience():
    with pytest.raises(ValueError):
        s.generate_program("bg", "expert", random.Random(1))


# --------------------------------------------------------------- SVG chart
def test_chart_empty_input_returns_empty_string():
    assert s.line_chart_svg("t", [], []) == ""
    assert s.line_chart_svg("t", ["a"], [1, 2]) == ""


def test_chart_structure_and_determinism():
    svg = s.line_chart_svg("Adherence", ["w1", "w2", "w3"], [50, 75, 90], "%", 0, 100)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert svg.count("<circle") == 3 and "<polyline" in svg
    assert svg == s.line_chart_svg("Adherence", ["w1", "w2", "w3"], [50, 75, 90], "%", 0, 100)
    assert "matplotlib" not in svg


def test_chart_single_point_and_flat_series_do_not_crash():
    assert "<circle" in s.line_chart_svg("t", ["a"], [10])
    assert s.line_chart_svg("t", ["a", "b"], [5, 5]).count("<circle") == 2


def test_chart_escapes_labels_and_title():
    svg = s.line_chart_svg("<b>x</b>", ["<script>alert(1)</script>"], [1])
    assert "<script>" not in svg and "<b>x</b>" not in svg
    assert "&lt;script&gt;" in svg


def test_chart_many_points_thins_x_labels():
    labels = [f"d{i}" for i in range(40)]
    svg = s.line_chart_svg("t", labels, list(range(40)))
    assert svg.count("<circle") == 40
    assert svg.count('class="chart-label"') < 40 + 5


# --------------------------------------------------------------------- PDF
SUMMARY = {
    "membership": {"state": "Active", "end": "2027-01-31", "days_left": 115},
    "weeks_logged": 2, "avg_adherence": 80.0,
    "bmi": {"bmi": 22.0, "category": "Normal", "risk": "Low"},
    "plan": {"experience": "beginner",
             "rows": [{"day": "Monday", "exercise": "Lunge", "sets": 3, "reps": 10}]},
}
CLIENT = {"name": "Asha Rao", "age": 29, "height": 165, "weight": 60, "program": "fl3",
          "calories": 1320, "target_weight": 55, "target_adherence": 90}


def test_pdf_is_valid_and_reproducible():
    first = s.build_pdf_report(CLIENT, SUMMARY, TODAY)
    second = s.build_pdf_report(CLIENT, SUMMARY, TODAY)
    assert first.startswith(b"%PDF-") and first.rstrip().endswith(b"%%EOF")
    assert first == second


def test_pdf_handles_missing_values_and_non_latin_names():
    client = {**CLIENT, "name": "Aša \u4e2d\u6587", "age": None, "weight": None, "calories": None}
    summary = {**SUMMARY, "bmi": None, "plan": None}
    assert s.build_pdf_report(client, summary, TODAY).startswith(b"%PDF-")
