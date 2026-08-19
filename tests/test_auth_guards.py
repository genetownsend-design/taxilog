"""Auth guard behaviour.

/api/change-password is the one mutating endpoint that does not go through
_auth_write, because it acts on ctx.user_id — the logged-in account — rather
than ctx.effective_id. That is correct, but it is one identifier away from
letting an impersonating admin rewrite the viewed driver's password, so it is
pinned here.
"""
import pytest
from fastapi.testclient import TestClient

import main
from conftest import DRIVER_ID

ADMIN_ID = "admin-1"
ADMIN_PW = "admin-original-pw"
DRIVER_PW = "driver-original-pw"
NEW_PW = "brand-new-pw"


@pytest.fixture
def accounts(data_dir):
    main._write_users([
        {"id": ADMIN_ID, "username": "boss", "password_hash": main._hash_pw(ADMIN_PW)},
        {"id": DRIVER_ID, "username": "test", "password_hash": main._hash_pw(DRIVER_PW)},
    ])


def hash_for(user_id):
    return next(u["password_hash"] for u in main._read_users() if u["id"] == user_id)


def signed_in(uid, role, viewing=None):
    c = TestClient(main.app)
    c.cookies.set("txl_sess", main._signer.dumps({"uid": uid, "role": role}))
    if viewing:
        c.cookies.set("txl_view", main._signer.dumps(
            {"driver_id": viewing, "driver_name": "Test Driver"}))
    return c


def change(client, current, new=NEW_PW):
    return client.post("/api/change-password",
                       json={"current_password": current, "new_password": new})


def test_driver_can_change_their_own_password(accounts):
    r = change(signed_in(DRIVER_ID, "driver"), DRIVER_PW)
    assert r.status_code == 200
    assert main._check_pw(NEW_PW, hash_for(DRIVER_ID))


def test_impersonating_admin_changes_their_own_password_not_the_driver_s(accounts):
    """Targets ctx.user_id. Switching this to effective_id would let an admin
    rewrite a driver's password from inside a read-only view."""
    driver_before = hash_for(DRIVER_ID)

    r = change(signed_in(ADMIN_ID, "admin", viewing=DRIVER_ID), ADMIN_PW)

    assert r.status_code == 200
    assert main._check_pw(NEW_PW, hash_for(ADMIN_ID)), "admin's own password was not changed"
    assert hash_for(DRIVER_ID) == driver_before, "the viewed driver's password was rewritten"


def test_viewed_drivers_password_is_not_accepted_while_impersonating(accounts):
    """The other half: the credential checked is the admin's, not the driver's."""
    driver_before, admin_before = hash_for(DRIVER_ID), hash_for(ADMIN_ID)

    r = change(signed_in(ADMIN_ID, "admin", viewing=DRIVER_ID), DRIVER_PW)

    assert r.status_code == 400
    assert hash_for(DRIVER_ID) == driver_before
    assert hash_for(ADMIN_ID) == admin_before


def test_change_password_requires_authentication(data_dir):
    assert change(TestClient(main.app), DRIVER_PW).status_code == 401


# ── /admin/reset mints password-reset tokens; it must be admin-only ──

def test_admin_reset_page_is_not_public(accounts):
    """It listed every driver username to anyone who asked."""
    r = TestClient(main.app).get("/admin/reset")
    assert r.status_code == 401
    assert "test" not in r.text


def test_admin_reset_page_rejects_a_plain_driver(accounts):
    assert signed_in(DRIVER_ID, "driver").get("/admin/reset").status_code == 403


def test_anonymous_request_cannot_mint_a_reset_token(accounts):
    """The whole takeover chain started here: no auth, and the reset URL came
    back in the response body."""
    r = TestClient(main.app).post("/admin/reset", data={"username": "test"})
    assert r.status_code == 401
    assert "reset-password?token=" not in r.text


def test_a_driver_cannot_mint_a_reset_token(accounts):
    r = signed_in(DRIVER_ID, "driver").post("/admin/reset", data={"username": "boss"})
    assert r.status_code == 403
    assert "reset-password?token=" not in r.text


def test_admin_can_still_mint_a_reset_token(accounts):
    """The guard must not break the feature it protects."""
    r = signed_in(ADMIN_ID, "admin").post("/admin/reset", data={"username": "test"})
    assert r.status_code == 200
    assert "reset-password?token=" in r.text


# ── one driver must never reach another driver's data ────────────

OTHER_ID = "other-driver"

MINE = {"id": "mine", "pickup_date": "2026-07-01", "pickup_time": "09:00",
        "street_address": "1 My St", "city": "Mine", "customer_name": "My Rider",
        "phone_number": "", "destination_address": "My Dest", "meter_total": 10.0,
        "payment_method": "Cash", "tip": 0.0, "tip_payment_method": "",
        "calculated_total": 10.0}
THEIRS = dict(MINE, id="theirs", street_address="9 Their Ave", city="Theirs",
              customer_name="Their Rider", destination_address="Their Dest")


@pytest.fixture
def two_drivers(data_dir):
    main._write(main.PICKUPS_F, [MINE], DRIVER_ID)
    main._write(main.PICKUPS_F, [THEIRS], OTHER_ID)
    return signed_in(DRIVER_ID, "driver")


def test_listing_returns_only_your_own_pickups(two_drivers):
    ids = [p["id"] for p in two_drivers.get("/api/pickups").json()]
    assert ids == ["mine"]


def test_another_drivers_pickup_is_not_fetchable_by_id(two_drivers):
    assert two_drivers.get("/api/pickups/theirs").status_code == 404


def test_another_drivers_pickup_cannot_be_deleted(two_drivers):
    assert two_drivers.delete("/api/pickups/theirs").status_code == 404
    assert main._read(main.PICKUPS_F, OTHER_ID) == [THEIRS]


def test_another_drivers_pickup_cannot_be_overwritten(two_drivers):
    r = two_drivers.put("/api/pickups/theirs", json=dict(THEIRS, city="Hijacked"))
    assert r.status_code == 404
    assert main._read(main.PICKUPS_F, OTHER_ID) == [THEIRS]


def test_backup_contains_only_your_own_data(two_drivers):
    import io, json, zipfile
    raw = two_drivers.get("/api/backup/all").content
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert json.loads(zf.read("pickups.json")) == [MINE]


def test_customer_autocomplete_does_not_span_drivers(two_drivers):
    main._write(main.CUSTOMERS_F, [{"name": "Their Rider", "address": "9 Their Ave",
                                    "city": "Theirs", "phone": ""}], OTHER_ID)
    names = [c.get("name") for c in two_drivers.get("/api/customers/suggest?q=their").json()]
    assert names == []
