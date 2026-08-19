"""Report and daily-total arithmetic, against hand-computed fixtures.

Every number below is worked out by hand in the comments rather than taken from
a run, so a formula change has to disagree with the arithmetic rather than with
a recorded output.

Fixture (two days, three pickups):
  A  2026-07-01  meter 100 cash    tip 10 cash    total 110
  B  2026-07-01  meter  60 credit  tip 20 credit  total  80
  C  2026-07-02  meter  40 voucher tip  0         total  40

  day 1: meter_cash 100, meter_credit 60,  tips: cash 10, credit 20  grand 190
  day 2: meter_voucher 40,                                          grand  40
"""
import pytest

import main
from conftest import DRIVER_ID, seed

A = {"id": "a", "pickup_date": "2026-07-01", "pickup_time": "09:00",
     "street_address": "1 A", "city": "X", "customer_name": "", "phone_number": "",
     "destination_address": "", "meter_total": 100.0, "payment_method": "Cash",
     "tip": 10.0, "tip_payment_method": "Cash", "calculated_total": 110.0}
B = {"id": "b", "pickup_date": "2026-07-01", "pickup_time": "13:00",
     "street_address": "2 B", "city": "X", "customer_name": "", "phone_number": "",
     "destination_address": "", "meter_total": 60.0, "payment_method": "Credit",
     "tip": 20.0, "tip_payment_method": "Credit", "calculated_total": 80.0}
C = {"id": "c", "pickup_date": "2026-07-02", "pickup_time": "10:00",
     "street_address": "3 C", "city": "X", "customer_name": "", "phone_number": "",
     "destination_address": "", "meter_total": 40.0, "payment_method": "Voucher",
     "tip": 0.0, "tip_payment_method": "", "calculated_total": 40.0}
ALL = [A, B, C]

STANDARD = {"driver_name": "D", "pay_mode": "standard"}
GATE = {"driver_name": "D", "pay_mode": "gate", "gate_fee": 10.0}
COMMISSION = {"driver_name": "D", "pay_mode": "commission", "company_pct": 40.0}
OWNER = {"driver_name": "D", "pay_mode": "owner"}


# ── the four pay-mode branches ───────────────────────────────────

def test_standard_credits_half_the_split_and_nets_off_cash_in_hand():
    """Driver keeps 50% and already holds the cash, so the company owes
    (cash + credit + voucher)/2 - cash  ==  ((credit + voucher) - cash)/2.
    Day 1: ((60 + 0) - 100)/2 + 20 = -20 + 20 = 0.00"""
    t = main.day_totals([A, B], STANDARD)
    assert t["meter_cash"] == 100.0 and t["meter_credit"] == 60.0
    assert t["tip_credit"] == 20.0 and t["grand_total"] == 190.0
    assert t["owed_driver"] == 0.00


def test_standard_over_the_whole_range():
    """((60 + 40) - 100)/2 + 20 = 0 + 20 = 20.00"""
    assert main.day_totals(ALL, STANDARD)["owed_driver"] == 20.00


def test_gate_takes_the_fee_off_a_single_day():
    """(60 + 0)/2 + 20 - 10 = 30 + 20 - 10 = 40.00"""
    assert main.day_totals([A, B], GATE)["owed_driver"] == 40.00


def test_gate_charges_nothing_on_a_day_with_no_pickups():
    """No shift means no gate fee — otherwise a day off would owe -10.00."""
    assert main.day_totals([], GATE)["owed_driver"] == 0.00


def test_commission_pays_the_drivers_share_plus_every_tip():
    """company_pct 40 leaves 60% of 200 meter, plus all 30 in tips:
    200 * 0.60 + 30 = 150.00"""
    assert main.day_totals(ALL, COMMISSION)["owed_driver"] == 150.00


def test_commission_defaults_to_a_fifty_fifty_split():
    """company_pct unset: 200 * 0.50 + 30 = 130.00"""
    profile = {"driver_name": "D", "pay_mode": "commission"}
    assert main.day_totals(ALL, profile)["owed_driver"] == 130.00


def test_owner_keeps_the_whole_grand_total():
    """110 + 80 + 40 = 230.00"""
    assert main.day_totals(ALL, OWNER)["owed_driver"] == 230.00


def test_missing_profile_is_treated_as_standard():
    assert main.day_totals(ALL, None)["owed_driver"] == main.day_totals(ALL, STANDARD)["owed_driver"]


