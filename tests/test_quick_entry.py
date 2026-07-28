import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
from conftest import DRIVER_ID, STANDARD_PROFILE, seed

URL = "/api/parse-pickup"

FULL_NOTE = {"text": "Pickup at 125 W. 3rd at 10:00, going to Palo Alto",
             "local_date": "2026-07-27", "local_time": "09:40"}


def reply(**fields):
    """A model reply with every schema field present, blank unless overridden."""
    return json.dumps({f: fields.get(f, "") for f in main._PICKUP_FIELDS})


# ── field mapping ────────────────────────────────────────────────

def test_maps_json_to_pickup_fields(client, mock_claude):
    seed(profile=STANDARD_PROFILE)
    mock_claude.reply = reply(pickup_date="2026-07-27", pickup_time="10:00",
                              street_address="125 W. 3rd",
                              destination_address="Palo Alto")
    d = client.post(URL, json=FULL_NOTE).json()
    assert d["fields"]["pickup_time"] == "10:00"
    assert d["fields"]["street_address"] == "125 W. 3rd"
    assert d["fields"]["destination_address"] == "Palo Alto"

def test_returns_every_pickup_field(client, mock_claude):
    seed(profile=STANDARD_PROFILE)
    mock_claude.reply = reply(street_address="1 A St")
    assert set(client.post(URL, json=FULL_NOTE).json()["fields"]) == set(main._PICKUP_FIELDS)

def test_unstated_fields_stay_blank(client, mock_claude):
    seed(profile=STANDARD_PROFILE)
    mock_claude.reply = reply(street_address="1 A St")
    f = client.post(URL, json=FULL_NOTE).json()["fields"]
    assert f["meter_total"] == "" and f["payment_method"] == "" and f["customer_name"] == ""

def test_null_values_become_blank_not_none(client, mock_claude):
    """A null in the JSON must not reach the form as the string "None"."""
    seed(profile=STANDARD_PROFILE)
    mock_claude.reply = json.dumps({f: None for f in main._PICKUP_FIELDS} |
                                   {"street_address": "1 A St"})
    f = client.post(URL, json=FULL_NOTE).json()["fields"]
    assert f["city"] == "" and f["tip"] == ""

def test_nothing_extracted_is_an_error_not_an_empty_form(client, mock_claude):
    seed(profile=STANDARD_PROFILE)
    mock_claude.reply = reply()
    d = client.post(URL, json=FULL_NOTE).json()
    assert "fields" not in d
    assert "pickup address" in d["error"]


# ── prompt construction ──────────────────────────────────────────

def test_local_clock_reaches_the_prompt(client, mock_claude):
    seed(profile=STANDARD_PROFILE)
    mock_claude.reply = reply(street_address="1 A St")
    client.post(URL, json=FULL_NOTE)
    system = mock_claude.calls[0]["system"]
    assert "2026-07-27" in system and "09:40" in system

def test_note_is_the_user_turn_and_schema_is_sent(client, mock_claude):
    seed(profile=STANDARD_PROFILE)
    mock_claude.reply = reply(street_address="1 A St")
    client.post(URL, json=FULL_NOTE)
    call = mock_claude.calls[0]
    assert call["user_content"] == FULL_NOTE["text"]
    assert call["model"] == main._PARSE_MODEL
    assert call["effort"] == "low"
    assert call["output_schema"]["required"] == list(main._PICKUP_FIELDS)
    assert call["output_schema"]["additionalProperties"] is False

def test_places_glossary_reaches_the_prompt(client, mock_claude):
    seed(profile=dict(STANDARD_PROFILE,
                      places="Chope ER = Chope ER, 222 W 39th Ave, San Mateo"))
    mock_claude.reply = reply(street_address="Chope ER")
    client.post(URL, json=FULL_NOTE)
    system = mock_claude.calls[0]["system"]
    assert "Chope ER = Chope ER, 222 W 39th Ave, San Mateo" in system
    assert "by sound, not spelling" in system

def test_empty_glossary_omits_the_whole_section(client, mock_claude):
    """Most drivers leave this blank — no stray glossary preamble in that case."""
    seed(profile=STANDARD_PROFILE)
    mock_claude.reply = reply(street_address="1 A St")
    client.post(URL, json=FULL_NOTE)
    assert "by sound, not spelling" not in mock_claude.calls[0]["system"]

def test_whitespace_only_glossary_omits_the_section(client, mock_claude):
    seed(profile=dict(STANDARD_PROFILE, places="   \n  "))
    mock_claude.reply = reply(street_address="1 A St")
    client.post(URL, json=FULL_NOTE)
    assert "by sound, not spelling" not in mock_claude.calls[0]["system"]

def test_missing_profile_does_not_crash(client, mock_claude):
    seed()  # no profile written at all
    mock_claude.reply = reply(street_address="1 A St")
    assert client.post(URL, json=FULL_NOTE).status_code == 200


# ── error paths ──────────────────────────────────────────────────

def test_blank_text_skips_the_api(client, mock_claude):
    seed(profile=STANDARD_PROFILE)
    d = client.post(URL, json={"text": "   "}).json()
    assert "error" in d
    assert mock_claude.calls == []

