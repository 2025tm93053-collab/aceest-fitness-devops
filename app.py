"""ACEest Fitness & Gym - Flask web application.

Run locally:   flask --app app run
Run with WSGI: gunicorn "app:create_app()"
"""
from __future__ import annotations

import hmac
import json
import os
import random
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import date
from functools import lru_cache, wraps

import click
from flask import (Flask, Response, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

import db
import services

ROLES = ("Admin", "Coach")  # informational labels; the source application never enforced roles
MIN_PASSWORD_LENGTH = 8
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Hash checked for unknown usernames so login timing does not reveal them."""
    return generate_password_hash(secrets.token_hex(8))


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def validate_new_user(username: str, password: str) -> str | None:
    """Return an error message, or None when the credentials are acceptable."""
    if not USERNAME_RE.match(username or ""):
        return "Username must be 3-50 characters: letters, digits, '.', '_' or '-'."
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    secret = os.environ.get("SECRET_KEY")
    app.config.from_mapping(
        SECRET_KEY=secret or secrets.token_hex(32),
        DATABASE=os.environ.get("ACEEST_DB_PATH") or os.path.join(app.instance_path, "aceest.db"),
        BOOTSTRAP_ADMIN_USERNAME=os.environ.get("ACEEST_ADMIN_USERNAME"),
        BOOTSTRAP_ADMIN_PASSWORD=os.environ.get("ACEEST_ADMIN_PASSWORD"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_env_flag("ACEEST_COOKIE_SECURE"),
        MAX_CONTENT_LENGTH=64 * 1024,
        PROGRAM_RNG_SEED=None,  # tests set an int for reproducible generated programs
        TODAY_FUNC=None,        # tests inject a fixed clock
    )
    if test_config:
        app.config.update(test_config)
    if not secret and not (test_config and "SECRET_KEY" in test_config):
        app.logger.warning("SECRET_KEY is not set: using a random key, so sessions end "
                           "whenever the server restarts. Set SECRET_KEY for stable sessions.")

    database_dir = os.path.dirname(os.path.abspath(app.config["DATABASE"]))
    os.makedirs(database_dir, exist_ok=True)
    with closing(db.connect(app.config["DATABASE"])) as conn:
        db.init_db(conn)
        _bootstrap_admin(app, conn)

    register_security(app)
    register_routes(app)
    register_cli(app)
    return app


# ----------------------------------------------------------------- helpers

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = db.connect(current_app.config["DATABASE"])
    return g.db


def _today() -> date:
    clock = current_app.config.get("TODAY_FUNC")
    return clock() if clock else date.today()


def _bootstrap_admin(app: Flask, conn: sqlite3.Connection) -> None:
    """Create the first account from environment variables, if both are provided."""
    username = app.config.get("BOOTSTRAP_ADMIN_USERNAME")
    password = app.config.get("BOOTSTRAP_ADMIN_PASSWORD")
    app.config["BOOTSTRAP_ADMIN_PASSWORD"] = None  # do not keep the secret around
    if not username or not password:
        return
    error = validate_new_user(username, password)
    if error:
        app.logger.error("Bootstrap admin not created: %s", error)
        return
    if db.get_user_by_username(conn, username) is None:
        db.create_user(conn, username, generate_password_hash(password), "Admin")
        app.logger.info("Bootstrap admin account %r created.", username)


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def _safe_next(target: str | None) -> str | None:
    """Only follow same-site relative redirects (blocks open redirects)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            target = request.path if request.method == "GET" else None
            return redirect(url_for("login", next=target))
        return view(*args, **kwargs)
    return wrapped


def _client_or_404(client_id: int):
    client = db.get_client(get_db(), client_id)
    if client is None:
        abort(404)
    return client


# ---------------------------------------------------------------- security

def register_security(app: Flask) -> None:
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["csrf_field"] = lambda: Markup(
        f'<input type="hidden" name="csrf_token" value="{csrf_token()}">')

    @app.before_request
    def load_user_and_check_csrf():
        g.user = None
        if request.endpoint == "static":
            return None
        user_id = session.get("user_id")
        if user_id is not None:
            g.user = db.get_user(get_db(), user_id)
            if g.user is None:
                session.pop("user_id", None)
        if request.method in UNSAFE_METHODS:
            expected = session.get("csrf_token", "")
            supplied = request.form.get("csrf_token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                abort(400, description="Your form session expired. Reload the page and try again.")
        return None

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'")
        return response

    def render_error(error):
        code = getattr(error, "code", 500)
        message = getattr(error, "description", "Something went wrong.")
        if code == 404:
            message = "We could not find that page."
        return render_template("error.html", code=code, message=message), code

    for code in (400, 404, 405, 500):
        app.register_error_handler(code, render_error)


# ------------------------------------------------------------------ routes

def _form_values(client=None, source=None) -> dict[str, str]:
    """Strings for pre-filling the client form."""
    fields = ("name", "age", "height", "weight", "program", "target_weight",
              "target_adherence", "membership_status", "membership_end")
    if source is not None:
        return {f: source.get(f, "") for f in fields}
    if client is None:
        return {f: "" for f in fields} | {"membership_status": "Active"}
    return {f: ("" if client[f] is None else str(client[f])) for f in fields}


def _client_context(client) -> dict:
    conn = get_db()
    progress = db.list_progress(conn, client["id"])
    weeks, average = db.progress_stats(conn, client["id"])
    metrics = db.list_metrics(conn, client["id"])
    weights = [m for m in metrics if m["weight"] is not None]
    plan = json.loads(client["generated_program"]) if client["generated_program"] else None
    return {
        "client": client,
        "program": services.PROGRAMS.get(client["program"]),
        "membership": services.membership_status(
            client["membership_status"], client["membership_end"], _today()),
        "bmi": services.bmi_info(client["height"], client["weight"]),
        "weeks_logged": weeks,
        "avg_adherence": average,
        "last_metric": db.latest_metric(conn, client["id"]),
        "adherence_chart": services.line_chart_svg(
            "Weekly adherence", [p["week"] for p in progress],
            [p["adherence"] for p in progress], "%", y_min=0, y_max=100),
        "weight_chart": services.line_chart_svg(
            "Weight trend", [m["date"] for m in weights], [m["weight"] for m in weights], "kg"),
        "plan": plan,
        "experience_levels": list(services.EXPERIENCE_LEVELS),
        "errors": {},
        "form": {},
    }


def register_routes(app: Flask) -> None:

    @app.get("/health")
    def health():
        try:
            db.ping(get_db())
        except sqlite3.Error:
            return jsonify(status="error"), 503
        return jsonify(status="ok")

    @app.get("/")
    def index():
        return redirect(url_for("dashboard" if g.user else "login"))

    # ---- authentication
    @app.route("/login", methods=("GET", "POST"))
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = db.get_user_by_username(get_db(), username)
            hashed = user["password_hash"] if user else _dummy_hash()
            if check_password_hash(hashed, password) and user is not None:
                session.clear()
                session["user_id"] = user["id"]
                return redirect(_safe_next(request.args.get("next")) or url_for("dashboard"))
            flash("Invalid username or password.", "error")
            return render_template("login.html", username=username), 401
        if g.user:
            return redirect(url_for("dashboard"))
        return render_template("login.html", username="")

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "info")
        return redirect(url_for("login"))

    # ---- dashboard and clients
    @app.get("/dashboard")
    @login_required
    def dashboard():
        today = _today()
        rows = [{
            "client": c,
            "program": services.PROGRAMS.get(c["program"]),
            "membership": services.membership_status(
                c["membership_status"], c["membership_end"], today),
        } for c in db.list_clients(get_db())]
        return render_template("dashboard.html", rows=rows)

    def _save_client(client_id: int | None):
        clean, errors = services.validate_client(request.form)
        if not errors:
            clean["calories"] = services.estimate_calories(clean["weight"], clean["program"])
            try:
                if client_id is None:
                    client_id = db.create_client(get_db(), clean)
                    flash("Client created.", "success")
                else:
                    db.update_client(get_db(), client_id, clean)
                    flash("Client updated.", "success")
                return redirect(url_for("client_detail", client_id=client_id))
            except sqlite3.IntegrityError:
                errors["name"] = "A client with this name already exists."
        client = db.get_client(get_db(), client_id) if client_id else None
        return render_template("client_form.html", client=client, errors=errors,
                               form=_form_values(source=request.form),
                               programs=services.PROGRAMS), 400

    @app.route("/clients/new", methods=("GET", "POST"))
    @login_required
    def client_new():
        if request.method == "POST":
            return _save_client(None)
        return render_template("client_form.html", client=None, errors={},
                               form=_form_values(), programs=services.PROGRAMS)

    @app.route("/clients/<int:client_id>/edit", methods=("GET", "POST"))
    @login_required
    def client_edit(client_id: int):
        client = _client_or_404(client_id)
        if request.method == "POST":
            return _save_client(client_id)
        return render_template("client_form.html", client=client, errors={},
                               form=_form_values(client), programs=services.PROGRAMS)

    @app.get("/clients/<int:client_id>")
    @login_required
    def client_detail(client_id: int):
        return render_template("client.html", **_client_context(_client_or_404(client_id)))

    def _client_page_with_errors(client, errors: dict, form):
        context = _client_context(client)
        context.update(errors=errors, form=form)
        return render_template("client.html", **context), 400

    # ---- progress, metrics, program
    @app.post("/clients/<int:client_id>/progress")
    @login_required
    def add_progress(client_id: int):
        client = _client_or_404(client_id)
        clean, errors = services.validate_progress(request.form)
        if errors:
            return _client_page_with_errors(client, errors, request.form)
        db.add_progress(get_db(), client_id, services.week_label(_today()), clean["adherence"])
        flash("Weekly adherence logged.", "success")
        return redirect(url_for("client_detail", client_id=client_id))

    @app.post("/clients/<int:client_id>/metrics")
    @login_required
    def add_metrics(client_id: int):
        client = _client_or_404(client_id)
        clean, errors = services.validate_metrics(request.form, _today())
        if errors:
            return _client_page_with_errors(client, errors, request.form)
        db.add_metric(get_db(), client_id, clean)
        flash("Body metrics logged.", "success")
        return redirect(url_for("client_detail", client_id=client_id))

    @app.post("/clients/<int:client_id>/program")
    @login_required
    def generate_program(client_id: int):
        client = _client_or_404(client_id)
        level, errors = services.validate_experience(request.form)
        if errors:
            return _client_page_with_errors(client, errors, request.form)
        seed = current_app.config.get("PROGRAM_RNG_SEED")
        rows = services.generate_program(client["program"], level, random.Random(seed))
        db.set_generated_program(get_db(), client_id,
                                 json.dumps({"experience": level, "rows": rows}))
        flash("Program generated.", "success")
        return redirect(url_for("client_detail", client_id=client_id))

    # ---- workouts
    def _workouts_page(client, errors: dict, form, status: int = 200):
        return render_template(
            "workouts.html", client=client, workouts=db.list_workouts(get_db(), client["id"]),
            workout_types=services.WORKOUT_TYPES, errors=errors, form=form,
            today=_today().isoformat()), status

    @app.route("/clients/<int:client_id>/workouts", methods=("GET", "POST"))
    @login_required
    def workouts(client_id: int):
        client = _client_or_404(client_id)
        if request.method == "POST":
            clean, errors = services.validate_workout(request.form, _today())
            if errors:
                return _workouts_page(client, errors, request.form, 400)
            db.add_workout(get_db(), client_id, clean["workout"], clean["exercise"])
            flash("Workout logged.", "success")
            return redirect(url_for("workouts", client_id=client_id))
        return _workouts_page(client, {}, {})

    # ---- PDF report
    @app.get("/clients/<int:client_id>/report.pdf")
    @login_required
    def client_report(client_id: int):
        context = _client_context(_client_or_404(client_id))
        pdf = services.build_pdf_report(dict(context["client"]), context, _today())
        return Response(pdf, mimetype="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="client-{client_id}-report.pdf"'})


# --------------------------------------------------------------------- CLI

def register_cli(app: Flask) -> None:

    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--role", type=click.Choice(ROLES, case_sensitive=False), default="Admin",
                  show_default=True, help="Informational role label stored with the account.")
    @click.password_option(help="Password (prompted, hidden, when omitted).")
    def create_user_command(username: str, role: str, password: str) -> None:
        """Create a user account with a hashed password."""
        error = validate_new_user(username, password)
        if error:
            raise click.ClickException(error)
        role = next(r for r in ROLES if r.lower() == role.lower())
        try:
            db.create_user(get_db(), username, generate_password_hash(password), role)
        except sqlite3.IntegrityError:
            raise click.ClickException(f"User {username!r} already exists.") from None
        click.echo(f"Created {role} user {username!r}.")
