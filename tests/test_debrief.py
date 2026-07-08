import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from conftest import (CURRENT_PICKUPS, PRIOR_PICKUPS, STANDARD_PROFILE,
                      GATE_PROFILE, DRIVER_ID, seed)

TODAY = date(2026, 7, 8)  # a Wednesday


# ── period / range resolution ────────────────────────────────────

def test_range_day():
    assert main._debrief_range("day", "", "", TODAY) == \
        ("2026-07-08", "2026-07-08", "2026-07-07", "2026-07-07")

def test_range_week_starts_monday():
    assert main._debrief_range("week", "", "", TODAY) == \
        ("2026-07-06", "2026-07-08", "2026-06-29", "2026-07-05")

def test_range_month():
    assert main._debrief_range("month", "", "", TODAY) == \
        ("2026-07-01", "2026-07-08", "2026-06-01", "2026-06-30")

def test_range_custom_prior_same_length():
    assert main._debrief_range("custom", "2026-07-01", "2026-07-04", TODAY) == \
        ("2026-07-01", "2026-07-04", "2026-06-27", "2026-06-30")

@pytest.mark.parametrize("period,start,end", [
    ("bogus", "", ""),
    ("custom", "", ""),
    ("custom", "2026-07-01", ""),
    ("custom", "not-a-date", "2026-07-04"),
    ("custom", "2026-07-05", "2026-07-01"),
])
def test_range_validation_errors(period, start, end):
    with pytest.raises(HTTPException) as exc:
        main._debrief_range(period, start, end, TODAY)
    assert exc.value.status_code == 400


# ── hour blocks / display names ──────────────────────────────────

@pytest.mark.parametrize("t,block", [
    ("08:30", "morning"), ("13:15", "afternoon"), ("18:45", "evening"),
    ("23:30", "night"), ("04:59", "night"),
    ("1:15 PM", "afternoon"), ("12:05 AM", "night"), ("12:30 PM", "afternoon"),
    ("", "unknown"), ("noonish", "unknown"), ("99:00", "unknown"),
])
def test_hour_block(t, block):
    assert main._hour_block(t) == block

def test_display_name():
    assert main._display_name("Alice Smith") == "Alice S."
    assert main._display_name("Carol") == "Carol"
    assert main._display_name("") == ""
    assert main._display_name(None) == ""


# ── stats computation ────────────────────────────────────────────

def test_stats_totals():
    s = main._debrief_stats(CURRENT_PICKUPS, [], STANDARD_PROFILE)
    assert s["total_revenue"] == 120.0
    assert s["pickup_count"] == 4
    assert s["average_fare"] == 30.0
    assert s["pay_mode"] == "standard"

def test_stats_payment_breakdown():
    s = main._debrief_stats(CURRENT_PICKUPS, [], STANDARD_PROFILE)
    assert s["by_payment_method"] == {
        "cash":    {"revenue": 40.0, "count": 2},
        "credit":  {"revenue": 30.0, "count": 1},
        "voucher": {"revenue": 50.0, "count": 1},
    }

def test_stats_day_of_week_and_hour_blocks():
    s = main._debrief_stats(CURRENT_PICKUPS, [], STANDARD_PROFILE)
    assert s["by_day_of_week"] == {
        "Wednesday": {"revenue": 55.0, "count": 2},
        "Thursday":  {"revenue": 65.0, "count": 2},
    }
    assert s["by_hour_block"] == {
        "morning":   {"revenue": 25.0, "count": 1},
        "afternoon": {"revenue": 30.0, "count": 1},
        "evening":   {"revenue": 50.0, "count": 1},
        "night":     {"revenue": 15.0, "count": 1},
    }

def test_stats_top_customers():
    s = main._debrief_stats(CURRENT_PICKUPS, [], STANDARD_PROFILE)
    assert s["top_customers_by_revenue"][0] == {"name": "Alice S.", "revenue": 75.0, "rides": 2}
    assert [c["name"] for c in s["top_customers_by_revenue"]] == ["Alice S.", "Bob J.", "Carol"]
    assert s["top_customers_by_frequency"][0]["name"] == "Alice S."
    assert s["top_customers_by_frequency"][0]["rides"] == 2

def test_stats_owed_driver_standard():
    # standard formula per day: ((mcr+mv)-mc)/2 + tcr + tv
    # day1: ((30+0)-20)/2 + 0 = 5.0
    # day2: ((0+40)-15)/2 + 10 = 22.5   → total 27.5
    s = main._debrief_stats(CURRENT_PICKUPS, [], STANDARD_PROFILE)
    assert s["owed_driver"] == 27.5

def test_stats_owed_driver_gate_sums_per_day():
    # gate fee applies once per day worked:
    # day1: (30+0)/2 + 0  - 10 =  5.0
    # day2: (0+40)/2 + 10 - 10 = 20.0   → total 25.0
    # pooled (wrong) would be 70/2 + 10 - 10 = 35.0
    s = main._debrief_stats(CURRENT_PICKUPS, [], GATE_PROFILE)
    assert s["owed_driver"] == 25.0

