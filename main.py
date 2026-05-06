import uuid
import json
import csv
import io
import os
from datetime import datetime, date
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import aiofiles

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
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/clocklet@0.3.0/css/clocklet.min.css">
</head>
<body>
<header class="site-header">
  <div class="header-inner">
    <div class="header-brand">
      <span class="taxi-icon">🚕</span>
      <div>
        <div class="brand-title">Taxi Pickup Daily Log</div>
        {% if profile %}
        <div class="brand-sub">{{ profile.driver_name }}{% if profile.vehicle %} &middot; {{ profile.vehicle }}{% endif %}</div>
        {% endif %}
      </div>
    </div>
    {% if profile %}
    <button class="hamburger" id="hamburger" onclick="toggleNav()" aria-label="Menu">
      <span></span><span></span><span></span>
    </button>
    {% endif %}
  </div>
  {% if profile %}
  <nav class="site-nav" id="siteNav">
    <a href="/" class="nav-link {% if request.url.path == '/' %}active{% endif %}" onclick="closeNav()">📋 Log</a>
    <a href="#" class="nav-link" onclick="closeNav();openShiftModal()">⏱ Shift</a>
    <a href="#" class="nav-link" onclick="closeNav();openExpenseModal()">💸 Expenses</a>
    <a href="#" class="nav-link" onclick="closeNav();openModal('reportModal')">📊 Report</a>
    <a href="#" class="nav-link" onclick="closeNav();openModal('backupModal')">💾 Backup</a>
    <a href="/setup" class="nav-link {% if request.url.path == '/setup' %}active{% endif %}" onclick="closeNav()">⚙️ Setup</a>
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
        <button class="btn btn-primary" onclick="saveFullBackup()">💾 Save Full Backup</button>
      </div>
      <div class="section-label">Full Restore</div>
      <div class="warning-text">⚠️ Restores ALL data from a backup ZIP. Cannot be undone.</div>
      <div class="btn-group mb-4">
        <button class="btn btn-warning" onclick="restoreFromZip()">📂 Select Backup &amp; Restore</button>
      </div>
      <input type="file" id="restoreZip" accept=".zip" style="display:none">
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
            <input type="text" id="sh_start" class="field-input" data-clocklet="format: hh:mm A;" placeholder="--:-- AM" oninput="calcShiftStats()" onchange="calcShiftStats()">
          </div>
          <div class="field-group">
            <label class="field-label">End Time</label>
            <input type="text" id="sh_end" class="field-input" data-clocklet="format: hh:mm A;" placeholder="--:-- AM" oninput="calcShiftStats()" onchange="calcShiftStats()">
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
<script src="https://cdn.jsdelivr.net/npm/clocklet@0.3.0"></script>
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
          <input type="text" id="pickup_time" name="pickup_time" class="field-input" required data-clocklet="format: hh:mm A;" placeholder="--:-- AM">
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
                 step="0.01" min="0" placeholder="0.00" oninput="updateCalcTotal()">
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
      </div>
    </div>
  </section>

</div>
{% endblock %}
{% block extra_js %}
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
  </div>