# ── /api/daily-totals ────────────────────────────────────────────

def test_daily_totals_separates_money_owed_from_money_in_hand(client):
    """owed_driver is what the company owes; driver_earnings adds the cash the
    driver is already holding. Day 1 standard, 15.00 of expenses:
      owed            = 0.00
      net_earnings    = 0 - 15               = -15.00
      driver_earnings = 0 + 100 + 10 - 15    =  95.00"""
    seed(ALL, STANDARD)
    main._write(main.EXPENSES_F, [{"id": "e", "date": "2026-07-01",
                                   "kind": "Gas", "amount": 15.0}], DRIVER_ID)

    t = client.get("/api/daily-totals?date=2026-07-01").json()
    assert t["count"] == 2
    assert t["owed_driver"] == 0.00
    assert t["expense_total"] == 15.00
    assert t["net_earnings"] == -15.00
    assert t["driver_earnings"] == 95.00
    assert t["pay_mode"] == "standard"


def test_daily_totals_counts_only_the_requested_day(client):
    seed(ALL, STANDARD)
    t = client.get("/api/daily-totals?date=2026-07-02").json()
    assert t["count"] == 1
    assert t["meter_voucher"] == 40.0 and t["meter_cash"] == 0
    assert t["owed_driver"] == 20.00


# ── /api/report ──────────────────────────────────────────────────

def test_report_groups_by_day_and_totals_the_range(client):
    seed(ALL, STANDARD)
    r = client.get("/api/report").json()

    assert [d["date"] for d in r["days"]] == ["2026-07-01", "2026-07-02"]
    assert [d["totals"]["count"] for d in r["days"]] == [2, 1]
    assert [d["totals"]["owed_driver"] for d in r["days"]] == [0.00, 20.00]
    assert r["summary"]["count"] == 3
    assert r["summary"]["owed_driver"] == 20.00
    assert r["summary"]["grand_total"] == 230.00


def test_report_gate_fee_is_charged_per_day_not_once_per_range(client):
    """The one that would silently overpay. Per day:
        1 Jul: (60 + 0)/2 + 20 - 10 = 40.00
        2 Jul: (0 + 40)/2 +  0 - 10 = 10.00   → 50.00
    Computing the range in one pass instead gives (60+40)/2 + 20 - 10 = 60.00,
    charging the fee once and overstating the driver by a day's gate."""
    seed(ALL, GATE)
    r = client.get("/api/report").json()

    assert [d["totals"]["owed_driver"] for d in r["days"]] == [40.00, 10.00]
    assert r["summary"]["owed_driver"] == 50.00
    assert r["summary"]["owed_driver"] != 60.00


def test_report_date_bounds_are_inclusive(client):
    seed(ALL, STANDARD)
    r = client.get("/api/report?from_date=2026-07-02&to_date=2026-07-02").json()
    assert [d["date"] for d in r["days"]] == ["2026-07-02"]
    assert r["summary"]["count"] == 1
    assert r["summary"]["owed_driver"] == 20.00


def test_report_subtracts_expenses_across_the_range(client):
    """20.00 + 5.00 of expenses against 20.00 owed → net -5.00."""
    seed(ALL, STANDARD)
    main._write(main.EXPENSES_F, [
        {"id": "e1", "date": "2026-07-01", "kind": "Gas", "amount": 20.0},
        {"id": "e2", "date": "2026-07-02", "kind": "Wash", "amount": 5.0},
    ], DRIVER_ID)

    r = client.get("/api/report").json()
    assert r["summary"]["expense_total"] == 25.00
    assert r["summary"]["net_earnings"] == -5.00
    assert r["summary"]["driver_earnings"] == 20.00 + 100.0 + 10.0 - 25.0


def test_report_keeps_a_day_that_has_expenses_but_no_pickups(client):
    """An expense-only day still has to appear, or the money vanishes."""
    seed(ALL, STANDARD)
    main._write(main.EXPENSES_F, [{"id": "e", "date": "2026-07-03",
                                   "kind": "Repair", "amount": 75.0}], DRIVER_ID)

    r = client.get("/api/report").json()
    day3 = next(d for d in r["days"] if d["date"] == "2026-07-03")
    assert day3["totals"]["count"] == 0
    assert day3["totals"]["expense_total"] == 75.00
    assert r["summary"]["expense_total"] == 75.00