def test_stats_prior_period_deltas():
    s = main._debrief_stats(CURRENT_PICKUPS, PRIOR_PICKUPS, STANDARD_PROFILE)
    assert s["prior_period"] == {"total_revenue": 50.0, "pickup_count": 1,
                                 "average_fare": 50.0, "owed_driver": -25.0}
    assert s["vs_prior_pct"]["total_revenue"] == 140.0
    assert s["vs_prior_pct"]["pickup_count"] == 300.0
    assert s["vs_prior_pct"]["average_fare"] == -40.0
    assert s["vs_prior_pct"]["owed_driver"] == -210.0

def test_stats_no_prior_data():
    s = main._debrief_stats(CURRENT_PICKUPS, [], STANDARD_PROFILE)
    assert s["prior_period"] is None
    assert s["vs_prior_pct"] is None

def test_stats_empty():
    s = main._debrief_stats([], [], STANDARD_PROFILE)
    assert s["total_revenue"] == 0.0
    assert s["pickup_count"] == 0
    assert s["average_fare"] == 0.0
    assert s["owed_driver"] == 0.0


# ── record stripping (privacy) ───────────────────────────────────

def test_debrief_records_strips_pii():
    recs = main._debrief_records(CURRENT_PICKUPS)
    assert len(recs) == 4
    dumped = json.dumps(recs)
    assert "555-1234" not in dumped
    assert "123 Main St" not in dumped
    assert "Airport Dr" not in dumped
    assert "Alice Smith" not in dumped
    assert recs[0]["customer"] == "Alice S."
    assert recs[0]["city"] == "Ann Arbor"
    assert recs[0]["fare"] == 20.0

def test_debrief_records_caps_at_50():
    many = [dict(CURRENT_PICKUPS[0], id=str(i), pickup_date=f"2026-06-{(i % 28) + 1:02d}")
            for i in range(80)]
    assert len(main._debrief_records(many)) == 50


# ── /api/debrief endpoint ────────────────────────────────────────

URL = "/api/debrief?period=custom&start=2026-07-01&end=2026-07-02"

def test_endpoint_zero_pickups_skips_api(client, mock_claude):
    seed(pickups=[], profile=STANDARD_PROFILE)
    r = client.get(URL)
    assert r.status_code == 200
    d = r.json()
    assert d["empty"] is True
    assert "No pickups" in d["message"]
    assert mock_claude.calls == []

def test_endpoint_generates_then_caches(client, mock_claude):
    seed(pickups=CURRENT_PICKUPS, profile=STANDARD_PROFILE)
    d1 = client.get(URL).json()
    assert d1["debrief"] == mock_claude.reply
    assert d1["cached"] is False
    assert d1["model"] == main._CLAUDE_MODEL
    assert len(mock_claude.calls) == 1
    assert mock_claude.calls[0]["max_tokens"] == 1500

    d2 = client.get(URL).json()
    assert d2["cached"] is True
    assert d2["debrief"] == mock_claude.reply
    assert len(mock_claude.calls) == 1  # served from cache, no second call

def test_endpoint_force_regenerates(client, mock_claude):
    seed(pickups=CURRENT_PICKUPS, profile=STANDARD_PROFILE)
    client.get(URL)
    d = client.get(URL + "&force=1").json()
    assert d["cached"] is False
    assert len(mock_claude.calls) == 2

def test_endpoint_cache_invalidated_by_edit(client, mock_claude):
    seed(pickups=CURRENT_PICKUPS, profile=STANDARD_PROFILE)
    client.get(URL)
    assert len(mock_claude.calls) == 1
    edited = json.loads(json.dumps(CURRENT_PICKUPS))
    edited[0]["tip"] = 6.0
    edited[0]["calculated_total"] = 26.0
    seed(pickups=edited, profile=STANDARD_PROFILE)
    d = client.get(URL).json()
    assert d["cached"] is False
    assert len(mock_claude.calls) == 2

def test_endpoint_prompt_has_no_pii(client, mock_claude):
    seed(pickups=CURRENT_PICKUPS, profile=STANDARD_PROFILE)
    client.get(URL)
    content = mock_claude.calls[0]["user_content"]
    assert "555-1234" not in content
    assert "123 Main St" not in content
    assert "Airport Dr" not in content
    assert "Alice Smith" not in content
    assert "Alice S." in content

def test_endpoint_validation_errors(client, mock_claude):
    seed(pickups=CURRENT_PICKUPS, profile=STANDARD_PROFILE)
    assert client.get("/api/debrief?period=bogus").status_code == 400
    assert client.get("/api/debrief?period=custom&start=2026-07-01").status_code == 400
    assert client.get("/api/debrief?period=custom&start=2026-07-05&end=2026-07-01").status_code == 400
    assert mock_claude.calls == []

def test_endpoint_503_without_key(client, mock_claude, monkeypatch):
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "")
    assert client.get(URL).status_code == 503

def test_endpoint_401_unauthenticated(data_dir, monkeypatch):
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "test-key")
    c = TestClient(main.app)
    assert c.get(URL).status_code == 401

