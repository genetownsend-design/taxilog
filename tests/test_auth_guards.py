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
