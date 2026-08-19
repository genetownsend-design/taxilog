"""Backup / restore round-trips — the path you reach for after a bad day.

Covers /api/backup/all, /api/restore/all and the two admin variants. The five
per-file endpoints (/api/backup/pickups etc.) are NOT covered: each captures its
Path in a closure at import time, so a test cannot redirect them away from the
real data/ directory without changing main.py. See conftest.data_dir.
"""
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

import main
from conftest import DRIVER_ID, CURRENT_PICKUPS, STANDARD_PROFILE

OTHER_ID = "other-driver"

CUSTOMERS = [{"name": "Alice Smith", "address": "123 Main St",
              "city": "Ann Arbor", "phone": "555-1234"}]
EXPENSES = [{"id": "e1", "date": "2026-07-01", "kind": "Gas", "amount": 45.5}]
SHIFTS = [{"id": "s1", "date": "2026-07-01", "start_time": "07:00",
           "end_time": "17:00", "start_odo": 100, "end_odo": 240}]

ALL_FILES = {
    "pickups": CURRENT_PICKUPS, "customers": CUSTOMERS,
    "expenses": EXPENSES, "shifts": SHIFTS, "profile": STANDARD_PROFILE,
}


def seed_all(driver_id=DRIVER_ID):
    for name, data in ALL_FILES.items():
        main._write(main._BACKUP_FILES[name][0], data, driver_id)


def read_all(driver_id=DRIVER_ID):
    return {name: main._read(path, driver_id)
            for name, (path, _) in main._BACKUP_FILES.items()}


def wipe(driver_id=DRIVER_ID):
    for name, (path, expect_list) in main._BACKUP_FILES.items():
        main._write(path, [] if expect_list else {}, driver_id)


def zip_of(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for fname, data in members.items():
            zf.writestr(fname, json.dumps(data))
    return buf.getvalue()


def upload(client, url, raw, filename="backup.zip"):
    return client.post(url, files={"file": (filename, io.BytesIO(raw), "application/zip")})


@pytest.fixture
def admin(data_dir, monkeypatch):
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "test-key")
    c = TestClient(main.app)
    c.cookies.set("txl_sess", main._signer.dumps({"uid": "admin-1", "role": "admin"}))
    return c


# ── driver round-trip ────────────────────────────────────────────

def test_backup_zip_contains_every_data_file(client):
    seed_all()
    r = client.get("/api/backup/all")
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert sorted(zf.namelist()) == sorted(f"{n}.json" for n in ALL_FILES)
        assert json.loads(zf.read("pickups.json")) == CURRENT_PICKUPS
        assert json.loads(zf.read("profile.json")) == STANDARD_PROFILE


def test_round_trip_restores_every_file_unchanged(client):
    """The whole point: back up, lose everything, restore, get it all back."""
    seed_all()
    before = read_all()
    backup = client.get("/api/backup/all").content

    wipe()
    assert read_all() != before, "wipe() did not actually clear the data"

    r = upload(client, "/api/restore/all", backup)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert sorted(r.json()["restored"]) == sorted(f"{n}.json" for n in ALL_FILES)
    assert read_all() == before


def test_restore_leaves_files_the_zip_does_not_carry(client):
    """A partial zip must not blank the files it omits."""
    seed_all()
    raw = zip_of({"pickups.json": []})

    r = upload(client, "/api/restore/all", raw)
    assert r.status_code == 200
    assert r.json()["restored"] == ["pickups.json"]

    after = read_all()
    assert after["pickups"] == []
    assert after["shifts"] == SHIFTS
    assert after["profile"] == STANDARD_PROFILE


def test_restore_rejects_a_file_that_is_not_a_zip(client):
    seed_all()
    r = upload(client, "/api/restore/all", b"this is not a zip")
    assert r.status_code == 400
    assert "ZIP" in r.json()["detail"]
    assert read_all()["pickups"] == CURRENT_PICKUPS, "rejected upload still wrote data"


def test_restore_rejects_wrong_json_shape_without_writing(client):
    """pickups.json holding an object must not land as a pickup list."""
    seed_all()
    raw = zip_of({"pickups.json": {"not": "a list"}})
    r = upload(client, "/api/restore/all", raw)
    assert r.status_code == 400
    assert read_all()["pickups"] == CURRENT_PICKUPS


def test_restore_rejects_malformed_json_inside_the_zip(client):
    seed_all()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("pickups.json", "{ not json")
    r = upload(client, "/api/restore/all", buf.getvalue())
    assert r.status_code == 400
    assert read_all()["pickups"] == CURRENT_PICKUPS


def test_backup_and_restore_require_authentication(data_dir):
    anon = TestClient(main.app)
    assert anon.get("/api/backup/all").status_code == 401
    assert upload(anon, "/api/restore/all", zip_of({"pickups.json": []})).status_code == 401


def test_impersonating_admin_can_back_up_but_not_restore(admin):
    """_auth_write blocks the mutation; _auth still allows the read."""
    seed_all()
    admin.cookies.set("txl_view", main._signer.dumps(
        {"driver_id": DRIVER_ID, "driver_name": "Test Driver"}))

    assert admin.get("/api/backup/all").status_code == 200

    r = upload(admin, "/api/restore/all", zip_of({"pickups.json": []}))
    assert r.status_code == 403
    assert read_all()["pickups"] == CURRENT_PICKUPS


# ── admin / fleet round-trip ─────────────────────────────────────

def test_admin_round_trip_restores_every_driver(admin):
    users = [{"id": DRIVER_ID, "username": "test"}, {"id": OTHER_ID, "username": "other"}]
    main._write_users(users)
    seed_all(DRIVER_ID)
    seed_all(OTHER_ID)
    before = {d: read_all(d) for d in (DRIVER_ID, OTHER_ID)}

    backup = admin.get("/api/admin/backup/all").content
    with zipfile.ZipFile(io.BytesIO(backup)) as zf:
        assert "users.json" in zf.namelist()
        assert f"{OTHER_ID}/pickups.json" in zf.namelist()

    wipe(DRIVER_ID)
    wipe(OTHER_ID)
    main._write_users([])

    r = upload(admin, "/api/admin/restore/all", backup)
    assert r.status_code == 200
    assert main._read_users() == users
    assert {d: read_all(d) for d in (DRIVER_ID, OTHER_ID)} == before


def test_admin_backup_restore_reject_a_plain_driver(client):
    seed_all()
    assert client.get("/api/admin/backup/all").status_code == 403
    r = upload(client, "/api/admin/restore/all", zip_of({"users.json": []}))
    assert r.status_code == 403
    assert read_all()["pickups"] == CURRENT_PICKUPS
