import uuid
import json
import csv
import io
import os
from urllib.parse import quote
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import aiofiles
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import bcrypt as _bcrypt_lib

# ── paths ────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
PICKUPS_F   = DATA_DIR / "pickups.json"
CUSTOMERS_F = DATA_DIR / "customers.json"
PROFILE_F   = DATA_DIR / "profile.json"
EXPENSES_F  = DATA_DIR / "expenses.json"
SHIFTS_F    = DATA_DIR / "shifts.json"

DATA_DIR.mkdir(exist_ok=True)
(BASE_DIR / "static" / "css").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "static" / "js").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "templates").mkdir(exist_ok=True)

# ════════════════════════════════════════════════════════════════
# HTML TEMPLATES
# ════════════════════════════════════════════════════════════════

BASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Taxi Log{% endblock %}</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
{% if is_impersonating %}
<div class="view-banner">
  👁 Viewing <strong>{{ viewed_name }}</strong>'s account &mdash; Read Only &nbsp;
  <form action="/admin/exit-view" method="post" style="display:inline;margin:0">
    <button type="submit" class="view-banner-exit">Exit View →</button>
  </form>
</div>
{% endif %}
<header class="site-header">
  <div class="header-inner">
    <div class="header-brand">
      <span class="taxi-icon">🚕</span>
      <div>
        <div class="brand-title">Taxi Pickup Daily Log</div>
        {% if profile %}
        <div class="brand-sub">{{ profile.driver_name }}{% if profile.vehicle %} &middot; {{ profile.vehicle }}{% endif %}</div>
        {% elif role == "admin" %}
        <div class="brand-sub">Administrator</div>
        {% endif %}
      </div>
    </div>
    {% if user_id %}
    <button class="hamburger" id="hamburger" onclick="toggleNav()" aria-label="Menu">
      <span></span><span></span><span></span>
    </button>
    {% endif %}
  </div>
  {% if user_id %}
  <nav class="site-nav" id="siteNav">
    {% if role == "admin" and not is_impersonating %}
    <a href="/admin" class="nav-link {% if request.url.path == '/admin' %}active{% endif %}" onclick="closeNav()">🏠 Admin Dashboard</a>
    <form action="/logout" method="post" style="margin:0">
      <button type="submit" class="nav-link" style="background:none;border:none;cursor:pointer;width:100%;text-align:left">🚪 Sign Out</button>
    </form>
    {% else %}
    <a href="/" class="nav-link {% if request.url.path == '/' %}active{% endif %}" onclick="closeNav()">📋 Log</a>
    <a href="#" class="nav-link" onclick="closeNav();openShiftModal()">⏱ Shift</a>
    <a href="#" class="nav-link" onclick="closeNav();openExpenseModal()">💸 Expenses</a>
    <a href="#" class="nav-link" onclick="closeNav();openModal('reportModal')">📊 Report</a>
    <a href="#" class="nav-link" onclick="closeNav();openModal('backupModal')">💾 Backup</a>
    {% if not is_impersonating %}
    <a href="/setup" class="nav-link {% if request.url.path == '/setup' %}active{% endif %}" onclick="closeNav()">⚙️ Setup</a>
    {% endif %}
    <form action="/logout" method="post" style="margin:0">
      <button type="submit" class="nav-link" style="background:none;border:none;cursor:pointer;width:100%;text-align:left">🚪 Sign Out</button>
    </form>
    {% endif %}
  </nav>
  {% endif %}
</header>
<main class="site-main">{% block content %}{% endblock %}</main>

<!-- Report Modal -->
<div id="reportModal" class="modal-overlay" style="display:none">
  <div class="modal-box modal-wide">
    <div class="modal-header">
      <h2>📊 Earnings Report</h2>
      <button class="modal-close" onclick="closeModal('reportModal')">✕</button>
    </div>
    <div class="modal-body">
      <div class="report-controls mb-4">
        <div class="row-2">
          <div class="field-group"><label class="field-label">From Date</label><input type="date" id="rptFrom" class="field-input"></div>
          <div class="field-group"><label class="field-label">To Date</label><input type="date" id="rptTo" class="field-input"></div>
        </div>
        <div class="btn-group mt-2">
          <button class="btn btn-primary" onclick="generateReport()">Generate Report</button>
          <button class="btn btn-secondary btn-sm" onclick="downloadReportCSV()">⬇ CSV Export</button>
          <button class="btn btn-secondary btn-sm" onclick="downloadReportPDF()">⬇ PDF Report</button>
        </div>
      </div>
      <div id="reportOutput" class="report-output mt-4"></div>
    </div>
  </div>
</div>

<!-- Backup Modal -->
<div id="backupModal" class="modal-overlay" style="display:none">
  <div class="modal-box">
    <div class="modal-header">
      <h2>💾 Backup &amp; Restore</h2>
      <button class="modal-close" onclick="closeModal('backupModal')">✕</button>
    </div>
    <div class="modal-body">
      <div class="section-label">Full Backup</div>
      <p style="font-size:12px;color:var(--text3);margin-bottom:10px">Saves all data files as a single ZIP — you choose where.</p>
      <div class="btn-group mb-4">
        <a href="/api/backup/all" class="btn btn-primary" download>💾 Save Full Backup</a>
      </div>
      <div class="section-label">Full Restore</div>
      <div class="warning-text">⚠️ Restores ALL data from a backup ZIP. Cannot be undone.</div>
      <div class="btn-group mb-4">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:4px">
          <input type="file" id="restoreZip" accept=".zip" class="field-input" style="flex:1;min-width:180px">
          <button class="btn btn-warning" onclick="restoreFromZip()">📂 Restore</button>
        </div>
      </div>
      <hr class="divider">
      <div class="section-label">Individual File Backups</div>
      <div class="btn-group mb-4">
        <a href="/api/backup/pickups"   class="btn btn-secondary btn-sm" download>⬇ Pickups</a>
        <a href="/api/backup/customers" class="btn btn-secondary btn-sm" download>⬇ Customers</a>
        <a href="/api/backup/expenses"  class="btn btn-secondary btn-sm" download>⬇ Expenses</a>
        <a href="/api/backup/shifts"    class="btn btn-secondary btn-sm" download>⬇ Shifts</a>
        <a href="/api/backup/profile"   class="btn btn-secondary btn-sm" download>⬇ Profile</a>
        <a href="/api/requirements-pdf" class="btn btn-secondary btn-sm" download>⬇ Requirements PDF</a>
      </div>
      <div class="section-label">Restore Individual Files</div>
      <div class="warning-text">⚠️ Restore overwrites existing data and cannot be undone.</div>
      <div class="restore-row"><span class="restore-label">Pickups</span><input type="file" id="restorePickups" accept=".json"><button class="btn btn-sm btn-warning" onclick="restoreFile('pickups')">Restore</button></div>
      <div class="restore-row"><span class="restore-label">Customers</span><input type="file" id="restoreCustomers" accept=".json"><button class="btn btn-sm btn-warning" onclick="restoreFile('customers')">Restore</button></div>
      <div class="restore-row"><span class="restore-label">Expenses</span><input type="file" id="restoreExpenses" accept=".json"><button class="btn btn-sm btn-warning" onclick="restoreFile('expenses')">Restore</button></div>
      <div class="restore-row"><span class="restore-label">Shifts</span><input type="file" id="restoreShifts" accept=".json"><button class="btn btn-sm btn-warning" onclick="restoreFile('shifts')">Restore</button></div>
      <div class="restore-row"><span class="restore-label">Profile</span><input type="file" id="restoreProfile" accept=".json"><button class="btn btn-sm btn-warning" onclick="restoreFile('profile')">Restore</button></div>
      <hr class="divider">
      <div class="section-label danger-label">Danger Zone</div>
      <button class="btn btn-danger" onclick="deleteAll()">🗑 Delete ALL Pickups &amp; Customers</button>
    </div>
  </div>
</div>

<!-- Edit Pickup Modal -->
<div id="editModal" class="modal-overlay" style="display:none">
  <div class="modal-box modal-wide">
    <div class="modal-header">
      <h2>✏️ Edit Pickup</h2>
      <button class="modal-close" onclick="closeModal('editModal')">✕</button>
    </div>
    <div class="modal-body" id="editModalBody"></div>
  </div>
</div>

<!-- Map Modal -->
<div id="mapModal" class="modal-overlay" style="display:none">
  <div class="modal-box modal-wide">
    <div class="modal-header">
      <h2>Map</h2>
      <button class="modal-close" onclick="closeModal('mapModal')">✕</button>
    </div>
    <div class="modal-body" id="mapModalBody"></div>
  </div>
</div>

<!-- Expense Modal -->
<div id="expenseModal" class="modal-overlay" style="display:none">
  <div class="modal-box">
    <div class="modal-header">
      <h2>💸 Daily Expenses</h2>
      <button class="modal-close" onclick="closeModal('expenseModal')">✕</button>
    </div>
    <div class="modal-body">
      <form id="expenseForm" onsubmit="submitExpense(event)">
        <div class="row-2">
          <div class="field-group">
            <label class="field-label">Date <span class="required">*</span></label>
            <input type="date" id="exp_date" class="field-input" required onchange="loadExpenses()">
          </div>
          <div class="field-group">
            <label class="field-label">Amount ($) <span class="required">*</span></label>
            <input type="number" id="exp_amount" class="field-input" step="0.01" min="0" required placeholder="0.00">
          </div>
        </div>
        <div class="field-group">
          <label class="field-label">Category <span class="required">*</span></label>
          <select id="exp_category" class="field-input" required>
            <option value="">— Select —</option>
            <option>Gate Fee</option><option>Fuel</option><option>Tolls</option>
            <option>Maintenance</option><option>Car Wash</option>
            <option>Insurance</option><option>Phone</option><option>Other</option>
          </select>
        </div>
        <div class="field-group">
          <label class="field-label">Notes</label>
          <input type="text" id="exp_notes" class="field-input" placeholder="Optional">
        </div>
        <button type="submit" class="btn btn-primary btn-full">Add Expense</button>
      </form>
      <div id="expenseList" class="expense-list mt-4"></div>
      <div id="expenseTotalBar" class="expense-total-bar" style="display:none">
        <span class="expense-total-label">Day Total Expenses</span>
        <span id="expenseTotalVal" class="expense-total-val">$0.00</span>
      </div>
    </div>
  </div>
</div>

<!-- Shift Modal -->
<div id="shiftModal" class="modal-overlay" style="display:none">
  <div class="modal-box">
    <div class="modal-header">
      <h2>⏱ Shift Log</h2>
      <button class="modal-close" onclick="closeModal('shiftModal')">✕</button>
    </div>
    <div class="modal-body">
      <form id="shiftForm" onsubmit="submitShift(event)">
        <div class="field-group">
          <label class="field-label">Date <span class="required">*</span></label>
          <input type="date" id="sh_date" class="field-input" required onchange="loadShift()">
        </div>
        <div class="row-2">
          <div class="field-group">
            <label class="field-label">Start Time</label>
            <input type="text" id="sh_start" class="field-input clk-input" placeholder="--:-- AM" readonly onclick="openClockPicker(this)">
          </div>
          <div class="field-group">
            <label class="field-label">End Time</label>
            <input type="text" id="sh_end" class="field-input clk-input" placeholder="--:-- AM" readonly onclick="openClockPicker(this)">
          </div>
        </div>
        <div class="row-2">
          <div class="field-group">
            <label class="field-label">Odometer Start</label>
            <input type="number" id="sh_odo_start" class="field-input" step="1" min="0" placeholder="Miles" oninput="calcShiftStats()">
          </div>
          <div class="field-group">
            <label class="field-label">Odometer End</label>
            <input type="number" id="sh_odo_end" class="field-input" step="1" min="0" placeholder="Miles" oninput="calcShiftStats()">
          </div>
        </div>
        <div id="shiftStatsBar" class="shift-stats-bar" style="display:none">
          <div class="shift-stat"><div class="shift-stat-label">Miles Driven</div><div class="shift-stat-val" id="shiftMilesVal">0</div></div>
          <div class="shift-stat"><div class="shift-stat-label">Hours on Shift</div><div class="shift-stat-val" id="shiftHoursVal">0</div></div>
        </div>
        <div class="field-group">
          <label class="field-label">Notes</label>
          <input type="text" id="sh_notes" class="field-input" placeholder="Optional">
        </div>
        <button type="submit" class="btn btn-primary btn-full">Save Shift</button>
      </form>
      <div id="shiftSaved" class="shift-saved mt-4" style="display:none"></div>
    </div>
  </div>
</div>

<div id="toast" class="toast" style="display:none"></div>
<script src="/static/js/app.js"></script>
{% block extra_js %}{% endblock %}
</body>
</html>
"""

INDEX_HTML = """{% extends "base.html" %}
{% block title %}Daily Log – Taxi Log{% endblock %}
{% block content %}
<div class="page-layout">

  <section class="panel">
    <div class="panel-header">
      <div class="panel-title">➕ New Pickup</div>
    </div>
    <div class="panel-body">
    <form id="pickupForm" autocomplete="off" onsubmit="submitPickup(event)">
      <div class="row-2">
        <div class="field-group">
          <label class="field-label">Date <span class="required">*</span></label>
          <input type="date" id="pickup_date" name="pickup_date" class="field-input" required value="{{ today }}">
        </div>
        <div class="field-group">
          <label class="field-label">Time <span class="required">*</span></label>
          <input type="text" id="pickup_time" name="pickup_time" class="field-input clk-input" required placeholder="--:-- AM" readonly onclick="openClockPicker(this)">
        </div>
      </div>
      <div class="field-group autocomplete-wrap">
        <label class="field-label">Street Address <span class="required">*</span></label>
        <input type="text" id="street_address" name="street_address" class="field-input" required
               placeholder="123 Main St" oninput="suggestCustomers(this,'address')">
        <div class="autocomplete-list" id="ac-address"></div>
      </div>
      <div class="row-2">
        <div class="field-group">
          <label class="field-label">City</label>
          <input type="text" id="city" name="city" class="field-input" placeholder="City">
        </div>
        <div class="field-group autocomplete-wrap">
          <label class="field-label">Phone</label>
          <input type="tel" id="phone_number" name="phone_number" class="field-input"
                 placeholder="(555) 555-5555" oninput="suggestCustomers(this,'phone')" onblur="lookupByPhone()">
          <div class="autocomplete-list" id="ac-phone"></div>
        </div>
      </div>
      <div class="field-group autocomplete-wrap">
        <label class="field-label">Customer Name</label>
        <input type="text" id="customer_name" name="customer_name" class="field-input"
               placeholder="Full name" oninput="suggestCustomers(this,'name')">
        <div class="autocomplete-list" id="ac-name"></div>
      </div>
      <div class="field-group">
        <label class="field-label">Destination <span class="required">*</span></label>
        <input type="text" id="destination_address" name="destination_address" class="field-input"
               required placeholder="Drop-off location">
      </div>
      <div class="row-2">
        <div class="field-group">
          <label class="field-label">Meter Total ($)</label>
          <input type="number" id="meter_total" name="meter_total" class="field-input"
                 step="0.01" min="0" placeholder="0.00" oninput="updateCalcTotal()">
        </div>
        <div class="field-group">
          <label class="field-label">Payment</label>
          <select id="payment_method" name="payment_method" class="field-input">
            <option value="">— Select —</option><option>Cash</option><option>Credit</option><option>Voucher</option>
          </select>
        </div>
      </div>
      <div class="row-2">
        <div class="field-group">
          <label class="field-label">Tip ($)</label>
          <input type="number" id="tip" name="tip" class="field-input"
                 step="0.01" min="0" placeholder="0.00" oninput="updateCalcTotal();autoTipPm()">
        </div>
        <div class="field-group">
          <label class="field-label">Tip Payment</label>
          <select id="tip_payment_method" name="tip_payment_method" class="field-input">
            <option value="">— Select —</option><option>Cash</option><option>Credit</option><option>Voucher</option>
          </select>
        </div>
      </div>
      <div class="calc-total-bar">
        <span class="calc-total-label">Calculated Total</span>
        <span id="calcTotal" class="calc-total-value">$0.00</span>
      </div>
      <button type="submit" class="btn btn-primary btn-full">Record Pickup</button>
      <button type="button" class="btn btn-ghost btn-full mt-2" onclick="resetForm()">Clear Form</button>
    </form>
    </div>
  </section>

  <section class="panel">
    <div class="log-header">
      <div class="panel-title">📋 Daily Log</div>
      <div class="log-date-wrap">
        <label>Date</label>
        <input type="date" id="logDate" class="field-input" style="width:auto" value="{{ today }}" onchange="loadDailyLog()">
      </div>
    </div>
    <div id="logList" class="log-list"><p class="empty-msg">Loading pickups…</p></div>
    <div id="dailyTotals" style="display:none">
      <div class="totals-panel">
        <div class="totals-head"><div class="totals-head-label">Daily Totals</div></div>
        <div class="totals-grid" id="totalsGrid"></div>
        <div class="owed-driver-bar">
          <span class="owed-driver-label" id="owedDriverLabel">Owed Driver</span>
          <span class="owed-driver-val" id="owedDriverVal">$0.00</span>
        </div>
        <div class="owed-driver-bar earnings-bar" id="earningsBar" style="display:none">
          <span class="owed-driver-label">Earnings</span>
          <span class="owed-driver-val" id="earningsVal">$0.00</span>
        </div>
      </div>
    </div>
  </section>

{% if ask_enabled %}
  <section class="panel">
    <div class="panel-header">
      <div class="panel-title">🤖 Ask About Your Data</div>
    </div>
    <div class="panel-body">
      <div class="row-2" style="margin-bottom:12px">
        <div class="field-group">
          <label class="field-label">From</label>
          <input type="date" id="askFrom" class="field-input">
        </div>
        <div class="field-group">
          <label class="field-label">To</label>
          <input type="date" id="askTo" class="field-input">
        </div>
      </div>
      <div class="field-group" style="margin-bottom:12px">
        <label class="field-label">Question</label>
        <textarea id="askQuestion" class="field-input" rows="2" placeholder="e.g. What percentage of my pickups are voucher runs?"></textarea>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" onclick="submitAsk()">Ask</button>
        <button class="btn btn-ghost" onclick="clearAsk()">Clear</button>
      </div>
      <div id="askResult" style="margin-top:16px;display:none">
        <div style="border-top:1px solid var(--border);padding-top:14px;white-space:pre-wrap;font-size:14px;line-height:1.7;color:var(--text)" id="askAnswer"></div>
      </div>
    </div>
  </section>
{% endif %}

</div>
{% endblock %}
{% block extra_js %}
<script>const GMAPS_KEY="{{google_maps_key}}";</script>
<script>
  (function(){
    const d = new Date(); d.setMinutes(d.getMinutes()+20);
    const h24=String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
    document.getElementById('pickup_time').value=to12h(h24);
  })();
  loadDailyLog();
</script>
{% endblock %}
"""

SETUP_HTML = """{% extends "base.html" %}
{% block title %}Setup – Taxi Log{% endblock %}
{% block content %}
<div class="setup-page">
  <div class="setup-card">
    <div class="setup-icon">🚕</div>
    <div class="setup-title">Driver Profile Setup</div>
    <div class="setup-sub">Enter your details to get started.</div>
    <form action="/setup" method="post" class="setup-form">
      <div class="field-group">
        <label class="field-label">Driver Name <span class="required">*</span></label>
        <input type="text" name="driver_name" class="field-input" required
               value="{{ profile.driver_name if profile else '' }}" placeholder="Your full name">
      </div>
      <div class="field-group">
        <label class="field-label">Vehicle / Cab Number</label>
        <input type="text" name="vehicle" class="field-input"
               value="{{ profile.vehicle if profile else '' }}" placeholder="e.g. Cab #42 or 2022 Toyota Camry">
      </div>
      <div class="field-group">
        <label class="field-label">Phone Number</label>
        <input type="tel" name="phone" class="field-input"
               value="{{ profile.phone if profile else '' }}" placeholder="(555) 555-5555">
      </div>

      <hr class="divider">
      <div class="setup-section-title">💰 Payment Settings</div>
      <div class="setup-section-sub">Controls how "Owed Driver" is calculated on the daily log and reports.</div>

      <div class="field-group">
        <label class="field-label">Payment Mode</label>
        <select name="pay_mode" id="pay_mode_sel" class="field-input" onchange="togglePayFields()">
          <option value="standard"   {% if not profile or profile.get('pay_mode','standard')=='standard'   %}selected{% endif %}>Standard (split formula)</option>
          <option value="gate"       {% if profile and profile.get('pay_mode')=='gate'       %}selected{% endif %}>Flat Daily Gate Fee</option>
          <option value="commission" {% if profile and profile.get('pay_mode')=='commission' %}selected{% endif %}>Meter Commission Split</option>
          <option value="owner"      {% if profile and profile.get('pay_mode')=='owner'      %}selected{% endif %}>Owner-Operator (keep all)</option>
        </select>
      </div>

      <div id="gateField" class="field-group" style="display:none">
        <label class="field-label">Daily Gate Fee ($)</label>
        <input type="number" name="gate_fee" class="field-input" step="0.01" min="0"
               value="{{ profile.gate_fee if profile and profile.gate_fee else '' }}" placeholder="120.00">
        <div class="field-hint">Amount you pay the company each shift</div>
      </div>

      <div id="commField" class="field-group" style="display:none">
        <label class="field-label">Company % of Meter</label>
        <input type="number" name="company_pct" class="field-input" step="0.1" min="0" max="100"
               value="{{ profile.company_pct if profile and profile.company_pct else '' }}" placeholder="50">
        <div class="field-hint">Company keeps this % of meter fares. You keep 100% of tips.</div>
      </div>

      <div id="payModeExplain" class="pay-mode-explain"></div>

      <button type="submit" class="btn btn-primary btn-full mt-4">Save Profile &amp; Continue →</button>
    </form>

    <hr class="divider" style="margin:28px 0">
    <div class="setup-section-title">🔑 Change Password</div>
    <div id="pwMsg" style="display:none;margin-bottom:12px;font-size:13px;padding:8px 12px;border-radius:8px"></div>
    <form id="pwForm" class="setup-form" onsubmit="changePw(event)">
      <div class="field-group">
        <label class="field-label">Current Password</label>
        <input type="password" id="pwCurrent" class="field-input" autocomplete="current-password" placeholder="••••••••">
      </div>
      <div class="field-group">
        <label class="field-label">New Password</label>
        <input type="password" id="pwNew" class="field-input" autocomplete="new-password" placeholder="••••••••" minlength="6">
      </div>
      <div class="field-group">
        <label class="field-label">Confirm New Password</label>
        <input type="password" id="pwConfirm" class="field-input" autocomplete="new-password" placeholder="••••••••" minlength="6">
      </div>
      <button type="submit" class="btn btn-secondary btn-full">Update Password</button>
    </form>
  </div>
</div>
{% endblock %}
{% block extra_js %}
<script>
const _explains = {
  standard:   'Formula: ((Credit Meter + Voucher Meter) − Cash Meter) ÷ 2 + Credit Tips + Voucher Tips',
  gate:       'Formula: (Credit Meter + Voucher Meter) ÷ 2 + Credit Tips + Voucher Tips − Daily Gate Fee',
  commission: 'Formula: Meter Total × Driver% + All Tips  (you keep everything above the company cut)',
  owner:      'You keep 100% of all fares and tips. Track your own expenses separately.'
};
function togglePayFields(){
  const mode = document.getElementById('pay_mode_sel').value;
  document.getElementById('gateField').style.display   = mode === 'gate'       ? '' : 'none';
  document.getElementById('commField').style.display   = mode === 'commission' ? '' : 'none';
  document.getElementById('payModeExplain').textContent = _explains[mode] || '';
}
togglePayFields();

async function changePw(e){
  e.preventDefault();
  const cur=document.getElementById('pwCurrent').value;
  const nw=document.getElementById('pwNew').value;
  const cf=document.getElementById('pwConfirm').value;
  const msg=document.getElementById('pwMsg');
  if(nw!==cf){showMsg(msg,'Passwords do not match.','#fee2e2','#991b1b');return;}
  if(nw.length<6){showMsg(msg,'New password must be at least 6 characters.','#fee2e2','#991b1b');return;}
  const r=await fetch('/api/change-password',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({current_password:cur,new_password:nw})});
  const d=await r.json();
  if(r.ok){showMsg(msg,'Password updated.','#dcfce7','#166534');document.getElementById('pwForm').reset();}
  else{showMsg(msg,d.detail||'Error.','#fee2e2','#991b1b');}
}
function showMsg(el,text,bg,color){el.style.display='';el.style.background=bg;el.style.color=color;el.textContent=text;}
</script>
{% endblock %}
"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sign In – Taxi Log</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
<div class="auth-page">
  <div class="auth-card">
    <div class="setup-icon">🚕</div>
    <div class="setup-title">Taxi Log</div>
    <div class="setup-sub">Sign in to your account</div>
    {% if success %}<div class="auth-success">{{ success }}</div>{% endif %}
    {% if error %}<div class="auth-error">{{ error }}</div>{% endif %}
    <form action="/login" method="post" class="setup-form">
      <div class="field-group">
        <label class="field-label">Username</label>
        <input type="text" name="username" class="field-input" required autofocus
               autocomplete="username" placeholder="Your username">
      </div>
      <div class="field-group">
        <label class="field-label">Password</label>
        <input type="password" name="password" class="field-input" required
               autocomplete="current-password" placeholder="••••••••">
      </div>
      <button type="submit" class="btn btn-primary btn-full mt-4">Sign In →</button>
    </form>
    {% if allow_register %}
    <p class="auth-foot">No account yet? <a href="/register" class="auth-link">Create one</a></p>
    {% endif %}
  </div>