def test_endpoint_api_error_not_cached(client, monkeypatch):
    seed(pickups=CURRENT_PICKUPS, profile=STANDARD_PROFILE)
    def boom(system, user_content, max_tokens=1500):
        raise main.AskClaudeError("AI request failed: rate limit reached. Try again shortly.")
    monkeypatch.setattr(main, "ask_claude", boom)
    d = client.get(URL).json()
    assert "rate limit" in d["error"]
    assert main._read(main.DEBRIEFS_F, DRIVER_ID) == []  # nothing cached

def test_endpoint_impersonation_reads_cache_but_cannot_generate(client, mock_claude, monkeypatch):
    seed(pickups=CURRENT_PICKUPS, profile=STANDARD_PROFILE)
    client.get(URL)  # driver generates → cache populated
    admin = TestClient(main.app)
    admin.cookies.set("txl_sess", main._signer.dumps({"uid": "admin-1", "role": "admin"}))
    admin.cookies.set("txl_view", main._signer.dumps({"driver_id": DRIVER_ID,
                                                      "driver_name": "Test Driver"}))
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "test-key")
    r = admin.get(URL)
    assert r.status_code == 200
    assert r.json()["cached"] is True
    assert admin.get(URL + "&force=1").status_code == 403
    assert len(mock_claude.calls) == 1  # only the driver's original generation

def test_cache_pruned_to_20_entries(client, mock_claude):
    seed(pickups=CURRENT_PICKUPS, profile=STANDARD_PROFILE)
    for i in range(1, 25):
        client.get(f"/api/debrief?period=custom&start=2026-06-{i:02d}&end=2026-07-02")
    cache = main._read(main.DEBRIEFS_F, DRIVER_ID)
    assert len(cache) == 20


# ── /api/ask through the shared helper ───────────────────────────

def test_ask_endpoint_uses_helper(client, mock_claude):
    seed(pickups=CURRENT_PICKUPS, profile=STANDARD_PROFILE)
    r = client.post("/api/ask", json={"question": "How did I do?",
                                      "from_date": "2026-07-01", "to_date": "2026-07-02"})
    assert r.json() == {"answer": mock_claude.reply}
    assert mock_claude.calls[0]["max_tokens"] == 8192

def test_ask_endpoint_reports_helper_error(client, monkeypatch):
    seed(pickups=CURRENT_PICKUPS, profile=STANDARD_PROFILE)
    def boom(system, user_content, max_tokens=1500):
        raise main.AskClaudeError("AI request timed out after 60 seconds. Try again.")
    monkeypatch.setattr(main, "ask_claude", boom)
    r = client.post("/api/ask", json={"question": "How did I do?"})
    assert "timed out" in r.json()["error"]


# ── ask_claude error mapping (mocked SDK, no network) ────────────

import anthropic

def _fake_client_raising(exc):
    return SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: (_ for _ in ()).throw(exc)))

def _status_error(cls, status, headers=None):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status, request=req, headers=headers or {})
    return cls("err", response=resp, body=None)

@pytest.fixture
def claude_key(monkeypatch):
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "test-key")

@pytest.mark.parametrize("exc_factory,fragment", [
    (lambda: _status_error(anthropic.AuthenticationError, 401), "API key was rejected"),
    (lambda: _status_error(anthropic.PermissionDeniedError, 403), "lacks permission"),
    (lambda: _status_error(anthropic.NotFoundError, 404), "was not found"),
    (lambda: _status_error(anthropic.RateLimitError, 429, {"retry-after": "7"}), "Try again in 7 seconds"),
    (lambda: _status_error(anthropic.InternalServerError, 529), "service error (529)"),
    (lambda: anthropic.APITimeoutError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")), "timed out"),
    (lambda: anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")), "could not reach"),
])
def test_ask_claude_error_messages(claude_key, monkeypatch, exc_factory, fragment):
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake_client_raising(exc_factory()))
    with pytest.raises(main.AskClaudeError) as exc:
        main.ask_claude("sys", "hello")
    assert fragment in str(exc.value)

def test_ask_claude_success_and_truncation(claude_key, monkeypatch):
    msg = SimpleNamespace(content=[SimpleNamespace(text="analysis")], stop_reason="end_turn")
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: msg))
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: fake)
    assert main.ask_claude("sys", "hello") == "analysis"
    msg.stop_reason = "max_tokens"
    assert main.ask_claude("sys", "hello").startswith("analysis\n\n(Response cut off")

def test_ask_claude_refusal(claude_key, monkeypatch):
    msg = SimpleNamespace(content=[], stop_reason="refusal")
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: msg))
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: fake)
    with pytest.raises(main.AskClaudeError) as exc:
        main.ask_claude("sys", "hello")
    assert "declined" in str(exc.value)

def test_ask_claude_no_key(monkeypatch):
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "")
    with pytest.raises(main.AskClaudeError) as exc:
        main.ask_claude("sys", "hello")
    assert "not configured" in str(exc.value)
