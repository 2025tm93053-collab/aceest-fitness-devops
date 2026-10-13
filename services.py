"""Pure business logic for ACEest Fitness & Gym.

Nothing in this module touches Flask or the database, so every function can be
unit-tested in isolation and behaves deterministically given its inputs.
"""
from __future__ import annotations

import html
import math
import re
from datetime import date, datetime
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Reference data (consolidated from the desktop prototypes v2.2.4 / v3.1.2)
# ---------------------------------------------------------------------------

PROGRAMS: dict[str, dict[str, Any]] = {
    "fl3": {"name": "Fat Loss (FL) - 3 day", "factor": 22,
            "desc": "3-day full-body fat loss", "focus": "Conditioning"},
    "fl5": {"name": "Fat Loss (FL) - 5 day", "factor": 24,
            "desc": "5-day split, higher volume fat loss", "focus": "Conditioning"},
    "mg-ppl": {"name": "Muscle Gain (MG) - PPL", "factor": 35,
               "desc": "Push/Pull/Legs hypertrophy", "focus": "Hypertrophy"},
    "bg": {"name": "Beginner (BG)", "factor": 26,
           "desc": "3-day simple beginner full-body", "focus": "Full Body"},
}
DEFAULT_CALORIE_FACTOR = 25

MEMBERSHIP_STATUSES = ("Active", "Inactive")
WORKOUT_TYPES = ("Strength", "Hypertrophy", "Conditioning", "Mixed", "Mobility")