</div>
</body>
</html>
"""

REGISTER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Create Account – Taxi Log</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
<div class="auth-page">
  <div class="auth-card">
    <div class="setup-icon">🚕</div>
    <div class="setup-title">Create Account</div>
    <div class="setup-sub">{% if is_first %}Welcome — set up the first driver account{% else %}Register a new driver{% endif %}</div>
    {% if error %}<div class="auth-error">{{ error }}</div>{% endif %}
    <form action="/register" method="post" class="setup-form">
      <div class="field-group">
        <label class="field-label">Username <span class="required">*</span></label>
        <input type="text" name="username" class="field-input" required autofocus
               autocomplete="username" placeholder="Choose a username">
      </div>
      <div class="field-group">
        <label class="field-label">Password <span class="required">*</span></label>
        <input type="password" name="password" class="field-input" required
               autocomplete="new-password" placeholder="••••••••" minlength="6">
      </div>
      <div class="field-group">
        <label class="field-label">Confirm Password <span class="required">*</span></label>
        <input type="password" name="confirm" class="field-input" required
               autocomplete="new-password" placeholder="••••••••" minlength="6">
      </div>
      <button type="submit" class="btn btn-primary btn-full mt-4">Create Account →</button>
    </form>
    <p class="auth-foot">Already have an account? <a href="/login" class="auth-link">Sign in</a></p>
  </div>
</div>
</body>
</html>
"""

ADMIN_REGISTER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Create Admin Account – Taxi Log</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
<div class="auth-page">
  <div class="auth-card">
    <div class="setup-icon">🔐</div>
    <div class="setup-title">Create Admin Account</div>
    <div class="setup-sub">Administrator access — requires admin secret key</div>
    {% if error %}<div class="auth-error">{{ error }}</div>{% endif %}
    <form action="/admin/register" method="post" class="setup-form">
      <div class="field-group">
        <label class="field-label">Username <span class="required">*</span></label>
        <input type="text" name="username" class="field-input" required autofocus
               autocomplete="username" placeholder="Choose a username">
      </div>
      <div class="field-group">
        <label class="field-label">Password <span class="required">*</span></label>
        <input type="password" name="password" class="field-input" required
               autocomplete="new-password" placeholder="••••••••" minlength="6">
      </div>
      <div class="field-group">
        <label class="field-label">Confirm Password <span class="required">*</span></label>
        <input type="password" name="confirm" class="field-input" required
               autocomplete="new-password" placeholder="••••••••" minlength="6">
      </div>
      <div class="field-group">
        <label class="field-label">Admin Secret Key <span class="required">*</span></label>
        <input type="password" name="admin_secret" class="field-input" required
               autocomplete="off" placeholder="Provided by system administrator">
      </div>
      <button type="submit" class="btn btn-primary btn-full mt-4">Create Admin Account →</button>
    </form>
    <p class="auth-foot"><a href="/login" class="auth-link">← Back to Sign In</a></p>
  </div>
</div>
</body>
</html>
"""

ADMIN_RESET_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Generate Reset Link – Taxi Log</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
<div class="auth-page">
  <div class="auth-card">
    <div class="setup-icon">🔑</div>
    <div class="setup-title">Reset Password</div>
    <div class="setup-sub">Generate a one-time reset link for a driver</div>
    {% if error %}<div class="auth-error">{{ error }}</div>{% endif %}
    {% if reset_url %}
    <div class="reset-url-box">
      <p style="font-size:13px;color:#065F46;font-weight:600;margin:0 0 6px">Link generated — expires in 1 hour.</p>
      <p style="font-size:12px;color:var(--text3);margin:0 0 8px">Copy and send this URL to the driver:</p>
      <textarea readonly onclick="this.select()" rows="3">{{ reset_url }}</textarea>
    </div>
    {% endif %}
    {% if users %}
    <div style="margin-bottom:16px;padding:10px 14px;background:var(--surface-alt,#F8FAFC);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px">
      <div style="font-weight:600;margin-bottom:6px;color:var(--text2)">Driver accounts:</div>
      {% for u in users %}
      <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border)">
        <span style="font-family:monospace;color:var(--text1)">{{ u.username }}</span>
        <span style="color:var(--text3)">{{ u.driver_name or '' }}</span>
      </div>
      {% endfor %}
    </div>
    {% endif %}
    <form action="/admin/reset" method="post" class="setup-form">
      <div class="field-group">
        <label class="field-label">Username</label>
        <input type="text" name="username" class="field-input" required autofocus placeholder="Driver username">
      </div>
      <button type="submit" class="btn btn-primary btn-full mt-4">Generate Link →</button>
    </form>
    <p class="auth-foot"><a href="/login" class="auth-link">← Back to Sign In</a></p>
  </div>
</div>
</body>
</html>
"""

RESET_PASSWORD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Password – Taxi Log</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
<div class="auth-page">
  <div class="auth-card">
    <div class="setup-icon">🔐</div>
    <div class="setup-title">Reset Password</div>
    {% if error %}
    <div class="setup-sub" style="color:var(--red)">{{ error }}</div>
    <p class="auth-foot">Ask the admin to <a href="/admin/reset" class="auth-link">generate a new link</a>.</p>
    {% else %}
    <div class="setup-sub">Enter your new password</div>
    {% if form_error %}<div class="auth-error">{{ form_error }}</div>{% endif %}
    <form action="/reset-password" method="post" class="setup-form">
      <input type="hidden" name="token" value="{{ token }}">
      <div class="field-group">
        <label class="field-label">New Password</label>
        <input type="password" name="new_password" class="field-input" required autofocus
               autocomplete="new-password" placeholder="••••••••" minlength="6">
      </div>
      <div class="field-group">
        <label class="field-label">Confirm Password</label>
        <input type="password" name="new_password2" class="field-input" required
               autocomplete="new-password" placeholder="••••••••" minlength="6">
      </div>
      <button type="submit" class="btn btn-primary btn-full mt-4">Set New Password →</button>
    </form>
    {% endif %}
  </div>
</div>
</body>
</html>
"""

ADMIN_HTML = """{% extends "base.html" %}
{% block title %}Admin Dashboard – Taxi Log{% endblock %}
{% block content %}
<div class="admin-page">
  <h1 style="font-size:22px;font-weight:800;margin-bottom:24px;color:var(--text)">🏠 Admin Dashboard</h1>

  {% if msg %}
  <div style="background:{% if msg_type=='ok' %}var(--green-lt){% else %}var(--red-lt){% endif %};
              color:{% if msg_type=='ok' %}#166534{% else %}#991b1b{% endif %};
              border-radius:var(--radius);padding:12px 16px;margin-bottom:20px;font-weight:600;font-size:13px">
    {{ msg }}
  </div>
  {% endif %}

  {% if reset_url %}
  <div class="admin-section" style="border-color:#A7F3D0">
    <div class="admin-section-header" style="background:var(--green-lt);color:#065F46">🔑 Reset link for {{ reset_for }} — expires in 1 hour</div>
    <div style="padding:14px">
      <p style="font-size:13px;color:var(--text2);margin:0 0 8px">Copy and send this URL to the driver:</p>
      <textarea readonly onclick="this.select()" rows="2"
        style="width:100%;font-family:monospace;font-size:12px;padding:8px;border:1px solid var(--border);border-radius:4px;resize:none;background:#fff;box-sizing:border-box">{{ reset_url }}</textarea>
    </div>
  </div>
  {% endif %}

  <!-- Stats -->
  <div class="admin-section">
    <div class="admin-section-header">📊 Fleet Overview</div>
    <div class="admin-stat-grid">
      <div class="admin-stat">
        <div class="admin-stat-val">{{ active_drivers|length }}</div>
        <div class="admin-stat-label">Active Drivers</div>
      </div>
      <div class="admin-stat">
        <div class="admin-stat-val">{{ fleet_today.count }}</div>
        <div class="admin-stat-label">Pickups Today</div>
      </div>
      <div class="admin-stat">
        <div class="admin-stat-val">${{ "%.2f"|format(fleet_today.grand_total) }}</div>
        <div class="admin-stat-label">Gross Today</div>
      </div>
      <div class="admin-stat">
        <div class="admin-stat-val">${{ "%.2f"|format(fleet_today.driver_earnings) }}</div>
        <div class="admin-stat-label">Driver Earnings Today</div>
      </div>
    </div>
  </div>

  <!-- Today's Fleet Totals -->
  <div class="admin-section">
    <div class="admin-section-header">📋 Today's Totals — {{ today_str }}</div>
    {% if today_rows and fleet_today.count > 0 %}
    <div class="admin-table-wrap"><table class="admin-table">
      <thead><tr>
        <th>Driver</th><th>Pickups</th><th>Meter</th><th>Tips</th>
        <th>Gross</th><th>Expenses</th><th>Owed Driver</th><th>Earnings</th>
      </tr></thead>
      <tbody>
      {% for r in today_rows %}
      <tr>
        <td><strong>{{ r.driver_name }}</strong></td>
        <td style="text-align:center">{{ r.count }}</td>
        <td>${{ "%.2f"|format(r.meter_total) }}</td>
        <td>${{ "%.2f"|format(r.tip_total) }}</td>
        <td>${{ "%.2f"|format(r.grand_total) }}</td>
        <td style="color:var(--red)">${{ "%.2f"|format(r.expense_total) }}</td>
        <td>${{ "%.2f"|format(r.owed_driver) }}</td>
        <td style="color:var(--green);font-weight:700">${{ "%.2f"|format(r.driver_earnings) }}</td>
      </tr>
      {% endfor %}
      </tbody>
      <tfoot>
      <tr style="background:var(--amber-xl);font-weight:700;border-top:2px solid var(--amber)">
        <td>Fleet Total</td>
        <td style="text-align:center">{{ fleet_today.count }}</td>
        <td>${{ "%.2f"|format(fleet_today.meter) }}</td>
        <td>${{ "%.2f"|format(fleet_today.tips) }}</td>
        <td>${{ "%.2f"|format(fleet_today.grand_total) }}</td>
        <td style="color:var(--red)">${{ "%.2f"|format(fleet_today.expense_total) }}</td>
        <td>${{ "%.2f"|format(fleet_today.owed_driver) }}</td>
        <td style="color:var(--green)">${{ "%.2f"|format(fleet_today.driver_earnings) }}</td>
      </tr>
      </tfoot>
    </table></div>
    {% else %}
    <div style="padding:20px;color:var(--text3);font-size:13px">No pickups recorded today across any driver.</div>
    {% endif %}
  </div>

  <!-- Fleet Report -->
  <div class="admin-section">
    <div class="admin-section-header">📊 Fleet Report</div>
    <div style="padding:16px 20px">
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:16px">
        <div class="field-group" style="margin:0;min-width:140px;flex:1">
          <label class="field-label">From Date</label>
          <input type="date" id="frFrom" class="field-input">
        </div>
        <div class="field-group" style="margin:0;min-width:140px;flex:1">
          <label class="field-label">To Date</label>
          <input type="date" id="frTo" class="field-input">
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-primary" onclick="loadFleetReport()">Generate</button>
          <button class="btn btn-secondary" onclick="downloadFleetPDF()" id="frPdfBtn" style="display:none">⬇ PDF</button>
        </div>
      </div>
      <div id="frOutput"></div>
    </div>
  </div>

  <!-- Fleet Backup & Restore -->
  <div class="admin-section">
    <div class="admin-section-header">💾 Fleet Backup &amp; Restore</div>
    <div style="padding:16px 20px">
      <div class="setup-section-title">Full Fleet Backup</div>
      <p style="font-size:12px;color:var(--text3);margin:4px 0 12px">Downloads a single ZIP containing every driver's data plus user accounts — use this for complete disaster recovery.</p>
      <a href="/api/admin/backup/all" class="btn btn-primary" download>💾 Save Fleet Backup</a>
      <hr class="divider" style="margin:20px 0">
      <div class="setup-section-title">Full Fleet Restore</div>
      <div class="warning-text" style="margin:6px 0 12px">⚠️ Restores ALL driver data and user accounts from a fleet backup ZIP. Overwrites everything. Cannot be undone.</div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:4px">
        <input type="file" id="fleetRestoreInput" accept=".zip" class="field-input" style="flex:1;min-width:180px">
        <button class="btn btn-warning" onclick="restoreFleetBackup()">📂 Restore</button>
      </div>
    </div>
  </div>

  <!-- Design Document -->
  <div class="admin-section">
    <div class="admin-section-header">📄 Application Design Document</div>
    <div style="padding:16px 20px">
      <div class="setup-section-title">Current Design Document</div>
      <p style="font-size:12px;color:var(--text3);margin:4px 0 12px">Downloads a PDF describing the current application architecture, features, data model, and technical stack.</p>
      <a href="/api/admin/design-pdf" class="btn btn-primary" download>📄 Download Design PDF</a>
    </div>
  </div>

  <!-- Danger Zone -->
  <div class="admin-section" style="border-color:var(--red)">
    <div class="admin-section-header" style="color:var(--red);background:#fff5f5">🗑 Danger Zone</div>
    <div style="padding:16px 20px">
      <div class="setup-section-title" style="color:var(--red)">Delete Entire Database</div>
      <p style="font-size:12px;color:var(--text3);margin:4px 0 12px">Permanently deletes <strong>all driver accounts and all data</strong> for every driver. Only admin logins are preserved. This cannot be undone.</p>
      <button class="btn btn-danger" onclick="document.getElementById('delConfirmPanel').style.display=''">🗑 Delete Entire Database</button>
      <div id="delConfirmPanel" style="display:none;margin-top:16px;background:#fff5f5;border:1px solid #fecaca;border-radius:var(--radius);padding:16px">
        <p style="font-size:13px;font-weight:700;color:var(--red);margin-bottom:8px">⚠️ This will permanently delete ALL driver accounts and ALL their data. Admin logins are preserved. This cannot be undone.</p>
        <label class="field-label">Type DELETE to confirm</label>
        <input type="text" id="delConfirmInput" class="field-input" placeholder="DELETE" autocomplete="off" style="margin-bottom:12px">
        <div style="display:flex;gap:8px">
          <button class="btn btn-danger" onclick="confirmDeleteAll()">Confirm Delete</button>
          <button class="btn btn-secondary" onclick="document.getElementById('delConfirmPanel').style.display='none';document.getElementById('delConfirmInput').value=''">Cancel</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Active Drivers -->
  <div class="admin-section">
    <div class="admin-section-header">🚕 Active Drivers</div>
    {% if active_drivers %}
    <div class="admin-table-wrap"><table class="admin-table">
      <thead><tr>
        <th>Driver Name</th><th>Username</th><th>Joined</th><th>Actions</th>
      </tr></thead>
      <tbody>
      {% for d in active_drivers %}
      <tr>
        <td><strong>{{ d.profile_name or '(no profile)' }}</strong></td>
        <td>{{ d.username }}</td>
        <td style="color:var(--text3);font-size:12px">{{ d.created_at[:10] }}</td>
        <td>
          <div class="admin-actions">
            <a href="/admin/view/{{ d.id }}" class="btn btn-sm btn-secondary">👁 View</a>
            <form action="/admin/driver/{{ d.id }}/reset" method="post" style="margin:0">
              <button type="submit" class="btn btn-sm btn-secondary">🔑 Reset</button>
            </form>
            <form action="/admin/deactivate/{{ d.id }}" method="post" style="margin:0"
                  onsubmit="return confirm('Deactivate {{ d.username }}? They will not be able to log in.')">
              <button type="submit" class="btn btn-sm btn-warning">Deactivate</button>
            </form>
          </div>
        </td>
      </tr>
      {% endfor %}
      </tbody>
    </table></div>
    {% else %}
    <div style="padding:20px;color:var(--text3);font-size:13px">No active drivers yet. Share <a href="/register" class="auth-link">/register</a> with drivers to get started.</div>
    {% endif %}
  </div>

  <!-- Administrators -->
  <div class="admin-section">
    <div class="admin-section-header">🔐 Administrators</div>
    <div class="admin-table-wrap"><table class="admin-table">
      <thead><tr><th>Username</th><th>Joined</th><th>Actions</th></tr></thead>
      <tbody>
      {% for a in admins %}
      <tr>
        <td><strong>{{ a.username }}</strong> {% if a.id == current_user_id %}<span style="font-size:11px;color:var(--text3)">(you)</span>{% endif %}</td>
        <td style="color:var(--text3);font-size:12px">{{ a.created_at[:10] }}</td>
        <td>
          {% if a.id != current_user_id %}
          <div class="admin-actions">
            <form action="/admin/deactivate/{{ a.id }}" method="post" style="margin:0"
                  onsubmit="return confirm('Deactivate admin {{ a.username }}?')">
              <button type="submit" class="btn btn-sm btn-warning">Deactivate</button>
            </form>
          </div>
          {% else %}
          <span style="font-size:12px;color:var(--text3)">—</span>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
      </tbody>
    </table></div>
    <div style="padding:12px 20px;border-top:1px solid var(--border)">
      <button type="button" class="btn btn-sm btn-secondary"
              onclick="var p=document.getElementById('addAdminPanel');p.style.display=p.style.display==='none'?'block':'none'">
        ➕ Add Admin
      </button>
      <div id="addAdminPanel" style="display:none;margin-top:14px">
        <form action="/admin/create-admin" method="post" class="setup-form" style="max-width:340px">
          <div class="field-group">
            <label class="field-label">Username <span class="required">*</span></label>
            <input type="text" name="username" class="field-input" required autocomplete="off" placeholder="Choose a username">
          </div>
          <div class="field-group">
            <label class="field-label">Password <span class="required">*</span></label>
            <input type="password" name="password" class="field-input" required placeholder="••••••••" minlength="6">
          </div>
          <div class="field-group" style="margin-bottom:14px">
            <label class="field-label">Confirm Password <span class="required">*</span></label>
            <input type="password" name="confirm" class="field-input" required placeholder="••••••••" minlength="6">
          </div>
          <div style="display:flex;gap:8px">
            <button type="submit" class="btn btn-sm btn-primary">Create Admin Account</button>
            <button type="button" class="btn btn-sm btn-secondary"
                    onclick="document.getElementById('addAdminPanel').style.display='none'">Cancel</button>
          </div>
        </form>
      </div>
    </div>
  </div>

  <!-- Deactivated Accounts -->
  {% if inactive_drivers %}
  <div class="admin-section">
    <div class="admin-section-header" style="color:var(--red)">⚠️ Deactivated Accounts</div>
    <div class="admin-table-wrap"><table class="admin-table">
      <thead><tr><th>Username</th><th>Deactivated</th><th>Actions</th></tr></thead>
      <tbody>
      {% for d in inactive_drivers %}
      <tr>
        <td><strong>{{ d.username }}</strong></td>
        <td style="color:var(--text3);font-size:12px">{{ d.created_at[:10] }}</td>
        <td>
          <div class="admin-actions">
            <form action="/admin/reactivate/{{ d.id }}" method="post" style="margin:0">
              <button type="submit" class="btn btn-sm btn-secondary">Reactivate</button>
            </form>
            <form action="/admin/delete/{{ d.id }}" method="post" style="margin:0"
                  onsubmit="return confirm('Permanently delete {{ d.username }} and ALL their data? This cannot be undone.')">
              <button type="submit" class="btn btn-sm btn-danger">Delete Forever</button>
            </form>
          </div>
        </td>
      </tr>
      {% endfor %}
      </tbody>
    </table></div>
  </div>
  {% endif %}

