# ACEest Fitness & Gym

A Flask web application for running a small gym: client profiles, membership tracking,
weekly adherence, body metrics, workout logs, generated training programs and PDF
reports. It is the web migration of the earlier ACEest desktop prototypes (v1.0 to
v3.2.4), delivered with a complete CI/CD setup: Pytest, Docker, GitHub Actions and Jenkins.

Stack: **Flask + SQLite + Pytest + Docker + Jenkins + GitHub Actions**. Nothing else.

## Contents

1. [Features](#features)
2. [Project layout](#project-layout)
3. [Run locally](#run-locally)
4. [Create users](#create-users)
5. [Manual test walkthrough](#manual-test-walkthrough)
6. [Automated tests and lint](#automated-tests-and-lint)
7. [Docker](#docker)
8. [GitHub Actions](#github-actions)
9. [Jenkins](#jenkins)
10. [Git workflow](#git-workflow)
11. [Security notes and limitations](#security-notes-and-limitations)
12. [Origin of the features](#origin-of-the-features)

## Features

| Area | What it does |
|---|---|
| Authentication | Session login/logout, hashed passwords, CSRF protection on every form, no default account |
| Clients | Create, edit and list clients (age, height, weight, program, target weight, target adherence) |
| Calories | Daily estimate = weight x program factor (Fat Loss 22/24, Muscle Gain 35, Beginner 26) |
| Membership | Status (Active/Inactive) and end date. An end date in the past shows as **Expired** |
| Progress | Weekly adherence log, average, weeks logged |
| Body metrics | Weight, waist and body-fat log, latest entry summary, BMI with risk note |
| Workouts | Workout log (date, type, duration, notes) with an optional exercise (sets x reps @ weight) |
| Program generator | Weekly plan from the client's program and an experience level; the latest plan is saved |
| Charts | Adherence and weight-trend line charts rendered as inline SVG (no plotting library, no JavaScript) |
| PDF report | Per-client report generated with fpdf2 |
| Health check | `GET /health` for Docker and CI |

## Project layout

```
app.py                  Flask app factory, routes, authentication, CSRF, CLI command
db.py                   SQLite schema and queries (client_id foreign keys, ON DELETE CASCADE)
services.py             Pure logic: calories, BMI, membership, validation, generator, SVG, PDF
templates/ static/      Jinja templates and stylesheet
tests/                  Pytest suite (services, database, auth, clients, tracking, programs, PDF)
requirements.txt        Runtime dependencies (pinned)
requirements-dev.txt    Test and lint dependencies (pinned, not in the runtime image)
Dockerfile              Multi-stage build: base -> test, base -> runtime
Jenkinsfile             Jenkins pipeline
.github/workflows/main.yml   GitHub Actions pipeline
.env.example            Configuration template (placeholders only)
```

## Run locally

Requires Python 3.12 (Flask 3.1 itself supports older 3.x versions, but 3.12 is what CI and Docker use).

```bash
git clone <your-repository-url>
cd <repository-folder>

python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt  # or requirements.txt if you only want to run the app

# Stable session signing key (otherwise a random key is generated on every start)
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"

# Create your first account (prompts for a hidden password)
flask --app app create-user <your-username>

flask --app app run                  # http://127.0.0.1:5000
```

On Windows PowerShell set variables with `$env:SECRET_KEY = "..."` instead of `export`.
`gunicorn` is not installed on Windows (see `requirements.txt`); use `flask run` there.

### Configuration

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Signs session cookies. Set it for sessions that survive restarts | random per start (warning logged) |
| `ACEEST_DB_PATH` | SQLite file location | `instance/aceest.db` (`/data/aceest.db` in Docker) |
| `ACEEST_ADMIN_USERNAME`, `ACEEST_ADMIN_PASSWORD` | Optional: create the first account on startup (both required, password at least 8 characters). An existing user is never overwritten | unset |
| `ACEEST_COOKIE_SECURE` | Set to `1` when serving over HTTPS | off |

See `.env.example`. Never commit a real `.env` file; it is git-ignored.

## Create users

There is deliberately **no default account**. Create users in one of two ways:

1. **CLI (recommended).** Prompts for the password, which is hashed before storage:

   ```bash
   flask --app app create-user alice                 # role defaults to Admin
   flask --app app create-user bob --role Coach
   ```

   Usernames are 3 to 50 characters (letters, digits, `.`, `_`, `-`); passwords need at
   least 8 characters. Roles are informational labels shown in the header.

2. **Environment variables.** Start the app with `ACEEST_ADMIN_USERNAME` and
   `ACEEST_ADMIN_PASSWORD` set; if that user does not exist yet it is created as `Admin`.
   Useful for containers (see [Docker](#docker)).

## Manual test walkthrough

Start the app, sign in, then check each item:

1. **Login protection.** Open `/dashboard` while signed out: you are redirected to the sign-in page. A wrong password shows "Invalid username or password."
2. **Create a client.** Add client, enter name `Asha Rao`, weight `60`, height `165`, program *Fat Loss (FL) - 3 day*. Expect the client page with `1320 kcal/day` and BMI `22.0 Normal`.
3. **Validation.** Submit the form with an empty name or age `abc`: the form returns with an error message under the field and nothing is saved.
4. **Membership.** Edit the client and set the end date to a past date: the badge becomes **Expired**. Set a future date: **Active** with days left.
5. **Adherence.** Log `80`, then `90`: weeks logged `2`, average `85.0%`, and an adherence chart appears.
6. **Metrics.** Log a weight: "Last metrics" updates, and the weight-trend chart appears after a weight is logged.
7. **Workouts.** Open Workouts, log a Strength session with exercise `Back Squat`, 5 sets, 5 reps: it appears in the history, newest first.
8. **Program.** Choose an experience level and generate: a weekly table appears and survives a page reload.
9. **PDF.** Click PDF report: a PDF downloads containing profile, goals, membership, progress and the plan.
10. **Sign out.** Use Sign out; `/dashboard` redirects to sign-in again.

## Automated tests and lint

```bash
pytest -q        # the whole suite
flake8           # lint (max line length 100, see .flake8)
python -m compileall -q app.py db.py services.py tests   # build check used in CI
```

The tests use a temporary SQLite file per test, a fixed clock and a seeded random
generator, so they are deterministic and need no network or display. They cover the pure
logic (calories, BMI, membership, validation, generator, SVG, PDF), the database layer
(foreign keys, cascades, atomic writes), authentication (hashing, CSRF, open-redirect
protection, bootstrap credentials, the `create-user` command) and every route.

## Docker

The `Dockerfile` is multi-stage:

| Stage | Purpose | Contains |
|---|---|---|
| `base` | Shared layer | Python 3.12 slim + runtime dependencies |
| `test` | `docker build --target test` | `base` + pytest/flake8 + tests |
| `runtime` | Default (last stage) | `base` + application code only, runs as a non-root user |

The runtime image has no test or development dependencies and no tests.

```bash
# Build the runtime image
docker build -t aceest-fitness .

# Run it (named volume keeps the SQLite database between runs)
docker run --rm -p 5000:5000 \
  -e SECRET_KEY="<random-value>" \
  -e ACEEST_ADMIN_USERNAME="<admin-username>" \
  -e ACEEST_ADMIN_PASSWORD="<choose-a-password>" \
  -v aceest-data:/data \
  aceest-fitness
# open http://localhost:5000 and check http://localhost:5000/health

# Add another user to a running container
docker exec -it <container-name> flask create-user alice

# Build the test image and run Pytest INSIDE the container
docker build --target test -t aceest-fitness:test .
docker run --rm aceest-fitness:test pytest -q
```

The container runs Gunicorn with a single worker and four threads. Sessions are signed
cookies, so one worker with a fixed `SECRET_KEY` keeps logins valid without any shared
store. If you bind-mount a host folder instead of a named volume, make it writable by UID 10001.

## GitHub Actions

Workflow file: `.github/workflows/main.yml`. It runs on every **push** and every
**pull_request**.

| Job | Steps | Fails the pipeline when |
|---|---|---|
| **Build & Lint** (`build-lint`) | Install pinned dev dependencies, `compileall` the sources, run `flake8` | A syntax error or lint violation exists |
| **Docker image assembly & containerized tests** (`docker-build-and-test`, runs only after the first job passes) | Build the `runtime` image, build the `test` image, run `pytest -q` inside the test container, start the runtime container and check `/health` | The image fails to build, any test fails inside the container, or the runtime container never becomes healthy |

Pytest therefore runs inside the container built from the Dockerfile's `test` target,
not on the runner's Python.

## Jenkins

`Jenkinsfile` (declarative pipeline) does a clean build from GitHub on each run.

**One-time setup**

1. A Jenkins server whose agent has `git` and Docker, and whose `jenkins` user can run `docker` (for example, member of the `docker` group).
2. Plugins: *Pipeline*, *Git* and *JUnit* (the last is normally bundled). No other plugins are needed.
3. Create a **Pipeline** job. Under *Pipeline*, choose **Pipeline script from SCM**, SCM **Git**, enter your public repository URL, branch `*/main`, script path `Jenkinsfile`.
4. Build triggers: the Jenkinsfile polls SCM every ~5 minutes. For instant builds, add a GitHub webhook to `http://<your-jenkins>/github-webhook/` (needs a publicly reachable Jenkins and the *GitHub* plugin's trigger enabled in the job). Otherwise rely on polling or press **Build Now**.

**What a build does**

| Stage | Action |
|---|---|
| Clean workspace | `deleteDir()` removes everything from earlier builds |
| Checkout | Pulls the latest commit from GitHub |
| Build | `docker build --no-cache --pull` for the `runtime` and `test` targets |
| Test (Pytest in container) | Runs `pytest -q` inside the test image and publishes the JUnit report |
| Smoke test | Starts the runtime image and checks `/health` from inside the container |
| Post | Removes containers and the images tagged for this build |

## Git workflow

```bash
git init -b main
git add .
git commit -m "Add Flask application, database layer and business logic"
git remote add origin <your-github-repository-url>
git push -u origin main
```

Suggested branch and commit structure for the history evaluators look at:

```bash
git switch -c feature/ci-pipelines
# commit Dockerfile, then workflow, then Jenkinsfile as separate commits
git push -u origin feature/ci-pipelines
# open a pull request: the workflow runs on the pull_request event, then merge
```

Use small, descriptive commits (for example `Add membership expiry logic`, `Add pytest suite
for services`, `Add multi-stage Dockerfile`).

## Security notes and limitations

- Passwords are hashed (Werkzeug scrypt); no plaintext storage and no hard-coded account.
- Every state-changing form carries a per-session CSRF token checked with a constant-time compare. Logout is a `POST`.
- All SQL is parameterised; templates auto-escape; a strict Content-Security-Policy is sent (no inline scripts or styles).
- Open redirects after login are blocked (only same-site relative `next` paths are followed).
- Not included, by design for this assignment: login rate limiting, password reset, multi-factor auth, HTTPS termination (run behind a TLS proxy and set `ACEEST_COOKIE_SECURE=1`).
- Roles (`Admin`, `Coach`) are labels only. The original application never enforced them, and this one does not either.
- SQLite with one Gunicorn worker is sized for a single gym or demo, not for heavy concurrent use.
- Databases from the earlier desktop prototypes are not imported.

## Origin of the features

The application consolidates the useful behaviour of the earlier ACEest prototypes:
authentication, client management, program generation and PDF reporting (v3.1.2); the client,
progress, workout, exercise and body-metric model (v2.2.4); and membership handling (v3.2.4).
Those prototypes were desktop programs and are not part of this repository.

### Assignment requirement map

| Assignment requirement | Where it is implemented |
|---|---|
| Flask web application with `app.py` and `requirements.txt` | `app.py`, `db.py`, `services.py`, `requirements.txt` |
| Git/GitHub version control | [Git workflow](#git-workflow) |
| Pytest unit tests | `tests/`, `pytest.ini`, `requirements-dev.txt` |
| Dockerfile (size and security) | `Dockerfile` (slim base, multi-stage, non-root, no test dependencies in runtime), `.dockerignore` |
| Jenkins clean build from GitHub | `Jenkinsfile`, [Jenkins](#jenkins) |
| GitHub Actions on push and pull_request | `.github/workflows/main.yml` |
| Stage: Build & Lint | job `build-lint` |
| Stage: Docker image assembly | job `docker-build-and-test`, steps "Docker image assembly" |
| Stage: Automated testing in the container | job `docker-build-and-test`, step "run Pytest inside the container" |
| README (setup, manual tests, pipelines) | this file |
