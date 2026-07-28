import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))
import main

DRIVER_ID = "test-driver"

# Fixture pickups with hand-computed totals (see test_debrief.py asserts):
#   revenue 120.00, count 4, avg 30.00
#   2026-07-01 = Wednesday, 2026-07-02 = Thursday
CURRENT_PICKUPS = [
    {"id": "p1", "pickup_date": "2026-07-01", "pickup_time": "08:30",
     "street_address": "123 Main St", "city": "Ann Arbor",
     "customer_name": "Alice Smith", "phone_number": "555-1234",
     "destination_address": "400 Airport Dr",
     "meter_total": 20.0, "payment_method": "Cash",
     "tip": 5.0, "tip_payment_method": "Cash", "calculated_total": 25.0},
    {"id": "p2", "pickup_date": "2026-07-01", "pickup_time": "13:15",
     "street_address": "9 Elm St", "city": "Ypsilanti",
     "customer_name": "Bob Jones", "phone_number": "555-9876",
     "destination_address": "1 Depot Way",
     "meter_total": 30.0, "payment_method": "Credit",
     "tip": 0.0, "tip_payment_method": "", "calculated_total": 30.0},
    {"id": "p3", "pickup_date": "2026-07-02", "pickup_time": "18:45",
     "street_address": "77 Oak Ave", "city": "Ann Arbor",
     "customer_name": "Alice Smith", "phone_number": "555-1234",
     "destination_address": "400 Airport Dr",
     "meter_total": 40.0, "payment_method": "Voucher",
     "tip": 10.0, "tip_payment_method": "Credit", "calculated_total": 50.0},
    {"id": "p4", "pickup_date": "2026-07-02", "pickup_time": "23:30",
     "street_address": "5 Pine Ct", "city": "Saline",
     "customer_name": "Carol", "phone_number": "",
     "destination_address": "Kroger",
     "meter_total": 15.0, "payment_method": "Cash",
     "tip": 0.0, "tip_payment_method": "", "calculated_total": 15.0},
]

# one prior-period pickup: revenue 50.00, count 1
PRIOR_PICKUPS = [
    {"id": "q1", "pickup_date": "2026-06-24", "pickup_time": "10:00",
     "street_address": "1 A St", "city": "Ann Arbor",
     "customer_name": "Dan", "phone_number": "",
     "destination_address": "B St",
     "meter_total": 50.0, "payment_method": "Cash",
     "tip": 0.0, "tip_payment_method": "", "calculated_total": 50.0},
]

STANDARD_PROFILE = {"driver_name": "Test Driver", "pay_mode": "standard"}
GATE_PROFILE     = {"driver_name": "Test Driver", "pay_mode": "gate", "gate_fee": 10.0}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point every per-driver file constant at a temp directory."""
    monkeypatch.setattr(main, "DATA_DIR",    tmp_path)
    monkeypatch.setattr(main, "PICKUPS_F",   tmp_path / "pickups.json")
    monkeypatch.setattr(main, "CUSTOMERS_F", tmp_path / "customers.json")
    monkeypatch.setattr(main, "PROFILE_F",   tmp_path / "profile.json")
    monkeypatch.setattr(main, "EXPENSES_F",  tmp_path / "expenses.json")
    monkeypatch.setattr(main, "SHIFTS_F",    tmp_path / "shifts.json")
    monkeypatch.setattr(main, "DEBRIEFS_F",  tmp_path / "debriefs.json")
    return tmp_path


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setattr(main, "_ANTHROPIC_KEY", "test-key")
    c = TestClient(main.app)
    c.cookies.set("txl_sess", main._signer.dumps({"uid": DRIVER_ID, "role": "driver"}))
    return c


@pytest.fixture
def mock_claude(monkeypatch):
    """Replace ask_claude with a recorder; returns the recorder."""
    class Recorder:
        def __init__(self):
            self.calls = []
            self.reply = "**Headline**\n\nSolid day.\n\n- keep evenings\n- drop slow mornings"
        def __call__(self, system, user_content, max_tokens=1500,
                     model=None, output_schema=None, effort=None):
            self.calls.append({"system": system, "user_content": user_content,
                               "max_tokens": max_tokens, "model": model,
                               "output_schema": output_schema, "effort": effort})
            return self.reply
    rec = Recorder()
    monkeypatch.setattr(main, "ask_claude", rec)
    return rec


def seed(pickups=None, profile=None):
    main._write(main.PICKUPS_F, pickups if pickups is not None else [], DRIVER_ID)
    if profile is not None:
        main._write(main.PROFILE_F, profile, DRIVER_ID)