# experience -> (sets range, reps range, training days)
EXPERIENCE_LEVELS: dict[str, tuple[tuple[int, int], tuple[int, int], int]] = {
    "beginner": ((2, 3), (8, 12), 3),
    "intermediate": ((3, 4), (8, 15), 4),
    "advanced": ((4, 5), (6, 15), 5),
}
WEEK_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
EXERCISE_POOL: dict[str, tuple[str, ...]] = {
    "Hypertrophy": ("Leg Press", "Incline Dumbbell Press", "Lat Pulldown",
                    "Lateral Raise", "Bicep Curl", "Tricep Extension"),
    "Conditioning": ("Running", "Cycling", "Rowing", "Burpees",
                     "Jump Rope", "Kettlebell Swings"),
    "Full Body": ("Push-Up", "Pull-Up", "Lunge", "Plank",
                  "Dumbbell Row", "Dumbbell Press"),
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def estimate_calories(weight_kg: float | None, program: str | None) -> int | None:
    """Daily calorie estimate: body weight x program factor."""
    if not weight_kg or weight_kg <= 0:
        return None
    factor = PROGRAMS.get(program or "", {}).get("factor", DEFAULT_CALORIE_FACTOR)
    return int(weight_kg * factor)


def bmi_info(height_cm: float | None, weight_kg: float | None) -> dict[str, Any] | None:
    """BMI, category and risk note. Returns None when inputs are missing."""
    if not height_cm or not weight_kg or height_cm <= 0 or weight_kg <= 0:
        return None
    metres = height_cm / 100.0
    bmi = round(weight_kg / (metres * metres), 1)
    if bmi < 18.5:
        category, risk = "Underweight", "Potential nutrient deficiency, low energy."
    elif bmi < 25:
        category, risk = "Normal", "Low risk if active and strong."
    elif bmi < 30:
        category = "Overweight"
        risk = "Moderate risk; focus on adherence and progressive activity."
    else:
        category = "Obese"
        risk = "Higher risk; prioritize fat loss, consistency, and supervision."
    return {"bmi": bmi, "category": category, "risk": risk}


def membership_status(status: str | None, end: str | None, today: date) -> dict[str, Any]:
    """Effective membership state.

    A stored "Inactive" status always wins. Otherwise a membership whose end
    date is before ``today`` is "Expired"; anything else is "Active".
    """
    end_date = date.fromisoformat(end) if end else None
    days_left = (end_date - today).days if end_date else None
    if status == "Inactive":
        state = "Inactive"
    elif end_date is not None and end_date < today:
        state = "Expired"
    else:
        state = "Active"
    return {"state": state, "end": end, "days_left": days_left}


def week_label(day: date) -> str:
    """Week label used for adherence entries, e.g. 'Week 40 - 2026'."""
    return day.strftime("Week %U - %Y")


# ---------------------------------------------------------------------------
# Input validation - each returns (clean_values, errors)
# ---------------------------------------------------------------------------

def _number(raw: Any, cast: type, label: str, lo: float, hi: float,
            errors: dict[str, str], key: str, required: bool = False):
    text = (raw or "").strip() if isinstance(raw, str) or raw is None else str(raw).strip()
    if text == "":
        if required:
            errors[key] = f"{label} is required."
        return None
    try:
        value = cast(text)
    except ValueError:
        errors[key] = f"{label} must be a number."
        return None
    if isinstance(value, float) and not math.isfinite(value):
        errors[key] = f"{label} must be a number."
        return None
    if not lo <= value <= hi:
        errors[key] = f"{label} must be between {lo:g} and {hi:g}."
        return None
    return value


def _date(raw: Any, label: str, errors: dict[str, str], key: str, required: bool = False):
    text = (raw or "").strip()
    if text == "":
        if required:
            errors[key] = f"{label} is required."
        return None
    if not _DATE_RE.match(text):
        errors[key] = f"{label} must use the format YYYY-MM-DD."
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        errors[key] = f"{label} is not a valid date."
        return None


def validate_client(form: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, str]]:
    errors: dict[str, str] = {}
    name = (form.get("name") or "").strip()
    if not name:
        errors["name"] = "Name is required."
    elif len(name) > 100:
        errors["name"] = "Name must be 100 characters or fewer."

    program = (form.get("program") or "").strip()
    if not program:
        errors["program"] = "Program is required."
    elif program not in PROGRAMS:
        errors["program"] = "Choose a program from the list."

    status = (form.get("membership_status") or "").strip() or "Active"
    if status not in MEMBERSHIP_STATUSES:
        errors["membership_status"] = "Membership status must be Active or Inactive."

    clean = {
        "name": name,
        "age": _number(form.get("age"), int, "Age", 1, 120, errors, "age"),
        "height": _number(form.get("height"), float, "Height (cm)", 50, 260, errors, "height"),
        "weight": _number(form.get("weight"), float, "Weight (kg)", 20, 500, errors, "weight"),
        "program": program,
        "target_weight": _number(form.get("target_weight"), float, "Target weight (kg)",
                                 20, 500, errors, "target_weight"),
        "target_adherence": _number(form.get("target_adherence"), int, "Target adherence (%)",
                                    1, 100, errors, "target_adherence"),
        "membership_status": status,
        "membership_end": _date(form.get("membership_end"), "Membership end date",
                                errors, "membership_end"),
    }
    return clean, errors


def validate_progress(form: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, str]]:
    errors: dict[str, str] = {}
    adherence = _number(form.get("adherence"), int, "Adherence (%)", 0, 100,
                        errors, "adherence", required=True)
    return {"adherence": adherence}, errors


def validate_metrics(form: Mapping[str, str],
                     today: date) -> tuple[dict[str, Any], dict[str, str]]:
    errors: dict[str, str] = {}
    when = _date(form.get("date") or today.isoformat(), "Date", errors, "date", required=True)
    clean = {
        "date": when,
        "weight": _number(form.get("weight"), float, "Weight (kg)", 20, 500, errors, "weight"),
        "waist": _number(form.get("waist"), float, "Waist (cm)", 20, 300, errors, "waist"),
        "bodyfat": _number(form.get("bodyfat"), float, "Body fat (%)", 1, 80, errors, "bodyfat"),
    }
    if not errors and all(clean[k] is None for k in ("weight", "waist", "bodyfat")):
        errors["weight"] = "Enter at least one measurement."
    return clean, errors


