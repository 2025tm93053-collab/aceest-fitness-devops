"""SQLite persistence layer for ACEest Fitness & Gym.

Every function takes an open ``sqlite3.Connection`` and uses parameterised
queries only. Related tables reference ``clients.id`` through real foreign keys
with ON DELETE CASCADE (foreign-key enforcement is switched on in ``connect``).
"""
from __future__ import annotations

import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE COLLATE NOCASE,
    age               INTEGER,
    height            REAL,
    weight            REAL,
    program           TEXT NOT NULL,
    calories          INTEGER,
    target_weight     REAL,
    target_adherence  INTEGER,
    membership_status TEXT NOT NULL DEFAULT 'Active',
    membership_end    TEXT,
    generated_program TEXT
);

CREATE TABLE IF NOT EXISTS progress (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    week      TEXT NOT NULL,
    adherence INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS workouts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,
    workout_type TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS exercises (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    sets       INTEGER NOT NULL,
    reps       INTEGER NOT NULL,
    weight     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    date      TEXT NOT NULL,
    weight    REAL,
    waist     REAL,
    bodyfat   REAL
);

CREATE INDEX IF NOT EXISTS idx_progress_client ON progress(client_id);
CREATE INDEX IF NOT EXISTS idx_workouts_client ON workouts(client_id);
CREATE INDEX IF NOT EXISTS idx_exercises_workout ON exercises(workout_id);
CREATE INDEX IF NOT EXISTS idx_metrics_client ON metrics(client_id);
"""

CLIENT_COLUMNS = ("name", "age", "height", "weight", "program", "calories",
                  "target_weight", "target_adherence", "membership_status",
                  "membership_end")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def ping(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1").fetchone()[0] == 1


# ---------------------------------------------------------------- users

def create_user(conn: sqlite3.Connection, username: str, password_hash: str, role: str) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role))
    return cur.lastrowid


def get_user(conn: sqlite3.Connection, user_id: int):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_username(conn: sqlite3.Connection, username: str):
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


# -------------------------------------------------------------- clients

def create_client(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    columns = ", ".join(CLIENT_COLUMNS)
    marks = ", ".join(f":{c}" for c in CLIENT_COLUMNS)
    with conn:
        cur = conn.execute(f"INSERT INTO clients ({columns}) VALUES ({marks})", data)
    return cur.lastrowid


def update_client(conn: sqlite3.Connection, client_id: int, data: dict[str, Any]) -> None:
    assignments = ", ".join(f"{c} = :{c}" for c in CLIENT_COLUMNS)
    with conn:
        conn.execute(f"UPDATE clients SET {assignments} WHERE id = :id", {**data, "id": client_id})


def get_client(conn: sqlite3.Connection, client_id: int):
    return conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()


def list_clients(conn: sqlite3.Connection):
    return conn.execute("SELECT * FROM clients ORDER BY name").fetchall()


def delete_client(conn: sqlite3.Connection, client_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))


def set_generated_program(conn: sqlite3.Connection, client_id: int, payload: str) -> None:
    with conn:
        conn.execute("UPDATE clients SET generated_program = ? WHERE id = ?",
                     (payload, client_id))


# ------------------------------------------------------------- progress

def add_progress(conn: sqlite3.Connection, client_id: int, week: str, adherence: int) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO progress (client_id, week, adherence) VALUES (?, ?, ?)",
            (client_id, week, adherence))
    return cur.lastrowid


def list_progress(conn: sqlite3.Connection, client_id: int):
    return conn.execute("SELECT week, adherence FROM progress WHERE client_id = ? ORDER BY id",
                        (client_id,)).fetchall()


def progress_stats(conn: sqlite3.Connection, client_id: int) -> tuple[int, float]:
    count, avg = conn.execute(
        "SELECT COUNT(*), AVG(adherence) FROM progress WHERE client_id = ?",
        (client_id,)).fetchone()
    return count, round(avg, 1) if avg is not None else 0


# -------------------------------------------------------------- metrics

def add_metric(conn: sqlite3.Connection, client_id: int, data: dict[str, Any]) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO metrics (client_id, date, weight, waist, bodyfat) "
            "VALUES (?, ?, ?, ?, ?)",
            (client_id, data["date"], data["weight"], data["waist"], data["bodyfat"]))
    return cur.lastrowid


def list_metrics(conn: sqlite3.Connection, client_id: int):
    return conn.execute(
        "SELECT date, weight, waist, bodyfat FROM metrics WHERE client_id = ? "
        "ORDER BY date, id", (client_id,)).fetchall()


def latest_metric(conn: sqlite3.Connection, client_id: int):
    return conn.execute(
        "SELECT date, weight, waist, bodyfat FROM metrics WHERE client_id = ? "
        "ORDER BY date DESC, id DESC LIMIT 1", (client_id,)).fetchone()


# ------------------------------------------------------------- workouts

def add_workout(conn: sqlite3.Connection, client_id: int, workout: dict[str, Any],
                exercise: dict[str, Any] | None = None) -> int:
    """Insert a workout and its optional exercise in a single transaction."""
    with conn:
        cur = conn.execute(
            "INSERT INTO workouts (client_id, date, workout_type, duration_min, notes) "
            "VALUES (?, ?, ?, ?, ?)",
            (client_id, workout["date"], workout["workout_type"],
             workout["duration_min"], workout["notes"]))
        workout_id = cur.lastrowid
        if exercise:
            conn.execute(
                "INSERT INTO exercises (workout_id, name, sets, reps, weight) "
                "VALUES (?, ?, ?, ?, ?)",
                (workout_id, exercise["name"], exercise["sets"],
                 exercise["reps"], exercise["weight"]))
    return workout_id


def list_workouts(conn: sqlite3.Connection, client_id: int) -> list[dict[str, Any]]:
    """Workouts newest first, each with its list of exercises."""
    workouts = [dict(r) for r in conn.execute(
        "SELECT id, date, workout_type, duration_min, notes FROM workouts "
        "WHERE client_id = ? ORDER BY date DESC, id DESC", (client_id,))]
    by_id = {w["id"]: w for w in workouts}
    for w in workouts:
        w["exercises"] = []
    for row in conn.execute(
            "SELECT e.workout_id, e.name, e.sets, e.reps, e.weight FROM exercises e "
            "JOIN workouts w ON w.id = e.workout_id WHERE w.client_id = ? ORDER BY e.id",
            (client_id,)):
        by_id[row["workout_id"]]["exercises"].append(dict(row))
    return workouts
