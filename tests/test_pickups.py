"""Pickup create/update field handling."""
import main
from conftest import DRIVER_ID, seed

PADDED = {"pickup_date": "2026-07-28", "pickup_time": "11:00",
          "street_address": " 121 Wildwood ", "city": "San Mateo ",
          "customer_name": " Mrs Kim", "phone_number": "(650) 555-1212 ",
          "destination_address": " East Palo Alto ",
          "meter_total": "24.50", "payment_method": "Cash ",
          "tip": "5", "tip_payment_method": " Cash"}


def test_create_strips_surrounding_whitespace(client):
    seed()
    rec = client.post("/api/pickups", json=PADDED).json()
    assert rec["city"] == "San Mateo"
    assert rec["street_address"] == "121 Wildwood"
    assert rec["destination_address"] == "East Palo Alto"
    assert rec["customer_name"] == "Mrs Kim"
    assert rec["phone_number"] == "(650) 555-1212"
    assert rec["payment_method"] == "Cash"
    assert rec["tip_payment_method"] == "Cash"

def test_create_stores_stripped_values(client):
    seed()
    client.post("/api/pickups", json=PADDED)
    stored = main._read(main.PICKUPS_F, DRIVER_ID)[0]
    assert stored["city"] == "San Mateo"

def test_padded_city_matches_clean_one_after_strip(client):
    """The whole point: 'San Mateo ' and 'San Mateo' stop being two cities."""
    seed()
    client.post("/api/pickups", json=PADDED)
    client.post("/api/pickups", json=dict(PADDED, city="San Mateo"))
    cities = {p["city"] for p in main._read(main.PICKUPS_F, DRIVER_ID)}
    assert cities == {"San Mateo"}

def test_update_strips_too(client):
    seed()
    pid = client.post("/api/pickups", json=dict(PADDED, city="San Mateo")).json()["id"]
    rec = client.put(f"/api/pickups/{pid}", json={"city": "  Belmont  "}).json()
    assert rec["city"] == "Belmont"

def test_money_fields_still_parse_after_trim(client):
    seed()
    rec = client.post("/api/pickups", json=dict(PADDED, meter_total=" 24.50 ", tip=" 5 ")).json()
    assert rec["meter_total"] == 24.5
    assert rec["tip"] == 5.0
    assert rec["calculated_total"] == 29.5

def test_customer_book_gets_the_stripped_values(client):
    seed()
    client.post("/api/pickups", json=PADDED)
    cust = main._read(main.CUSTOMERS_F, DRIVER_ID)
    assert cust and cust[0]["city"] == "San Mateo"
    assert cust[0]["street_address"] == "121 Wildwood"

def test_non_string_values_pass_through(client):
    """Numeric meter/tip from a JSON client must not hit .strip()."""
    seed()
    rec = client.post("/api/pickups", json=dict(PADDED, meter_total=24.5, tip=5)).json()
    assert rec["meter_total"] == 24.5 and rec["tip"] == 5.0


# ── second tip ───────────────────────────────────────────────────

def test_create_totals_both_tips(client):
    """24.50 meter + 5.00 tip + 3.00 second tip = 32.50"""
    seed()
    rec = client.post("/api/pickups", json=dict(
        PADDED, tip2=" 3 ", tip2_payment_method=" Credit")).json()
    assert rec["tip2"] == 3.0
    assert rec["tip2_payment_method"] == "Credit"
    assert rec["calculated_total"] == 32.50


def test_update_recomputes_the_total_when_a_second_tip_is_added(client):
    """Adding the cash tip afterwards has to move calculated_total with it —
    every report reads the stored value rather than recomputing."""
    seed()
    pid = client.post("/api/pickups", json=PADDED).json()["id"]
    assert main._read(main.PICKUPS_F, DRIVER_ID)[0]["calculated_total"] == 29.50

    rec = client.put(f"/api/pickups/{pid}",
                     json={"tip2": "3", "tip2_payment_method": "Credit"}).json()
    assert rec["calculated_total"] == 32.50


def test_omitting_the_second_tip_leaves_it_zero(client):
    """The default path: nearly every pickup never touches these fields."""
    seed()
    rec = client.post("/api/pickups", json=PADDED).json()
    assert rec["tip2"] == 0.0
    assert rec["tip2_payment_method"] == ""
    assert rec["calculated_total"] == 29.50