def validate_workout(form: Mapping[str, str],
                     today: date) -> tuple[dict[str, Any], dict[str, str]]:
    errors: dict[str, str] = {}
    when = _date(form.get("date") or today.isoformat(), "Date", errors, "date", required=True)
    workout_type = (form.get("workout_type") or "").strip()
    if workout_type not in WORKOUT_TYPES:
        errors["workout_type"] = "Choose a workout type from the list."
    duration = _number(form.get("duration_min") or "60", int, "Duration (min)", 1, 600,
                       errors, "duration_min", required=True)
    notes = (form.get("notes") or "").strip()
    if len(notes) > 1000:
        errors["notes"] = "Notes must be 1000 characters or fewer."

    exercise = None
    ex_name = (form.get("exercise_name") or "").strip()
    if ex_name:
        if len(ex_name) > 100:
            errors["exercise_name"] = "Exercise name must be 100 characters or fewer."
        exercise = {
            "name": ex_name,
            "sets": _number(form.get("sets") or "3", int, "Sets", 1, 50, errors, "sets",
                            required=True),
            "reps": _number(form.get("reps") or "10", int, "Reps", 1, 500, errors, "reps",
                            required=True),
            "weight": _number(form.get("exercise_weight") or "0", float, "Exercise weight (kg)",
                              0, 1000, errors, "exercise_weight", required=True),
        }
    workout = {"date": when, "workout_type": workout_type,
               "duration_min": duration, "notes": notes}
    return {"workout": workout, "exercise": exercise}, errors


def validate_experience(form: Mapping[str, str]) -> tuple[str | None, dict[str, str]]:
    level = (form.get("experience") or "").strip().lower()
    if level not in EXPERIENCE_LEVELS:
        return None, {"experience": "Choose beginner, intermediate or advanced."}
    return level, {}


# ---------------------------------------------------------------------------
# Program generator (v3.1.2 logic, made deterministic via an injected RNG)
# ---------------------------------------------------------------------------

def generate_program(program: str | None, experience: str, rng) -> list[dict[str, Any]]:
    """Build a weekly plan from the client's program and experience level.

    ``rng`` is any object with ``sample`` and ``randint`` (e.g. random.Random),
    so callers - and tests - control the randomness.
    """
    if experience not in EXPERIENCE_LEVELS:
        raise ValueError(f"Unknown experience level: {experience!r}")
    sets_range, reps_range, days = EXPERIENCE_LEVELS[experience]
    focus = PROGRAMS.get(program or "", {}).get("focus", "Full Body")
    per_day = 3 if days < 4 else 4
    plan = []
    for day in WEEK_DAYS[:days]:
        for exercise in rng.sample(EXERCISE_POOL[focus], k=per_day):
            plan.append({"day": day, "exercise": exercise,
                         "sets": rng.randint(*sets_range),
                         "reps": rng.randint(*reps_range)})
    return plan


# ---------------------------------------------------------------------------
# SVG line chart (headless: plain string output, no GUI or plotting library)
# ---------------------------------------------------------------------------