</div>
{% endblock %}
{% block extra_js %}
<script>
const _explains = {
  standard:   'Formula: ((Credit Meter + Voucher Meter) − Cash Meter) ÷ 2 + Credit Tips + Voucher Tips',
  gate:       'Formula: Grand Total − Daily Gate Fee',
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
</script>
{% endblock %}
"""

# ════════════════════════════════════════════════════════════════
# CSS
# ════════════════════════════════════════════════════════════════

CSS = """\
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --amber:#F59E0B;--amber-d:#D97706;--amber-dd:#B45309;
  --amber-lt:#FEF3C7;--amber-xl:#FFFBEB;
  --bg:#F8F7F4;--surface:#FFFFFF;--surface2:#F3F2EF;
  --border:#E5E3DE;--border2:#D1CEC7;
  --text:#1A1815;--text2:#6B6660;--text3:#9C9790;
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
.site-header{background:linear-gradient(135deg,#1A1815 0%,#2D2A26 100%);border-bottom:1px solid rgba(255,255,255,.08);position:sticky;top:0;z-index:200;box-shadow:0 2px 20px rgba(0,0,0,.25)}
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
.site-nav{display:none;flex-direction:column;background:#1C1917;border-top:1px solid rgba(255,255,255,.08);padding:8px 24px 12px}
.site-nav.open{display:flex}
.nav-link{color:rgba(255,255,255,.7);text-decoration:none;padding:10px 14px;border-radius:var(--radius-sm);font-size:14px;font-weight:500;transition:all .15s;display:flex;align-items:center;gap:8px}
.nav-link:hover{color:#fff;background:rgba(255,255,255,.08)}
.nav-link.active{color:var(--amber);background:rgba(245,158,11,.12)}
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
.field-input:focus{outline:none;border-color:var(--amber);box-shadow:0 0 0 3px rgba(245,158,11,.12)}
select.field-input{cursor:pointer}
.row-2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.autocomplete-wrap{position:relative}
.autocomplete-list{position:absolute;top:calc(100% + 4px);left:0;right:0;background:var(--surface);border:1.5px solid var(--amber);border-radius:var(--radius);box-shadow:var(--shadow);z-index:300;max-height:200px;overflow-y:auto}
.ac-item{padding:10px 12px;cursor:pointer;border-bottom:1px solid var(--border);transition:background .1s}
.ac-item:last-child{border-bottom:none}
.ac-item:hover{background:var(--amber-xl)}
.ac-name{font-weight:600;font-size:13px;color:var(--text)}
.ac-detail{font-size:11px;color:var(--text3);margin-top:1px}
.calc-total-bar{background:linear-gradient(135deg,var(--amber-dd) 0%,var(--amber-d) 100%);border-radius:var(--radius);padding:14px 16px;display:flex;justify-content:space-between;align-items:center;margin:16px 0 12px;box-shadow:0 2px 8px rgba(217,119,6,.25)}
.calc-total-label{color:rgba(255,255,255,.8);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.calc-total-value{color:#fff;font-size:24px;font-weight:800;letter-spacing:-.5px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 18px;border-radius:var(--radius-sm);font-size:13.5px;font-weight:600;cursor:pointer;border:none;transition:all .15s;text-decoration:none;font-family:var(--font);letter-spacing:-.1px}
.btn:active{transform:scale(.97)}
.btn-primary{background:var(--amber);color:#fff;box-shadow:0 2px 8px rgba(245,158,11,.3)}
.btn-primary:hover{background:var(--amber-d);box-shadow:0 4px 12px rgba(245,158,11,.4);transform:translateY(-1px)}
.btn-secondary{background:var(--text);color:#fff}
.btn-secondary:hover{background:#333}
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
.totals-head{background:var(--text);padding:10px 14px}
.totals-head-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:rgba(255,255,255,.45);font-weight:600}
.totals-grid{display:grid;grid-template-columns:1fr 1fr;background:var(--surface2)}
.total-cell{padding:10px 14px;border-right:1px solid var(--border);border-bottom:1px solid var(--border)}
.total-cell:nth-child(even){border-right:none}
.total-cell-label{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--text3);font-weight:600;margin-bottom:2px}
.total-cell-val{font-size:16px;font-weight:700;color:var(--text);letter-spacing:-.3px}
.owed-driver-bar{padding:14px 16px;background:var(--amber-d);display:flex;justify-content:space-between;align-items:center}
.owed-driver-label{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:rgba(255,255,255,.8)}
.owed-driver-val{font-size:26px;font-weight:800;color:#fff;letter-spacing:-.5px}
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
.report-day{margin-bottom:20px;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
.report-day-hdr{background:var(--text);color:#fff;padding:10px 14px;display:flex;justify-content:space-between;align-items:center}
.report-shift-bar{background:#2D2A26;color:rgba(255,255,255,.6);font-size:11px;padding:5px 14px}
.report-table{width:100%;border-collapse:collapse}
.report-table th{background:var(--amber-lt);padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--amber-dd);border-bottom:1px solid var(--border)}
.report-table td{padding:8px 12px;border-bottom:1px solid var(--border);font-size:13px}
.report-table tr:last-child td{border-bottom:none}
.report-table tr:hover td{background:var(--surface2)}
.report-expense-row td{background:var(--red-lt);color:#991B1B;font-style:italic}
.report-day-foot{background:var(--surface2);padding:10px 14px;display:flex;flex-wrap:wrap;gap:14px;font-size:12px;border-top:1px solid var(--border)}
.report-net{color:var(--green);font-weight:700}
.report-summary{background:var(--text);color:#fff;border-radius:var(--radius);padding:18px;margin-top:16px}
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
.toast{position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:var(--text);color:#fff;padding:11px 22px;border-radius:var(--radius-xl);font-size:13.5px;font-weight:600;box-shadow:var(--shadow-lg);z-index:9999;pointer-events:none;letter-spacing:-.1px}
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
"""

# ════════════════════════════════════════════════════════════════
# JAVASCRIPT
# ════════════════════════════════════════════════════════════════

JS = """/* app.js */
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
/* open Clocklet on dynamically-created time fields */
document.addEventListener('focusin',e=>{
  if(e.target.classList.contains('clocklet-field')&&typeof clocklet!=='undefined'){
    clocklet.open(e.target,{format:'hh:mm A'});
  }
});

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
async function submitPickup(e){
  e.preventDefault();
  const f=e.target;
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
  if(btn.dataset.action==='delete')deletePickup(id);
  if(btn.dataset.action==='del-expense')deleteExpense(id);
  if(btn.dataset.action==='cancel-edit')closeModal('editModal');
});

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
  const net=t.net_earnings!==undefined?t.net_earnings:t.owed_driver;
  if(owedEl)owedEl.textContent=fmt(net);
  if(owedLabel)owedLabel.textContent=hasExp?'Net After Expenses':'Owed Driver';
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
      +'<div class="field-group"><label class="field-label">Time</label><input type="text" id="e_time" class="field-input clocklet-field" placeholder="--:-- AM" value="'+to12h(p.pickup_time)+'"></div>'
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
      +'<table class="report-table"><thead><tr>'
        +'<th>Time</th><th>From</th><th>To</th><th>Customer</th>'
        +'<th>Meter</th><th>Pay</th><th>Tip</th><th>Total</th>'
      +'</tr></thead><tbody>'+rows+expRows+'</tbody></table>'
      +'<div class="report-day-foot">'
        +'<span>Cash: '+fmt(t.meter_cash)+'</span>'
        +'<span>Credit: '+fmt(t.meter_credit)+'</span>'
        +'<span>Voucher: '+fmt(t.meter_voucher)+'</span>'
        +'<span>Tips: '+fmt(t.tip_cash+t.tip_credit+t.tip_voucher)+'</span>'
        +(t.expense_total>0?'<span style="color:var(--red)">Expenses: −'+fmt(t.expense_total)+'</span>':'')
        +'<strong>Owed: '+fmt(t.owed_driver)+'</strong>'
        +(t.expense_total>0?'<strong class="report-net">Net: '+fmt(t.net_earnings)+'</strong>':'')
      +'</div>'
    +'</div>';
  }).join('');
  const s=data.summary;
  const summaryItems=[
    ['Pickups',s.count,false],['Cash Meter',fmt(s.meter_cash),false],
    ['Credit Meter',fmt(s.meter_credit),false],['Voucher Meter',fmt(s.meter_voucher),false],
    ['Credit Tips',fmt(s.tip_credit),false],['Voucher Tips',fmt(s.tip_voucher),false],
    ['Grand Total',fmt(s.grand_total),false],['Total Expenses',fmt(s.expense_total||0),false],
    ['Owed Driver',fmt(s.owed_driver),true],['Net Earnings',fmt(s.net_earnings||s.owed_driver),'net'],
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
async function saveFullBackup(){
  const fname='taxilog_backup_'+new Date().toISOString().slice(0,10)+'.zip';
  if('showSaveFilePicker' in window){
    try{
      const handle=await window.showSaveFilePicker({
        suggestedName:fname,
        types:[{description:'ZIP Backup',accept:{'application/zip':['.zip']}}],
      });
      showToast('Saving…',60000);
      const blob=await(await fetch('/api/backup/all')).blob();
      const w=await handle.createWritable();
      await w.write(blob);await w.close();
      showToast('Backup saved');
    }catch(e){if(e.name!=='AbortError')showToast('Save failed');}
  }else{
    const a=document.createElement('a');
    a.href='/api/backup/all';a.download=fname;a.click();
  }
}

/* --- Full restore with Open File dialog --- */
async function restoreFromZip(){
  const doRestore=async(file)=>{
    if(!confirm('Restore all data from "'+file.name+'"?\\nThis overwrites all existing data and cannot be undone.'))return;
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
  };
  if('showOpenFilePicker' in window){
    try{
      const [handle]=await window.showOpenFilePicker({
        types:[{description:'ZIP Backup',accept:{'application/zip':['.zip']}}],
      });
      await doRestore(await handle.getFile());
    }catch(e){if(e.name!=='AbortError')showToast('No file selected');}
  }else{
    const input=document.getElementById('restoreZip');
    input.onchange=async()=>{if(input.files.length)await doRestore(input.files[0]);input.value='';};
    input.click();
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
    "templates/base.html":  BASE_HTML,
    "templates/index.html": INDEX_HTML,
    "templates/setup.html": SETUP_HTML,
    "static/css/style.css": CSS,
    "static/js/app.js":     JS,
}
for _rel, _content in _ASSETS.items():
    _p = BASE_DIR / _rel
    _p.parent.mkdir(parents=True, exist_ok=True)
    _p.write_text(_content, encoding="utf-8")

# ════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════

_GCS_BUCKET = os.environ.get("GCS_BUCKET")

def _gcs_client():
    from google.cloud import storage
    return storage.Client()

def _read(path: Path):
    if _GCS_BUCKET:
        try:
            blob = _gcs_client().bucket(_GCS_BUCKET).blob(path.name)
            if not blob.exists(): return []
            return json.loads(blob.download_as_text())
        except Exception: return []
    if not path.exists(): return []
    with open(path) as f: return json.load(f)

def _write(path: Path, data):
    if _GCS_BUCKET:
        blob = _gcs_client().bucket(_GCS_BUCKET).blob(path.name)
        blob.upload_from_string(json.dumps(data, indent=2, default=str),
                                content_type="application/json")
        return
    with open(path, "w") as f: json.dump(data, f, indent=2, default=str)

def _read_profile():
    if _GCS_BUCKET:
        try:
            blob = _gcs_client().bucket(_GCS_BUCKET).blob(PROFILE_F.name)
            if not blob.exists(): return {}
            return json.loads(blob.download_as_text())
        except Exception: return {}
    if not PROFILE_F.exists(): return {}
    with open(PROFILE_F) as f: return json.load(f)

def owed_driver_amount(t: dict, profile: dict) -> float:
    mode = (profile or {}).get("pay_mode", "standard")
    mc, mcr, mv = t["meter_cash"], t["meter_credit"], t["meter_voucher"]
    tc, tcr, tv = t["tip_cash"], t["tip_credit"], t["tip_voucher"]
    gt = t["grand_total"]
    if mode == "gate":
        return round(gt - float((profile or {}).get("gate_fee") or 0), 2)
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

def upsert_customer(name, address, city, phone):
    if not name: return
    customers = _read(CUSTOMERS_F)
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
    _write(CUSTOMERS_F, customers)

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

# ── pages ────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    profile = _read_profile()
    if not profile: return RedirectResponse("/setup")
    return _tmpl("index.html", request, {"profile": profile, "today": date.today().isoformat()})

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    return _tmpl("setup.html", request, {"profile": _read_profile()})

@app.post("/setup")
async def save_profile(request: Request,
                       driver_name:  str = Form(...),
                       vehicle:      str = Form(""),
                       phone:        str = Form(""),
                       pay_mode:     str = Form("standard"),
                       gate_fee:     str = Form(""),
                       company_pct:  str = Form("")):
    _write(PROFILE_F, {
        "driver_name": driver_name,
        "vehicle":     vehicle,
        "phone":       phone,
        "pay_mode":    pay_mode,
        "gate_fee":    float(gate_fee)    if gate_fee    else None,
        "company_pct": float(company_pct) if company_pct else None,
    })
    return RedirectResponse("/", status_code=303)

# ── pickups ──────────────────────────────────────────────────────

@app.get("/api/pickups")
async def get_pickups(date: Optional[str] = None):
    pickups = _read(PICKUPS_F)
    if date: pickups = [p for p in pickups if p.get("pickup_date") == date]
    return sorted(pickups, key=lambda p: p.get("pickup_time",""))

@app.post("/api/pickups")
async def create_pickup(request: Request):
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
    pickups = _read(PICKUPS_F); pickups.append(record); _write(PICKUPS_F, pickups)
    upsert_customer(record["customer_name"], record["street_address"], record["city"], record["phone_number"])
    return record

@app.get("/api/pickups/{pid}")
async def get_pickup(pid: str):
    rec = next((p for p in _read(PICKUPS_F) if p["id"] == pid), None)
    if not rec: raise HTTPException(404, "Not found")
    return rec

@app.put("/api/pickups/{pid}")
async def update_pickup(pid: str, request: Request):
    body = await request.json(); pickups = _read(PICKUPS_F)
    idx = next((i for i,p in enumerate(pickups) if p["id"] == pid), None)
    if idx is None: raise HTTPException(404, "Not found")
    rec = pickups[idx]
    for k in ["pickup_date","pickup_time","street_address","city","customer_name",
              "phone_number","destination_address","meter_total","payment_method","tip","tip_payment_method"]:
        if k in body: rec[k] = body[k]
    rec["meter_total"]       = float(rec.get("meter_total") or 0)
    rec["tip"]               = float(rec.get("tip") or 0)
    rec["calculated_total"]  = calc_total(rec["meter_total"], rec["tip"])
    pickups[idx] = rec; _write(PICKUPS_F, pickups)
    upsert_customer(rec["customer_name"], rec["street_address"], rec["city"], rec["phone_number"])
    return rec

@app.delete("/api/pickups/{pid}")
async def delete_pickup(pid: str):
    pickups = _read(PICKUPS_F)
    if not any(p["id"] == pid for p in pickups): raise HTTPException(404, "Not found")
    _write(PICKUPS_F, [p for p in pickups if p["id"] != pid]); return {"ok": True}

@app.delete("/api/pickups")
async def delete_all():
    _write(PICKUPS_F, []); _write(CUSTOMERS_F, []); return {"ok": True}

# ── expenses ─────────────────────────────────────────────────────

@app.get("/api/expenses")
async def get_expenses(date: Optional[str] = None):
    expenses = _read(EXPENSES_F)
    if date: expenses = [e for e in expenses if e.get("date") == date]
    return sorted(expenses, key=lambda e: e.get("date",""))

@app.post("/api/expenses")
async def create_expense(request: Request):
    body = await request.json()
    record = {
        "id": str(uuid.uuid4()),
        "date": body.get("date",""),
        "category": body.get("category",""),
        "amount": float(body.get("amount") or 0),
        "notes": body.get("notes",""),
        "created_at": datetime.utcnow().isoformat(),
    }
    expenses = _read(EXPENSES_F); expenses.append(record); _write(EXPENSES_F, expenses)
    return record

@app.delete("/api/expenses/{eid}")
async def delete_expense(eid: str):
    expenses = _read(EXPENSES_F)
    if not any(e["id"] == eid for e in expenses): raise HTTPException(404, "Not found")
    _write(EXPENSES_F, [e for e in expenses if e["id"] != eid]); return {"ok": True}

# ── shifts ───────────────────────────────────────────────────────

@app.get("/api/shifts")
async def get_shifts(date: Optional[str] = None):
    shifts = _read(SHIFTS_F)
    if date: shifts = [s for s in shifts if s.get("date") == date]
    return shifts

@app.post("/api/shifts")
async def save_shift(request: Request):
    body   = await request.json()
    shifts = _read(SHIFTS_F)
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
        _write(SHIFTS_F, shifts)
        return existing
    record = {
        "id": str(uuid.uuid4()), "date": d,
        "start_time":    body.get("start_time",""),
        "end_time":      body.get("end_time",""),
        "odometer_start": odo_start, "odometer_end": odo_end, "miles": miles,
        "notes":          body.get("notes",""),
        "created_at":     datetime.utcnow().isoformat(),
    }
    shifts.append(record); _write(SHIFTS_F, shifts)
    return record

# ── daily totals (server-side, payment-mode aware) ───────────────

@app.get("/api/daily-totals")
async def daily_totals_api(date: Optional[str] = None):
    profile  = _read_profile()
    pickups  = _read(PICKUPS_F)
    expenses = _read(EXPENSES_F)
    if date:
        pickups  = [p for p in pickups  if p.get("pickup_date") == date]
        expenses = [e for e in expenses if e.get("date")        == date]
    totals = day_totals(pickups, profile)
    exp_total = round(sum(e["amount"] for e in expenses), 2)
    totals["expense_total"] = exp_total
    totals["net_earnings"]  = round(totals["owed_driver"] - exp_total, 2)
    totals["pay_mode"]      = profile.get("pay_mode", "standard")
    return totals

# ── report ───────────────────────────────────────────────────────

@app.get("/api/report")
async def report(from_date: str = "", to_date: str = ""):
    profile      = _read_profile()
    pickups      = _read(PICKUPS_F)
    expenses_all = _read(EXPENSES_F)
    shifts_all   = _read(SHIFTS_F)

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
        totals["expense_total"] = exp_total
        totals["net_earnings"]  = round(totals["owed_driver"] - exp_total, 2)
        days.append({"date": d, "pickups": day_p, "expenses": day_e,
                     "shift": shift_map.get(d), "totals": totals})

    summary = day_totals(pickups, profile)
    total_exp = round(sum(e["amount"] for e in expenses_all), 2)
    summary["expense_total"] = total_exp
    summary["net_earnings"]  = round(summary["owed_driver"] - total_exp, 2)
    summary["pay_mode"]      = profile.get("pay_mode", "standard")
    return {"days": days, "summary": summary}

# ── CSV export ───────────────────────────────────────────────────

@app.get("/api/report/csv")
async def report_csv(from_date: str = "", to_date: str = ""):
    pickups = _read(PICKUPS_F)
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
async def report_pdf(from_date: str = "", to_date: str = ""):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib import colors

    profile  = _read_profile()
    driver   = profile.get("driver_name", "Unknown Driver")
    pay_mode = profile.get("pay_mode", "standard")
    mode_labels = {"standard":"Standard Split","gate":"Flat Gate Fee",
                   "commission":"Commission Split","owner":"Owner-Operator"}

    pickups      = _read(PICKUPS_F)
    expenses_all = _read(EXPENSES_F)
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

    grand_totals = {"meter":0,"tips":0,"gross":0,"expenses":0,"owed":0,"net":0,"count":0}

    for d in all_dates:
        day_p = sorted(pickup_map.get(d, []), key=lambda x: x.get("pickup_time",""))
        day_e = expense_map.get(d, [])
        totals= day_totals(day_p, profile)
        exp_total = round(sum(e["amount"] for e in day_e), 2)
        net = round(totals["owed_driver"] - exp_total, 2)

        story.append(Paragraph(f"{d}  —  {totals['count']} pickups  |  Gross: ${totals['grand_total']:.2f}  |  Owed: ${totals['owed_driver']:.2f}  |  Net: ${net:.2f}", h2))

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
        grand_totals["meter"]    += totals["meter_cash"]+totals["meter_credit"]+totals["meter_voucher"]
        grand_totals["tips"]     += totals["tip_cash"]+totals["tip_credit"]+totals["tip_voucher"]
        grand_totals["gross"]    += totals["grand_total"]
        grand_totals["expenses"] += exp_total
        grand_totals["owed"]     += totals["owed_driver"]
        grand_totals["net"]      += net
        grand_totals["count"]    += totals["count"]

    story.append(HRFlowable(width="100%", color=amber, thickness=2, spaceAfter=6))
    story.append(Paragraph("Summary", h2))
    sum_data = [
        ["Total Pickups", str(grand_totals["count"])],
        ["Total Meter",   f"${grand_totals['meter']:.2f}"],
        ["Total Tips",    f"${grand_totals['tips']:.2f}"],
        ["Gross Revenue", f"${grand_totals['gross']:.2f}"],
        ["Total Expenses",f"${grand_totals['expenses']:.2f}"],
        ["Total Owed Driver", f"${grand_totals['owed']:.2f}"],
        ["Net Earnings",  f"${grand_totals['net']:.2f}"],
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
async def suggest(q: str = ""):
    if not q or len(q) < 2: return []
    q_low = q.lower(); customers = _read(CUSTOMERS_F)
    return [c for c in customers if q_low in c.get("name","").lower()
            or q_low in c.get("street_address","").lower()
            or q_low in c.get("phone","").lower()][:10]

@app.get("/api/customers/lookup")
async def lookup(phone: str = "", address: str = ""):
    customers = _read(CUSTOMERS_F)
    if phone:
        c = next((x for x in customers if x.get("phone") == phone), None)
        if c: return c
    if address:
        c = next((x for x in customers if x.get("street_address","").lower() == address.lower()), None)
        if c: return c
    return {}

# ── backup / restore ─────────────────────────────────────────────

@app.get("/api/backup/pickups")
async def backup_pickups():
    if not PICKUPS_F.exists(): _write(PICKUPS_F, [])
    return FileResponse(PICKUPS_F, filename=f"pickups_{date.today().isoformat()}.json", media_type="application/json")

@app.get("/api/backup/customers")
async def backup_customers():
    if not CUSTOMERS_F.exists(): _write(CUSTOMERS_F, [])
    return FileResponse(CUSTOMERS_F, filename=f"customers_{date.today().isoformat()}.json", media_type="application/json")

@app.get("/api/backup/expenses")
async def backup_expenses():
    if not EXPENSES_F.exists(): _write(EXPENSES_F, [])
    return FileResponse(EXPENSES_F, filename=f"expenses_{date.today().isoformat()}.json", media_type="application/json")

@app.get("/api/backup/shifts")
async def backup_shifts():
    if not SHIFTS_F.exists(): _write(SHIFTS_F, [])
    return FileResponse(SHIFTS_F, filename=f"shifts_{date.today().isoformat()}.json", media_type="application/json")

@app.get("/api/backup/profile")
async def backup_profile():
    if not PROFILE_F.exists(): _write(PROFILE_F, {})
    return FileResponse(PROFILE_F, filename=f"profile_{date.today().isoformat()}.json", media_type="application/json")

@app.get("/api/backup/all")
async def backup_all():
    import zipfile as zf_mod
    files = [
        (PICKUPS_F,   "pickups.json",   "[]"),
        (CUSTOMERS_F, "customers.json", "[]"),
        (EXPENSES_F,  "expenses.json",  "[]"),
        (SHIFTS_F,    "shifts.json",    "[]"),
        (PROFILE_F,   "profile.json",   "{}"),
    ]
    buf = io.BytesIO()
    with zf_mod.ZipFile(buf, 'w', zf_mod.ZIP_DEFLATED) as zf:
        for path, name, default in files:
            if _GCS_BUCKET:
                try:
                    blob = _gcs_client().bucket(_GCS_BUCKET).blob(path.name)
                    content = blob.download_as_text() if blob.exists() else default
                except Exception:
                    content = default
            else:
                content = path.read_text() if path.exists() else default
            zf.writestr(name, content)
    buf.seek(0)
    fname = f"taxilog_backup_{date.today().isoformat()}.zip"
    return StreamingResponse(buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={fname}"})

async def _restore(file: UploadFile, path: Path, expect_list: bool):
    try: data = json.loads(await file.read())
    except Exception: raise HTTPException(400, "Invalid JSON file")
    if expect_list and not isinstance(data, list): raise HTTPException(400, "Expected a JSON array")
    if not expect_list and not isinstance(data, dict): raise HTTPException(400, "Expected a JSON object")
    _write(path, data); return {"ok": True}

@app.post("/api/restore/pickups")
async def restore_pickups(file: UploadFile = File(...)): return await _restore(file, PICKUPS_F, True)

@app.post("/api/restore/customers")
async def restore_customers(file: UploadFile = File(...)): return await _restore(file, CUSTOMERS_F, True)

@app.post("/api/restore/expenses")
async def restore_expenses(file: UploadFile = File(...)): return await _restore(file, EXPENSES_F, True)

@app.post("/api/restore/shifts")
async def restore_shifts(file: UploadFile = File(...)): return await _restore(file, SHIFTS_F, True)

@app.post("/api/restore/profile")
async def restore_profile(file: UploadFile = File(...)): return await _restore(file, PROFILE_F, False)

@app.post("/api/restore/all")
async def restore_all(file: UploadFile = File(...)):
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
                    _write(path, parsed)
                    restored.append(name)
    except zf_mod.BadZipFile:
        raise HTTPException(400, "Invalid ZIP file")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON in backup file")
    return {"ok": True, "restored": restored}

# ── requirements PDF (unchanged) ─────────────────────────────────

@app.get("/api/requirements-pdf")
async def requirements_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib import colors
    profile = _read_profile(); driver = profile.get("driver_name", "Unknown Driver")
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

# ── entry point ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    reload = not _GCS_BUCKET  # no reload in production
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload)