def test_malformed_json_reported_not_raised(client, monkeypatch):
    seed(profile=STANDARD_PROFILE)
    monkeypatch.setattr(main, "ask_claude", lambda *a, **k: "not json at all")
    d = client.post(URL, json=FULL_NOTE).json()
    assert "rephrasing" in d["error"]

def test_json_array_reported_not_raised(client, monkeypatch):
    seed(profile=STANDARD_PROFILE)
    monkeypatch.setattr(main, "ask_claude", lambda *a, **k: '["nope"]')
    d = client.post(URL, json=FULL_NOTE).json()
    assert "rephrasing" in d["error"]

def test_helper_error_surfaces_verbatim(client, monkeypatch):
    seed(profile=STANDARD_PROFILE)
    def boom(*a, **k):
        raise main.AskClaudeError("AI request failed: rate limit reached. Try again in 7 seconds.")
    monkeypatch.setattr(main, "ask_claude", boom)
    assert "Try again in 7 seconds" in client.post(URL, json=FULL_NOTE).json()["error"]

def test_no_api_key_reports_not_configured(client, monkeypatch):
    """Real ask_claude, no mock — it should refuse before touching the network."""
    seed(profile=STANDARD_PROFILE)
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "")
    assert "not configured" in client.post(URL, json=FULL_NOTE).json()["error"]


# ── auth ─────────────────────────────────────────────────────────

def test_unauthenticated_is_401(data_dir, monkeypatch):
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "test-key")
    assert TestClient(main.app).post(URL, json=FULL_NOTE).status_code == 401

def test_impersonating_admin_cannot_parse(client, mock_claude, monkeypatch):
    """Quick Entry exists only to create a record, so it is blocked read-only."""
    seed(profile=STANDARD_PROFILE)
    admin = TestClient(main.app)
    admin.cookies.set("txl_sess", main._signer.dumps({"uid": "admin-1", "role": "admin"}))
    admin.cookies.set("txl_view", main._signer.dumps({"driver_id": DRIVER_ID,
                                                      "driver_name": "Test Driver"}))
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "test-key")
    assert admin.post(URL, json=FULL_NOTE).status_code == 403
    assert mock_claude.calls == []


# ── ask_claude schema behaviour (mocked SDK, no network) ─────────

import anthropic


@pytest.fixture
def claude_key(monkeypatch):
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "test-key")


def _fake(msg, seen=None):
    def create(**kw):
        if seen is not None:
            seen.update(kw)
        return msg
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def test_truncated_schema_response_raises_instead_of_corrupting_json(claude_key, monkeypatch):
    msg = SimpleNamespace(content=[SimpleNamespace(text='{"a":')], stop_reason="max_tokens")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake(msg))
    with pytest.raises(main.AskClaudeError) as exc:
        main.ask_claude("sys", "hi", output_schema=main._PARSE_SCHEMA)
    assert "cut off" in str(exc.value)

def test_truncation_notice_still_appended_without_a_schema(claude_key, monkeypatch):
    """The Ask panel and Debrief keep their existing prose behaviour."""
    msg = SimpleNamespace(content=[SimpleNamespace(text="analysis")], stop_reason="max_tokens")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake(msg))
    assert main.ask_claude("sys", "hi").startswith("analysis\n\n(Response cut off")

def test_schema_is_passed_as_output_config(claude_key, monkeypatch):
    seen = {}
    msg = SimpleNamespace(content=[SimpleNamespace(text="{}")], stop_reason="end_turn")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake(msg, seen))
    main.ask_claude("sys", "hi", model="m", output_schema={"type": "object"})
    assert seen["model"] == "m"
    assert seen["output_config"] == {"format": {"type": "json_schema",
                                                "schema": {"type": "object"}}}

def test_skips_leading_thinking_block(claude_key, monkeypatch):
    """Opus 5 thinks by default, so content[0] is a thinking block, not the answer."""
    msg = SimpleNamespace(stop_reason="end_turn", content=[
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text='{"street_address":"1 A St"}'),
    ])
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake(msg))
    assert main.ask_claude("sys", "hi") == '{"street_address":"1 A St"}'

def test_no_text_block_at_all_raises(claude_key, monkeypatch):
    msg = SimpleNamespace(stop_reason="end_turn",
                          content=[SimpleNamespace(type="thinking", thinking="")])
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake(msg))
    with pytest.raises(main.AskClaudeError) as exc:
        main.ask_claude("sys", "hi")
    assert "no answer text" in str(exc.value)

def test_effort_rides_alongside_the_schema(claude_key, monkeypatch):
    seen = {}
    msg = SimpleNamespace(content=[SimpleNamespace(text="{}")], stop_reason="end_turn")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake(msg, seen))
    main.ask_claude("sys", "hi", output_schema={"type": "object"}, effort="low")
    assert seen["output_config"]["effort"] == "low"
    assert seen["output_config"]["format"]["type"] == "json_schema"

def test_no_output_config_when_no_schema(claude_key, monkeypatch):
    """Existing callers must keep sending exactly what they sent before."""
    seen = {}
    msg = SimpleNamespace(content=[SimpleNamespace(text="x")], stop_reason="end_turn")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: _fake(msg, seen))
    main.ask_claude("sys", "hi")
    assert "output_config" not in seen
    assert seen["model"] == main._CLAUDE_MODEL