def line_chart_svg(title: str, labels: list[str], values: list[float], unit: str = "",
                   y_min: float | None = None, y_max: float | None = None,
                   width: int = 640, height: int = 280) -> str:
    """Render a line chart as an inline SVG string. Empty input gives ''."""
    if not values or len(labels) != len(values):
        return ""
    left, right, top, bottom = 52, 16, 30, 62
    plot_w, plot_h = width - left - right, height - top - bottom

    lo = min(values) if y_min is None else y_min
    hi = max(values) if y_max is None else y_max
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    elif y_min is None and y_max is None:
        margin = (hi - lo) * 0.1
        lo, hi = lo - margin, hi + margin

    def x_at(i: int) -> float:
        return left + plot_w / 2 if len(values) == 1 else left + plot_w * i / (len(values) - 1)

    def y_at(v: float) -> float:
        return top + plot_h * (1 - (v - lo) / (hi - lo))

    esc = html.escape
    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{esc(title)}" xmlns="http://www.w3.org/2000/svg">',
        f'<title>{esc(title)}</title>',
        f'<text class="chart-title" x="{left}" y="18">{esc(title)}'
        f'{" (" + esc(unit) + ")" if unit else ""}</text>',
    ]
    for step in range(5):
        value = lo + (hi - lo) * step / 4
        y = y_at(value)
        parts.append(f'<line class="chart-grid" x1="{left}" y1="{y:.1f}" '
                     f'x2="{width - right}" y2="{y:.1f}"/>')
        parts.append(f'<text class="chart-label" x="{left - 6}" y="{y + 4:.1f}" '
                     f'text-anchor="end">{value:.0f}</text>')
    parts.append(f'<line class="chart-axis" x1="{left}" y1="{top + plot_h}" '
                 f'x2="{width - right}" y2="{top + plot_h}"/>')

    stride = max(1, math.ceil(len(values) / 8))
    for i, label in enumerate(labels):
        if i % stride == 0 or i == len(labels) - 1:
            x, y = x_at(i), top + plot_h + 14
            parts.append(f'<text class="chart-label" x="{x:.1f}" y="{y}" text-anchor="end" '
                         f'transform="rotate(-30 {x:.1f} {y})">{esc(label)}</text>')

    points = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(values))
    parts.append(f'<polyline class="chart-line" fill="none" points="{points}"/>')
    for i, v in enumerate(values):
        parts.append(f'<circle class="chart-dot" cx="{x_at(i):.1f}" cy="{y_at(v):.1f}" r="3.5">'
                     f'<title>{esc(labels[i])}: {v:g}{esc(unit)}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# PDF report (fpdf2, core fonts only, fixed metadata -> reproducible bytes)
# ---------------------------------------------------------------------------

def _latin1(text: Any) -> str:
    """Core PDF fonts only cover Latin-1; replace anything else with '?'."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def build_pdf_report(client: Mapping[str, Any], summary: Mapping[str, Any],
                     generated_on: date) -> bytes:
    """Return a one-client PDF report. Identical input gives identical bytes."""
    from fpdf import FPDF

    def show(value: Any, suffix: str = "") -> str:
        return "-" if value is None or value == "" else f"{value}{suffix}"

    pdf = FPDF()
    pdf.set_creation_date(datetime(generated_on.year, generated_on.month, generated_on.day))
    pdf.set_title("ACEest Client Report")
    pdf.set_author("ACEest Fitness & Gym")
    pdf.add_page()

    def line(text: str, style: str = "", size: int = 12, align: str = "L") -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, 8, _latin1(text), align=align, new_x="LMARGIN", new_y="NEXT")

    program = PROGRAMS.get(client.get("program") or "", {}).get("name", "-")
    line(f"Client Report - {client['name']}", "B", 16, "C")
    line(f"Generated on {generated_on.isoformat()}", "", 10, "C")
    pdf.ln(4)
    line("Profile", "B", 13)
    line(f"Age: {show(client.get('age'))}")
    line(f"Height: {show(client.get('height'), ' cm')}")
    line(f"Weight: {show(client.get('weight'), ' kg')}")
    line(f"Program: {program}")
    line(f"Estimated calories: {show(client.get('calories'), ' kcal/day')}")
    pdf.ln(2)
    line("Goals", "B", 13)
    line(f"Target weight: {show(client.get('target_weight'), ' kg')}")
    line(f"Target adherence: {show(client.get('target_adherence'), '%')}")
    pdf.ln(2)
    line("Membership", "B", 13)
    line(f"Status: {summary['membership']['state']}")
    line(f"End date: {show(summary['membership']['end'])}")
    pdf.ln(2)
    line("Progress", "B", 13)
    line(f"Weeks logged: {summary['weeks_logged']}")
    line(f"Average adherence: {summary['avg_adherence']}%")
    bmi = summary.get("bmi")
    line(f"BMI: {bmi['bmi']} ({bmi['category']})" if bmi else "BMI: -")
    plan = summary.get("plan")
    if plan:
        pdf.ln(2)
        line(f"Weekly plan ({plan['experience']})", "B", 13)
        for row in plan["rows"]:
            line(f"{row['day']}: {row['exercise']} - {row['sets']} x {row['reps']}")
    return bytes(pdf.output())
