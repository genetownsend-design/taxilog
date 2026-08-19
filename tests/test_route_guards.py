"""Sweep every route and assert the guard its category requires.

The point is not the individual assertions — it is that a route which is not
classified below fails the sweep. /admin/reset shipped with no guard at all for
eleven weeks; a spot-check suite would not have noticed, because nobody thought
to spot-check it.

Adding an endpoint means adding it to one of the sets here. That is the prompt
to think about which guard it needs.
"""
import io

import pytest
from fastapi.testclient import TestClient

import main
from conftest import DRIVER_ID

ADMIN_ID = "admin-1"

# Open by design: login/registration, the ADMIN_SECRET-gated admin bootstrap,
# the token-consuming reset form, and FastAPI's own docs routes.
PUBLIC = {
    ("GET", "/"), ("GET", "/login"), ("POST", "/login"), ("POST", "/logout"),
    ("GET", "/register"), ("POST", "/register"),
    ("GET", "/reset-password"), ("POST", "/reset-password"),
    ("GET", "/admin/register"), ("POST", "/admin/register"),
    ("GET", "/docs"), ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"), ("GET", "/openapi.json"),
}

# Reachable by any signed-in driver, including an admin who is impersonating.
DRIVER_READ = {
    ("GET", "/setup"), ("GET", "/debrief"),
    ("GET", "/api/pickups"), ("GET", "/api/pickups/{pid}"),
    ("GET", "/api/expenses"), ("GET", "/api/shifts"),
    ("GET", "/api/daily-totals"), ("GET", "/api/report"),
    ("GET", "/api/report/csv"), ("GET", "/api/report-pdf"),
    ("GET", "/api/debrief"), ("GET", "/api/requirements-pdf"),
    ("GET", "/api/customers/suggest"), ("GET", "/api/customers/lookup"),
    ("GET", "/api/backup/all"), ("GET", "/api/backup/pickups"),
    ("GET", "/api/backup/customers"), ("GET", "/api/backup/expenses"),
    ("GET", "/api/backup/shifts"), ("GET", "/api/backup/profile"),
    ("POST", "/api/ask"),
}

# Mutations: must be refused while impersonating.
DRIVER_WRITE = {
    ("POST", "/setup"),
    ("POST", "/api/pickups"), ("PUT", "/api/pickups/{pid}"),
    ("DELETE", "/api/pickups/{pid}"), ("DELETE", "/api/pickups"),
    ("POST", "/api/expenses"), ("DELETE", "/api/expenses/{eid}"),
    ("POST", "/api/shifts"), ("POST", "/api/parse-pickup"),
    ("POST", "/api/restore/all"), ("POST", "/api/restore/pickups"),
    ("POST", "/api/restore/customers"), ("POST", "/api/restore/expenses"),
    ("POST", "/api/restore/shifts"), ("POST", "/api/restore/profile"),
}

# Admin role required.
ADMIN_ONLY = {
    ("GET", "/admin"), ("GET", "/admin/reset"), ("POST", "/admin/reset"),
    ("POST", "/admin/create-admin"), ("POST", "/admin/exit-view"),
    ("GET", "/admin/view/{driver_id}"),
    ("POST", "/admin/deactivate/{user_id}"), ("POST", "/admin/reactivate/{user_id}"),
    ("POST", "/admin/delete/{user_id}"), ("POST", "/admin/driver/{driver_id}/reset"),
    ("GET", "/api/admin/backup/all"), ("POST", "/api/admin/restore/all"),
    ("POST", "/api/admin/delete-all"), ("GET", "/api/admin/fleet-report"),
    ("GET", "/api/admin/fleet-report-pdf"), ("GET", "/api/admin/design-pdf"),
}

# Acts on ctx.user_id, so impersonation does not apply — see test_auth_guards.py.
SELF_SERVICE = {("POST", "/api/change-password")}

CLASSIFIED = PUBLIC | DRIVER_READ | DRIVER_WRITE | ADMIN_ONLY | SELF_SERVICE