</div>
{% endblock %}
{% block extra_js %}
<script>
async function loadFleetReport(){
  const from=document.getElementById('frFrom').value;
  const to=document.getElementById('frTo').value;
  const out=document.getElementById('frOutput');
  out.innerHTML='<div style="color:var(--text3);font-size:13px;padding:8px 0">Loading…</div>';
  const params=new URLSearchParams();
  if(from)params.set('from_date',from);
  if(to)params.set('to_date',to);
  const r=await fetch('/api/admin/fleet-report?'+params);
  if(!r.ok){out.innerHTML='<div style="color:var(--red);font-size:13px">Error loading report.</div>';return;}
  const d=await r.json();
  if(!d.drivers.length){out.innerHTML='<div style="color:var(--text3);font-size:13px">No data for this period.</div>';document.getElementById('frPdfBtn').style.display='none';return;}
  let rows=d.drivers.map(dr=>`<tr>
    <td><strong>${dr.driver_name}</strong></td>
    <td style="text-align:center">${dr.days_worked}</td>
    <td style="text-align:center">${dr.count}</td>
    <td>$${dr.meter_total.toFixed(2)}</td>
    <td>$${dr.tip_total.toFixed(2)}</td>
    <td>$${dr.grand_total.toFixed(2)}</td>
    <td style="color:var(--red)">$${dr.expense_total.toFixed(2)}</td>
    <td>$${dr.owed_driver.toFixed(2)}</td>
    <td style="color:var(--green);font-weight:700">$${dr.driver_earnings.toFixed(2)}</td>
  </tr>`).join('');
  const s=d.summary;
  rows+=`<tr style="background:var(--amber-xl);font-weight:700;border-top:2px solid var(--amber)">
    <td>Fleet Total</td>
    <td style="text-align:center">${s.driver_count} drivers</td>
    <td style="text-align:center">${s.count}</td>
    <td>$${s.meter_total.toFixed(2)}</td>
    <td>$${s.tip_total.toFixed(2)}</td>
    <td>$${s.grand_total.toFixed(2)}</td>
    <td style="color:var(--red)">$${s.expense_total.toFixed(2)}</td>
    <td>$${s.owed_driver.toFixed(2)}</td>
    <td style="color:var(--green)">$${s.driver_earnings.toFixed(2)}</td>
  </tr>`;
  out.innerHTML=`<div class="admin-table-wrap"><table class="admin-table"><thead><tr>
    <th>Driver</th><th>Days</th><th>Pickups</th><th>Meter</th><th>Tips</th>
    <th>Gross</th><th>Expenses</th><th>Owed Driver</th><th>Earnings</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
  document.getElementById('frPdfBtn').style.display='';
}
function downloadFleetPDF(){
  const from=document.getElementById('frFrom').value;
  const to=document.getElementById('frTo').value;
  const p=new URLSearchParams();
  if(from)p.set('from_date',from);if(to)p.set('to_date',to);
  window.location='/api/admin/fleet-report-pdf?'+p;
}

async function confirmDeleteAll(){
  const val=document.getElementById('delConfirmInput').value.trim();
  if(val!=='DELETE'){showToast('Type DELETE to confirm');return;}
  document.getElementById('delConfirmPanel').style.display='none';
  showToast('Deleting…',60000);
  const r=await fetch('/api/admin/delete-all',{method:'POST'});
  if(r.ok){showToast('Database deleted — reloading…',3000);setTimeout(()=>window.location.reload(),2000);}
  else{const e=await r.json().catch(()=>({}));showToast(e.detail||'Delete failed');}
}

async function restoreFleetBackup(){
  const input=document.getElementById('fleetRestoreInput');
  if(!input.files.length){showToast('Select a ZIP file first');return;}
  const file=input.files[0];
  showToast('Restoring…',60000);
  const form=new FormData();form.append('file',file);
  const r=await fetch('/api/admin/restore/all',{method:'POST',body:form});
  if(r.ok){
    const d=await r.json();
    showToast('Restored '+d.restored.length+' files — reloading…',3000);
    setTimeout(()=>window.location.reload(),2000);
  }else{
    const err=await r.json().catch(()=>({}));
    showToast(err.detail||'Restore failed');
  }
}
</script>
{% endblock %}
"""

# ════════════════════════════════════════════════════════════════
# CSS
# ════════════════════════════════════════════════════════════════

CSS = """\
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --amber:#FFCB05;--amber-d:#E5B700;--amber-dd:#A38400;
  --amber-lt:#FFF8CC;--amber-xl:#FFFDE5;
  --bg:#F5F7FA;--surface:#FFFFFF;--surface2:#EEF1F6;
  --border:#DDE2EA;--border2:#C5CDD8;
  --text:#0A1628;--text2:#6B6660;--text3:#9C9790;
  --red:#EF4444;--red-lt:#FEE2E2;
  --green:#10B981;--green-lt:#D1FAE5;
  --blue:#3B82F6;--blue-lt:#DBEAFE;
  --purple:#8B5CF6;--purple-lt:#EDE9FE;
  --radius-sm:6px;--radius:10px;--radius-lg:14px;--radius-xl:20px;
  --shadow-xs:0 1px 3px rgba(0,0,0,.06);
  --shadow-sm:0 2px 6px rgba(0,0,0,.08);
  --shadow:0 4px 16px rgba(0,0,0,.10);
  --shadow-lg:0 8px 32px rgba(0,0,0,.12);
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
body{font-family:var(--font);background:var(--bg);color:var(--text);font-size:14px;line-height:1.5;min-height:100vh}
.view-banner{background:#00274C;color:#FFF8CC;font-size:13px;text-align:center;padding:8px 16px;position:sticky;top:0;z-index:300}
.view-banner strong{color:#FFCB05}
.view-banner-exit{background:#FFCB05;color:#00274C;border:none;border-radius:6px;padding:3px 10px;font-size:12px;cursor:pointer;margin-left:10px;font-weight:700}
.view-banner-exit:hover{background:#E5B700}
.site-header{background:linear-gradient(135deg,#00274C 0%,#003366 100%);border-bottom:1px solid rgba(255,255,255,.08);position:sticky;top:0;z-index:200;box-shadow:0 2px 20px rgba(0,0,0,.25)}
.header-inner{max-width:1280px;margin:0 auto;padding:0 24px;height:60px;display:flex;align-items:center;justify-content:space-between;gap:16px}
.header-brand{display:flex;align-items:center;gap:12px}
.taxi-icon{font-size:24px}
.brand-title{color:#FFF;font-size:17px;font-weight:700;letter-spacing:-.3px}
.brand-sub{color:rgba(255,255,255,.45);font-size:12px;margin-top:1px}
.hamburger{background:none;border:none;cursor:pointer;padding:6px 8px;display:flex;flex-direction:column;gap:5px;border-radius:var(--radius-sm);transition:background .15s}
.hamburger:hover{background:rgba(255,255,255,.08)}
.hamburger span{display:block;width:22px;height:2px;background:#fff;border-radius:2px;transition:transform .25s,opacity .25s}
.hamburger.open span:nth-child(1){transform:translateY(7px) rotate(45deg)}
.hamburger.open span:nth-child(2){opacity:0}
.hamburger.open span:nth-child(3){transform:translateY(-7px) rotate(-45deg)}
.site-nav{display:none;flex-direction:column;background:#001F3D;border-top:1px solid rgba(255,255,255,.08);padding:8px 24px 12px}
.site-nav.open{display:flex}
.nav-link{color:rgba(255,255,255,.7);text-decoration:none;padding:10px 14px;border-radius:var(--radius-sm);font-size:14px;font-weight:500;transition:all .15s;display:flex;align-items:center;gap:8px}
.nav-link:hover{color:#fff;background:rgba(255,255,255,.08)}
.nav-link.active{color:var(--amber);background:rgba(255,203,5,.15)}
.site-main{max-width:1280px;margin:0 auto;padding:24px}
.page-layout{display:grid;grid-template-columns:400px 1fr;gap:20px;align-items:start}
@media(max-width:900px){.page-layout{grid-template-columns:1fr}}
.panel{background:var(--surface);border-radius:var(--radius-lg);border:1px solid var(--border);box-shadow:var(--shadow-xs);overflow:hidden}
.panel-header{padding:16px 20px 14px;border-bottom:1px solid var(--border);background:var(--surface);display:flex;align-items:center;justify-content:space-between}
.panel-title{font-size:15px;font-weight:700;color:var(--text);display:flex;align-items:center;gap:8px}
.panel-body{padding:20px}
.field-group{display:flex;flex-direction:column;gap:5px;margin-bottom:14px}
.field-label{font-size:11.5px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:.06em}
.field-hint{font-size:11px;color:var(--text3);margin-top:2px}
.required{color:var(--amber-d);margin-left:2px}
.field-input{border:1.5px solid var(--border);border-radius:var(--radius-sm);padding:9px 11px;font-size:14px;color:var(--text);background:var(--surface);transition:border-color .15s,box-shadow .15s;width:100%;font-family:var(--font)}
.field-input:hover{border-color:var(--border2)}
.field-input:focus{outline:none;border-color:var(--amber);box-shadow:0 0 0 3px rgba(255,203,5,.18)}
select.field-input{cursor:pointer}
.row-2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.autocomplete-wrap{position:relative}
.autocomplete-list{position:absolute;top:calc(100% + 4px);left:0;right:0;background:var(--surface);border:1.5px solid var(--amber);border-radius:var(--radius);box-shadow:var(--shadow);z-index:300;max-height:200px;overflow-y:auto}
.ac-item{padding:10px 12px;cursor:pointer;border-bottom:1px solid var(--border);transition:background .1s}
.ac-item:last-child{border-bottom:none}
.ac-item:hover{background:var(--amber-xl)}
.ac-name{font-weight:600;font-size:13px;color:var(--text)}
.ac-detail{font-size:11px;color:var(--text3);margin-top:1px}
.calc-total-bar{background:linear-gradient(135deg,#00274C 0%,#003A6B 100%);border-radius:var(--radius);padding:14px 16px;display:flex;justify-content:space-between;align-items:center;margin:16px 0 12px;box-shadow:0 2px 8px rgba(0,39,76,.3)}
.calc-total-label{color:rgba(255,255,255,.8);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.calc-total-value{color:#fff;font-size:24px;font-weight:800;letter-spacing:-.5px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 18px;border-radius:var(--radius-sm);font-size:13.5px;font-weight:600;cursor:pointer;border:none;transition:all .15s;text-decoration:none;font-family:var(--font);letter-spacing:-.1px}
.btn:active{transform:scale(.97)}
.btn-primary{background:var(--amber);color:#00274C;box-shadow:0 2px 8px rgba(255,203,5,.35)}
.btn-primary:hover{background:var(--amber-d);box-shadow:0 4px 12px rgba(255,203,5,.45);transform:translateY(-1px)}
.btn-secondary{background:#00274C;color:#fff}
.btn-secondary:hover{background:#003A6B}
.btn-ghost{background:transparent;color:var(--text2);border:1.5px solid var(--border)}
.btn-ghost:hover{background:var(--surface2);border-color:var(--border2);color:var(--text)}
.btn-danger{background:var(--red);color:#fff}
.btn-danger:hover{background:#DC2626}
.btn-warning{background:#F97316;color:#fff;font-size:12px;padding:5px 11px}
.btn-sm{padding:6px 12px;font-size:12px}
.btn-full{width:100%}
.btn-group{display:flex;flex-wrap:wrap;gap:8px}
.log-header{padding:16px 20px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
.log-date-wrap{display:flex;align-items:center;gap:8px}
.log-date-wrap label{font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.05em}
.log-list{padding:12px;display:flex;flex-direction:column;gap:8px;min-height:80px}
.empty-msg{color:var(--text3);text-align:center;padding:32px 20px;font-size:13px}
.pickup-card{border:1px solid var(--border);border-radius:var(--radius);background:var(--surface);overflow:hidden;transition:border-color .15s,box-shadow .15s}
.pickup-card:hover{border-color:var(--amber);box-shadow:var(--shadow-sm)}
.pickup-card-head{padding:10px 14px;background:var(--surface2);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;gap:8px}
.pickup-time{font-size:13px;font-weight:700;color:var(--amber-dd)}
.pickup-total-wrap{display:flex;align-items:center;gap:6px}
.pickup-total{font-size:15px;font-weight:800;color:var(--text);letter-spacing:-.3px}
.pm-badge{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:20px;text-transform:uppercase;letter-spacing:.04em}
.pm-cash{background:var(--green-lt);color:#065F46}
.pm-credit{background:var(--blue-lt);color:#1E40AF}
.pm-voucher{background:var(--purple-lt);color:#5B21B6}
.pm-none{background:var(--surface2);color:var(--text3)}
.pickup-card-body{padding:10px 14px}
.pickup-route{font-size:13px;color:var(--text2);margin-bottom:5px;display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
.pickup-route strong{color:var(--text);font-weight:600}
.pickup-meta{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--text3)}
.pickup-card-foot{padding:8px 14px;border-top:1px solid var(--border);display:flex;gap:6px;background:var(--surface)}
.totals-panel{margin:0 12px 12px;border-radius:var(--radius);overflow:hidden;border:1px solid var(--border)}
.totals-head{background:#00274C;padding:10px 14px}
.totals-head-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:rgba(255,255,255,.45);font-weight:600}
.totals-grid{display:grid;grid-template-columns:1fr 1fr;background:var(--surface2)}
.total-cell{padding:10px 14px;border-right:1px solid var(--border);border-bottom:1px solid var(--border)}
.total-cell:nth-child(even){border-right:none}
.total-cell-label{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--text3);font-weight:600;margin-bottom:2px}
.total-cell-val{font-size:16px;font-weight:700;color:var(--text);letter-spacing:-.3px}
.owed-driver-bar{padding:14px 16px;background:#00274C;display:flex;justify-content:space-between;align-items:center}
.earnings-bar{background:#166534}
.owed-driver-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:rgba(255,203,5,.7)}
.owed-driver-val{font-size:26px;font-weight:800;color:#FFCB05;letter-spacing:-.5px}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:500;display:flex;align-items:center;justify-content:center;padding:20px}
.modal-box{background:var(--surface);border-radius:var(--radius-lg);box-shadow:var(--shadow-lg);width:100%;max-width:520px;max-height:90vh;overflow-y:auto;border:1px solid var(--border)}
.modal-wide{max-width:900px}
.modal-header{display:flex;justify-content:space-between;align-items:center;padding:18px 22px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--surface);z-index:1}
.modal-header h2{font-size:16px;font-weight:700}
.modal-close{background:var(--surface2);border:none;cursor:pointer;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;color:var(--text2);transition:all .15s}
.modal-close:hover{background:var(--border);color:var(--text)}
.modal-body{padding:22px}
.report-controls{border-bottom:1px solid var(--border);padding-bottom:16px}
.report-output{font-size:13px}
.report-day{margin-bottom:20px;border:1px solid var(--border);border-radius:var(--radius)}
.report-day-hdr{background:#00274C;color:#fff;padding:10px 14px;display:flex;justify-content:space-between;align-items:center}
.report-shift-bar{background:#001F3D;color:rgba(255,203,5,.6);font-size:11px;padding:5px 14px}
.report-table{width:100%;border-collapse:collapse;min-width:520px}
.report-table th{background:var(--amber-lt);padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--amber-dd);border-bottom:1px solid var(--border);white-space:nowrap}
.report-table td{padding:8px 12px;border-bottom:1px solid var(--border);font-size:13px;white-space:nowrap}
.report-table tr:last-child td{border-bottom:none}
.report-table tr:hover td{background:var(--surface2)}
.report-expense-row td{background:var(--red-lt);color:#991B1B;font-style:italic}
.report-day-foot{background:var(--surface2);padding:10px 14px;display:flex;flex-wrap:wrap;gap:14px;font-size:12px;border-top:1px solid var(--border)}
.report-net{color:var(--green);font-weight:700}
.report-summary{background:#00274C;color:#fff;border-radius:var(--radius);padding:18px;margin-top:16px}
.report-summary h3{color:var(--amber);margin-bottom:14px;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.07em}
.summary-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px}
.summary-item{background:rgba(255,255,255,.06);border-radius:var(--radius-sm);padding:10px 12px}
.summary-label{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:rgba(255,255,255,.4);margin-bottom:3px}
.summary-val{font-size:17px;font-weight:700;color:#fff;letter-spacing:-.3px}
.summary-owed{color:var(--amber)}
.summary-net{color:#34D399}
.restore-row{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)}
.restore-row:last-child{border-bottom:none}
.restore-label{width:80px;font-size:13px;font-weight:600;color:var(--text2);flex-shrink:0}
.restore-row input[type=file]{flex:1;font-size:12px;color:var(--text2)}
.section-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text3);margin:16px 0 8px}
.danger-label{color:var(--red)}
.warning-text{font-size:12px;color:#92400E;background:var(--amber-lt);border-radius:var(--radius-sm);padding:8px 10px;margin-bottom:10px;border:1px solid #FDE68A}
.divider{border:none;border-top:1px solid var(--border);margin:18px 0}
.mt-2{margin-top:8px}.mt-4{margin-top:16px}.mb-4{margin-bottom:16px}
.toast{position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:#00274C;color:#FFCB05;padding:11px 22px;border-radius:var(--radius-xl);font-size:13.5px;font-weight:600;box-shadow:var(--shadow-lg);z-index:9999;pointer-events:none;letter-spacing:-.1px}
.setup-page{display:flex;align-items:center;justify-content:center;min-height:calc(100vh - 60px);padding:40px 20px}
.setup-card{background:var(--surface);border-radius:var(--radius-xl);box-shadow:var(--shadow-lg);padding:40px;width:100%;max-width:480px;border:1px solid var(--border)}
.setup-icon{font-size:44px;text-align:center;margin-bottom:16px}
.setup-title{font-size:24px;font-weight:800;text-align:center;color:var(--text);margin-bottom:4px;letter-spacing:-.5px}
.setup-sub{text-align:center;color:var(--text3);margin-bottom:28px;font-size:14px}
.setup-form .field-group{margin-bottom:16px}
.setup-section-title{font-size:14px;font-weight:700;color:var(--text);margin-bottom:4px}
.setup-section-sub{font-size:12px;color:var(--text3);margin-bottom:16px}
.pay-mode-explain{font-size:12px;color:var(--text2);background:var(--surface2);border-radius:var(--radius-sm);padding:8px 10px;margin-top:4px;border:1px solid var(--border);min-height:36px;font-style:italic}
.expense-list{display:flex;flex-direction:column;gap:6px}
.expense-item{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:var(--surface2);border-radius:var(--radius-sm);border:1px solid var(--border)}
.expense-item-left{display:flex;flex-direction:column;gap:2px}
.expense-item-right{display:flex;align-items:center;gap:8px;flex-shrink:0}
.expense-cat-badge{font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px;background:var(--red-lt);color:#991B1B}
.expense-notes{font-size:11px;color:var(--text3)}
.expense-amt{font-size:15px;font-weight:700;color:var(--red)}
.expense-total-bar{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;background:var(--red-lt);border-radius:var(--radius-sm);margin-top:12px;border:1px solid #FECACA}
.expense-total-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#991B1B}
.expense-total-val{font-size:20px;font-weight:800;color:var(--red)}
.shift-stats-bar{display:flex;gap:12px;background:var(--amber-xl);border-radius:var(--radius-sm);padding:12px 14px;margin:12px 0;border:1px solid var(--amber-lt)}
.shift-stat{flex:1;text-align:center}
.shift-stat-label{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--amber-dd);font-weight:600;margin-bottom:2px}
.shift-stat-val{font-size:22px;font-weight:800;color:var(--amber-dd)}
.shift-saved{background:var(--surface2);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden}
.shift-saved-row{display:flex;justify-content:space-between;padding:8px 14px;border-bottom:1px solid var(--border);font-size:13px}
.shift-saved-row:last-child{border-bottom:none}
.shift-saved-row span{color:var(--text3)}
.shift-saved-row strong{color:var(--text)}
.auth-page{display:flex;align-items:center;justify-content:center;min-height:100vh;padding:40px 20px;background:linear-gradient(135deg,#00274C 0%,#003366 100%)}
.auth-card{background:var(--surface);border-radius:var(--radius-xl);box-shadow:var(--shadow-lg);padding:40px;width:100%;max-width:400px;border:1px solid var(--border)}
.auth-error{background:var(--red-lt);color:#991B1B;border:1px solid #FECACA;border-radius:var(--radius-sm);padding:10px 14px;font-size:13px;font-weight:600;margin-bottom:16px;text-align:center}
.auth-success{background:var(--green-lt);color:#065F46;border:1px solid #A7F3D0;border-radius:var(--radius-sm);padding:10px 14px;font-size:13px;font-weight:600;margin-bottom:16px;text-align:center}
.reset-url-box{background:#F8FAFC;border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;margin-bottom:16px}
.reset-url-box textarea{width:100%;font-family:monospace;font-size:12px;border:1px solid var(--border);border-radius:4px;padding:8px;resize:none;background:#fff;box-sizing:border-box}
.auth-foot{text-align:center;font-size:13px;color:var(--text3);margin-top:18px}
.auth-link{color:var(--amber-d);font-weight:600;text-decoration:none}
.auth-link:hover{text-decoration:underline}
.admin-page{max-width:900px;margin:0 auto;padding:24px 12px}
@media(min-width:600px){.admin-page{padding:32px 20px}}
.admin-section{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);margin-bottom:20px;overflow:hidden}
.admin-section-header{padding:14px 16px;background:var(--surface2);border-bottom:1px solid var(--border);font-weight:700;font-size:14px;color:var(--text)}
.admin-table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
.admin-table{width:100%;border-collapse:collapse;font-size:13px;min-width:480px}
.admin-table th{padding:9px 12px;text-align:left;font-weight:600;color:var(--text2);background:var(--surface2);border-bottom:1px solid var(--border);white-space:nowrap}
.admin-table td{padding:9px 12px;border-bottom:1px solid var(--border);vertical-align:middle;white-space:nowrap}
.admin-table tr:last-child td{border-bottom:none}
.admin-table tr:hover td{background:var(--amber-xl)}
.admin-badge{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px}
.badge-driver{background:var(--blue-lt);color:#1e40af}
.badge-admin{background:var(--amber-lt);color:#92400e}
.badge-inactive{background:var(--red-lt);color:#991b1b}
.admin-actions{display:flex;gap:6px;flex-wrap:wrap}
.admin-stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;padding:16px}
.admin-stat{background:var(--surface2);border-radius:var(--radius);padding:14px;text-align:center}
.admin-stat-val{font-size:22px;font-weight:800;color:var(--amber-d)}
.admin-stat-label{font-size:11px;color:var(--text3);margin-top:4px}
.clk-input{cursor:pointer;caret-color:transparent}
#clk-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;display:flex;align-items:center;justify-content:center}
#clk-popup{background:#fff;border-radius:var(--radius-xl);padding:22px 20px 16px;width:250px;box-shadow:var(--shadow-lg);border:1px solid var(--border)}
#clk-display{font-size:32px;font-weight:800;text-align:center;color:var(--text);letter-spacing:-1px;margin-bottom:14px;font-family:var(--font)}
#clk-ampm{display:flex;gap:8px;justify-content:center;margin-bottom:14px}
#clk-ampm button{flex:1;padding:8px;border:2px solid var(--border);border-radius:var(--radius-sm);font-size:13px;font-weight:700;cursor:pointer;background:#fff;color:var(--text2);transition:all .15s;font-family:var(--font)}
#clk-ampm button.clk-active{background:var(--amber);border-color:var(--amber);color:#fff}
#clk-face{position:relative;width:200px;height:200px;border-radius:50%;background:var(--surface2);border:2px solid var(--border);margin:0 auto 10px}
.clk-num{position:absolute;width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12.5px;font-weight:600;cursor:pointer;color:var(--text2);transition:background .1s,color .1s;user-select:none}
.clk-num:hover{background:var(--amber-lt);color:var(--amber-dd)}
.clk-num.clk-sel{background:var(--amber);color:#fff}
#clk-hint{text-align:center;font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.08em;font-weight:600;margin-bottom:12px}
#clk-cancel{width:100%;padding:8px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:#fff;cursor:pointer;font-size:13px;color:var(--text2);font-family:var(--font);transition:background .15s}
#clk-cancel:hover{background:var(--surface2)}
"""

# ════════════════════════════════════════════════════════════════
# JAVASCRIPT
# ════════════════════════════════════════════════════════════════

JS = """/* app.js */
(function(){
  const _f=window.fetch;
  window.fetch=async function(...a){
    const r=await _f(...a);
    if(r.status===401){window.location.href='/login';return r;}
    return r;
  };
})();

function fmt(v){return '$'+(parseFloat(v)||0).toFixed(2)}

/* 12h ↔ 24h helpers for Clocklet */
function to24h(t){
  if(!t)return'';
  const m=t.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if(!m)return t;
  let h=parseInt(m[1]);const min=m[2],p=m[3].toUpperCase();
  if(p==='PM'&&h!==12)h+=12;
  if(p==='AM'&&h===12)h=0;
  return String(h).padStart(2,'0')+':'+min;
}
function to12h(t){
  if(!t)return'';
  const parts=t.split(':');if(parts.length<2)return t;
  let h=parseInt(parts[0]);const min=parts[1].slice(0,2);
  const p=h>=12?'PM':'AM';
  if(h>12)h-=12;if(h===0)h=12;
  return String(h).padStart(2,'0')+':'+min+' '+p;
}
/* ── Analogue Clock Picker ───────────────────────────────────── */
(function(){
  var HOURS=[12,1,2,3,4,5,6,7,8,9,10,11];
  var MINS=[0,5,10,15,20,25,30,35,40,45,50,55];
  var _inp=null,_mode='hour',_h=12,_m=0,_per='AM';

  var ov=document.createElement('div');
  ov.id='clk-overlay';ov.style.display='none';
  ov.innerHTML='<div id="clk-popup">'
    +'<div id="clk-display">12:00 AM</div>'
    +'<div id="clk-ampm">'
      +'<button id="clk-am" class="clk-active">AM</button>'
      +'<button id="clk-pm">PM</button>'
    +'</div>'
    +'<div id="clk-face"></div>'
    +'<div id="clk-hint">Select hour</div>'
    +'<button id="clk-cancel">Cancel</button>'
    +'</div>';
  document.body.appendChild(ov);

  function buildFace(items){
    var face=ov.querySelector('#clk-face');face.innerHTML='';
    var R=76;
    items.forEach(function(val,i){
      var ang=(i*30-90)*Math.PI/180;
      var x=100+R*Math.cos(ang)-17;
      var y=100+R*Math.sin(ang)-17;
      var el=document.createElement('div');
      var isSel=_mode==='hour'?val===_h:val===_m;
      el.className='clk-num'+(isSel?' clk-sel':'');
      el.style.left=x+'px';el.style.top=y+'px';
      el.textContent=_mode==='minute'?String(val).padStart(2,'0'):String(val);
      el.onclick=function(){pick(val);};
      face.appendChild(el);
    });
  }

  function updDisp(){
    ov.querySelector('#clk-display').textContent=
      String(_h).padStart(2,'0')+':'+String(_m).padStart(2,'0')+' '+_per;
    ov.querySelector('#clk-am').className=_per==='AM'?'clk-active':'';
    ov.querySelector('#clk-pm').className=_per==='PM'?'clk-active':'';
  }

  function pick(val){
    if(_mode==='hour'){
      _h=val;_mode='minute';
      ov.querySelector('#clk-hint').textContent='Select minute';
      buildFace(MINS);
    }else{
      _m=val;commit();
    }
    updDisp();
  }

  function commit(){
    if(_inp){
      _inp.value=String(_h).padStart(2,'0')+':'+String(_m).padStart(2,'0')+' '+_per;
      _inp.dispatchEvent(new Event('input',{bubbles:true}));
      _inp.dispatchEvent(new Event('change',{bubbles:true}));
    }
    close();
  }

  function close(){ov.style.display='none';_inp=null;}

  window.openClockPicker=function(input){
    _inp=input;_mode='hour';
    var v=input.value;
    var mt=v.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
    if(mt){
      _h=parseInt(mt[1]);
      _m=Math.round(parseInt(mt[2])/5)*5%60;
      _per=mt[3].toUpperCase();
    }else{_h=12;_m=0;_per='AM';}
    ov.querySelector('#clk-hint').textContent='Select hour';
    buildFace(HOURS);updDisp();
    ov.style.display='flex';
  };

  ov.querySelector('#clk-am').onclick=function(){_per='AM';updDisp();};
  ov.querySelector('#clk-pm').onclick=function(){_per='PM';updDisp();};
  ov.querySelector('#clk-cancel').onclick=close;
  ov.addEventListener('click',function(e){if(e.target===ov)close();});
})();

function showToast(msg,d=2500){
  const t=document.getElementById('toast');
  t.textContent=msg;t.style.display='block';
  clearTimeout(t._t);t._t=setTimeout(()=>t.style.display='none',d);
}
function openModal(id){document.getElementById(id).style.display='flex'}
function closeModal(id){document.getElementById(id).style.display='none'}
document.querySelectorAll('.modal-overlay').forEach(el=>{
  el.addEventListener('click',e=>{if(e.target===el)el.style.display='none'});
});

function toggleNav(){
  const nav=document.getElementById('siteNav');
  const btn=document.getElementById('hamburger');
  if(!nav)return;
  nav.classList.toggle('open');
  if(btn)btn.classList.toggle('open');
}
function closeNav(){
  const nav=document.getElementById('siteNav');
  const btn=document.getElementById('hamburger');
  if(nav)nav.classList.remove('open');
  if(btn)btn.classList.remove('open');
}
document.addEventListener('click',e=>{
  const nav=document.getElementById('siteNav');
  const btn=document.getElementById('hamburger');
  if(!nav||!btn)return;
  if(!nav.contains(e.target)&&!btn.contains(e.target))closeNav();
});

function updateCalcTotal(){
  const m=parseFloat(document.getElementById('meter_total')?.value)||0;
  const t=parseFloat(document.getElementById('tip')?.value)||0;
  const el=document.getElementById('calcTotal');
  if(el)el.textContent=fmt(m+t);
}

/* --- Autocomplete --- */
let acTimer=null;
function suggestCustomers(input,field){
  clearTimeout(acTimer);
  const q=input.value.trim();
  const listId=field==='phone'?'ac-phone':field==='address'?'ac-address':'ac-name';
  if(q.length<2){clearAC();return}
  acTimer=setTimeout(async()=>{
    const r=await fetch('/api/customers/suggest?q='+encodeURIComponent(q));
    renderAC(listId,await r.json());
  },200);
}
function renderAC(listId,customers){
  clearAC();
  if(!customers.length)return;
  const list=document.getElementById(listId);
  customers.forEach(c=>{
    const d=document.createElement('div');
    d.className='ac-item';
    d.innerHTML='<div class="ac-name">'+(c.name||'—')+'</div>'
      +'<div class="ac-detail">'+(c.street_address||'')+' '+(c.city||'')+(c.phone?' · '+c.phone:'')+'</div>';
    d.onclick=()=>{fillFromCustomer(c);clearAC()};
    list.appendChild(d);
  });
}
function clearAC(){
  ['ac-phone','ac-address','ac-name'].forEach(id=>{
    const el=document.getElementById(id);if(el)el.innerHTML='';
  });
}
function fillFromCustomer(c){
  if(c.name)setValue('customer_name',c.name);
  if(c.street_address)setValue('street_address',c.street_address);
  if(c.city)setValue('city',c.city);
  if(c.phone)setValue('phone_number',c.phone);
}
function setValue(id,val){const el=document.getElementById(id);if(el)el.value=val}
async function lookupByPhone(){
  const phone=document.getElementById('phone_number')?.value.trim();
  if(!phone)return;
  const c=await(await fetch('/api/customers/lookup?phone='+encodeURIComponent(phone))).json();
  if(c&&c.name)fillFromCustomer(c);
}
document.addEventListener('click',e=>{if(!e.target.closest('.autocomplete-wrap'))clearAC()});

/* --- Pickup form --- */
function autoTipPm(){
  const tip=parseFloat(document.getElementById('tip').value)||0;
  const tpm=document.getElementById('tip_payment_method');
  if(tip>0&&!tpm.value){
    const pm=document.getElementById('payment_method').value;
    if(pm)tpm.value=pm;
  }
}

async function submitPickup(e){
  e.preventDefault();
  const f=e.target;
  const meter=parseFloat(f.meter_total.value)||0;
  const tip=parseFloat(f.tip.value)||0;
  if(meter>0&&!f.payment_method.value){showToast('Please select a Payment method');return;}
  if(tip>0&&!f.tip_payment_method.value){
    if(f.payment_method.value){f.tip_payment_method.value=f.payment_method.value;}
    else{showToast('Please select a Tip Payment method');return;}
  }
  const data={
    pickup_date:f.pickup_date.value,pickup_time:to24h(f.pickup_time.value),
    street_address:f.street_address.value,city:f.city.value,
    customer_name:f.customer_name.value,phone_number:f.phone_number.value,
    destination_address:f.destination_address.value,
    meter_total:f.meter_total.value,payment_method:f.payment_method.value,
    tip:f.tip.value,tip_payment_method:f.tip_payment_method.value,
  };
  const r=await fetch('/api/pickups',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(r.ok){
    showToast('Pickup recorded!');
    resetForm();
    const ld=document.getElementById('logDate');
    if(ld&&data.pickup_date)ld.value=data.pickup_date;
    loadDailyLog();
  }else showToast('Error saving pickup');
}
function resetForm(){
  const f=document.getElementById('pickupForm');if(!f)return;
  ['street_address','city','customer_name','phone_number','destination_address','meter_total','tip']
    .forEach(id=>setValue(id,''));
  ['payment_method','tip_payment_method'].forEach(id=>setValue(id,''));
  updateCalcTotal();clearAC();
}

/* --- Daily log (fetches server-side totals) --- */
async function loadDailyLog(){
  const el=document.getElementById('logDate');if(!el)return;
  const d=el.value;
  const [pickups,totals]=await Promise.all([
    fetch('/api/pickups?date='+d).then(r=>r.json()),
    fetch('/api/daily-totals?date='+d).then(r=>r.json())
  ]);
  renderLog(pickups);
  if(pickups.length||(totals&&totals.expense_total>0)) renderTotals(totals);
  else{const tp=document.getElementById('dailyTotals');if(tp)tp.style.display='none';}
}

function pmBadge(pm){
  if(!pm)return'';
  const cls={'cash':'pm-cash','credit':'pm-credit','voucher':'pm-voucher'}[pm.toLowerCase()]||'pm-none';
  return'<span class="pm-badge '+cls+'">'+pm+'</span>';
}

function renderLog(pickups){
  const list=document.getElementById('logList');
  if(!list)return;
  if(!pickups.length){
    list.innerHTML='<p class="empty-msg">No pickups recorded for this date.</p>';
    return;
  }
  list.innerHTML=pickups.map(p=>{
    const tipHtml=p.tip>0?'<span class="pickup-meta-item">Tip: '+fmt(p.tip)+' '+pmBadge(p.tip_payment_method)+'</span>':'';
    const custHtml=(p.customer_name?'<span class="pickup-meta-item">'+p.customer_name+'</span>':'');
    const phoneHtml=(p.phone_number?'<span class="pickup-meta-item">'+p.phone_number+'</span>':'');
    const noInfo=(!p.customer_name&&!p.phone_number&&!p.tip)?'<span style="color:var(--text3);font-style:italic">No customer info</span>':'';
    return'<div class="pickup-card" data-id="'+p.id+'">'
      +'<div class="pickup-card-head">'
        +'<span class="pickup-time">'+(p.pickup_time||'--:--')+'</span>'
        +'<div class="pickup-total-wrap">'
          +'<span class="pickup-total">'+fmt(p.calculated_total)+'</span>'
          +pmBadge(p.payment_method)
        +'</div>'
      +'</div>'
      +'<div class="pickup-card-body">'
        +'<div class="pickup-route">'
          +'<strong>'+p.street_address+(p.city?', '+p.city:'')+'</strong>'
          +' <span style="color:var(--text3)">→</span> '
          +p.destination_address
        +'</div>'
        +'<div class="pickup-meta">'+custHtml+phoneHtml+tipHtml+noInfo+'</div>'
      +'</div>'
      +'<div class="pickup-card-foot">'
        +'<button class="btn btn-sm btn-ghost" data-action="edit" data-id="'+p.id+'">Edit</button>'
        +(p.destination_address?'<button class="btn btn-sm btn-primary" data-action="map" data-id="'+p.id+'">Map</button>':'')
        +'<button class="btn btn-sm btn-danger" data-action="delete" data-id="'+p.id+'">Delete</button>'
      +'</div>'
    +'</div>';
  }).join('');
}

/* Event delegation for edit/delete/expense/cancel buttons */
document.addEventListener('click',e=>{
  const btn=e.target.closest('[data-action]');
  if(!btn)return;
  const id=btn.dataset.id;
  if(btn.dataset.action==='edit')openEdit(id);
  if(btn.dataset.action==='map')openMapModal(id);
  if(btn.dataset.action==='delete')deletePickup(id);
  if(btn.dataset.action==='del-expense')deleteExpense(id);
  if(btn.dataset.action==='cancel-edit')closeModal('editModal');
});

async function openMapModal(id){
  const body=document.getElementById('mapModalBody');
  let p;
  try{
    const r=await fetch('/api/pickups/'+id);
    if(!r.ok) throw new Error('Could not load pickup.');
    p=await r.json();
  }catch(e){
    body.innerHTML='<p style="color:var(--red)">Could not load pickup data. Please try again.</p>';
    openModal('mapModal');
    return;
  }
  const pickup=p.street_address+(p.city?', '+p.city:'');
  const dest=p.destination_address||'';
  if(!GMAPS_KEY){
    const url='https://www.google.com/maps/dir/Current+Location/'+encodeURIComponent(pickup);
    body.innerHTML='<p style="margin-bottom:12px;color:var(--text2)">No Maps API key configured — opening in Google Maps.</p>'
      +'<a href="'+url+'" target="_blank" class="btn btn-primary">Open in Google Maps</a>';
    window.open(url,'_blank');
    openModal('mapModal');
    return;
  }
  body.innerHTML='<div style="display:flex;flex-direction:column;gap:12px;padding:8px 0">'
    +'<p style="margin:0;font-size:14px;color:var(--text2)">Where do you want directions to?</p>'
    +'<div style="display:flex;gap:10px">'
      +'<button class="btn btn-primary" style="flex:1" onclick="startMapToPickup()">To Pickup</button>'
      +(dest?'<button class="btn btn-ghost" style="flex:1" onclick="startMapToDest()">To Destination</button>':'')
    +'</div>'
    +'</div>';
  window._mapPickup=pickup;
  window._mapDest=dest;
  openModal('mapModal');
}

function _mapDirError(body,status){
  const msgs={
    NOT_FOUND:'Address not recognized — check the pickup or destination address.',
    ZERO_RESULTS:'No drivable route found between these locations.',
    REQUEST_DENIED:'Maps API request denied — check that the Directions API is enabled and authorized for this key.',
    OVER_QUERY_LIMIT:'Maps API rate limit reached — please wait a moment and try again.',
    OVER_DAILY_LIMIT:'Maps API billing limit reached — check your Google Cloud billing account.',
    INVALID_REQUEST:'Invalid request — the address may be missing or incomplete.',
    UNKNOWN_ERROR:'Google Maps returned an unknown error — please try again.'
  };
  const msg=msgs[status]||('Directions unavailable ('+status+').');
  body.innerHTML='<p style="color:var(--red);font-size:14px">'+msg+'</p>';
}

function startMapToPickup(){startMap(window._mapPickup);}
function startMapToDest(){startMap(window._mapDest);}
async function startMap(target){
  const body=document.getElementById('mapModalBody');
  body.innerHTML='<p style="color:var(--text3);font-size:13px">Getting your location…</p>';
  const doRoute=origin=>{
    body.innerHTML='<div id="gmapDiv" style="width:100%;height:360px;border-radius:8px;margin-bottom:12px"></div>'
      +'<div id="gmapPanel" style="font-size:13px;line-height:1.6;max-height:300px;overflow-y:auto"></div>';
    const map=new google.maps.Map(document.getElementById('gmapDiv'),{zoom:12,center:{lat:37.5,lng:-122.0}});
    const svc=new google.maps.DirectionsService();
    const rend=new google.maps.DirectionsRenderer({map,panel:document.getElementById('gmapPanel')});
    svc.route({origin,destination:target,travelMode:google.maps.TravelMode.DRIVING},(res,status)=>{
      if(status==='OK') rend.setDirections(res);
      else _mapDirError(body,status);
    });
  };
  if(!window.google||!window.google.maps){
    try{
      await new Promise((res,rej)=>{
        const s=document.createElement('script');
        s.src='https://maps.googleapis.com/maps/api/js?key='+GMAPS_KEY;
        s.onload=res; s.onerror=rej;
        document.head.appendChild(s);
      });
    }catch(e){
      body.innerHTML='<p style="color:var(--red);font-size:14px">Could not load Google Maps — check your internet connection.</p>';
      return;
    }
  }
  if(navigator.geolocation){
    navigator.geolocation.getCurrentPosition(
      pos=>doRoute({lat:pos.coords.latitude,lng:pos.coords.longitude}),
      ()=>doRoute(target),
      {timeout:10000,maximumAge:60000}
    );
  }else{
    doRoute(target);
  }
}

function renderTotals(t){
  const tp=document.getElementById('dailyTotals');
  const grid=document.getElementById('totalsGrid');
  const owedEl=document.getElementById('owedDriverVal');
  const owedLabel=document.getElementById('owedDriverLabel');
  if(!tp)return;
  const hasExp=t.expense_total>0;
  const cells=[
    ['Cash Meter',fmt(t.meter_cash)],['Credit Meter',fmt(t.meter_credit)],
    ['Voucher Meter',fmt(t.meter_voucher)],['Cash Tips',fmt(t.tip_cash)],
    ['Credit Tips',fmt(t.tip_credit)],['Voucher Tips',fmt(t.tip_voucher)],
    ['Expenses',fmt(t.expense_total||0)],['Pickups',t.count],
  ];
  if(grid)grid.innerHTML=cells.map(([l,v])=>
    '<div class="total-cell"><div class="total-cell-label">'+l+'</div><div class="total-cell-val">'+v+'</div></div>'
  ).join('');
  if(owedEl)owedEl.textContent=fmt(t.owed_driver);
  if(owedLabel)owedLabel.textContent='Owed Driver';
  const earningsBar=document.getElementById('earningsBar');
  const earningsVal=document.getElementById('earningsVal');
  if(earningsVal)earningsVal.textContent=fmt(t.driver_earnings!==undefined?t.driver_earnings:t.owed_driver);
  if(earningsBar)earningsBar.style.display='flex';
  tp.style.display='block';
}

/* --- Edit modal --- */
async function openEdit(id){
  const p=await(await fetch('/api/pickups/'+id)).json();
  const body=document.getElementById('editModalBody');
  const pmOpts=['','Cash','Credit','Voucher'].map(v=>'<option'+(p.payment_method===v?' selected':'')+'>'+v+'</option>').join('');
  const tpmOpts=['','Cash','Credit','Voucher'].map(v=>'<option'+(p.tip_payment_method===v?' selected':'')+'>'+v+'</option>').join('');
  body.innerHTML=
    '<div class="row-2">'
      +'<div class="field-group"><label class="field-label">Date</label><input type="date" id="e_date" class="field-input" value="'+p.pickup_date+'"></div>'
      +'<div class="field-group"><label class="field-label">Time</label><input type="text" id="e_time" class="field-input clk-input" placeholder="--:-- AM" readonly onclick="openClockPicker(this)" value="'+to12h(p.pickup_time)+'"></div>'
    +'</div>'
    +'<div class="field-group"><label class="field-label">Street Address</label><input type="text" id="e_street" class="field-input" value="'+p.street_address+'"></div>'
    +'<div class="row-2">'
      +'<div class="field-group"><label class="field-label">City</label><input type="text" id="e_city" class="field-input" value="'+(p.city||'')+'"></div>'
      +'<div class="field-group"><label class="field-label">Phone</label><input type="text" id="e_phone" class="field-input" value="'+(p.phone_number||'')+'"></div>'
    +'</div>'
    +'<div class="field-group"><label class="field-label">Customer Name</label><input type="text" id="e_name" class="field-input" value="'+(p.customer_name||'')+'"></div>'
    +'<div class="field-group"><label class="field-label">Destination</label><input type="text" id="e_dest" class="field-input" value="'+p.destination_address+'"></div>'
    +'<div class="row-2">'
      +'<div class="field-group"><label class="field-label">Meter ($)</label><input type="number" id="e_meter" class="field-input" step="0.01" value="'+(p.meter_total||0)+'" oninput="eCalc()"></div>'
      +'<div class="field-group"><label class="field-label">Payment</label><select id="e_pm" class="field-input">'+pmOpts+'</select></div>'
    +'</div>'
    +'<div class="row-2">'
      +'<div class="field-group"><label class="field-label">Tip ($)</label><input type="number" id="e_tip" class="field-input" step="0.01" value="'+(p.tip||0)+'" oninput="eCalc()"></div>'
      +'<div class="field-group"><label class="field-label">Tip Payment</label><select id="e_tpm" class="field-input">'+tpmOpts+'</select></div>'
    +'</div>'
    +'<div class="calc-total-bar"><span class="calc-total-label">Calculated Total</span><span id="e_calc" class="calc-total-value">'+fmt(p.calculated_total)+'</span></div>'
    +'<div class="btn-group mt-2">'
      +'<button class="btn btn-primary" data-action="save-edit" data-id="'+id+'">Save Changes</button>'
      +'<button class="btn btn-ghost" data-action="cancel-edit">Cancel</button>'
    +'</div>';
  openModal('editModal');
}
function eCalc(){
  const m=parseFloat(document.getElementById('e_meter')?.value)||0;
  const t=parseFloat(document.getElementById('e_tip')?.value)||0;
  const el=document.getElementById('e_calc');if(el)el.textContent=fmt(m+t);
}
document.addEventListener('click',async e=>{
  const btn=e.target.closest('[data-action="save-edit"]');
  if(!btn)return;
  const id=btn.dataset.id;
  const eMeter=parseFloat(document.getElementById('e_meter').value)||0;
  const eTip=parseFloat(document.getElementById('e_tip').value)||0;
  const ePm=document.getElementById('e_pm');
  const eTpm=document.getElementById('e_tpm');
  if(eMeter>0&&!ePm.value){showToast('Please select a Payment method');return;}
  if(eTip>0&&!eTpm.value){
    if(ePm.value){eTpm.value=ePm.value;}
    else{showToast('Please select a Tip Payment method');return;}
  }
  const data={
    pickup_date:document.getElementById('e_date').value,
    pickup_time:to24h(document.getElementById('e_time').value),
    street_address:document.getElementById('e_street').value,
    city:document.getElementById('e_city').value,
    customer_name:document.getElementById('e_name').value,
    phone_number:document.getElementById('e_phone').value,
    destination_address:document.getElementById('e_dest').value,
    meter_total:document.getElementById('e_meter').value,
    payment_method:document.getElementById('e_pm').value,
    tip:document.getElementById('e_tip').value,
    tip_payment_method:document.getElementById('e_tpm').value,
  };
  const r=await fetch('/api/pickups/'+id,{method:'PUT',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(r.ok){closeModal('editModal');showToast('Record updated!');loadDailyLog();}
  else showToast('Error updating record');
});

async function deletePickup(id){
  if(!confirm('Delete this pickup record?'))return;
  const r=await fetch('/api/pickups/'+id,{method:'DELETE'});
  if(r.ok){showToast('Pickup deleted');loadDailyLog();}
  else showToast('Error deleting record');
}

/* --- Delete all --- */
async function deleteAll(){
  if(!confirm('Delete ALL pickups and customers?\\nDriver profile will NOT be deleted.'))return;
  const r=await fetch('/api/pickups',{method:'DELETE'});
  if(r.ok){showToast('All pickups and customers deleted');closeModal('backupModal');loadDailyLog();}
  else showToast('Error during deletion');
}

/* --- Ask panel --- */
(function(){
  const today=new Date();
  const pad=n=>String(n).padStart(2,'0');
  const fmt=d=>d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
  const ago=new Date(today); ago.setDate(ago.getDate()-30);
  const f=document.getElementById('askFrom');
  const t=document.getElementById('askTo');
  if(f)f.value=fmt(ago);
  if(t)t.value=fmt(today);
})();
async function submitAsk(){
  const q=document.getElementById('askQuestion').value.trim();
  if(!q)return;
  const from=document.getElementById('askFrom').value;
  const to=document.getElementById('askTo').value;
  const result=document.getElementById('askResult');
  const answer=document.getElementById('askAnswer');
  result.style.display='block';
  answer.textContent='Thinking…';
  const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({question:q,from_date:from,to_date:to})});
  const d=await r.json();
  answer.textContent=d.answer||d.error||'No response.';
}
function clearAsk(){
  document.getElementById('askQuestion').value='';
  document.getElementById('askResult').style.display='none';
  document.getElementById('askAnswer').textContent='';
}

/* --- Expense Modal --- */
function openExpenseModal(){
  const d=document.getElementById('logDate');
  const expDate=document.getElementById('exp_date');
  if(d&&expDate)expDate.value=d.value;
  loadExpenses();
  openModal('expenseModal');
}

async function loadExpenses(){
  const dateEl=document.getElementById('exp_date');
  if(!dateEl||!dateEl.value)return;
  const expenses=await fetch('/api/expenses?date='+dateEl.value).then(r=>r.json());
  renderExpenses(expenses);
}

function renderExpenses(expenses){
  const list=document.getElementById('expenseList');
  const bar=document.getElementById('expenseTotalBar');
  const totalEl=document.getElementById('expenseTotalVal');
  if(!list)return;
  if(!expenses.length){
    list.innerHTML='<p class="empty-msg">No expenses for this date.</p>';
    if(bar)bar.style.display='none';
    return;
  }
  const total=expenses.reduce((s,e)=>s+(e.amount||0),0);
  list.innerHTML=expenses.map(e=>
    '<div class="expense-item">'
      +'<div class="expense-item-left">'
        +'<span class="expense-cat-badge">'+e.category+'</span>'
        +(e.notes?'<span class="expense-notes">'+e.notes+'</span>':'')
      +'</div>'
      +'<div class="expense-item-right">'
        +'<span class="expense-amt">'+fmt(e.amount)+'</span>'
        +'<button class="btn btn-sm btn-danger" data-action="del-expense" data-id="'+e.id+'">✕</button>'
      +'</div>'
    +'</div>'
  ).join('');
  if(totalEl)totalEl.textContent=fmt(total);
  if(bar)bar.style.display='flex';
}

async function submitExpense(e){
  e.preventDefault();
  const data={
    date:document.getElementById('exp_date').value,
    amount:document.getElementById('exp_amount').value,
    category:document.getElementById('exp_category').value,
    notes:document.getElementById('exp_notes').value,
  };
  const r=await fetch('/api/expenses',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(r.ok){
    showToast('Expense added');
    setValue('exp_amount','');setValue('exp_notes','');setValue('exp_category','');
    loadExpenses();
    loadDailyLog();
  }else showToast('Error saving expense');
}

async function deleteExpense(id){
  if(!confirm('Delete this expense?'))return;
  const r=await fetch('/api/expenses/'+id,{method:'DELETE'});
  if(r.ok){showToast('Expense deleted');loadExpenses();loadDailyLog();}
  else showToast('Error deleting expense');
}

/* --- Shift Modal --- */
document.addEventListener('change',function(e){
  if(e.target.id==='sh_start'||e.target.id==='sh_end')calcShiftStats();
});
function openShiftModal(){
  const d=document.getElementById('logDate');
  const shDate=document.getElementById('sh_date');
  if(d&&shDate)shDate.value=d.value;
  loadShift();
  openModal('shiftModal');
}

async function loadShift(){
  const dateEl=document.getElementById('sh_date');
  if(!dateEl||!dateEl.value)return;
  const shifts=await fetch('/api/shifts?date='+dateEl.value).then(r=>r.json());
  const savedEl=document.getElementById('shiftSaved');
  if(shifts.length){
    const s=shifts[0];
    setValue('sh_start',to12h(s.start_time||''));
    setValue('sh_end',to12h(s.end_time||''));
    setValue('sh_odo_start',s.odometer_start>0?s.odometer_start:'');
    setValue('sh_odo_end',s.odometer_end>0?s.odometer_end:'');
    setValue('sh_notes',s.notes||'');
    calcShiftStats();
    renderShiftSaved(s);
  }else{
    setValue('sh_start','');
    setValue('sh_end','');
    setValue('sh_odo_start','');
    setValue('sh_odo_end','');
    setValue('sh_notes','');
    const bar=document.getElementById('shiftStatsBar');
    if(bar)bar.style.display='none';
    if(savedEl)savedEl.style.display='none';
  }
}

function calcShiftStats(){
  const s=to24h(document.getElementById('sh_start')?.value);
  const e=to24h(document.getElementById('sh_end')?.value);
  const os=parseFloat(document.getElementById('sh_odo_start')?.value)||0;
  const oe=parseFloat(document.getElementById('sh_odo_end')?.value)||0;
  const bar=document.getElementById('shiftStatsBar');
  let show=false;
  if(oe>os){document.getElementById('shiftMilesVal').textContent=Math.round(oe-os);show=true;}
  if(s&&e){
    const sm=parseInt(s.split(':')[0])*60+parseInt(s.split(':')[1]);
    const em=parseInt(e.split(':')[0])*60+parseInt(e.split(':')[1]);
    let diff=em-sm;if(diff<0)diff+=1440;
    document.getElementById('shiftHoursVal').textContent=(diff/60).toFixed(1);show=true;
  }
  if(bar)bar.style.display=show?'flex':'none';
}

async function submitShift(e){
  e.preventDefault();
  const data={
    date:document.getElementById('sh_date').value,
    start_time:to24h(document.getElementById('sh_start').value),
    end_time:to24h(document.getElementById('sh_end').value),
    odometer_start:document.getElementById('sh_odo_start').value||0,
    odometer_end:document.getElementById('sh_odo_end').value||0,
    notes:document.getElementById('sh_notes').value,
  };
  const r=await fetch('/api/shifts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if(r.ok){showToast('Shift saved');renderShiftSaved(await r.json());}
  else showToast('Error saving shift');
}

function renderShiftSaved(s){
  const el=document.getElementById('shiftSaved');
  if(!el)return;
  let hours='—';
  if(s.start_time&&s.end_time){
    const sm=parseInt(s.start_time.split(':')[0])*60+parseInt(s.start_time.split(':')[1]);
    const em=parseInt(s.end_time.split(':')[0])*60+parseInt(s.end_time.split(':')[1]);
    let d=em-sm;if(d<0)d+=1440;
    hours=(d/60).toFixed(1)+' hrs';
  }
  el.innerHTML='<div class="shift-saved">'
    +'<div class="shift-saved-row"><span>Start</span><strong>'+(s.start_time||'—')+'</strong></div>'
    +'<div class="shift-saved-row"><span>End</span><strong>'+(s.end_time||'—')+'</strong></div>'
    +'<div class="shift-saved-row"><span>Hours</span><strong>'+hours+'</strong></div>'
    +'<div class="shift-saved-row"><span>Miles</span><strong>'+(s.miles>0?Math.round(s.miles)+' mi':'—')+'</strong></div>'
    +(s.notes?'<div class="shift-saved-row"><span>Notes</span><strong>'+s.notes+'</strong></div>':'')
  +'</div>';
  el.style.display='block';
}

/* --- Report --- */
async function generateReport(){
  const from=document.getElementById('rptFrom').value;
  const to=document.getElementById('rptTo').value;
  let url='/api/report';
  const p=[];
  if(from)p.push('from_date='+from);
  if(to)p.push('to_date='+to);
  if(p.length)url+='?'+p.join('&');
  renderReport(await(await fetch(url)).json());
}

function renderReport(data){
  const out=document.getElementById('reportOutput');
  if(!data.days||!data.days.length){out.innerHTML='<p class="empty-msg">No data found for this date range.</p>';return}
  const modeLabels={standard:'Standard Split',gate:'Flat Gate Fee',commission:'Commission Split',owner:'Owner-Operator'};
  const modeLabel=modeLabels[data.summary.pay_mode]||'Standard';
  const dayBlocks=data.days.map(day=>{
    const rows=day.pickups.map(p=>
      '<tr><td>'+(p.pickup_time||'')+'</td>'
      +'<td>'+p.street_address+(p.city?', '+p.city:'')+'</td>'
      +'<td>'+p.destination_address+'</td>'
      +'<td>'+(p.customer_name||'—')+'</td>'
      +'<td>'+fmt(p.meter_total)+'</td>'
      +'<td>'+(p.payment_method||'—')+'</td>'
      +'<td>'+fmt(p.tip)+'</td>'
      +'<td>'+fmt(p.calculated_total)+'</td></tr>'
    ).join('');
    const expRows=(day.expenses&&day.expenses.length)?
      day.expenses.map(e=>
        '<tr class="report-expense-row"><td colspan="4">💸 '+e.category+(e.notes?' – '+e.notes:'')+'</td>'
        +'<td colspan="4" style="text-align:right">− '+fmt(e.amount)+'</td></tr>'
      ).join(''):'';
    const t=day.totals;
    const sh=day.shift;
    const shiftBar=sh?(sh.start_time||sh.end_time||sh.miles>0?
      '⏱ '+(sh.start_time?'In: '+sh.start_time:'')+
      (sh.end_time?' Out: '+sh.end_time:'')+
      (sh.miles>0?' | '+Math.round(sh.miles)+' mi':''):''):'';
    return'<div class="report-day">'
      +'<div class="report-day-hdr"><span style="font-weight:700">'+day.date+'</span>'
        +'<span style="font-size:12px;color:rgba(255,255,255,.5)">'+t.count+' pickups &nbsp;|&nbsp; '+fmt(t.grand_total)+'</span></div>'
      +(shiftBar?'<div class="report-shift-bar">'+shiftBar+'</div>':'')
      +'<div style="overflow-x:auto;-webkit-overflow-scrolling:touch"><table class="report-table"><thead><tr>'
        +'<th>Time</th><th>From</th><th>To</th><th>Customer</th>'
        +'<th>Meter</th><th>Pay</th><th>Tip</th><th>Total</th>'
      +'</tr></thead><tbody>'+rows+expRows+'</tbody></table></div>'
      +'<div class="report-day-foot">'
        +'<span>Cash: '+fmt(t.meter_cash)+'</span>'
        +'<span>Credit: '+fmt(t.meter_credit)+'</span>'
        +'<span>Voucher: '+fmt(t.meter_voucher)+'</span>'
        +'<span>Tips: '+fmt(t.tip_cash+t.tip_credit+t.tip_voucher)+'</span>'
        +(t.expense_total>0?'<span style="color:var(--red)">Expenses: −'+fmt(t.expense_total)+'</span>':'')
        +'<strong>Owed: '+fmt(t.owed_driver)+'</strong>'
        +'<strong class="report-net">Earnings: '+fmt(t.driver_earnings!==undefined?t.driver_earnings:t.owed_driver)+'</strong>'
      +'</div>'
    +'</div>';
  }).join('');
  const s=data.summary;
  const summaryItems=[
    ['Pickups',s.count,false],['Cash Meter',fmt(s.meter_cash),false],
    ['Credit Meter',fmt(s.meter_credit),false],['Voucher Meter',fmt(s.meter_voucher),false],
    ['Cash Tips',fmt(s.tip_cash),false],['Credit Tips',fmt(s.tip_credit),false],['Voucher Tips',fmt(s.tip_voucher),false],
    ['Grand Total',fmt(s.grand_total),false],['Total Expenses',fmt(s.expense_total||0),false],
    ['Owed Driver',fmt(s.owed_driver),true],['Earnings',fmt(s.driver_earnings!==undefined?s.driver_earnings:s.owed_driver),'net'],
  ];
  out.innerHTML=dayBlocks
    +'<div class="report-summary"><h3>Summary — '+modeLabel+'</h3><div class="summary-grid">'
    +summaryItems.map(([l,v,cls])=>
      '<div class="summary-item"><div class="summary-label">'+l+'</div>'
      +'<div class="summary-val'+(cls==='net'?' summary-net':cls?' summary-owed':'')+'">'
      +v+'</div></div>'
    ).join('')
    +'</div></div>';
}

function downloadReportCSV(){
  const from=document.getElementById('rptFrom').value;
  const to=document.getElementById('rptTo').value;
  const p=[];
  if(from)p.push('from_date='+from);
  if(to)p.push('to_date='+to);
  window.location.href='/api/report/csv'+(p.length?'?'+p.join('&'):'');
}

function downloadReportPDF(){
  const from=document.getElementById('rptFrom').value;
  const to=document.getElementById('rptTo').value;
  const p=[];
  if(from)p.push('from_date='+from);
  if(to)p.push('to_date='+to);
  window.location.href='/api/report-pdf'+(p.length?'?'+p.join('&'):'');
}

/* --- Full backup with Save As dialog --- */

/* --- Full restore with Open File dialog --- */
async function restoreFromZip(){
  const input=document.getElementById('restoreZip');
  if(!input.files.length){showToast('Select a ZIP file first');return;}
  const file=input.files[0];
  const form=new FormData();form.append('file',file);
  const r=await fetch('/api/restore/all',{method:'POST',body:form});
  if(r.ok){
    const d=await r.json();
    showToast('Restored '+d.restored.length+' files successfully');
    closeModal('backupModal');loadDailyLog();
  }else{
    const err=await r.json().catch(()=>({}));
    showToast(err.detail||'Restore failed');
  }
}

async function restoreFile(type){
  const inputId='restore'+type.charAt(0).toUpperCase()+type.slice(1);
  const input=document.getElementById(inputId);
  if(!input?.files?.length){showToast('Please select a JSON file first');return}
  if(!confirm('Restore '+type+'? This will overwrite current data.'))return;
  const form=new FormData();form.append('file',input.files[0]);
  const r=await fetch('/api/restore/'+type,{method:'POST',body:form});
  if(r.ok){
    showToast(type+' restored successfully');
    if(type==='pickups')loadDailyLog();
    if(type==='profile')window.location.reload();
  }else{
    const err=await r.json().catch(()=>({}));
    showToast(err.detail||'Restore failed');
  }
}
"""

# ── write assets to disk (always refresh) ───────────────────────
_ASSETS = {
    "templates/base.html":          BASE_HTML,
    "templates/index.html":         INDEX_HTML,
    "templates/setup.html":         SETUP_HTML,
    "templates/login.html":         LOGIN_HTML,
    "templates/register.html":      REGISTER_HTML,
    "templates/admin.html":         ADMIN_HTML,
    "templates/admin_register.html": ADMIN_REGISTER_HTML,
    "templates/admin_reset.html":   ADMIN_RESET_HTML,
    "templates/reset_password.html": RESET_PASSWORD_HTML,
    "static/css/style.css":         CSS,
    "static/js/app.js":             JS,
}
for _rel, _content in _ASSETS.items():
    _p = BASE_DIR / _rel
    _p.parent.mkdir(parents=True, exist_ok=True)
    _p.write_text(_content, encoding="utf-8")

# ════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════

_GCS_BUCKET       = os.environ.get("GCS_BUCKET")
_SECRET_KEY       = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
_ADMIN_SECRET     = os.environ.get("ADMIN_SECRET", "")
_GOOGLE_MAPS_KEY  = os.environ.get("GOOGLE_MAPS_KEY", "")
_ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
_signer       = URLSafeTimedSerializer(_SECRET_KEY)
_SESSION_MAX  = 86400 * 30   # 30-day sessions
_VIEW_MAX     = 3600 * 4     # 4-hour impersonation window
_RESET_MAX    = 3600         # 1-hour reset tokens
_reset_tokens: dict[str, str] = {}  # token → user_id

@dataclass
class AuthCtx:
    user_id: str
    role: str           # "driver" | "admin"
    effective_id: str   # own ID, or driver ID being viewed
    is_impersonating: bool
    viewed_name: str

def _hash_pw(password: str) -> str:
    return _bcrypt_lib.hashpw(password.encode(), _bcrypt_lib.gensalt()).decode()

def _check_pw(password: str, hashed: str) -> bool:
    return _bcrypt_lib.checkpw(password.encode(), hashed.encode())

def _gcs_client():
    from google.cloud import storage
    return storage.Client()

def _blob(name: str, driver_id: str = "") -> str:
    return f"{driver_id}/{name}" if driver_id else name

def _local(path: Path, driver_id: str = "") -> Path:
    if driver_id:
        p = path.parent / driver_id / path.name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return path

def _read(path: Path, driver_id: str = ""):
    if _GCS_BUCKET:
        try:
            blob = _gcs_client().bucket(_GCS_BUCKET).blob(_blob(path.name, driver_id))
            if not blob.exists(): return []
            return json.loads(blob.download_as_text())
        except Exception: return []
    p = _local(path, driver_id)
    if not p.exists(): return []
    with open(p) as f: return json.load(f)

def _write(path: Path, data, driver_id: str = ""):
    if _GCS_BUCKET:
        blob = _gcs_client().bucket(_GCS_BUCKET).blob(_blob(path.name, driver_id))
        blob.upload_from_string(json.dumps(data, indent=2, default=str),
                                content_type="application/json")
        return
    p = _local(path, driver_id)
    with open(p, "w") as f: json.dump(data, f, indent=2, default=str)

def _read_profile(driver_id: str = ""):
    if _GCS_BUCKET:
        try:
            blob = _gcs_client().bucket(_GCS_BUCKET).blob(_blob(PROFILE_F.name, driver_id))
            if not blob.exists(): return {}
            return json.loads(blob.download_as_text())
        except Exception: return {}
    p = _local(PROFILE_F, driver_id)
    if not p.exists(): return {}
    with open(p) as f: return json.load(f)

# ── users (no driver namespace — stored at root) ─────────────────

def _read_users() -> list:
    if _GCS_BUCKET:
        try:
            blob = _gcs_client().bucket(_GCS_BUCKET).blob("users.json")
            if not blob.exists(): return []
            return json.loads(blob.download_as_text())
        except Exception: return []
    p = DATA_DIR / "users.json"
    if not p.exists(): return []
    with open(p) as f: return json.load(f)

def _write_users(users: list):
    if _GCS_BUCKET:
        blob = _gcs_client().bucket(_GCS_BUCKET).blob("users.json")
        blob.upload_from_string(json.dumps(users, indent=2, default=str),
                                content_type="application/json")
        return
    p = DATA_DIR / "users.json"
    with open(p, "w") as f: json.dump(users, f, indent=2, default=str)

# ── session helpers ──────────────────────────────────────────────

def _get_auth_ctx(request: Request) -> Optional[AuthCtx]:
    token = request.cookies.get("txl_sess")
    if not token: return None
    try:
        payload = _signer.loads(token, max_age=_SESSION_MAX)
    except Exception:
        return None
    # backward-compat: old cookies stored plain driver_id string
    if isinstance(payload, str):
        return AuthCtx(user_id=payload, role="driver", effective_id=payload,
                       is_impersonating=False, viewed_name="")
    uid  = payload.get("uid", "")
    role = payload.get("role", "driver")
    if not uid: return None
    # check impersonation cookie (admin only)
    view_ctx = None
    if role == "admin":
        vtoken = request.cookies.get("txl_view")
        if vtoken:
            try: view_ctx = _signer.loads(vtoken, max_age=_VIEW_MAX)
            except Exception: view_ctx = None
    if view_ctx:
        return AuthCtx(user_id=uid, role=role,
                       effective_id=view_ctx.get("driver_id", uid),
                       is_impersonating=True,
                       viewed_name=view_ctx.get("driver_name", ""))
    return AuthCtx(user_id=uid, role=role, effective_id=uid,
                   is_impersonating=False, viewed_name="")

def _set_cookie(response: Response, user_id: str, role: str = "driver"):
    token = _signer.dumps({"uid": user_id, "role": role})
    response.set_cookie("txl_sess", token, max_age=_SESSION_MAX,
                        httponly=True, samesite="lax", secure=bool(_GCS_BUCKET))

def _set_view_cookie(response: Response, driver_id: str, driver_name: str):
    token = _signer.dumps({"driver_id": driver_id, "driver_name": driver_name})
    response.set_cookie("txl_view", token, max_age=_VIEW_MAX,
                        httponly=True, samesite="lax", secure=bool(_GCS_BUCKET))

def _clear_cookie(response: Response):
    response.delete_cookie("txl_sess")
    response.delete_cookie("txl_view")

def _ctx_tmpl(ctx: Optional[AuthCtx]) -> dict:
    if not ctx:
        return {"user_id": None, "role": None, "is_impersonating": False, "viewed_name": ""}
    return {"user_id": ctx.user_id, "role": ctx.role,
            "is_impersonating": ctx.is_impersonating, "viewed_name": ctx.viewed_name}

# ── data migration (flat → namespaced, first registration only) ──

def _migrate_flat_data(driver_id: str):
    names = ["pickups.json","customers.json","expenses.json","shifts.json","profile.json"]
    if _GCS_BUCKET:
        client  = _gcs_client()
        bucket  = client.bucket(_GCS_BUCKET)
        for name in names:
            old = bucket.blob(name)
            if old.exists():
                new_name = f"{driver_id}/{name}"
                if not bucket.blob(new_name).exists():
                    bucket.copy_blob(old, bucket, new_name)
                old.delete()
    else:
        for name in names:
            old = DATA_DIR / name
            new = DATA_DIR / driver_id / name
            (DATA_DIR / driver_id).mkdir(exist_ok=True)
            if old.exists() and not new.exists():
                old.rename(new)

def owed_driver_amount(t: dict, profile: dict) -> float:
    mode = (profile or {}).get("pay_mode", "standard")
    mc, mcr, mv = t["meter_cash"], t["meter_credit"], t["meter_voucher"]
    tc, tcr, tv = t["tip_cash"], t["tip_credit"], t["tip_voucher"]
    gt = t["grand_total"]
    if mode == "gate":
        if t.get("count", 0) == 0:
            return 0.0
        gate_fee = float((profile or {}).get("gate_fee") or 0)
        return round((mcr + mv) / 2 + tcr + tv - gate_fee, 2)
    elif mode == "commission":
        pct = float((profile or {}).get("company_pct") or 50) / 100
        all_meter = mc + mcr + mv
        all_tips  = tc + tcr + tv
        return round(all_meter * (1 - pct) + all_tips, 2)
    elif mode == "owner":
        return round(gt, 2)
    else:  # standard
        return round(((mcr + mv) - mc) / 2 + tcr + tv, 2)

def day_totals(recs, profile=None):
    t = {"meter_cash":0,"meter_credit":0,"meter_voucher":0,
         "tip_cash":0,"tip_credit":0,"tip_voucher":0,"grand_total":0,"count":0}
    for r in recs:
        pm  = (r.get("payment_method")     or "").lower()
        tpm = (r.get("tip_payment_method") or "").lower()
        m   = float(r.get("meter_total") or 0)
        tip = float(r.get("tip") or 0)
        if   pm  == "cash":    t["meter_cash"]    += m
        elif pm  == "credit":  t["meter_credit"]  += m
        elif pm  == "voucher": t["meter_voucher"]  += m
        if   tpm == "cash":    t["tip_cash"]       += tip
        elif tpm == "credit":  t["tip_credit"]     += tip
        elif tpm == "voucher": t["tip_voucher"]    += tip
        t["grand_total"] += float(r.get("calculated_total") or 0)
        t["count"] += 1
    result = {k: (round(v, 2) if k != "count" else v) for k, v in t.items()}
    result["owed_driver"] = owed_driver_amount(result, profile)
    return result

def calc_total(meter: float, tip: float) -> float:
    return round((meter or 0) + (tip or 0), 2)

def upsert_customer(name, address, city, phone, driver_id: str = ""):
    if not name: return
    customers = _read(CUSTOMERS_F, driver_id)
    match = None
    if phone: match = next((c for c in customers if c.get("phone") == phone), None)
    if not match: match = next((c for c in customers if c.get("name","").lower() == name.lower()), None)
    if match:
        if name:    match["name"]           = name
        if address: match["street_address"] = address
        if city:    match["city"]           = city
        if phone:   match["phone"]          = phone
    else:
        customers.append({"id": str(uuid.uuid4()), "name": name,
                          "street_address": address or "", "city": city or "", "phone": phone or ""})
    _write(CUSTOMERS_F, customers, driver_id)

# ════════════════════════════════════════════════════════════════
# APP
# ════════════════════════════════════════════════════════════════

TEMPLATES_DIR = (BASE_DIR / "templates").resolve()
STATIC_DIR    = (BASE_DIR / "static").resolve()

app = FastAPI(title="Taxi Pickup Daily Log")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

import inspect as _inspect

def _tmpl(name, request, ctx):
    params = list(_inspect.signature(templates.TemplateResponse).parameters)
    if params[0] == "self": params = params[1:]
    if params[0] == "request":
        return templates.TemplateResponse(request, name, ctx)
    return templates.TemplateResponse(name, {"request": request, **ctx})

# ── auth routes ──────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    ctx = _get_auth_ctx(request)
    if ctx: return RedirectResponse("/admin" if ctx.role == "admin" else "/", status_code=303)
    success = "Password reset successfully. Please sign in." if request.query_params.get("reset") == "1" else None
    return _tmpl("login.html", request, {"error": None, "success": success, "allow_register": True})

@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request,
                       username: str = Form(...),
                       password: str = Form(...)):
    users = _read_users()
    user  = next((u for u in users if u["username"].lower() == username.lower()), None)
    if not user or not _check_pw(password, user["password_hash"]):
        return _tmpl("login.html", request, {"error": "Invalid username or password.", "allow_register": True})
    if not user.get("active", True):
        return _tmpl("login.html", request, {"error": "This account has been deactivated.", "allow_register": True})
    role = user.get("role", "driver")
    dest = "/admin" if role == "admin" else "/"
    resp = RedirectResponse(dest, status_code=303)
    _set_cookie(resp, user["id"], role)
    return resp

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    ctx = _get_auth_ctx(request)
    if ctx: return RedirectResponse("/admin" if ctx.role == "admin" else "/", status_code=303)
    return _tmpl("register.html", request, {"error": None, "is_first": len(_read_users()) == 0})

@app.post("/register", response_class=HTMLResponse)
async def register_submit(request: Request,
                          username: str = Form(...),
                          password: str = Form(...),
                          confirm:  str = Form(...)):
    users = _read_users()
    if password != confirm:
        return _tmpl("register.html", request, {"error": "Passwords do not match.", "is_first": len(users) == 0})
    if len(password) < 6:
        return _tmpl("register.html", request, {"error": "Password must be at least 6 characters.", "is_first": len(users) == 0})
    if any(u["username"].lower() == username.lower() for u in users):
        return _tmpl("register.html", request, {"error": "Username already taken.", "is_first": len(users) == 0})
    is_first = len(users) == 0
    new_user = {"id": str(uuid.uuid4()), "username": username,
                "password_hash": _hash_pw(password), "role": "driver", "active": True,
                "created_at": datetime.utcnow().isoformat()}
    users.append(new_user)
    _write_users(users)
    if is_first:
        _migrate_flat_data(new_user["id"])
    resp = RedirectResponse("/setup" if is_first else "/", status_code=303)
    _set_cookie(resp, new_user["id"], "driver")
    return resp

@app.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    _clear_cookie(resp)
    return resp

@app.get("/admin/reset", response_class=HTMLResponse)
async def admin_reset_get(request: Request):
    users = [u for u in _read_users() if u.get("role") != "admin"]
    return _tmpl("admin_reset.html", request, {"error": None, "reset_url": None, "users": users})

@app.post("/admin/reset", response_class=HTMLResponse)
async def admin_reset_post(request: Request, username: str = Form(...)):
    all_users = _read_users()
    driver_list = [u for u in all_users if u.get("role") != "admin"]
    def err(msg):
        return _tmpl("admin_reset.html", request, {"error": msg, "reset_url": None, "users": driver_list})
    if not username.strip():
        return err("Username is required.")
    user = next((u for u in all_users if u["username"].lower() == username.lower()), None)
    if not user:
        return err(f"Username '{username}' not found.")
    token = _signer.dumps(user["id"], salt="password-reset")
    _reset_tokens[token] = user["id"]
    reset_url = str(request.base_url).rstrip("/") + f"/reset-password?token={token}"
    return _tmpl("admin_reset.html", request, {"error": None, "reset_url": reset_url, "users": driver_list})

@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_get(request: Request):
    token = request.query_params.get("token", "")
    def err(msg):
        return _tmpl("reset_password.html", request, {"error": msg, "token": "", "form_error": None})
    if not token:
        return err("No reset token provided.")
    if token not in _reset_tokens:
        return err("This link is invalid or has already been used.")
    try:
        _signer.loads(token, salt="password-reset", max_age=_RESET_MAX)
    except SignatureExpired:
        _reset_tokens.pop(token, None)
        return err("This link has expired (1-hour limit). Please generate a new one.")
    except BadSignature:
        return err("This link is invalid.")
    return _tmpl("reset_password.html", request, {"error": None, "token": token, "form_error": None})

@app.post("/reset-password", response_class=HTMLResponse)
async def reset_password_post(request: Request,
        token: str = Form(...), new_password: str = Form(...), new_password2: str = Form(...)):
    def link_err(msg):
        return _tmpl("reset_password.html", request, {"error": msg, "token": "", "form_error": None})
    def form_err(msg):
        return _tmpl("reset_password.html", request, {"error": None, "token": token, "form_error": msg})
    if token not in _reset_tokens:
        return link_err("This link is invalid or has already been used.")
    try:
        uid = _signer.loads(token, salt="password-reset", max_age=_RESET_MAX)
    except SignatureExpired:
        _reset_tokens.pop(token, None)
        return link_err("This link has expired. Please generate a new one.")
    except BadSignature:
        return link_err("This link is invalid.")
    users = _read_users()
    user = next((u for u in users if u["id"] == uid), None)
    if not user:
        _reset_tokens.pop(token, None)
        return link_err("User account not found.")
    if len(new_password) < 6:
        return form_err("Password must be at least 6 characters.")
    if new_password != new_password2:
        return form_err("Passwords do not match.")
    user["password_hash"] = _hash_pw(new_password)
    _write_users(users)
    for t in list(_reset_tokens.keys()):
        if _reset_tokens[t] == uid:
            del _reset_tokens[t]
    return RedirectResponse("/login?reset=1", status_code=303)

@app.post("/api/change-password")
async def change_password(request: Request):
    ctx = _get_auth_ctx(request)
    if not ctx: raise HTTPException(401, "Not authenticated")
    body = await request.json()
    current_pw = body.get("current_password", "")
    new_pw     = body.get("new_password", "")
    if len(new_pw) < 6:
        raise HTTPException(400, "New password must be at least 6 characters.")
    users = _read_users()
    user  = next((u for u in users if u["id"] == ctx.user_id), None)
    if not user or not _check_pw(current_pw, user["password_hash"]):
        raise HTTPException(400, "Current password is incorrect.")
    user["password_hash"] = _hash_pw(new_pw)
    _write_users(users)
    return {"ok": True}

# ── admin routes ─────────────────────────────────────────────────

@app.get("/admin/register", response_class=HTMLResponse)
async def admin_register_page(request: Request):
    if not _ADMIN_SECRET:
        raise HTTPException(404, "Not found")
    ctx = _get_auth_ctx(request)
    if ctx and ctx.role == "admin": return RedirectResponse("/admin", status_code=303)
    return _tmpl("admin_register.html", request, {"error": None})

@app.post("/admin/register", response_class=HTMLResponse)
async def admin_register_submit(request: Request,
                                username:     str = Form(...),
                                password:     str = Form(...),
                                confirm:      str = Form(...),
                                admin_secret: str = Form(...)):
    if not _ADMIN_SECRET:
        raise HTTPException(404, "Not found")
    if admin_secret != _ADMIN_SECRET:
        return _tmpl("admin_register.html", request, {"error": "Invalid admin secret key."})
    users = _read_users()
    if password != confirm:
        return _tmpl("admin_register.html", request, {"error": "Passwords do not match."})
    if len(password) < 6:
        return _tmpl("admin_register.html", request, {"error": "Password must be at least 6 characters."})
    if any(u["username"].lower() == username.lower() for u in users):
        return _tmpl("admin_register.html", request, {"error": "Username already taken."})
    new_user = {"id": str(uuid.uuid4()), "username": username,
                "password_hash": _hash_pw(password), "role": "admin", "active": True,
                "created_at": datetime.utcnow().isoformat()}
    users.append(new_user)
    _write_users(users)
    resp = RedirectResponse("/admin", status_code=303)
    _set_cookie(resp, new_user["id"], "admin")
    return resp

def _admin_dashboard_data(ctx: AuthCtx) -> dict:
    users = _read_users()
    active_drivers, inactive_drivers, admins = [], [], []
    for u in users:
        role   = u.get("role", "driver")
        active = u.get("active", True)
        profile = _read_profile(u["id"])
        entry = {**u, "profile_name": profile.get("driver_name", "") if profile else ""}
        if role == "admin":
            admins.append(entry)
        elif active:
            active_drivers.append(entry)
        else:
            inactive_drivers.append(entry)

    today_str = date.today().isoformat()
    today_rows = []
    fleet_today = {"count":0,"meter":0.0,"tips":0.0,"grand_total":0.0,
                   "owed_driver":0.0,"expense_total":0.0,"driver_earnings":0.0}
    for driver in active_drivers:
        profile_obj   = _read_profile(driver["id"])
        pickups_today = [p for p in _read(PICKUPS_F, driver["id"]) if p.get("pickup_date") == today_str]
        expenses_today= [e for e in _read(EXPENSES_F, driver["id"]) if e.get("date") == today_str]
        t = day_totals(pickups_today, profile_obj)
        exp_total  = round(sum(e["amount"] for e in expenses_today), 2)
        meter_tot  = round(t["meter_cash"] + t["meter_credit"] + t["meter_voucher"], 2)
        tip_tot    = round(t["tip_cash"]   + t["tip_credit"]   + t["tip_voucher"],   2)
        earnings   = round(t["owed_driver"] + t["meter_cash"] + t["tip_cash"] - exp_total, 2)
        today_rows.append({"driver_name": driver["profile_name"] or driver["username"],
                           "count": t["count"], "meter_total": meter_tot, "tip_total": tip_tot,
                           "grand_total": t["grand_total"], "owed_driver": t["owed_driver"],
                           "expense_total": exp_total, "driver_earnings": earnings})
        fleet_today["count"]          += t["count"]
        fleet_today["meter"]          += meter_tot
        fleet_today["tips"]           += tip_tot
        fleet_today["grand_total"]    += t["grand_total"]
        fleet_today["owed_driver"]    += t["owed_driver"]
        fleet_today["expense_total"]  += exp_total
        fleet_today["driver_earnings"]+= earnings
    fleet_today = {k: round(v, 2) if isinstance(v, float) else v for k, v in fleet_today.items()}

    return {
        "active_drivers": active_drivers,
        "inactive_drivers": inactive_drivers,
        "admins": admins,
        "current_user_id": ctx.user_id,
        "admin_secret_set": bool(_ADMIN_SECRET),
        "today_str": today_str,
        "today_rows": today_rows,
        "fleet_today": fleet_today,
        "msg": None, "msg_type": "ok",
    }

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    ctx = _require_admin(request)
    data = _admin_dashboard_data(ctx)
    reset_url  = request.query_params.get("reset_url", "")
    reset_for  = request.query_params.get("reset_for", "")
    if request.query_params.get("msg"):
        data["msg"]      = request.query_params.get("msg")
        data["msg_type"] = request.query_params.get("msg_type", "ok")
    return _tmpl("admin.html", request, {**data, **_ctx_tmpl(ctx),
                                         "reset_url": reset_url, "reset_for": reset_for})

@app.post("/admin/create-admin")
async def admin_create_admin(request: Request,
        username: str = Form(...), password: str = Form(...), confirm: str = Form(...)):
    ctx = _require_admin(request)
    def err(msg):
        return RedirectResponse(f"/admin?msg={quote(msg)}&msg_type=err", status_code=303)
    username = username.strip()
    if not username:
        return err("Username is required.")
    if len(password) < 6:
        return err("Password must be at least 6 characters.")
    if len(password) > 128:
        return err("Password must be 128 characters or fewer.")
    if password != confirm:
        return err("Passwords do not match.")
    users = _read_users()
    if any(u["username"].lower() == username.lower() for u in users):
        return err(f"Username '{username}' is already taken.")
    users.append({"id": str(uuid.uuid4()), "username": username,
                  "password_hash": _hash_pw(password), "role": "admin",
                  "active": True, "created_at": datetime.utcnow().isoformat()})
    try:
        _write_users(users)
    except Exception:
        return err("Failed to save user — please try again.")
    return RedirectResponse(f"/admin?msg={quote('Admin account created for ' + username)}&msg_type=ok", status_code=303)

@app.post("/admin/driver/{driver_id}/reset")
async def admin_driver_reset(driver_id: str, request: Request):
    ctx = _require_admin(request)
    users = _read_users()
    user = next((u for u in users if u["id"] == driver_id), None)
    if not user: raise HTTPException(404, "Driver not found")
    token = _signer.dumps(user["id"], salt="password-reset")
    _reset_tokens[token] = user["id"]
    reset_url = str(request.base_url).rstrip("/") + f"/reset-password?token={token}"
    return RedirectResponse(f"/admin?reset_url={quote(reset_url)}&reset_for={quote(user['username'])}", status_code=303)

@app.get("/admin/view/{driver_id}", response_class=HTMLResponse)
async def admin_view_driver(driver_id: str, request: Request):
    ctx = _require_admin(request)
    users = _read_users()
    user = next((u for u in users if u["id"] == driver_id and u.get("role","driver") == "driver"), None)
    if not user: raise HTTPException(404, "Driver not found")
    profile = _read_profile(driver_id)
    driver_name = profile.get("driver_name", user["username"]) if profile else user["username"]
    resp = RedirectResponse("/", status_code=303)
    _set_view_cookie(resp, driver_id, driver_name)
    return resp

@app.post("/admin/exit-view")
async def admin_exit_view(request: Request):
    ctx = _get_auth_ctx(request)
    if not ctx or ctx.role != "admin":
        return RedirectResponse("/login", status_code=303)
    resp = RedirectResponse("/admin", status_code=303)
    resp.delete_cookie("txl_view")
    return resp

@app.post("/admin/deactivate/{user_id}")
async def admin_deactivate(user_id: str, request: Request):
    ctx = _require_admin(request)
    if user_id == ctx.user_id:
        raise HTTPException(400, "Cannot deactivate your own account.")
    users = _read_users()
    user = next((u for u in users if u["id"] == user_id), None)
    if not user: raise HTTPException(404, "User not found")
    user["active"] = False
    _write_users(users)
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/reactivate/{user_id}")
async def admin_reactivate(user_id: str, request: Request):
    _require_admin(request)
    users = _read_users()
    user = next((u for u in users if u["id"] == user_id), None)
    if not user: raise HTTPException(404, "User not found")
    user["active"] = True
    _write_users(users)
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/delete/{user_id}")
async def admin_delete(user_id: str, request: Request):
    ctx = _require_admin(request)
    if user_id == ctx.user_id:
        raise HTTPException(400, "Cannot delete your own account.")
    users = _read_users()
    user = next((u for u in users if u["id"] == user_id), None)
    if not user: raise HTTPException(404, "User not found")
    if user.get("active", True):
        raise HTTPException(400, "Deactivate the account before deleting.")
    # delete their data namespace
    if _GCS_BUCKET:
        client = _gcs_client()
        bucket = client.bucket(_GCS_BUCKET)
        for blob in list(bucket.list_blobs(prefix=f"{user_id}/")):
            blob.delete()
    else:
        import shutil
        d = DATA_DIR / user_id
        if d.exists(): shutil.rmtree(d)
    users = [u for u in users if u["id"] != user_id]
    _write_users(users)
    return RedirectResponse("/admin", status_code=303)

# ── fleet report APIs ────────────────────────────────────────────

def _fleet_report_data(from_date: str, to_date: str) -> dict:
    users = _read_users()
    drivers = [u for u in users if u.get("role","driver") == "driver" and u.get("active", True)]
    result = []
    summary = {"count":0,"meter_total":0.0,"tip_total":0.0,"grand_total":0.0,
               "owed_driver":0.0,"expense_total":0.0,"driver_earnings":0.0}
    for u in drivers:
        profile_obj  = _read_profile(u["id"])
        pickups      = _read(PICKUPS_F, u["id"])
        expenses_all = _read(EXPENSES_F, u["id"])
        if from_date: pickups      = [p for p in pickups      if p.get("pickup_date","") >= from_date]
        if to_date:   pickups      = [p for p in pickups      if p.get("pickup_date","") <= to_date]
        if from_date: expenses_all = [e for e in expenses_all if e.get("date","")        >= from_date]
        if to_date:   expenses_all = [e for e in expenses_all if e.get("date","")        <= to_date]
        if not pickups and not expenses_all: continue
        t = day_totals(pickups, profile_obj)
        # Gate mode: fee applies once per day with pickups, so sum per-day values
        if (profile_obj or {}).get("pay_mode","standard") == "gate" and pickups:
            pmap = {}
            for p in pickups: pmap.setdefault(p.get("pickup_date",""), []).append(p)
            t["owed_driver"] = round(sum(day_totals(dp, profile_obj)["owed_driver"] for dp in pmap.values()), 2)
        exp_total  = round(sum(e["amount"] for e in expenses_all), 2)
        meter_tot  = round(t["meter_cash"] + t["meter_credit"] + t["meter_voucher"], 2)
        tip_tot    = round(t["tip_cash"]   + t["tip_credit"]   + t["tip_voucher"],   2)
        earnings   = round(t["owed_driver"] + t["meter_cash"] + t["tip_cash"] - exp_total, 2)
        days_worked= len(set(p.get("pickup_date","") for p in pickups))
        row = {"driver_id": u["id"],
               "driver_name": profile_obj.get("driver_name","") if profile_obj else u["username"],
               "days_worked": days_worked, "count": t["count"],
               "meter_total": meter_tot, "tip_total": tip_tot,
               "grand_total": round(t["grand_total"],2), "owed_driver": t["owed_driver"],
               "expense_total": exp_total, "driver_earnings": earnings}
        result.append(row)
        for k in ("count","grand_total","owed_driver","expense_total"):
            summary[k] += row[k]
        summary["meter_total"]    += meter_tot
        summary["tip_total"]      += tip_tot
        summary["driver_earnings"]+= earnings
    summary = {k: round(v,2) if isinstance(v,float) else v for k,v in summary.items()}
    summary["driver_count"] = len(result)
    return {"drivers": result, "summary": summary}

@app.get("/api/admin/fleet-report")
async def fleet_report_json(request: Request, from_date: str = "", to_date: str = ""):
    _require_admin(request)
    return _fleet_report_data(from_date, to_date)

@app.get("/api/admin/fleet-report-pdf")
async def fleet_report_pdf(request: Request, from_date: str = "", to_date: str = ""):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib import colors
    _require_admin(request)
    data   = _fleet_report_data(from_date, to_date)
    amber  = colors.HexColor("#D97706")
    dark   = colors.HexColor("#1C1917")
    green  = colors.HexColor("#10B981")
    red    = colors.HexColor("#EF4444")
    buf    = io.BytesIO()
    doc    = SimpleDocTemplate(buf, pagesize=letter,
                               leftMargin=0.75*inch, rightMargin=0.75*inch,
                               topMargin=0.75*inch,  bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    h1  = ParagraphStyle("h1", parent=styles["Heading1"], textColor=amber, fontSize=18, spaceAfter=4)
    body= styles["BodyText"]
    period = f"{from_date or 'all'} to {to_date or 'all'}"
    story  = [
        Paragraph("Taxi Log — Fleet Report", h1),
        Paragraph(f"Period: {period} &nbsp;|&nbsp; Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", body),
        HRFlowable(width="100%", color=amber, thickness=2, spaceAfter=10),
    ]
    col_w = [1.4*inch,0.55*inch,0.6*inch,0.85*inch,0.75*inch,0.85*inch,0.85*inch,0.85*inch,0.85*inch]
    hdr = [["Driver","Days","Trips","Meter","Tips","Gross","Expenses","Owed Driver","Earnings"]]
    rows = hdr + [[
        d["driver_name"], str(d["days_worked"]), str(d["count"]),
        f'${d["meter_total"]:.2f}', f'${d["tip_total"]:.2f}', f'${d["grand_total"]:.2f}',
        f'${d["expense_total"]:.2f}', f'${d["owed_driver"]:.2f}', f'${d["driver_earnings"]:.2f}'
    ] for d in data["drivers"]]
    s = data["summary"]
    rows.append(["Fleet Total", f'{s["driver_count"]} drivers', str(s["count"]),
                 f'${s["meter_total"]:.2f}', f'${s["tip_total"]:.2f}', f'${s["grand_total"]:.2f}',
                 f'${s["expense_total"]:.2f}', f'${s["owed_driver"]:.2f}', f'${s["driver_earnings"]:.2f}'])
    tbl = Table(rows, colWidths=col_w)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0), amber),
        ("TEXTCOLOR",(0,0),(-1,0), colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("BACKGROUND",(0,-1),(-1,-1), colors.HexColor("#FFFBEB")),
        ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,-1),(-2,-1), dark),
        ("TEXTCOLOR",(-1,-1),(-1,-1), green),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[colors.white, colors.HexColor("#FFFBEB")]),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#D1D5DB")),
        ("LINEABOVE",(0,-1),(-1,-1),1.5,amber),
    ]))
    story.append(tbl)
    doc.build(story); buf.seek(0)
    label = f"{from_date or 'all'}_to_{to_date or 'all'}"
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=fleet_report_{label}.pdf"})

@app.post("/api/admin/delete-all")
async def admin_delete_all(request: Request):
    ctx = _require_admin(request)
    users = _read_users()
    drivers = [u for u in users if u.get("role", "driver") != "admin"]
    admins  = [u for u in users if u.get("role", "driver") == "admin"]
    if _GCS_BUCKET:
        client = _gcs_client()
        bucket = client.bucket(_GCS_BUCKET)
        for u in drivers:
            for blob in list(bucket.list_blobs(prefix=f"{u['id']}/")):
                blob.delete()
    else:
        import shutil
        for u in drivers:
            d = DATA_DIR / u["id"]
            if d.exists(): shutil.rmtree(d)
    _write_users(admins)
    return {"ok": True, "deleted_drivers": len(drivers)}

@app.get("/api/admin/backup/all")
async def admin_backup_all(request: Request):
    _require_admin(request)
    import zipfile as zf_mod
    users = _read_users()
    buf = io.BytesIO()
    with zf_mod.ZipFile(buf, 'w', zf_mod.ZIP_DEFLATED) as zf:
        zf.writestr("users.json", json.dumps(users, indent=2, default=str))
        for u in users:
            did = u["id"]
            files = [
                (PICKUPS_F,   "pickups.json",   False),
                (CUSTOMERS_F, "customers.json", False),
                (EXPENSES_F,  "expenses.json",  False),
                (SHIFTS_F,    "shifts.json",    False),
                (PROFILE_F,   "profile.json",   True),
            ]
            for path, name, is_profile in files:
                data = _read_profile(did) if is_profile else _read(path, did)
                zf.writestr(f"{did}/{name}", json.dumps(data or ({} if is_profile else []), indent=2, default=str))
    buf.seek(0)
    fname = f"taxilog_fleet_backup_{date.today().isoformat()}.zip"
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={fname}"})

@app.post("/api/admin/restore/all")
async def admin_restore_all(request: Request, file: UploadFile = File(...)):
    _require_admin(request)
    import zipfile as zf_mod
    file_map = {
        "pickups.json":   (PICKUPS_F,   True),
        "customers.json": (CUSTOMERS_F, True),
        "expenses.json":  (EXPENSES_F,  True),
        "shifts.json":    (SHIFTS_F,    True),
        "profile.json":   (PROFILE_F,   False),
    }
    try:
        raw = await file.read()
        with zf_mod.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            restored = []
            if "users.json" in names:
                users = json.loads(zf.read("users.json").decode())
                if not isinstance(users, list):
                    raise HTTPException(400, "users.json: expected array")
                _write_users(users)
                restored.append("users.json")
            for entry in names:
                parts = entry.split("/")
                if len(parts) != 2: continue
                driver_id, fname = parts
                if fname not in file_map: continue
                path, expect_list = file_map[fname]
                parsed = json.loads(zf.read(entry).decode())
                if expect_list and not isinstance(parsed, list):
                    raise HTTPException(400, f"{entry}: expected array")
                if not expect_list and not isinstance(parsed, dict):
                    raise HTTPException(400, f"{entry}: expected object")
                _write(path, parsed, driver_id)
                restored.append(entry)
    except zf_mod.BadZipFile:
        raise HTTPException(400, "Invalid ZIP file")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON in backup file")
    return {"ok": True, "restored": restored}

# ── pages ────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    ctx = _get_auth_ctx(request)
    if not ctx: return RedirectResponse("/login", status_code=303)
    if ctx.role == "admin" and not ctx.is_impersonating:
        return RedirectResponse("/admin", status_code=303)
    profile = _read_profile(ctx.effective_id)
    if not profile: return RedirectResponse("/setup", status_code=303)
    return _tmpl("index.html", request, {"profile": profile, "today": date.today().isoformat(),
                                         "google_maps_key": _GOOGLE_MAPS_KEY,
                                         "ask_enabled": bool(_ANTHROPIC_KEY),
                                         **_ctx_tmpl(ctx)})

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    ctx = _get_auth_ctx(request)
    if not ctx: return RedirectResponse("/login", status_code=303)
    return _tmpl("setup.html", request, {"profile": _read_profile(ctx.effective_id), **_ctx_tmpl(ctx)})

@app.post("/setup")
async def save_profile(request: Request,
                       driver_name:  str = Form(...),
                       vehicle:      str = Form(""),
                       phone:        str = Form(""),
                       pay_mode:     str = Form("standard"),
                       gate_fee:     str = Form(""),
                       company_pct:  str = Form("")):
    ctx = _get_auth_ctx(request)
    if not ctx: return RedirectResponse("/login", status_code=303)
    if ctx.is_impersonating: return RedirectResponse("/", status_code=303)
    driver_id = ctx.effective_id
    _write(PROFILE_F, {
        "driver_name": driver_name,
        "vehicle":     vehicle,
        "phone":       phone,
        "pay_mode":    pay_mode,
        "gate_fee":    float(gate_fee)    if gate_fee    else None,
        "company_pct": float(company_pct) if company_pct else None,
    }, driver_id)
    return RedirectResponse("/", status_code=303)

# ── pickups ──────────────────────────────────────────────────────

def _auth(request: Request) -> str:
    ctx = _get_auth_ctx(request)
    if not ctx: raise HTTPException(401, "Not authenticated")
    return ctx.effective_id

def _auth_write(request: Request) -> str:
    ctx = _get_auth_ctx(request)
    if not ctx: raise HTTPException(401, "Not authenticated")
    if ctx.is_impersonating: raise HTTPException(403, "Read-only — viewing another driver's account.")
    return ctx.effective_id

def _require_admin(request: Request) -> AuthCtx:
    ctx = _get_auth_ctx(request)
    if not ctx: raise HTTPException(401, "Not authenticated")
    if ctx.role != "admin": raise HTTPException(403, "Admin access required")
    return ctx

@app.get("/api/pickups")
async def get_pickups(request: Request, date: Optional[str] = None):
    did = _auth(request)
    pickups = _read(PICKUPS_F, did)
    if date: pickups = [p for p in pickups if p.get("pickup_date") == date]
    return sorted(pickups, key=lambda p: p.get("pickup_time",""))

@app.post("/api/pickups")
async def create_pickup(request: Request):
    did = _auth_write(request)
    body = await request.json()
    m, t = float(body.get("meter_total") or 0), float(body.get("tip") or 0)
    record = {
        "id": str(uuid.uuid4()),
        "pickup_date": body.get("pickup_date",""),
        "pickup_time": body.get("pickup_time",""),
        "street_address": body.get("street_address",""),
        "city": body.get("city",""),
        "customer_name": body.get("customer_name",""),
        "phone_number": body.get("phone_number",""),
        "destination_address": body.get("destination_address",""),
        "meter_total": m, "payment_method": body.get("payment_method",""),
        "tip": t, "tip_payment_method": body.get("tip_payment_method",""),
        "calculated_total": calc_total(m, t),
        "created_at": datetime.utcnow().isoformat(),
    }
    pickups = _read(PICKUPS_F, did); pickups.append(record); _write(PICKUPS_F, pickups, did)
    upsert_customer(record["customer_name"], record["street_address"], record["city"], record["phone_number"], did)
    return record

@app.get("/api/pickups/{pid}")
async def get_pickup(pid: str, request: Request):
    did = _auth(request)
    rec = next((p for p in _read(PICKUPS_F, did) if p["id"] == pid), None)
    if not rec: raise HTTPException(404, "Not found")
    return rec

@app.put("/api/pickups/{pid}")
async def update_pickup(pid: str, request: Request):
    did = _auth_write(request)
    body = await request.json(); pickups = _read(PICKUPS_F, did)
    idx = next((i for i,p in enumerate(pickups) if p["id"] == pid), None)
    if idx is None: raise HTTPException(404, "Not found")
    rec = pickups[idx]
    for k in ["pickup_date","pickup_time","street_address","city","customer_name",
              "phone_number","destination_address","meter_total","payment_method","tip","tip_payment_method"]:
        if k in body: rec[k] = body[k]
    rec["meter_total"]       = float(rec.get("meter_total") or 0)
    rec["tip"]               = float(rec.get("tip") or 0)
    rec["calculated_total"]  = calc_total(rec["meter_total"], rec["tip"])
    pickups[idx] = rec; _write(PICKUPS_F, pickups, did)
    upsert_customer(rec["customer_name"], rec["street_address"], rec["city"], rec["phone_number"], did)
    return rec

@app.delete("/api/pickups/{pid}")
async def delete_pickup(pid: str, request: Request):
    did = _auth_write(request)
    pickups = _read(PICKUPS_F, did)
    if not any(p["id"] == pid for p in pickups): raise HTTPException(404, "Not found")
    _write(PICKUPS_F, [p for p in pickups if p["id"] != pid], did); return {"ok": True}

@app.delete("/api/pickups")
async def delete_all(request: Request):
    did = _auth_write(request)
    _write(PICKUPS_F, [], did); _write(CUSTOMERS_F, [], did); return {"ok": True}

# ── expenses ─────────────────────────────────────────────────────

@app.get("/api/expenses")
async def get_expenses(request: Request, date: Optional[str] = None):
    did = _auth(request)
    expenses = _read(EXPENSES_F, did)
    if date: expenses = [e for e in expenses if e.get("date") == date]
    return sorted(expenses, key=lambda e: e.get("date",""))

@app.post("/api/expenses")
async def create_expense(request: Request):
    did = _auth_write(request)
    body = await request.json()
    record = {
        "id": str(uuid.uuid4()),
        "date": body.get("date",""),
        "category": body.get("category",""),
        "amount": float(body.get("amount") or 0),
        "notes": body.get("notes",""),
        "created_at": datetime.utcnow().isoformat(),
    }
    expenses = _read(EXPENSES_F, did); expenses.append(record); _write(EXPENSES_F, expenses, did)
    return record

@app.delete("/api/expenses/{eid}")
async def delete_expense(eid: str, request: Request):
    did = _auth_write(request)
    expenses = _read(EXPENSES_F, did)
    if not any(e["id"] == eid for e in expenses): raise HTTPException(404, "Not found")
    _write(EXPENSES_F, [e for e in expenses if e["id"] != eid], did); return {"ok": True}

# ── shifts ───────────────────────────────────────────────────────

@app.get("/api/shifts")
async def get_shifts(request: Request, date: Optional[str] = None):
    did = _auth(request)
    shifts = _read(SHIFTS_F, did)
    if date: shifts = [s for s in shifts if s.get("date") == date]
    return shifts

@app.post("/api/shifts")
async def save_shift(request: Request):
    did    = _auth_write(request)
    body   = await request.json()
    shifts = _read(SHIFTS_F, did)
    d      = body.get("date","")
    existing = next((s for s in shifts if s.get("date") == d), None)
    odo_start = float(body.get("odometer_start") or 0)
    odo_end   = float(body.get("odometer_end")   or 0)
    miles     = round(max(odo_end - odo_start, 0), 1)
    if existing:
        existing.update({
            "start_time":    body.get("start_time",""),
            "end_time":      body.get("end_time",""),
            "odometer_start": odo_start,
            "odometer_end":   odo_end,
            "miles":          miles,
            "notes":          body.get("notes",""),
        })
        _write(SHIFTS_F, shifts, did)
        return existing
    record = {
        "id": str(uuid.uuid4()), "date": d,
        "start_time":    body.get("start_time",""),
        "end_time":      body.get("end_time",""),
        "odometer_start": odo_start, "odometer_end": odo_end, "miles": miles,
        "notes":          body.get("notes",""),
        "created_at":     datetime.utcnow().isoformat(),
    }
    shifts.append(record); _write(SHIFTS_F, shifts, did)
    return record

# ── daily totals (server-side, payment-mode aware) ───────────────

@app.get("/api/daily-totals")
async def daily_totals_api(request: Request, date: Optional[str] = None):
    did      = _auth(request)
    profile  = _read_profile(did)
    pickups  = _read(PICKUPS_F, did)
    expenses = _read(EXPENSES_F, did)
    if date:
        pickups  = [p for p in pickups  if p.get("pickup_date") == date]
        expenses = [e for e in expenses if e.get("date")        == date]
    totals = day_totals(pickups, profile)
    exp_total = round(sum(e["amount"] for e in expenses), 2)
    totals["expense_total"]    = exp_total
    totals["net_earnings"]     = round(totals["owed_driver"] - exp_total, 2)
    totals["driver_earnings"]  = round(totals["owed_driver"] + totals["meter_cash"] + totals["tip_cash"] - exp_total, 2)
    totals["pay_mode"]         = profile.get("pay_mode", "standard")
    return totals

# ── report ───────────────────────────────────────────────────────

@app.get("/api/report")
async def report(request: Request, from_date: str = "", to_date: str = ""):
    did          = _auth(request)
    profile      = _read_profile(did)
    pickups      = _read(PICKUPS_F, did)
    expenses_all = _read(EXPENSES_F, did)
    shifts_all   = _read(SHIFTS_F, did)

    if from_date:
        pickups      = [p for p in pickups      if p.get("pickup_date","") >= from_date]
        expenses_all = [e for e in expenses_all if e.get("date","")        >= from_date]
    if to_date:
        pickups      = [p for p in pickups      if p.get("pickup_date","") <= to_date]
        expenses_all = [e for e in expenses_all if e.get("date","")        <= to_date]

    all_dates = set(p.get("pickup_date","") for p in pickups) | set(e.get("date","") for e in expenses_all)
    pickup_map  = {}
    for p in pickups: pickup_map.setdefault(p.get("pickup_date",""), []).append(p)
    expense_map = {}
    for e in expenses_all: expense_map.setdefault(e.get("date",""), []).append(e)
    shift_map = {s["date"]: s for s in shifts_all}

    days = []
    for d in sorted(all_dates):
        day_p  = sorted(pickup_map.get(d, []),  key=lambda x: x.get("pickup_time",""))
        day_e  = expense_map.get(d, [])
        totals = day_totals(day_p, profile)
        exp_total = round(sum(e["amount"] for e in day_e), 2)
        totals["expense_total"]   = exp_total
        totals["net_earnings"]    = round(totals["owed_driver"] - exp_total, 2)
        totals["driver_earnings"] = round(totals["owed_driver"] + totals["meter_cash"] + totals["tip_cash"] - exp_total, 2)
        days.append({"date": d, "pickups": day_p, "expenses": day_e,
                     "shift": shift_map.get(d), "totals": totals})

    summary = day_totals(pickups, profile)
    # Gate mode: fee applies once per day with pickups, so sum per-day values
    if profile.get("pay_mode", "standard") == "gate":
        summary["owed_driver"] = round(sum(d["totals"]["owed_driver"] for d in days), 2)
    total_exp = round(sum(e["amount"] for e in expenses_all), 2)
    summary["expense_total"]   = total_exp
    summary["net_earnings"]    = round(summary["owed_driver"] - total_exp, 2)
    summary["driver_earnings"] = round(summary["owed_driver"] + summary["meter_cash"] + summary["tip_cash"] - total_exp, 2)
    summary["pay_mode"]      = profile.get("pay_mode", "standard")
    return {"days": days, "summary": summary}

# ── Ask (AI analysis) ────────────────────────────────────────────

@app.post("/api/ask")
async def ask(request: Request):
    if not _ANTHROPIC_KEY:
        raise HTTPException(status_code=503, detail="AI analysis not configured.")
    did     = _auth(request)
    body    = await request.json()
    question   = str(body.get("question", "")).strip()
    from_date  = str(body.get("from_date", ""))
    to_date    = str(body.get("to_date", ""))
    if not question:
        raise HTTPException(status_code=400, detail="No question provided.")

    profile      = _read_profile(did) or {}
    pickups      = _read(PICKUPS_F, did)
    expenses_all = _read(EXPENSES_F, did)
    shifts_all   = _read(SHIFTS_F, did)

    if from_date:
        pickups      = [p for p in pickups      if p.get("pickup_date","") >= from_date]
        expenses_all = [e for e in expenses_all if e.get("date","")        >= from_date]
        shifts_all   = [s for s in shifts_all   if s.get("date","")        >= from_date]
    if to_date:
        pickups      = [p for p in pickups      if p.get("pickup_date","") <= to_date]
        expenses_all = [e for e in expenses_all if e.get("date","")        <= to_date]
        shifts_all   = [s for s in shifts_all   if s.get("date","")        <= to_date]

    date_range = f"{from_date or 'all time'} to {to_date or 'all time'}"
    system = f"""You are a data analyst for a taxi driver. Answer the driver's question using only the data provided. Calculate all totals, averages, and counts directly from the raw records.
Driver profile: {json.dumps(profile)}
Date range: {date_range}
Pickup records ({len(pickups)}): {json.dumps(pickups)}
Expense records ({len(expenses_all)}): {json.dumps(expenses_all)}
Shift records ({len(shifts_all)}): {json.dumps(shifts_all)}
Be concise and precise. If the data is insufficient to answer, say so."""

    try:
        import anthropic as _anthropic
        client = _anthropic.Anthropic(api_key=_ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": question}],
            system=system,
        )
        return {"answer": msg.content[0].text}
    except Exception as e:
        return {"error": str(e)}

# ── CSV export ───────────────────────────────────────────────────

@app.get("/api/report/csv")
async def report_csv(request: Request, from_date: str = "", to_date: str = ""):
    did = _auth(request)
    pickups = _read(PICKUPS_F, did)
    if from_date: pickups = [p for p in pickups if p.get("pickup_date","") >= from_date]
    if to_date:   pickups = [p for p in pickups if p.get("pickup_date","") <= to_date]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date","Time","Street Address","City","Customer","Phone",
                "Destination","Meter","Payment","Tip","Tip Payment","Total"])
    for p in sorted(pickups, key=lambda x: (x.get("pickup_date",""), x.get("pickup_time",""))):
        w.writerow([p.get("pickup_date",""), p.get("pickup_time",""),
                    p.get("street_address",""), p.get("city",""),
                    p.get("customer_name",""), p.get("phone_number",""),
                    p.get("destination_address",""), p.get("meter_total",0),
                    p.get("payment_method",""), p.get("tip",0),
                    p.get("tip_payment_method",""), p.get("calculated_total",0)])
    fname = f"taxilog_{from_date or 'all'}_to_{to_date or 'all'}.csv"
    return StreamingResponse(io.BytesIO(buf.getvalue().encode()),
                             media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={fname}"})

# ── PDF report ───────────────────────────────────────────────────

@app.get("/api/report-pdf")
async def report_pdf(request: Request, from_date: str = "", to_date: str = ""):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib import colors

    did      = _auth(request)
    profile  = _read_profile(did)
    driver   = profile.get("driver_name", "Unknown Driver")
    pay_mode = profile.get("pay_mode", "standard")
    mode_labels = {"standard":"Standard Split","gate":"Flat Gate Fee",
                   "commission":"Commission Split","owner":"Owner-Operator"}

    pickups      = _read(PICKUPS_F, did)
    expenses_all = _read(EXPENSES_F, did)
    if from_date:
        pickups      = [p for p in pickups      if p.get("pickup_date","") >= from_date]
        expenses_all = [e for e in expenses_all if e.get("date","")        >= from_date]
    if to_date:
        pickups      = [p for p in pickups      if p.get("pickup_date","") <= to_date]
        expenses_all = [e for e in expenses_all if e.get("date","")        <= to_date]

    pickup_map  = {}
    for p in pickups: pickup_map.setdefault(p.get("pickup_date",""), []).append(p)
    expense_map = {}
    for e in expenses_all: expense_map.setdefault(e.get("date",""), []).append(e)
    all_dates = sorted(set(pickup_map) | set(expense_map))

    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=letter,
                             leftMargin=0.75*inch, rightMargin=0.75*inch,
                             topMargin=0.75*inch,  bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    amber  = colors.HexColor("#D97706")
    dark   = colors.HexColor("#1C1917")
    red    = colors.HexColor("#EF4444")
    green  = colors.HexColor("#10B981")
    h1  = ParagraphStyle("h1",  parent=styles["Heading1"], textColor=amber, fontSize=18, spaceAfter=2)
    h2  = ParagraphStyle("h2",  parent=styles["Heading2"], textColor=dark,  fontSize=12, spaceBefore=10, spaceAfter=4)
    h3  = ParagraphStyle("h3",  parent=styles["Heading3"], textColor=dark,  fontSize=10, spaceBefore=6,  spaceAfter=2)
    body= styles["BodyText"]

    date_range = f"{from_date or 'all'} to {to_date or 'all'}"
    story = [
        Paragraph("Taxi Pickup Daily Log — Earnings Report", h1),
        Paragraph(f"Driver: {driver} &nbsp;|&nbsp; Payment Mode: {mode_labels.get(pay_mode,'Standard')} &nbsp;|&nbsp; Period: {date_range}", body),
        Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", body),
        HRFlowable(width="100%", color=amber, thickness=2, spaceAfter=8),
    ]

    col_w = [0.7*inch, 1.3*inch, 1.3*inch, 0.9*inch, 0.7*inch, 0.7*inch, 0.7*inch, 0.7*inch]
    hdr_style = [
        ("BACKGROUND", (0,0), (-1,0), amber),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 7),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FFFBEB")]),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D1D5DB")),
    ]

    grand_totals = {"meter":0,"tip_cash":0,"tip_credit":0,"tip_voucher":0,"gross":0,"expenses":0,"owed":0,"net":0,"earnings":0,"count":0}

    for d in all_dates:
        day_p = sorted(pickup_map.get(d, []), key=lambda x: x.get("pickup_time",""))
        day_e = expense_map.get(d, [])
        totals= day_totals(day_p, profile)
        exp_total = round(sum(e["amount"] for e in day_e), 2)
        net      = round(totals["owed_driver"] - exp_total, 2)
        earnings = round(totals["owed_driver"] + totals["meter_cash"] + totals["tip_cash"] - exp_total, 2)

        story.append(Paragraph(f"{d}  —  {totals['count']} pickups  |  Gross: ${totals['grand_total']:.2f}  |  Owed: ${totals['owed_driver']:.2f}  |  Earnings: ${earnings:.2f}", h2))

        rows = [["Time","From","To","Customer","Meter","Pay","Tip","Total"]]
        for p in day_p:
            rows.append([
                p.get("pickup_time",""),
                (p.get("street_address","")[:18]+"…" if len(p.get("street_address",""))>18 else p.get("street_address","")),
                (p.get("destination_address","")[:18]+"…" if len(p.get("destination_address",""))>18 else p.get("destination_address","")),
                (p.get("customer_name","") or "—")[:14],
                f"${p.get('meter_total',0):.2f}", p.get("payment_method","—"),
                f"${p.get('tip',0):.2f}", f"${p.get('calculated_total',0):.2f}",
            ])
        tbl = Table(rows, colWidths=col_w)
        tbl.setStyle(TableStyle(hdr_style))
        story.append(tbl)

        if day_e:
            story.append(Paragraph("Expenses", h3))
            exp_rows = [["Category","Notes","Amount"]]
            for e in day_e:
                exp_rows.append([e.get("category",""), e.get("notes",""), f"${e['amount']:.2f}"])
            exp_rows.append(["","Total",f"${exp_total:.2f}"])
            et = Table(exp_rows, colWidths=[1.5*inch, 3.5*inch, 1.0*inch])
            et.setStyle(TableStyle([
                ("BACKGROUND",(0,0),(-1,0), red),
                ("TEXTCOLOR",(0,0),(-1,0), colors.white),
                ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
                ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
                ("FONTSIZE",(0,0),(-1,-1),7),
                ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
                ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#FECACA")),
            ]))
            story.append(et)

        story.append(Spacer(1, 6))
        grand_totals["meter"]      += totals["meter_cash"]+totals["meter_credit"]+totals["meter_voucher"]
        grand_totals["tip_cash"]   += totals["tip_cash"]
        grand_totals["tip_credit"] += totals["tip_credit"]
        grand_totals["tip_voucher"]+= totals["tip_voucher"]
        grand_totals["gross"]    += totals["grand_total"]
        grand_totals["expenses"] += exp_total
        grand_totals["owed"]     += totals["owed_driver"]
        grand_totals["net"]      += net
        grand_totals["earnings"] += earnings
        grand_totals["count"]    += totals["count"]

    story.append(HRFlowable(width="100%", color=amber, thickness=2, spaceAfter=6))
    story.append(Paragraph("Summary", h2))
    sum_data = [
        ["Total Pickups",    str(grand_totals["count"])],
        ["Total Meter",      f"${grand_totals['meter']:.2f}"],
        ["Cash Tips",        f"${grand_totals['tip_cash']:.2f}"],
        ["Credit Tips",      f"${grand_totals['tip_credit']:.2f}"],
        ["Voucher Tips",     f"${grand_totals['tip_voucher']:.2f}"],
        ["Gross Revenue",    f"${grand_totals['gross']:.2f}"],
        ["Total Expenses",   f"${grand_totals['expenses']:.2f}"],
        ["Total Owed Driver",f"${grand_totals['owed']:.2f}"],
        ["Earnings",         f"${grand_totals['earnings']:.2f}"],
    ]
    st = Table(sum_data, colWidths=[2*inch, 1.5*inch])
    st.setStyle(TableStyle([
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("ROWBACKGROUNDS",(0,0),(-1,-1),[colors.white, colors.HexColor("#FFFBEB")]),
        ("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#D1D5DB")),
        ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,-1),(-1,-1),green),
    ]))
    story.append(st)

    doc.build(story); buf.seek(0)
    label = f"{from_date or 'all'}_to_{to_date or 'all'}"
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=earnings_report_{label}.pdf"})

# ── customers ────────────────────────────────────────────────────

@app.get("/api/customers/suggest")
async def suggest(request: Request, q: str = ""):
    did = _auth(request)
    if not q or len(q) < 2: return []
    q_low = q.lower(); customers = _read(CUSTOMERS_F, did)
    return [c for c in customers if q_low in c.get("name","").lower()
            or q_low in c.get("street_address","").lower()
            or q_low in c.get("phone","").lower()][:10]

@app.get("/api/customers/lookup")
async def lookup(request: Request, phone: str = "", address: str = ""):
    did = _auth(request)
    customers = _read(CUSTOMERS_F, did)
    if phone:
        c = next((x for x in customers if x.get("phone") == phone), None)
        if c: return c
    if address:
        c = next((x for x in customers if x.get("street_address","").lower() == address.lower()), None)
        if c: return c
    return {}

# ── backup / restore ─────────────────────────────────────────────

def _json_download(data, filename: str):
    content = json.dumps(data, indent=2, default=str).encode()
    return StreamingResponse(io.BytesIO(content), media_type="application/json",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})

@app.get("/api/backup/pickups")
async def backup_pickups(request: Request):
    did = _auth(request)
    return _json_download(_read(PICKUPS_F, did), f"pickups_{date.today().isoformat()}.json")

@app.get("/api/backup/customers")
async def backup_customers(request: Request):
    did = _auth(request)
    return _json_download(_read(CUSTOMERS_F, did), f"customers_{date.today().isoformat()}.json")

@app.get("/api/backup/expenses")
async def backup_expenses(request: Request):
    did = _auth(request)
    return _json_download(_read(EXPENSES_F, did), f"expenses_{date.today().isoformat()}.json")

@app.get("/api/backup/shifts")
async def backup_shifts(request: Request):
    did = _auth(request)
    return _json_download(_read(SHIFTS_F, did), f"shifts_{date.today().isoformat()}.json")

@app.get("/api/backup/profile")
async def backup_profile(request: Request):
    did = _auth(request)
    return _json_download(_read_profile(did), f"profile_{date.today().isoformat()}.json")

@app.get("/api/backup/all")
async def backup_all(request: Request):
    did = _auth(request)
    import zipfile as zf_mod
    files = [
        (PICKUPS_F,   "pickups.json",   []),
        (CUSTOMERS_F, "customers.json", []),
        (EXPENSES_F,  "expenses.json",  []),
        (SHIFTS_F,    "shifts.json",    []),
        (PROFILE_F,   "profile.json",   {}),
    ]
    buf = io.BytesIO()
    with zf_mod.ZipFile(buf, 'w', zf_mod.ZIP_DEFLATED) as zf:
        for path, name, default in files:
            if path == PROFILE_F:
                data = _read_profile(did) or default
            else:
                data = _read(path, did) or default
            zf.writestr(name, json.dumps(data, indent=2, default=str))
    buf.seek(0)
    fname = f"taxilog_backup_{date.today().isoformat()}.zip"
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={fname}"})

async def _restore(file: UploadFile, path: Path, expect_list: bool, driver_id: str):
    try: data = json.loads(await file.read())
    except Exception: raise HTTPException(400, "Invalid JSON file")
    if expect_list and not isinstance(data, list): raise HTTPException(400, "Expected a JSON array")
    if not expect_list and not isinstance(data, dict): raise HTTPException(400, "Expected a JSON object")
    _write(path, data, driver_id); return {"ok": True}

@app.post("/api/restore/pickups")
async def restore_pickups(request: Request, file: UploadFile = File(...)):
    return await _restore(file, PICKUPS_F, True, _auth_write(request))

@app.post("/api/restore/customers")
async def restore_customers(request: Request, file: UploadFile = File(...)):
    return await _restore(file, CUSTOMERS_F, True, _auth_write(request))

@app.post("/api/restore/expenses")
async def restore_expenses(request: Request, file: UploadFile = File(...)):
    return await _restore(file, EXPENSES_F, True, _auth_write(request))

@app.post("/api/restore/shifts")
async def restore_shifts(request: Request, file: UploadFile = File(...)):
    return await _restore(file, SHIFTS_F, True, _auth_write(request))

@app.post("/api/restore/profile")
async def restore_profile(request: Request, file: UploadFile = File(...)):
    return await _restore(file, PROFILE_F, False, _auth_write(request))

@app.post("/api/restore/all")
async def restore_all(request: Request, file: UploadFile = File(...)):
    did = _auth_write(request)
    import zipfile as zf_mod
    try:
        data = await file.read()
        with zf_mod.ZipFile(io.BytesIO(data)) as zf:
            mapping = {
                "pickups.json":   (PICKUPS_F,   True),
                "customers.json": (CUSTOMERS_F, True),
                "expenses.json":  (EXPENSES_F,  True),
                "shifts.json":    (SHIFTS_F,    True),
                "profile.json":   (PROFILE_F,   False),
            }
            restored = []
            for name, (path, expect_list) in mapping.items():
                if name in zf.namelist():
                    parsed = json.loads(zf.read(name).decode())
                    if expect_list and not isinstance(parsed, list):
                        raise HTTPException(400, f"{name}: expected JSON array")
                    if not expect_list and not isinstance(parsed, dict):
                        raise HTTPException(400, f"{name}: expected JSON object")
                    _write(path, parsed, did)
                    restored.append(name)
    except zf_mod.BadZipFile:
        raise HTTPException(400, "Invalid ZIP file")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON in backup file")
    return {"ok": True, "restored": restored}

# ── requirements PDF (unchanged) ─────────────────────────────────

@app.get("/api/requirements-pdf")
async def requirements_pdf(request: Request):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib import colors
    did = _auth(request)
    profile = _read_profile(did); driver = profile.get("driver_name", "Unknown Driver")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch)
    styles = getSampleStyleSheet(); amber = colors.HexColor("#D97706"); dark = colors.HexColor("#1C1917")
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=amber, fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=dark,  fontSize=13, spaceBefore=12, spaceAfter=4)
    body = styles["BodyText"]
    story = [Paragraph("Taxi Pickup Daily Log", h1), Paragraph("Application Requirements Document", body),
             Paragraph(f"Driver: {driver} &nbsp;&nbsp; Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", body),
             HRFlowable(width="100%", color=amber, thickness=2, spaceAfter=12),
             Paragraph("1. Application Overview", h2),
             Paragraph("Web-based application for taxi drivers to record and manage passenger pickups. Data stored in JSON files.", body),
             Spacer(1,6), Paragraph("2. Technical Stack", h2)]
    td = [["Component","Technology","Notes"],["Backend","FastAPI","Async Python"],["Templating","Jinja2","Server-side HTML"],
          ["Frontend","Vanilla JS","No framework"],["Styling","Custom CSS","Amber theme"],
          ["Storage","JSON files","pickups/customers/profile/expenses/shifts"],["PDF","ReportLab","Server-side"],["Server","Uvicorn","ASGI"]]
    tbl = Table(td, colWidths=[1.5*inch, 1.5*inch, 3.5*inch])
    tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),amber),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#FEF3C7")]),
        ("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#D1D5DB")),("FONTSIZE",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story += [tbl, Spacer(1,6), Paragraph("3. Payment Modes", h2),
              Paragraph("<b>Standard:</b> ((Credit + Voucher) − Cash) / 2 + Credit Tips + Voucher Tips", body),
              Paragraph("<b>Gate:</b> Grand Total − Daily Gate Fee", body),
              Paragraph("<b>Commission:</b> Meter Total × Driver% + All Tips", body),
              Paragraph("<b>Owner-Operator:</b> Grand Total (keep everything)", body)]
    doc.build(story); buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=requirements_{date.today().isoformat()}.pdf"})

# ── admin design document PDF ────────────────────────────────────

@app.get("/api/admin/design-pdf")
async def admin_design_pdf(request: Request):
    _require_admin(request)
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak
    from reportlab.lib import colors

    W = 6.5 * inch  # usable width

    maize  = colors.HexColor("#FFCB05")
    blue   = colors.HexColor("#00274C")
    blue2  = colors.HexColor("#003366")
    ltblue = colors.HexColor("#EEF1F6")
    gray   = colors.HexColor("#6B6660")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=0.85*inch, rightMargin=0.85*inch,
                            topMargin=0.85*inch, bottomMargin=0.85*inch)
    styles = getSampleStyleSheet()

    h1     = ParagraphStyle("h1",     parent=styles["Heading1"], textColor=blue,  fontSize=20, spaceAfter=2, leading=24)
    h2     = ParagraphStyle("h2",     parent=styles["Heading2"], textColor=blue,  fontSize=13, spaceBefore=14, spaceAfter=5, leading=17)
    h3     = ParagraphStyle("h3",     parent=styles["Heading3"], textColor=blue2, fontSize=10.5, spaceBefore=8, spaceAfter=3)
    body   = ParagraphStyle("body",   parent=styles["BodyText"], fontSize=9,   leading=13, spaceAfter=3)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=14, spaceAfter=2)
    code   = ParagraphStyle("code",   parent=body, fontName="Courier", fontSize=8, leading=11, leftIndent=10, spaceAfter=2, backColor=ltblue)
    small  = ParagraphStyle("small",  parent=body, fontSize=8, textColor=gray)
    note   = ParagraphStyle("note",   parent=body, fontSize=8.5, textColor=blue2, leftIndent=8)

    def T(col_widths, data, hbg=blue, alt=ltblue):
        t = Table(data, colWidths=col_widths, repeatRows=1)
        s = [
            ("BACKGROUND",    (0,0),(-1,0), hbg),
            ("TEXTCOLOR",     (0,0),(-1,0), colors.white),
            ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),(-1,-1), 8),
            ("TOPPADDING",    (0,0),(-1,-1), 3),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ("LEFTPADDING",   (0,0),(-1,-1), 5),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, alt]),
            ("GRID",          (0,0),(-1,-1), 0.3, colors.HexColor("#C5CDD8")),
            ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
            ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ]
        t.setStyle(TableStyle(s))
        return t

    def hr(): return HRFlowable(width="100%", color=maize, thickness=2, spaceAfter=8, spaceBefore=4)
    def sp(n=6): return Spacer(1, n)

    gen = datetime.now().strftime("%B %d, %Y  %I:%M %p")

    story = []

    # ══════════════════════════════════════════════════════════════
    # COVER
    # ══════════════════════════════════════════════════════════════
    story += [
        sp(20),
        Paragraph("Taxi Log", h1),
        Paragraph("Application Design &amp; Specification Document", ParagraphStyle("sub", parent=h2, textColor=blue2, spaceBefore=0)),
        hr(),
        Paragraph(f"Version 3.0 — Generated {gen}", small),
        sp(10),
        Paragraph(
            "This document provides complete specifications for the Taxi Log web application — "
            "sufficient detail for an AI coding tool or developer to recreate the application from scratch. "
            "It covers architecture, data models, authentication, business logic, every API endpoint, "
            "UI structure, and deployment configuration.", body),
        PageBreak(),
    ]

    # ══════════════════════════════════════════════════════════════
    # 1. PURPOSE & SCOPE
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("1. Purpose &amp; Scope", h2), hr(),
        Paragraph("Taxi Log is a multi-driver web application that lets taxi drivers record every "
                  "passenger pickup during their shift and produces end-of-day financial summaries, "
                  "date-range earnings reports, and PDF/CSV exports. An admin role provides "
                  "fleet-wide oversight with impersonation, reporting, and account management.", body),
        sp(4),
        Paragraph("Primary users:", h3),
        Paragraph("• <b>Driver</b> — records pickups in real time, tracks expenses and shift hours, "
                  "views own earnings, downloads reports.", bullet),
        Paragraph("• <b>Admin</b> — manages all driver accounts, views fleet-wide totals, runs "
                  "fleet reports, performs fleet backup and restore.", bullet),
        sp(6),
    ]

    # ══════════════════════════════════════════════════════════════
    # 2. TECHNICAL STACK
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("2. Technical Stack", h2), hr(),
        T([1.4*inch, 1.5*inch, 3.6*inch], [
            ["Layer",           "Technology",             "Detail"],
            ["Language",        "Python 3.11",            "Single-file app — entire backend in main.py"],
            ["Web framework",   "FastAPI 0.104.1",        "Async; Jinja2 templating; form parsing via python-multipart"],
            ["HTML templates",  "Jinja2 3.1.4",           "Server-side rendered; templates written to disk at startup"],
            ["Frontend",        "Vanilla JS + HTML/CSS",  "No build step; all JS/CSS embedded in main.py as Python strings"],
            ["Clock picker",    "Clocklet (CDN)",         "MIT, ~7 kB; analogue 12-hr clock for all time inputs"],
            ["Storage",         "Google Cloud Storage",   "JSON files per driver namespace; local files when GCS_BUCKET unset"],
            ["PDF generation",  "ReportLab 4.x",          "Server-side; used for earnings reports and this document"],
            ["Auth library",    "itsdangerous",           "HMAC-SHA1 signed cookies (URLSafeTimedSerializer)"],
            ["Password hash",   "bcrypt 5.x",             "Direct bcrypt — hashpw / checkpw (no passlib)"],
            ["ASGI server",     "Uvicorn",                "With uvloop + httptools in production"],
            ["Container",       "Docker (python:3.11-slim)", "Built by Cloud Build; run by Cloud Run"],
        ]),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 3. INFRASTRUCTURE & DEPLOYMENT
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("3. Infrastructure &amp; Deployment", h2), hr(),
        T([1.7*inch, 4.8*inch], [
            ["Resource",              "Value"],
            ["GCP Project ID",        "taxi-log-app-494917"],
            ["Cloud Run service",     "taxilog  —  region: us-central1"],
            ["Service URL",           "https://taxilog-841286102686.us-central1.run.app"],
            ["Docker image registry", "us-central1-docker.pkg.dev/taxi-log-app-494917/taxilog/app"],
            ["GCS data bucket",       "taxilog-data-genetownsend"],
            ["Cloud Run memory",      "512 Mi"],
            ["Scaling",               "Scales to zero when idle; one container handles all requests"],
            ["Deploy script",         "./deploy.sh — runs: gcloud builds submit ... && gcloud run deploy ..."],
        ]),
        sp(8),
        Paragraph("Environment variables (set via --set-env-vars in deploy.sh):", h3),
        T([1.6*inch, 1.3*inch, 3.6*inch], [
            ["Variable",      "Required", "Purpose"],
            ["GCS_BUCKET",        "Yes",  "GCS bucket name. When absent, data is stored in local ./data/ files (dev mode)."],
            ["SECRET_KEY",        "Yes",  "Signing key for itsdangerous. Must be a long random hex string."],
            ["ADMIN_SECRET",      "Yes",  "Passphrase required on the admin registration form. Keep private."],
            ["GOOGLE_MAPS_KEY",   "No",   "Google Maps Embed API key. Enables inline map overlay; if absent, map opens in a new tab."],
            ["PORT",          "Auto",     "Set by Cloud Run. App reads os.environ.get('PORT', 8000) at startup."],
        ]),
        sp(6),
        Paragraph("Dockerfile (production):", h3),
        Paragraph("FROM python:3.11-slim", code),
        Paragraph("WORKDIR /app", code),
        Paragraph("COPY requirements.txt .", code),
        Paragraph("RUN pip install --no-cache-dir -r requirements.txt", code),
        Paragraph("COPY main.py .", code),
        Paragraph("ENV PORT=8080", code),
        Paragraph('CMD ["python3", "main.py"]', code),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 4. APPLICATION STRUCTURE
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("4. Application Structure", h2), hr(),
        Paragraph("The entire application lives in a single file: <b>main.py</b>. At startup it writes "
                  "HTML templates and static assets to disk from Python string constants, then starts "
                  "serving. This eliminates the need for a separate static file deployment.", body),
        sp(4),
        T([1.8*inch, 4.7*inch], [
            ["Section in main.py",       "Contents"],
            ["Imports & path constants", "uuid, json, csv, io, os, datetime, Path, FastAPI, itsdangerous, bcrypt"],
            ["HTML string constants",    "BASE_HTML, INDEX_HTML, SETUP_HTML, LOGIN_HTML, REGISTER_HTML, ADMIN_HTML, ADMIN_REGISTER_HTML"],
            ["CSS string constant",      "CSS — all styles as one minified string"],
            ["JS string constant",       "JS — all client-side logic as one string"],
            ["Asset writer",             "Writes templates/ and static/ from the string constants above"],
            ["Helpers",                  "_read, _write, _read_profile, _read_users, _write_users, session helpers, calc functions"],
            ["FastAPI app & routes",     "All HTTP route handlers in order: auth, admin, pickups, expenses, shifts, reports, backup"],
            ["Entry point",              "uvicorn.run() — reload=True locally, reload=False in production (GCS_BUCKET set)"],
        ]),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 5. AUTHENTICATION & SESSIONS
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("5. Authentication &amp; Session Management", h2), hr(),

        Paragraph("5.1  Cookies", h3),
        T([1.4*inch, 1.1*inch, 1.1*inch, 3.4*inch], [
            ["Cookie",     "Max-age",    "httponly", "Contents"],
            ["txl_sess",   "30 days",    "Yes",      "itsdangerous-signed dict: {uid: <uuid>, role: 'driver'|'admin'}"],
            ["txl_view",   "4 hours",   "Yes",      "itsdangerous-signed dict: {driver_id: <uuid>, driver_name: <str>} — admin impersonation only"],
        ]),
        sp(4),
        Paragraph("Both cookies use samesite=lax. The secure flag is True when GCS_BUCKET is set (i.e. in production), "
                  "False in local dev.", note),
        sp(6),

        Paragraph("5.2  AuthCtx dataclass", h3),
        Paragraph("Every request parses cookies into an AuthCtx object:", body),
        T([1.6*inch, 1.1*inch, 3.8*inch], [
            ["Field",           "Type",   "Meaning"],
            ["user_id",         "str",    "UUID of the logged-in user"],
            ["role",            "str",    "'driver' or 'admin'"],
            ["effective_id",    "str",    "UUID used to read/write data. Equals user_id normally; equals impersonated driver's ID when txl_view cookie is set."],
            ["is_impersonating","bool",   "True when admin is viewing a driver. All write endpoints return HTTP 403 when this is True."],
            ["viewed_name",     "str",    "Display name of the impersonated driver (from txl_view cookie)."],
        ]),
        sp(6),

        Paragraph("5.3  Auth helper functions", h3),
        T([1.5*inch, 5.0*inch], [
            ["Helper",          "Behaviour"],
            ["_auth(request)",       "Returns effective_id. Raises HTTP 401 if no valid session."],
            ["_auth_write(request)", "Returns effective_id. Raises HTTP 401 if no session; HTTP 403 if is_impersonating."],
            ["_require_admin(request)", "Returns AuthCtx. Raises HTTP 401 if no session; HTTP 403 if role != 'admin'."],
        ]),
        sp(6),

        Paragraph("5.4  Registration rules", h3),
        Paragraph("• Username: case-insensitive unique across all users. No minimum length.", bullet),
        Paragraph("• Password: minimum 6 characters. Stored as bcrypt hash (gensalt default cost).", bullet),
        Paragraph("• Driver registration (/register): open to anyone. First user to register triggers "
                  "a one-time data migration (flat files → driver namespace).", bullet),
        Paragraph("• Admin registration (/admin/register): form accepts an admin_secret field that must "
                  "exactly match the ADMIN_SECRET env var. The GET endpoint returns HTTP 404 if "
                  "ADMIN_SECRET is not configured.", bullet),
        sp(6),

        Paragraph("5.5  Login flow", h3),
        Paragraph("POST /login → look up username (case-insensitive) → verify bcrypt hash → check active=True "
                  "→ set txl_sess cookie → redirect to /admin (admin) or / (driver).", body),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 6. DATA MODELS
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("6. Data Models", h2), hr(),
        Paragraph("All files are JSON arrays (or a single object for profile.json). "
                  "All IDs are UUID4 strings. Dates are YYYY-MM-DD strings. "
                  "Timestamps (created_at) are UTC ISO-8601 strings.", body),
        sp(4),

        Paragraph("6.1  users.json  (global, not namespaced)", h3),
        T([1.5*inch, 0.8*inch, 0.7*inch, 3.5*inch], [
            ["Field",           "Type",   "Req",  "Description"],
            ["id",              "string", "Yes",  "UUID4 — primary key; used as GCS namespace prefix"],
            ["username",        "string", "Yes",  "Login name; stored as entered, compared case-insensitively"],
            ["password_hash",   "string", "Yes",  "bcrypt hash of the password"],
            ["role",            "string", "Yes",  "'driver' or 'admin'"],
            ["active",          "bool",   "Yes",  "False = account deactivated; login rejected"],
            ["created_at",      "string", "Yes",  "UTC ISO-8601 datetime of registration"],
        ]),
        sp(6),

        Paragraph("6.2  pickups.json  (array, per driver)", h3),
        T([1.7*inch, 0.8*inch, 0.7*inch, 3.3*inch], [
            ["Field",               "Type",   "Req",  "Description"],
            ["id",                  "string", "Yes",  "UUID4"],
            ["pickup_date",         "string", "Yes",  "YYYY-MM-DD"],
            ["pickup_time",         "string", "Yes",  "HH:MM (12- or 24-hr, as entered)"],
            ["street_address",      "string", "No",   "Pickup street address"],
            ["city",                "string", "No",   "Pickup city"],
            ["customer_name",       "string", "No",   "Customer full name"],
            ["phone_number",        "string", "No",   "Customer phone"],
            ["destination_address", "string", "No",   "Drop-off address"],
            ["meter_total",         "float",  "Yes",  "Fare shown on meter"],
            ["payment_method",      "string", "Yes",  "'cash', 'credit', or 'voucher'"],
            ["tip",                 "float",  "No",   "Tip amount (0 if none)"],
            ["tip_payment_method",  "string", "No",   "'cash', 'credit', or 'voucher'"],
            ["calculated_total",    "float",  "Yes",  "meter_total + tip  (server-computed)"],
            ["created_at",          "string", "Yes",  "UTC ISO-8601 datetime"],
        ]),
        sp(6),

        Paragraph("6.3  customers.json  (array, per driver)", h3),
        T([1.6*inch, 0.8*inch, 0.7*inch, 3.4*inch], [
            ["Field",          "Type",   "Req", "Description"],
            ["id",             "string", "Yes", "UUID4"],
            ["name",           "string", "Yes", "Customer full name (used as lookup key when no phone)"],
            ["street_address", "string", "No",  "Most recent pickup address for this customer"],
            ["city",           "string", "No",  "City"],
            ["phone",          "string", "No",  "Phone number (primary lookup key)"],
        ]),
        Paragraph("Upsert logic: when a pickup is saved, the customer record is created or updated. "
                  "Match priority: (1) phone number exact match; (2) name case-insensitive match. "
                  "Non-empty incoming fields overwrite stored fields.", note),
        sp(6),

        Paragraph("6.4  expenses.json  (array, per driver)", h3),
        T([1.5*inch, 0.8*inch, 0.7*inch, 3.5*inch], [
            ["Field",      "Type",   "Req", "Description"],
            ["id",         "string", "Yes", "UUID4"],
            ["date",       "string", "Yes", "YYYY-MM-DD"],
            ["category",   "string", "Yes", "Free-text category (e.g. 'Fuel', 'Tolls')"],
            ["amount",     "float",  "Yes", "Expense amount in dollars"],
            ["notes",      "string", "No",  "Optional notes"],
            ["created_at", "string", "Yes", "UTC ISO-8601 datetime"],
        ]),
        sp(6),

        Paragraph("6.5  shifts.json  (array, per driver — one record per date)", h3),
        T([1.6*inch, 0.8*inch, 0.7*inch, 3.4*inch], [
            ["Field",           "Type",   "Req", "Description"],
            ["id",              "string", "Yes", "UUID4"],
            ["date",            "string", "Yes", "YYYY-MM-DD — unique per driver; POST is an upsert by date"],
            ["start_time",      "string", "No",  "Shift start time (HH:MM)"],
            ["end_time",        "string", "No",  "Shift end time (HH:MM)"],
            ["odometer_start",  "float",  "No",  "Odometer reading at shift start"],
            ["odometer_end",    "float",  "No",  "Odometer reading at shift end"],
            ["miles",           "float",  "Yes", "max(odometer_end − odometer_start, 0)  — server-computed"],
            ["notes",           "string", "No",  "Free-text shift notes"],
            ["created_at",      "string", "Yes", "UTC ISO-8601 datetime (first save only; not updated on upsert)"],
        ]),
        sp(6),

        Paragraph("6.6  profile.json  (single object, per driver)", h3),
        T([1.6*inch, 0.8*inch, 0.7*inch, 3.4*inch], [
            ["Field",        "Type",         "Req", "Description"],
            ["driver_name",  "string",        "Yes", "Display name shown in app and reports"],
            ["vehicle",      "string",        "No",  "Vehicle description (free text)"],
            ["phone",        "string",        "No",  "Driver's own phone number"],
            ["pay_mode",     "string",        "Yes", "'standard', 'gate', 'commission', or 'owner'"],
            ["gate_fee",     "float or null", "No",  "Daily gate fee — used when pay_mode='gate'"],
            ["company_pct",  "float or null", "No",  "Company percentage (0–100) — used when pay_mode='commission'"],
        ]),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 7. BUSINESS LOGIC
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("7. Business Logic — Financial Calculations", h2), hr(),

        Paragraph("7.1  Day totals (day_totals function)", h3),
        Paragraph("Iterates all pickups for a date, accumulates meter and tip amounts into six buckets "
                  "by payment method, sums calculated_total into grand_total, then calls owed_driver_amount.", body),
        Paragraph("meter_cash    += meter_total  where payment_method == 'cash'", code),
        Paragraph("meter_credit  += meter_total  where payment_method == 'credit'", code),
        Paragraph("meter_voucher += meter_total  where payment_method == 'voucher'", code),
        Paragraph("tip_cash      += tip  where tip_payment_method == 'cash'", code),
        Paragraph("tip_credit    += tip  where tip_payment_method == 'credit'", code),
        Paragraph("tip_voucher   += tip  where tip_payment_method == 'voucher'", code),
        Paragraph("grand_total   += calculated_total  (for every pickup)", code),
        sp(6),

        Paragraph("7.2  Owed Driver calculation (owed_driver_amount function)", h3),
        T([1.4*inch, 2.5*inch, 2.6*inch], [
            ["pay_mode",    "Formula",                                          "Variables"],
            ["standard",    "((mcr + mv) - mc) / 2 + tcr + tv",               "mc=meter_cash, mcr=meter_credit, mv=meter_voucher, tcr=tip_credit, tv=tip_voucher"],
            ["gate",        "grand_total - gate_fee",                          "gate_fee from profile.json"],
            ["commission",  "(mc+mcr+mv) * (1 - company_pct/100) + (tc+tcr+tv)", "company_pct from profile.json; tc=tip_cash"],
            ["owner",       "grand_total",                                     "Driver keeps everything"],
        ]),
        sp(6),

        Paragraph("7.3  Earnings (driver take-home after expenses)", h3),
        Paragraph("earnings = owed_driver + meter_cash + tip_cash - expense_total", code),
        Paragraph("Rationale: in standard mode owed_driver already excludes cash meter and cash tips "
                  "(which the driver physically collected). Adding them back gives true take-home "
                  "before deducting expenses.", note),
        sp(6),

        Paragraph("7.4  Pickup calculated_total", h3),
        Paragraph("calculated_total = round(meter_total + tip, 2)  — server-computed on every create/update.", code),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 8. API REFERENCE
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("8. API Reference", h2), hr(),
        Paragraph("Auth column: P=Public, D=Driver (any logged-in user), W=Write (driver, not impersonating), A=Admin only.", small),
        sp(4),

        Paragraph("8.1  Authentication &amp; Account Routes", h3),
        T([0.9*inch, 2.0*inch, 0.45*inch, 3.15*inch], [
            ["Method", "Path",              "Auth", "Behaviour"],
            ["GET",  "/login",              "P",    "Render login form"],
            ["POST", "/login",              "P",    "Form: username, password. Validates, sets txl_sess, redirects to / or /admin"],
            ["GET",  "/register",           "P",    "Render driver registration form"],
            ["POST", "/register",           "P",    "Form: username, password, confirm. Creates driver account; redirects to /setup (first user) or /"],
            ["POST", "/logout",             "D",    "Clears txl_sess and txl_view cookies; redirects to /login"],
            ["GET",  "/admin/register",     "P",    "Render admin registration form. Returns 404 if ADMIN_SECRET not configured."],
            ["POST", "/admin/register",     "P",    "Form: username, password, confirm, admin_secret. Creates admin account."],
            ["POST", "/api/change-password","D",    "JSON: {current_password, new_password}. Min 6 chars. Returns {ok:true}."],
        ]),
        sp(6),

        Paragraph("8.2  Page Routes", h3),
        T([0.9*inch, 2.0*inch, 0.45*inch, 3.15*inch], [
            ["Method", "Path",                "Auth", "Behaviour"],
            ["GET",  "/",                     "D",    "Main log page. Query param: date (YYYY-MM-DD, default today)."],
            ["GET",  "/setup",                "D",    "Profile / expenses / shifts / backup page."],
            ["POST", "/setup",                "W",    "Form: driver_name, vehicle, phone, pay_mode, gate_fee, company_pct. Saves profile.json."],
            ["GET",  "/admin",                "A",    "Admin dashboard with today's fleet totals and driver list."],
            ["GET",  "/admin/view/{id}",      "A",    "Sets txl_view cookie for driver {id}; redirects to /."],
            ["POST", "/admin/exit-view",      "A",    "Clears txl_view cookie; redirects to /admin."],
            ["POST", "/admin/deactivate/{id}","A",    "Sets active=False on driver account."],
            ["POST", "/admin/reactivate/{id}","A",    "Sets active=True on driver account."],
            ["POST", "/admin/delete/{id}",    "A",    "Removes driver from users.json and deletes all GCS files under {id}/."],
        ]),
        sp(6),

        Paragraph("8.3  Pickup API", h3),
        T([0.9*inch, 2.3*inch, 0.45*inch, 2.85*inch], [
            ["Method",   "Path",             "Auth", "Behaviour"],
            ["GET",    "/api/pickups",        "D",    "Query param: date (optional). Returns array sorted by pickup_time."],
            ["POST",   "/api/pickups",        "W",    "JSON body: pickup fields. Server computes calculated_total. Upserts customer. Returns created record."],
            ["GET",    "/api/pickups/{pid}",  "D",    "Returns single pickup by id. 404 if not found."],
            ["PUT",    "/api/pickups/{pid}",  "W",    "JSON body: partial or full pickup fields. Recomputes calculated_total. Upserts customer."],
            ["DELETE", "/api/pickups/{pid}",  "W",    "Deletes single pickup. 404 if not found."],
            ["DELETE", "/api/pickups",        "W",    "Deletes ALL pickups and ALL customers for this driver."],
        ]),
        sp(6),

        Paragraph("8.4  Expense API", h3),
        T([0.9*inch, 2.3*inch, 0.45*inch, 2.85*inch], [
            ["Method",   "Path",               "Auth", "Behaviour"],
            ["GET",    "/api/expenses",         "D",    "Query param: date (optional). Returns array sorted by date."],
            ["POST",   "/api/expenses",         "W",    "JSON: {date, category, amount, notes}. Returns created record."],
            ["DELETE", "/api/expenses/{eid}",   "W",    "Deletes expense by id. 404 if not found."],
        ]),
        sp(6),

        Paragraph("8.5  Shift API", h3),
        T([0.9*inch, 2.3*inch, 0.45*inch, 2.85*inch], [
            ["Method", "Path",          "Auth", "Behaviour"],
            ["GET",  "/api/shifts",     "D",    "Query param: date (optional). Returns array."],
            ["POST", "/api/shifts",     "W",    "JSON: {date, start_time, end_time, odometer_start, odometer_end, notes}. Upsert by date: updates existing record if date already exists. Miles = max(odo_end - odo_start, 0)."],
        ]),
        sp(6),

        Paragraph("8.6  Totals &amp; Reports API", h3),
        T([0.9*inch, 2.6*inch, 0.45*inch, 2.55*inch], [
            ["Method", "Path",                  "Auth", "Behaviour"],
            ["GET", "/api/daily-totals",         "D",    "Query param: date. Returns day_totals object plus expense_total, net_earnings, driver_earnings, pay_mode."],
            ["GET", "/api/report",               "D",    "Query params: from_date, to_date. Returns {days: [...], summary: {...}} with per-day pickup arrays, totals, shift data, and aggregate summary."],
            ["GET", "/api/report/csv",           "D",    "Same params as /api/report. Returns CSV download of all pickups (no summary)."],
            ["GET", "/api/report-pdf",           "D",    "Same params. Returns PDF with per-day tables and grand-total summary."],
            ["GET", "/api/customers/suggest",    "D",    "Query param: q (min 2 chars). Returns up to 10 customer records matching name, address, or phone."],
            ["GET", "/api/customers/lookup",     "D",    "Query params: phone, address. Exact match — phone takes priority. Returns single customer or {}."],
        ]),
        sp(6),

        Paragraph("8.7  Driver Backup &amp; Restore API", h3),
        T([0.9*inch, 2.4*inch, 0.45*inch, 2.75*inch], [
            ["Method", "Path",                   "Auth", "Behaviour"],
            ["GET",  "/api/backup/pickups",       "D",    "Downloads pickups.json as attachment."],
            ["GET",  "/api/backup/customers",     "D",    "Downloads customers.json."],
            ["GET",  "/api/backup/expenses",      "D",    "Downloads expenses.json."],
            ["GET",  "/api/backup/shifts",        "D",    "Downloads shifts.json."],
            ["GET",  "/api/backup/profile",       "D",    "Downloads profile.json."],
            ["GET",  "/api/backup/all",           "D",    "Downloads ZIP containing all 5 files above. Filename: taxilog_backup_YYYY-MM-DD.zip."],
            ["POST", "/api/restore/pickups",      "W",    "Multipart file upload. Expects JSON array. Overwrites pickups.json."],
            ["POST", "/api/restore/customers",    "W",    "Expects JSON array. Overwrites customers.json."],
            ["POST", "/api/restore/expenses",     "W",    "Expects JSON array. Overwrites expenses.json."],
            ["POST", "/api/restore/shifts",       "W",    "Expects JSON array. Overwrites shifts.json."],
            ["POST", "/api/restore/profile",      "W",    "Expects JSON object. Overwrites profile.json."],
            ["POST", "/api/restore/all",          "W",    "Multipart ZIP upload. Restores any of the 5 files found inside the ZIP. Returns {ok:true, restored:[...]}."],
        ]),
        sp(6),

        Paragraph("8.8  Admin API", h3),
        T([0.9*inch, 2.6*inch, 0.45*inch, 2.55*inch], [
            ["Method", "Path",                       "Auth", "Behaviour"],
            ["GET",  "/api/admin/fleet-report",       "A",    "Query params: from_date, to_date. Returns {drivers:[...], summary:{...}} — per-driver totals aggregated over date range."],
            ["GET",  "/api/admin/fleet-report-pdf",   "A",    "Same params. Returns fleet PDF report."],
            ["POST", "/api/admin/delete-all",         "A",    "Deletes all driver accounts and all their GCS data. Admin accounts preserved."],
            ["GET",  "/api/admin/backup/all",         "A",    "Downloads fleet ZIP: users.json + every driver's 5 data files under {id}/ folders."],
            ["POST", "/api/admin/restore/all",        "A",    "Multipart ZIP upload. Restores users.json and all driver data files from fleet backup ZIP."],
            ["GET",  "/api/admin/design-pdf",         "A",    "Downloads this design document."],
            ["GET",  "/api/requirements-pdf",         "D",    "Legacy: simplified requirements PDF (driver-accessible)."],
        ]),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 9. UI ARCHITECTURE
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("9. UI Architecture", h2), hr(),
        Paragraph("The UI is server-rendered HTML with JavaScript making AJAX calls to the JSON API. "
                  "There is no SPA router — each major section is a full-page load. Modals and dynamic "
                  "panels are plain HTML/CSS controlled by JS.", body),
        sp(4),

        Paragraph("9.1  Page: /  (Main Log)", h3),
        T([1.8*inch, 4.7*inch], [
            ["Component",           "Description"],
            ["Date picker",         "Defaults to today. Changing date reloads pickups and totals for that date."],
            ["Pickup form",         "Fields: pickup_time (clock picker), street_address, city, customer_name (autocomplete), phone_number, destination_address, meter_total, payment_method, tip, tip_payment_method. Submits to POST /api/pickups."],
            ["Pickup list",         "Cards rendered from GET /api/pickups?date=. Each card has Edit and Delete buttons."],
            ["Edit inline",         "Clicking Edit replaces card footer with editable fields; Save calls PUT /api/pickups/{id}."],
            ["Daily totals panel",  "Fetched from GET /api/daily-totals?date=. Shows meter by type, tips by type, owed driver (large), earnings. Refreshed after every pickup create/update/delete."],
            ["Customer autocomplete","Typeahead on customer_name: calls GET /api/customers/suggest?q=. On select, fills address and phone. On phone blur, calls GET /api/customers/lookup?phone= to auto-fill name and address."],
            ["Clock picker",        "Clocklet library (CDN). Attached to pickup_time input. 12-hour face with AM/PM toggle."],
        ]),
        sp(6),

        Paragraph("9.2  Page: /setup  (Driver Setup)", h3),
        T([1.8*inch, 4.7*inch], [
            ["Panel",           "Description"],
            ["Profile",         "Form: driver_name, vehicle, phone, pay_mode (select), gate_fee or company_pct (shown conditionally based on pay_mode). POST /setup."],
            ["Password change",  "Inline form: current_password, new_password. AJAX to POST /api/change-password."],
            ["Expenses",        "Add expense form (date, category, amount, notes). Lists today's expenses. Delete button per item."],
            ["Shift log",       "Fields: start_time, end_time (clock pickers), odometer_start, odometer_end, notes. Save calls POST /api/shifts (upsert by date)."],
            ["Earnings report", "Date range pickers. Generate button fetches GET /api/report and renders HTML table in a modal. Per-day accordion with pickup rows (horizontally scrollable). Summary grid at bottom. CSV and PDF export buttons."],
            ["Backup",          "Download buttons for each file and a ZIP of all. Uses plain <a download> tags — no JS fetch."],
            ["Restore",         "Visible file inputs per data type + restore button per type. Full restore accepts ZIP."],
        ]),
        sp(6),

        Paragraph("9.3  Page: /admin  (Admin Dashboard)", h3),
        T([1.8*inch, 4.7*inch], [
            ["Section",         "Description"],
            ["Fleet Overview",  "Stats cards: total drivers, today's fleet gross, today's fleet earnings."],
            ["Today's Totals",  "Table: one row per active driver showing pickups, meter, tips, expenses, owed, earnings. Footer row with fleet total."],
            ["Fleet Report",    "Date range pickers + Generate button. AJAX to /api/admin/fleet-report. Renders table in page. PDF button."],
            ["Fleet Backup",    "Single <a download> link to /api/admin/backup/all."],
            ["Fleet Restore",   "Visible file input + Restore button. Reads input.files[0] directly."],
            ["Design Document", "Single <a download> link to /api/admin/design-pdf."],
            ["Danger Zone",     "Delete database button → inline confirmation panel where admin must type 'DELETE' before confirming."],
            ["Active Drivers",  "Table with View (impersonate), Deactivate, Delete buttons per driver."],
            ["Administrators",  "List of admin accounts. Cannot delete own account."],
            ["Deactivated",     "List of deactivated accounts with Reactivate and Delete Forever buttons."],
        ]),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 10. NAVIGATION & THEMING
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("10. Navigation &amp; Visual Theme", h2), hr(),

        Paragraph("10.1  Navigation", h3),
        Paragraph("Hamburger menu (top-right) opens a vertical nav drawer. Links shown depend on role: "
                  "drivers see Log and Setup; admins see Admin Dashboard, Log, and Setup. "
                  "Sign Out is always present.", body),
        Paragraph("Impersonation banner: when admin is viewing a driver, a sticky banner at the top shows "
                  "'Viewing [Name] — Read Only' with an Exit View button.", body),
        sp(6),

        Paragraph("10.2  Color theme (Michigan Maize &amp; Blue)", h3),
        T([1.8*inch, 1.5*inch, 3.2*inch], [
            ["CSS variable",    "Value",        "Used for"],
            ["--amber",         "#FFCB05",      "Michigan Maize — primary accent, active nav, focus rings"],
            ["--amber-d",       "#E5B700",      "Hover state for Maize elements"],
            ["--amber-dd",      "#A38400",      "Maize text on light backgrounds"],
            ["--amber-lt",      "#FFF8CC",      "Light Maize fill (table alternating rows)"],
            ["--amber-xl",      "#FFFDE5",      "Extra-light Maize wash"],
            ["--bg",            "#F5F7FA",      "Page background (cool off-white)"],
            ["--surface",       "#FFFFFF",      "Card/panel background"],
            ["--surface2",      "#EEF1F6",      "Secondary surface, table header backgrounds"],
            ["--text",          "#0A1628",      "Body text (deep navy)"],
            ["Header / nav",    "#00274C",      "Michigan Blue — site header, nav drawer, secondary buttons"],
            ["Btn primary",     "#FFCB05 bg, #00274C text", "Maize button with Blue text (WCAG AA)"],
            ["Btn secondary",   "#00274C bg, white text",   "Michigan Blue button"],
            ["--red",           "#EF4444",      "Danger actions, expense amounts"],
            ["--green",         "#10B981",      "Earnings, positive values"],
        ]),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 11. BACKUP & RESTORE
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("11. Backup &amp; Restore System", h2), hr(),

        Paragraph("11.1  Driver backup ZIP structure", h3),
        Paragraph("taxilog_backup_YYYY-MM-DD.zip", code),
        Paragraph("  pickups.json      — JSON array", code),
        Paragraph("  customers.json    — JSON array", code),
        Paragraph("  expenses.json     — JSON array", code),
        Paragraph("  shifts.json       — JSON array", code),
        Paragraph("  profile.json      — JSON object", code),
        sp(6),

        Paragraph("11.2  Fleet backup ZIP structure", h3),
        Paragraph("taxilog_fleet_backup_YYYY-MM-DD.zip", code),
        Paragraph("  users.json                  — JSON array of all user accounts", code),
        Paragraph("  {driver_id}/pickups.json    — one folder per driver", code),
        Paragraph("  {driver_id}/customers.json", code),
        Paragraph("  {driver_id}/expenses.json", code),
        Paragraph("  {driver_id}/shifts.json", code),
        Paragraph("  {driver_id}/profile.json", code),
        sp(6),

        Paragraph("11.3  Restore validation", h3),
        Paragraph("• Array files (pickups, customers, expenses, shifts): server rejects if JSON root is not a list.", bullet),
        Paragraph("• Object files (profile): server rejects if JSON root is not a dict.", bullet),
        Paragraph("• ZIP restore: processes only files that are present in the ZIP; missing files are skipped.", bullet),
        Paragraph("• All restore endpoints require W auth (driver, not impersonating).", bullet),
        Paragraph("• Fleet restore requires A auth.", bullet),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 12. VALIDATION & CONSTRAINTS
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("12. Validation &amp; Constraints", h2), hr(),
        T([2.0*inch, 4.5*inch], [
            ["Rule",                        "Detail"],
            ["Password minimum",            "6 characters. Checked on registration and change-password."],
            ["Username uniqueness",         "Case-insensitive. Checked at registration time only (no rename)."],
            ["Impersonation write block",   "Any POST/PUT/DELETE data endpoint returns HTTP 403 if is_impersonating=True."],
            ["Admin self-delete",           "Admin cannot delete their own account; button hidden in UI, guard in route."],
            ["Session expiry",              "txl_sess: 30 days. txl_view: 4 hours. Expired tokens are rejected silently."],
            ["Shift uniqueness",            "One shift record per driver per date. POST /api/shifts is an upsert."],
            ["Odometer miles",              "Computed as max(odometer_end - odometer_start, 0) — never negative."],
            ["Meter / tip defaults",        "If missing or empty, server coerces to 0.0 before storage."],
            ["Delete all pickups",          "Also deletes all customers (DELETE /api/pickups with no path param)."],
            ["Delete database",             "UI requires admin to type 'DELETE' exactly before the form submits."],
            ["ADMIN_SECRET absent",         "GET /admin/register returns HTTP 404; POST returns HTTP 404."],
            ["Inactive account login",      "Login rejected with 'This account has been deactivated.' message."],
        ]),
        sp(8),
    ]

    # ══════════════════════════════════════════════════════════════
    # 13. DATA MIGRATION
    # ══════════════════════════════════════════════════════════════
    story += [
        Paragraph("13. Data Migration (first-user)", h2), hr(),
        Paragraph("Before the multi-driver system was introduced, all data was stored as flat GCS blobs "
                  "(pickups.json, customers.json, etc.) with no driver namespace prefix. When the first "
                  "driver account is registered, _migrate_flat_data() is called:", body),
        Paragraph("• In GCS: copies each flat blob to {driver_id}/{name}; deletes the old flat blob.", bullet),
        Paragraph("• Locally: renames ./data/{name} to ./data/{driver_id}/{name}.", bullet),
        Paragraph("• Only runs once (is_first = len(users) == 0 before appending the new user).", bullet),
        Paragraph("• Migration is idempotent: destination blob/file existence is checked before writing.", bullet),
        sp(8),
    ]

    doc.build(story)
    buf.seek(0)
    fname = f"taxilog_design_{date.today().isoformat()}.pdf"
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"})

# ── entry point ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    reload = not _GCS_BUCKET  # no reload in production
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload)
