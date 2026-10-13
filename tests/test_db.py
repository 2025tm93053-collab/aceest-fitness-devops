"""Tests for the SQLite persistence layer (isolated temporary databases)."""
import sqlite3

import pytest

import db

CLIENT = {"name": "Asha", "age": 29, "height": 165.0, "weight": 60.0, "program": "fl3",
          "calories": 1320, "target_weight": 55.0, "target_adherence": 90,
          "membership_status": "Active", "membership_end": "2027-01-31"}

METRIC = {"date": "2026-10-05", "weight": 60.0, "waist": None, "bodyfat": None}


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "db.sqlite3"))
    db.init_db(connection)
    yield connection
    connection.close()


def test_init_db_is_idempotent_and_creates_tables(conn):
    db.init_db(conn)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "clients", "progress", "workouts", "exercises", "metrics"} <= names
    assert db.ping(conn)


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_progress(conn, 999, "Week 1 - 2026", 50)


def test_client_name_is_unique_case_insensitively(conn):
    db.create_client(conn, CLIENT)
    with pytest.raises(sqlite3.IntegrityError):
        db.create_client(conn, {**CLIENT, "name": "ASHA"})


def test_update_client_changes_fields_but_keeps_generated_program(conn):
    client_id = db.create_client(conn, CLIENT)
    db.set_generated_program(conn, client_id, '{"rows": []}')
    db.update_client(conn, client_id, {**CLIENT, "weight": 58.5, "calories": 1287})
    row = db.get_client(conn, client_id)
    assert row["weight"] == 58.5 and row["target_weight"] == 55.0
    assert row["generated_program"] == '{"rows": []}'


def test_list_clients_sorted_by_name(conn):
    for name in ("Zed", "amy", "Bob"):
        db.create_client(conn, {**CLIENT, "name": name})
    assert [c["name"] for c in db.list_clients(conn)] == ["amy", "Bob", "Zed"]


def test_progress_stats(conn):
    client_id = db.create_client(conn, CLIENT)
    assert db.progress_stats(conn, client_id) == (0, 0)
    db.add_progress(conn, client_id, "Week 1 - 2026", 80)
    db.add_progress(conn, client_id, "Week 2 - 2026", 91)
    assert db.progress_stats(conn, client_id) == (2, 85.5)
    assert [r["adherence"] for r in db.list_progress(conn, client_id)] == [80, 91]


def test_latest_metric_orders_by_date(conn):
    client_id = db.create_client(conn, CLIENT)
    db.add_metric(conn, client_id, METRIC)
    db.add_metric(conn, client_id,
                  {"date": "2026-10-01", "weight": 62.0, "waist": 80.0, "bodyfat": 25.0})
    assert db.latest_metric(conn, client_id)["date"] == "2026-10-05"
    assert [m["date"] for m in db.list_metrics(conn, client_id)] == ["2026-10-01", "2026-10-05"]


def test_workouts_with_exercises_newest_first(conn):
    client_id = db.create_client(conn, CLIENT)
    base = {"workout_type": "Strength", "duration_min": 60, "notes": ""}
    db.add_workout(conn, client_id, {**base, "date": "2026-10-01"})
    db.add_workout(conn, client_id, {**base, "date": "2026-10-03"},
                   {"name": "Squat", "sets": 5, "reps": 5, "weight": 100.0})
    workouts = db.list_workouts(conn, client_id)
    assert [w["date"] for w in workouts] == ["2026-10-03", "2026-10-01"]
    assert workouts[0]["exercises"][0]["name"] == "Squat"
    assert workouts[1]["exercises"] == []


def test_add_workout_is_atomic(conn):
    client_id = db.create_client(conn, CLIENT)
    workout = {"date": "2026-10-01", "workout_type": "Strength", "duration_min": 60, "notes": ""}
    with pytest.raises(sqlite3.IntegrityError):
        db.add_workout(conn, client_id, workout,
                       {"name": None, "sets": 1, "reps": 1, "weight": 0.0})
    assert db.list_workouts(conn, client_id) == []


def test_deleting_a_client_cascades_to_related_rows(conn):
    client_id = db.create_client(conn, CLIENT)
    db.add_progress(conn, client_id, "Week 1 - 2026", 80)
    db.add_metric(conn, client_id, {**METRIC, "date": "2026-10-01"})
    db.add_workout(conn, client_id,
                   {"date": "2026-10-01", "workout_type": "Mixed", "duration_min": 30, "notes": ""},
                   {"name": "Plank", "sets": 3, "reps": 1, "weight": 0.0})
    db.delete_client(conn, client_id)
    for table in ("progress", "metrics", "workouts", "exercises"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_user_lookup_is_case_insensitive_and_unique(conn):
    db.create_user(conn, "Coach", "hash", "Admin")
    assert db.get_user_by_username(conn, "coach")["role"] == "Admin"
    with pytest.raises(sqlite3.IntegrityError):
        db.create_user(conn, "COACH", "hash", "Admin")