def live_routes():
    out = set()
    for r in main.app.routes:
        path = getattr(r, "path", None)
        if not path or path.startswith("/static"):
            continue
        for m in (getattr(r, "methods", set()) or set()) - {"HEAD", "OPTIONS"}:
            out.add((m, path))
    return out


def call(client, method, path):
    """Send a request with dummy params, so body validation never 422s ahead
    of the guard and hides it."""
    url = (path.replace("{pid}", "x").replace("{eid}", "x")
               .replace("{user_id}", "x").replace("{driver_id}", "x"))
    kw = {"follow_redirects": False}
    if path in ("/api/restore/all", "/api/restore/pickups", "/api/restore/customers",
                "/api/restore/expenses", "/api/restore/shifts", "/api/restore/profile",
                "/api/admin/restore/all"):
        kw["files"] = {"file": ("x.zip", io.BytesIO(b"x"), "application/zip")}
    elif path == "/admin/reset":
        kw["data"] = {"username": "test"}
    elif path == "/admin/create-admin":
        kw["data"] = {"username": "u", "password": "pw123456", "confirm": "pw123456"}
    elif path == "/setup" and method == "POST":
        kw["data"] = {"driver_name": "D", "vehicle": "", "phone": "",
                      "pay_mode": "standard", "gate_fee": "", "company_pct": "", "places": ""}
    elif method in ("POST", "PUT"):
        kw["json"] = {}
    return client.request(method, url, **kw)


def refused(response):
    """401/403 outright, or a redirect to the login/home page."""
    if response.status_code in (401, 403):
        return True
    if response.status_code in (302, 303, 307):
        return response.headers.get("location", "").split("?")[0] in ("/login", "/", "/admin")
    return False


@pytest.fixture
def anon(data_dir):
    return TestClient(main.app)


@pytest.fixture
def driver(data_dir, monkeypatch):
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "test-key")
    c = TestClient(main.app)
    c.cookies.set("txl_sess", main._signer.dumps({"uid": DRIVER_ID, "role": "driver"}))
    return c


@pytest.fixture
def impersonating(data_dir, monkeypatch):
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "test-key")
    c = TestClient(main.app)
    c.cookies.set("txl_sess", main._signer.dumps({"uid": ADMIN_ID, "role": "admin"}))
    c.cookies.set("txl_view", main._signer.dumps(
        {"driver_id": DRIVER_ID, "driver_name": "Test Driver"}))
    return c


def test_every_route_is_classified():
    """A new endpoint fails here until someone decides which guard it needs."""
    unknown = live_routes() - CLASSIFIED
    assert not unknown, ("unclassified routes — add each to a set in this module "
                         f"after deciding its guard: {sorted(unknown)}")


def test_no_classified_route_has_disappeared():
    """Keeps the sets from rotting into assertions about routes that are gone."""
    stale = CLASSIFIED - live_routes()
    assert not stale, f"classified routes that no longer exist: {sorted(stale)}"


@pytest.mark.parametrize("method,path", sorted(DRIVER_READ | DRIVER_WRITE | SELF_SERVICE))
def test_authenticated_routes_refuse_anonymous_callers(anon, method, path):
    assert refused(call(anon, method, path)), f"{method} {path} served an anonymous caller"


@pytest.mark.parametrize("method,path", sorted(ADMIN_ONLY))
def test_admin_routes_refuse_anonymous_callers(anon, method, path):
    assert refused(call(anon, method, path)), f"{method} {path} served an anonymous caller"


@pytest.mark.parametrize("method,path", sorted(ADMIN_ONLY))
def test_admin_routes_refuse_a_plain_driver(driver, method, path):
    assert refused(call(driver, method, path)), f"{method} {path} served a non-admin driver"


@pytest.mark.parametrize("method,path", sorted(DRIVER_WRITE))
def test_mutations_are_refused_while_impersonating(impersonating, method, path):
    assert refused(call(impersonating, method, path)), \
        f"{method} {path} mutated data from inside a read-only view"
