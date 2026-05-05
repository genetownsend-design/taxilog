# ════════════════════════════════════════════════════════════════
# CHUNK 1 of 5  —  paste into a NEW empty file called main.py
#                  then paste chunks 2-5 immediately after
# ════════════════════════════════════════════════════════════════
import uuid
import json
import os
from datetime import datetime, date, timedelta
from typing import Optional, List
from pathlib import Path

from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import aiofiles

# ── paths ───────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
PICKUPS_F   = DATA_DIR / "pickups.json"
CUSTOMERS_F = DATA_DIR / "customers.json"
PROFILE_F   = DATA_DIR / "profile.json"

DATA_DIR.mkdir(exist_ok=True)
(BASE_DIR / "static" / "css").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "static" / "js").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "templates").mkdir(exist_ok=True)

# ── embedded HTML templates ─────────────────────────────────────
BASE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Taxi Log{% endblock %}</title>
  <link rel="stylesheet" href="/static/css/style.css">
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
    <nav class="site-nav">
      <a href="/" class="nav-link {% if request.url.path == '/' %}active{% endif %}">📋 Log</a>
      <a href="#" onclick="openModal('reportModal')" class="nav-link">📊 Report</a>
      <a href="#" onclick="openModal('backupModal')" class="nav-link">💾 Backup</a>
      <a href="/setup" class="nav-link {% if request.url.path == '/setup' %}active{% endif %}">⚙️ Setup</a>
    </nav>
    {% endif %}
  </div>
</header>
<main class="site-main">{% block content %}{% endblock %}</main>

<div id="reportModal" class="modal-overlay" style="display:none">
  <div class="modal-box modal-wide">
    <div class="modal-header">
      <h2>📊 Daily Report</h2>
      <button class="modal-close" onclick="closeModal('reportModal')">✕</button>
    </div>
    <div class="modal-body">
      <div class="row-2 mb-4">
        <div class="field-group"><label class="field-label">From Date</label><input type="date" id="rptFrom" class="field-input"></div>
        <div class="field-group"><label class="field-label">To Date</label><input type="date" id="rptTo" class="field-input"></div>
      </div>
      <button class="btn btn-primary" onclick="generateReport()">Generate Report</button>
      <div id="reportOutput" class="report-output mt-4"></div>
    </div>
  </div>
</div>

<div id="backupModal" class="modal-overlay" style="display:none">
  <div class="modal-box">
    <div class="modal-header">
      <h2>💾 Backup &amp; Restore</h2>
      <button class="modal-close" onclick="closeModal('backupModal')">✕</button>
    </div>
    <div class="modal-body">
      <div class="section-label">Download Backup</div>
      <div class="btn-group mb-4">
        <a href="/api/backup/pickups" class="btn btn-secondary btn-sm" download>⬇ Pickups</a>
        <a href="/api/backup/customers" class="btn btn-secondary btn-sm" download>⬇ Customers</a>
        <a href="/api/backup/profile" class="btn btn-secondary btn-sm" download>⬇ Profile</a>
        <a href="/api/requirements-pdf" class="btn btn-secondary btn-sm" download>⬇ Requirements PDF</a>
      </div>
      <div class="section-label">Restore from Backup</div>
      <div class="warning-text">⚠️ Restore overwrites existing data and cannot be undone.</div>
      <div class="restore-row"><span class="restore-label">Pickups</span><input type="file" id="restorePickups" accept=".json"><button class="btn btn-sm btn-warning" onclick="restoreFile('pickups')">Restore</button></div>
      <div class="restore-row"><span class="restore-label">Customers</span><input type="file" id="restoreCustomers" accept=".json"><button class="btn btn-sm btn-warning" onclick="restoreFile('customers')">Restore</button></div>
      <div class="restore-row"><span class="restore-label">Profile</span><input type="file" id="restoreProfile" accept=".json"><button class="btn btn-sm btn-warning" onclick="restoreFile('profile')">Restore</button></div>
      <hr class="divider">
      <div class="section-label danger-label">Danger Zone</div>
      <button class="btn btn-danger" onclick="deleteAll()">🗑 Delete ALL Pickups &amp; Customers</button>
    </div>
  </div>
</div>

<div id="editModal" class="modal-overlay" style="display:none">
  <div class="modal-box modal-wide">
    <div class="modal-header">
      <h2>✏️ Edit Pickup</h2>
      <button class="modal-close" onclick="closeModal('editModal')">✕</button>
    </div>
    <div class="modal-body" id="editModalBody"></div>
  </div>
</div>

<div id="toast" class="toast" style="display:none"></div>
<script src="/static/js/app.js"></script>
{% block extra_js %}{% endblock %}
</body>
</html>
"""
# ════════════════════════════════════════════════════════════════
# CHUNK 2 of 5  —  paste immediately after chunk 1
# ════════════════════════════════════════════════════════════════

INDEX_HTML = """\
{% extends "base.html" %}
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
          <input type="time" id="pickup_time" name="pickup_time" class="field-input" required>
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
          <span class="owed-driver-label">Owed Driver</span>
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
    document.getElementById('pickup_time').value =
      String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
  })();
  loadDailyLog();
</script>
{% endblock %}
"""

SETUP_HTML = """\
{% extends "base.html" %}
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
      <button type="submit" class="btn btn-primary btn-full mt-4">Save Profile &amp; Continue →</button>
    </form>
  </div>
</div>
{% endblock %}
"""
# ════════════════════════════════════════════════════════════════
# CHUNK 3 of 5  —  paste immediately after chunk 2
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
.site-nav{display:flex;gap:2px}
.nav-link{color:rgba(255,255,255,.6);text-decoration:none;padding:6px 14px;border-radius:var(--radius-sm);font-size:13px;font-weight:500;transition:all .15s;display:flex;align-items:center;gap:5px}
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
.modal-wide{max-width:860px}
.modal-header{display:flex;justify-content:space-between;align-items:center;padding:18px 22px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--surface);z-index:1}
.modal-header h2{font-size:16px;font-weight:700}
.modal-close{background:var(--surface2);border:none;cursor:pointer;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;color:var(--text2);transition:all .15s}
.modal-close:hover{background:var(--border);color:var(--text)}
.modal-body{padding:22px}
.report-output{font-size:13px}
.report-day{margin-bottom:20px;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden}
.report-day-hdr{background:var(--text);color:#fff;padding:10px 14px;display:flex;justify-content:space-between;align-items:center}
.report-table{width:100%;border-collapse:collapse}
.report-table th{background:var(--amber-lt);padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--amber-dd);border-bottom:1px solid var(--border)}
.report-table td{padding:8px 12px;border-bottom:1px solid var(--border);font-size:13px}
.report-table tr:last-child td{border-bottom:none}
.report-table tr:hover td{background:var(--surface2)}
.report-day-foot{background:var(--surface2);padding:10px 14px;display:flex;flex-wrap:wrap;gap:14px;font-size:12px;border-top:1px solid var(--border)}
.report-summary{background:var(--text);color:#fff;border-radius:var(--radius);padding:18px;margin-top:16px}
.report-summary h3{color:var(--amber);margin-bottom:14px;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.07em}
.summary-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px}
.summary-item{background:rgba(255,255,255,.06);border-radius:var(--radius-sm);padding:10px 12px}
.summary-label{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:rgba(255,255,255,.4);margin-bottom:3px}
.summary-val{font-size:17px;font-weight:700;color:#fff;letter-spacing:-.3px}
.summary-owed{color:var(--amber)}
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
.setup-card{background:var(--surface);border-radius:var(--radius-xl);box-shadow:var(--shadow-lg);padding:40px;width:100%;max-width:440px;border:1px solid var(--border)}
.setup-icon{font-size:44px;text-align:center;margin-bottom:16px}
.setup-title{font-size:24px;font-weight:800;text-align:center;color:var(--text);margin-bottom:4px;letter-spacing:-.5px}
.setup-sub{text-align:center;color:var(--text3);margin-bottom:28px;font-size:14px}
.setup-form .field-group{margin-bottom:16px}
"""
# ════════════════════════════════════════════════════════════════
# CHUNK 4 of 5  —  paste immediately after chunk 3
# ════════════════════════════════════════════════════════════════

JS = '/* app.js */\nfunction fmt(v){return\'$\'+(parseFloat(v)||0).toFixed(2)}\n\nfunction showToast(msg,d=2500){\n  const t=document.getElementById(\'toast\');\n  t.textContent=msg;t.style.display=\'block\';\n  clearTimeout(t._t);t._t=setTimeout(()=>t.style.display=\'none\',d);\n}\nfunction openModal(id){document.getElementById(id).style.display=\'flex\'}\nfunction closeModal(id){document.getElementById(id).style.display=\'none\'}\ndocument.querySelectorAll(\'.modal-overlay\').forEach(el=>{\n  el.addEventListener(\'click\',e=>{if(e.target===el)el.style.display=\'none\'});\n});\n\nfunction updateCalcTotal(){\n  const m=parseFloat(document.getElementById(\'meter_total\')?.value)||0;\n  const t=parseFloat(document.getElementById(\'tip\')?.value)||0;\n  const el=document.getElementById(\'calcTotal\');\n  if(el)el.textContent=fmt(m+t);\n}\n\n/* --- Autocomplete --- */\nlet acTimer=null;\nfunction suggestCustomers(input,field){\n  clearTimeout(acTimer);\n  const q=input.value.trim();\n  const listId=field===\'phone\'?\'ac-phone\':field===\'address\'?\'ac-address\':\'ac-name\';\n  if(q.length<2){clearAC();return}\n  acTimer=setTimeout(async()=>{\n    const r=await fetch(\'/api/customers/suggest?q=\'+encodeURIComponent(q));\n    renderAC(listId,await r.json());\n  },200);\n}\nfunction renderAC(listId,customers){\n  clearAC();\n  if(!customers.length)return;\n  const list=document.getElementById(listId);\n  customers.forEach(c=>{\n    const d=document.createElement(\'div\');\n    d.className=\'ac-item\';\n    d.innerHTML=\'<div class="ac-name">\'+(c.name||\'—\')+\'</div>\'\n      +\'<div class="ac-detail">\'+(c.street_address||\'\')+\' \'+(c.city||\'\')+(c.phone?\' · \'+c.phone:\'\')+\'</div>\';\n    d.onclick=()=>{fillFromCustomer(c);clearAC()};\n    list.appendChild(d);\n  });\n}\nfunction clearAC(){\n  [\'ac-phone\',\'ac-address\',\'ac-name\'].forEach(id=>{\n    const el=document.getElementById(id);if(el)el.innerHTML=\'\';\n  });\n}\nfunction fillFromCustomer(c){\n  if(c.name)setValue(\'customer_name\',c.name);\n  if(c.street_address)setValue(\'street_address\',c.street_address);\n  if(c.city)setValue(\'city\',c.city);\n  if(c.phone)setValue(\'phone_number\',c.phone);\n}\nfunction setValue(id,val){const el=document.getElementById(id);if(el)el.value=val}\nasync function lookupByPhone(){\n  const phone=document.getElementById(\'phone_number\')?.value.trim();\n  if(!phone)return;\n  const c=await(await fetch(\'/api/customers/lookup?phone=\'+encodeURIComponent(phone))).json();\n  if(c&&c.name)fillFromCustomer(c);\n}\ndocument.addEventListener(\'click\',e=>{if(!e.target.closest(\'.autocomplete-wrap\'))clearAC()});\n\n/* --- Pickup form --- */\nasync function submitPickup(e){\n  e.preventDefault();\n  const f=e.target;\n  const data={\n    pickup_date:f.pickup_date.value,pickup_time:f.pickup_time.value,\n    street_address:f.street_address.value,city:f.city.value,\n    customer_name:f.customer_name.value,phone_number:f.phone_number.value,\n    destination_address:f.destination_address.value,\n    meter_total:f.meter_total.value,payment_method:f.payment_method.value,\n    tip:f.tip.value,tip_payment_method:f.tip_payment_method.value,\n  };\n  const r=await fetch(\'/api/pickups\',{method:\'POST\',\n    headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify(data)});\n  if(r.ok){\n    showToast(\'Pickup recorded!\');\n    resetForm();\n    const ld=document.getElementById(\'logDate\');\n    if(ld&&data.pickup_date)ld.value=data.pickup_date;\n    loadDailyLog();\n  }else showToast(\'Error saving pickup\');\n}\nfunction resetForm(){\n  const f=document.getElementById(\'pickupForm\');if(!f)return;\n  [\'street_address\',\'city\',\'customer_name\',\'phone_number\',\'destination_address\',\'meter_total\',\'tip\']\n    .forEach(id=>setValue(id,\'\'));\n  [\'payment_method\',\'tip_payment_method\'].forEach(id=>setValue(id,\'\'));\n  updateCalcTotal();clearAC();\n}\n\n/* --- Daily log --- */\nasync function loadDailyLog(){\n  const el=document.getElementById(\'logDate\');if(!el)return;\n  const pickups=await(await fetch(\'/api/pickups?date=\'+el.value)).json();\n  renderLog(pickups);\n}\n\nfunction pmBadge(pm){\n  if(!pm)return\'\';\n  const cls={\'cash\':\'pm-cash\',\'credit\':\'pm-credit\',\'voucher\':\'pm-voucher\'}[pm.toLowerCase()]||\'pm-none\';\n  return\'<span class="pm-badge \'+cls+\'">\'+pm+\'</span>\';\n}\n\nfunction renderLog(pickups){\n  const list=document.getElementById(\'logList\');\n  const tp=document.getElementById(\'dailyTotals\');\n  if(!list)return;\n  if(!pickups.length){\n    list.innerHTML=\'<p class="empty-msg">No pickups recorded for this date.</p>\';\n    if(tp)tp.style.display=\'none\';\n    return;\n  }\n  list.innerHTML=pickups.map(p=>{\n    const tipHtml=p.tip>0?\'<span class="pickup-meta-item">Tip: \'+fmt(p.tip)+\' \'+pmBadge(p.tip_payment_method)+\'</span>\':\'\';\n    const custHtml=(p.customer_name?\'<span class="pickup-meta-item">\'+p.customer_name+\'</span>\':\'\');\n    const phoneHtml=(p.phone_number?\'<span class="pickup-meta-item">\'+p.phone_number+\'</span>\':\'\');\n    const noInfo=(!p.customer_name&&!p.phone_number&&!p.tip)?\'<span style="color:var(--text3);font-style:italic">No customer info</span>\':\'\';\n    return\'<div class="pickup-card" data-id="\'+p.id+\'">\'\n      +\'<div class="pickup-card-head">\'\n        +\'<span class="pickup-time">\'+(p.pickup_time||\'--:--\')+\'</span>\'\n        +\'<div class="pickup-total-wrap">\'\n          +\'<span class="pickup-total">\'+fmt(p.calculated_total)+\'</span>\'\n          +pmBadge(p.payment_method)\n        +\'</div>\'\n      +\'</div>\'\n      +\'<div class="pickup-card-body">\'\n        +\'<div class="pickup-route">\'\n          +\'<strong>\'+p.street_address+(p.city?\', \'+p.city:\'\')+\'</strong>\'\n          +\' <span style="color:var(--text3)">→</span> \'\n          +p.destination_address\n        +\'</div>\'\n        +\'<div class="pickup-meta">\'+custHtml+phoneHtml+tipHtml+noInfo+\'</div>\'\n      +\'</div>\'\n      +\'<div class="pickup-card-foot">\'\n        +\'<button class="btn btn-sm btn-ghost" data-action="edit" data-id="\'+p.id+\'">Edit</button>\'\n        +\'<button class="btn btn-sm btn-danger" data-action="delete" data-id="\'+p.id+\'">Delete</button>\'\n      +\'</div>\'\n    +\'</div>\';\n  }).join(\'\');\n  renderTotals(pickups);\n}\n\n/* Event delegation for edit/delete buttons */\ndocument.addEventListener(\'click\',e=>{\n  const btn=e.target.closest(\'[data-action]\');\n  if(!btn)return;\n  const id=btn.dataset.id;\n  if(btn.dataset.action===\'edit\')openEdit(id);\n  if(btn.dataset.action===\'delete\')deletePickup(id);\n});\n\nfunction renderTotals(pickups){\n  const tp=document.getElementById(\'dailyTotals\');\n  const grid=document.getElementById(\'totalsGrid\');\n  const owedEl=document.getElementById(\'owedDriverVal\');\n  if(!tp)return;\n  let mCa=0,mCr=0,mV=0,tCa=0,tCr=0,tV=0,grand=0;\n  pickups.forEach(p=>{\n    const pm=(p.payment_method||\'\').toLowerCase();\n    const tpm=(p.tip_payment_method||\'\').toLowerCase();\n    const m=parseFloat(p.meter_total)||0;\n    const t=parseFloat(p.tip)||0;\n    if(pm===\'cash\')mCa+=m; else if(pm===\'credit\')mCr+=m; else if(pm===\'voucher\')mV+=m;\n    if(tpm===\'cash\')tCa+=t; else if(tpm===\'credit\')tCr+=t; else if(tpm===\'voucher\')tV+=t;\n    grand+=parseFloat(p.calculated_total)||0;\n  });\n  const owedAmt=((mCr+mV)-mCa)/2+tCr+tV;\n  if(grid)grid.innerHTML=[\n    [\'Cash Meter\',fmt(mCa)],[\'Credit Meter\',fmt(mCr)],[\'Voucher Meter\',fmt(mV)],\n    [\'Cash Tips\',fmt(tCa)],[\'Credit Tips\',fmt(tCr)],[\'Voucher Tips\',fmt(tV)],\n    [\'Grand Total\',fmt(grand)],[\'Pickups\',pickups.length],\n  ].map(([l,v])=>\'<div class="total-cell"><div class="total-cell-label">\'+l+\'</div><div class="total-cell-val">\'+v+\'</div></div>\').join(\'\');\n  if(owedEl)owedEl.textContent=fmt(owedAmt);\n  tp.style.display=\'block\';\n}\n\n/* --- Edit modal --- */\nasync function openEdit(id){\n  const p=await(await fetch(\'/api/pickups/\'+id)).json();\n  const body=document.getElementById(\'editModalBody\');\n  const pmOpts=[\'\',\'Cash\',\'Credit\',\'Voucher\'].map(v=>\'<option\'+(p.payment_method===v?\' selected\':\'\')+\'>\'+v+\'</option>\').join(\'\');\n  const tpmOpts=[\'\',\'Cash\',\'Credit\',\'Voucher\'].map(v=>\'<option\'+(p.tip_payment_method===v?\' selected\':\'\')+\'>\'+v+\'</option>\').join(\'\');\n  body.innerHTML=\n    \'<div class="row-2">\'\n      +\'<div class="field-group"><label class="field-label">Date</label><input type="date" id="e_date" class="field-input" value="\'+p.pickup_date+\'"></div>\'\n      +\'<div class="field-group"><label class="field-label">Time</label><input type="time" id="e_time" class="field-input" value="\'+p.pickup_time+\'"></div>\'\n    +\'</div>\'\n    +\'<div class="field-group"><label class="field-label">Street Address</label><input type="text" id="e_street" class="field-input" value="\'+p.street_address+\'"></div>\'\n    +\'<div class="row-2">\'\n      +\'<div class="field-group"><label class="field-label">City</label><input type="text" id="e_city" class="field-input" value="\'+(p.city||\'\')+\'"></div>\'\n      +\'<div class="field-group"><label class="field-label">Phone</label><input type="text" id="e_phone" class="field-input" value="\'+(p.phone_number||\'\')+\'"></div>\'\n    +\'</div>\'\n    +\'<div class="field-group"><label class="field-label">Customer Name</label><input type="text" id="e_name" class="field-input" value="\'+(p.customer_name||\'\')+\'"></div>\'\n    +\'<div class="field-group"><label class="field-label">Destination</label><input type="text" id="e_dest" class="field-input" value="\'+p.destination_address+\'"></div>\'\n    +\'<div class="row-2">\'\n      +\'<div class="field-group"><label class="field-label">Meter ($)</label><input type="number" id="e_meter" class="field-input" step="0.01" value="\'+(p.meter_total||0)+\'" oninput="eCalc()"></div>\'\n      +\'<div class="field-group"><label class="field-label">Payment</label><select id="e_pm" class="field-input">\'+pmOpts+\'</select></div>\'\n    +\'</div>\'\n    +\'<div class="row-2">\'\n      +\'<div class="field-group"><label class="field-label">Tip ($)</label><input type="number" id="e_tip" class="field-input" step="0.01" value="\'+(p.tip||0)+\'" oninput="eCalc()"></div>\'\n      +\'<div class="field-group"><label class="field-label">Tip Payment</label><select id="e_tpm" class="field-input">\'+tpmOpts+\'</select></div>\'\n    +\'</div>\'\n    +\'<div class="calc-total-bar"><span class="calc-total-label">Calculated Total</span><span id="e_calc" class="calc-total-value">\'+fmt(p.calculated_total)+\'</span></div>\'\n    +\'<div class="btn-group mt-2">\'\n      +\'<button class="btn btn-primary" data-action="save-edit" data-id="\'+id+\'">Save Changes</button>\'\n      +\'<button class="btn btn-ghost" onclick="closeModal(\\\'editModal\\\')">Cancel</button>\'\n    +\'</div>\';\n  openModal(\'editModal\');\n}\nfunction eCalc(){\n  const m=parseFloat(document.getElementById(\'e_meter\')?.value)||0;\n  const t=parseFloat(document.getElementById(\'e_tip\')?.value)||0;\n  const el=document.getElementById(\'e_calc\');if(el)el.textContent=fmt(m+t);\n}\ndocument.addEventListener(\'click\',async e=>{\n  const btn=e.target.closest(\'[data-action="save-edit"]\');\n  if(!btn)return;\n  const id=btn.dataset.id;\n  const data={\n    pickup_date:document.getElementById(\'e_date\').value,\n    pickup_time:document.getElementById(\'e_time\').value,\n    street_address:document.getElementById(\'e_street\').value,\n    city:document.getElementById(\'e_city\').value,\n    customer_name:document.getElementById(\'e_name\').value,\n    phone_number:document.getElementById(\'e_phone\').value,\n    destination_address:document.getElementById(\'e_dest\').value,\n    meter_total:document.getElementById(\'e_meter\').value,\n    payment_method:document.getElementById(\'e_pm\').value,\n    tip:document.getElementById(\'e_tip\').value,\n    tip_payment_method:document.getElementById(\'e_tpm\').value,\n  };\n  const r=await fetch(\'/api/pickups/\'+id,{method:\'PUT\',\n    headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify(data)});\n  if(r.ok){closeModal(\'editModal\');showToast(\'Record updated!\');loadDailyLog();}\n  else showToast(\'Error updating record\');\n});\n\nasync function deletePickup(id){\n  if(!confirm(\'Delete this pickup record?\'))return;\n  const r=await fetch(\'/api/pickups/\'+id,{method:\'DELETE\'});\n  if(r.ok){showToast(\'Pickup deleted\');loadDailyLog();}\n  else showToast(\'Error deleting record\');\n}\n\n/* --- Delete all --- */\nasync function deleteAll(){\n  if(!confirm(\'Delete ALL pickups and customers?\\nDriver profile will NOT be deleted.\'))return;\n  const r=await fetch(\'/api/pickups\',{method:\'DELETE\'});\n  if(r.ok){showToast(\'All pickups and customers deleted\');closeModal(\'backupModal\');loadDailyLog();}\n  else showToast(\'Error during deletion\');\n}\n\n/* --- Report --- */\nasync function generateReport(){\n  const from=document.getElementById(\'rptFrom\').value;\n  const to=document.getElementById(\'rptTo\').value;\n  let url=\'/api/report\';\n  const p=[];\n  if(from)p.push(\'from_date=\'+from);\n  if(to)p.push(\'to_date=\'+to);\n  if(p.length)url+=\'?\'+p.join(\'&\');\n  renderReport(await(await fetch(url)).json());\n}\nfunction renderReport(data){\n  const out=document.getElementById(\'reportOutput\');\n  if(!data.days.length){out.innerHTML=\'<p class="empty-msg">No pickups found.</p>\';return}\n  const dayBlocks=data.days.map(day=>{\n    const rows=day.pickups.map(p=>\n      \'<tr><td>\'+(p.pickup_time||\'\')+\'</td>\'\n      +\'<td>\'+p.street_address+(p.city?\', \'+p.city:\'\')+\'</td>\'\n      +\'<td>\'+p.destination_address+\'</td>\'\n      +\'<td>\'+(p.customer_name||\'—\')+\'</td>\'\n      +\'<td>\'+fmt(p.meter_total)+\'</td>\'\n      +\'<td>\'+(p.payment_method||\'—\')+\'</td>\'\n      +\'<td>\'+fmt(p.tip)+\'</td>\'\n      +\'<td>\'+fmt(p.calculated_total)+\'</td></tr>\'\n    ).join(\'\');\n    const t=day.totals;\n    return\'<div class="report-day">\'\n      +\'<div class="report-day-hdr"><span style="font-weight:700">\'+day.date+\'</span>\'\n        +\'<span style="font-size:12px;color:rgba(255,255,255,.5)">\'+t.count+\' pickups &nbsp; \'+fmt(t.grand_total)+\'</span></div>\'\n      +\'<table class="report-table"><thead><tr>\'\n        +\'<th>Time</th><th>From</th><th>To</th><th>Customer</th>\'\n        +\'<th>Meter</th><th>Pay</th><th>Tip</th><th>Total</th>\'\n      +\'</tr></thead><tbody>\'+rows+\'</tbody></table>\'\n      +\'<div class="report-day-foot">\'\n        +\'<span>Cash: \'+fmt(t.meter_cash)+\'</span>\'\n        +\'<span>Credit: \'+fmt(t.meter_credit)+\'</span>\'\n        +\'<span>Voucher: \'+fmt(t.meter_voucher)+\'</span>\'\n        +\'<span>Tips: \'+fmt(t.tip_cash+t.tip_credit+t.tip_voucher)+\'</span>\'\n        +\'<strong>Owed Driver: \'+fmt(t.owed_driver)+\'</strong>\'\n      +\'</div>\'\n    +\'</div>\';\n  }).join(\'\');\n  const s=data.summary;\n  out.innerHTML=dayBlocks\n    +\'<div class="report-summary"><h3>Summary</h3><div class="summary-grid">\'\n    +[[\'Pickups\',s.count],[\'Cash\',fmt(s.meter_cash)],[\'Credit\',fmt(s.meter_credit)],\n      [\'Voucher\',fmt(s.meter_voucher)],[\'Credit Tips\',fmt(s.tip_credit)],\n      [\'Voucher Tips\',fmt(s.tip_voucher)],[\'Grand Total\',fmt(s.grand_total)],\n      [\'Total Owed\',fmt(s.owed_driver)]]\n    .map(([l,v],i)=>\'<div class="summary-item"><div class="summary-label">\'+l+\'</div>\'\n      +\'<div class="summary-val\'+(i===7?\' summary-owed\':\'\')+\'">\'+v+\'</div></div>\').join(\'\')\n    +\'</div></div>\';\n}\n\n/* --- Restore --- */\nasync function restoreFile(type){\n  const inputId=\'restore\'+type.charAt(0).toUpperCase()+type.slice(1);\n  const input=document.getElementById(inputId);\n  if(!input?.files?.length){showToast(\'Please select a JSON file first\');return}\n  if(!confirm(\'Restore \'+type+\'? This will overwrite current data.\'))return;\n  const form=new FormData();form.append(\'file\',input.files[0]);\n  const r=await fetch(\'/api/restore/\'+type,{method:\'POST\',body:form});\n  if(r.ok){\n    showToast(type+\' restored successfully\');\n    if(type===\'pickups\')loadDailyLog();\n    if(type===\'profile\')window.location.reload();\n  }else{\n    const err=await r.json().catch(()=>({}));\n    showToast(err.detail||\'Restore failed\');\n  }\n}\n'

# ── write assets to disk ────────────────────────────────────────
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
    if not _p.exists():
        _p.write_text(_content, encoding="utf-8")
        print(f"[taxi-log] wrote {_rel}")
# ════════════════════════════════════════════════════════════════
# CHUNK 5 of 5  —  paste immediately after chunk 4
# ════════════════════════════════════════════════════════════════

# ── helpers ─────────────────────────────────────────────────────
def _read(path: Path):
    if not path.exists(): return []
    with open(path) as f: return json.load(f)

def _write(path: Path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2, default=str)

def _read_profile():
    if not PROFILE_F.exists(): return {}
    with open(PROFILE_F) as f: return json.load(f)

# ── app setup ────────────────────────────────────────────────────
TEMPLATES_DIR = (BASE_DIR / "templates").resolve()
STATIC_DIR    = (BASE_DIR / "static").resolve()

app = FastAPI(title="Taxi Pickup Daily Log")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── version-adaptive template helper ────────────────────────────
import inspect as _inspect

def _tmpl(name, request, ctx):
    params = list(_inspect.signature(templates.TemplateResponse).parameters)
    if params[0] == "self": params = params[1:]
    if params[0] == "request":
        return templates.TemplateResponse(request, name, ctx)
    return templates.TemplateResponse(name, {"request": request, **ctx})

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
async def save_profile(request: Request, driver_name: str = Form(...),
                       vehicle: str = Form(""), phone: str = Form("")):
    _write(PROFILE_F, {"driver_name": driver_name, "vehicle": vehicle, "phone": phone})
    return RedirectResponse("/", status_code=303)

# ── pickups API ──────────────────────────────────────────────────
@app.get("/api/pickups")
async def get_pickups(date: Optional[str] = None):
    pickups = _read(PICKUPS_F)
    if date: pickups = [p for p in pickups if p.get("pickup_date") == date]
    return sorted(pickups, key=lambda p: p.get("pickup_time",""))

@app.post("/api/pickups")
async def create_pickup(request: Request):
    body = await request.json()
    m, t = float(body.get("meter_total") or 0), float(body.get("tip") or 0)
    record = {"id": str(uuid.uuid4()), "pickup_date": body.get("pickup_date",""),
              "pickup_time": body.get("pickup_time",""), "street_address": body.get("street_address",""),
              "city": body.get("city",""), "customer_name": body.get("customer_name",""),
              "phone_number": body.get("phone_number",""), "destination_address": body.get("destination_address",""),
              "meter_total": m, "payment_method": body.get("payment_method",""),
              "tip": t, "tip_payment_method": body.get("tip_payment_method",""),
              "calculated_total": calc_total(m, t), "created_at": datetime.utcnow().isoformat()}
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
    rec["meter_total"] = float(rec.get("meter_total") or 0)
    rec["tip"]         = float(rec.get("tip") or 0)
    rec["calculated_total"] = calc_total(rec["meter_total"], rec["tip"])
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

# ── report ───────────────────────────────────────────────────────
def day_totals(recs):
    t = {"meter_cash":0,"meter_credit":0,"meter_voucher":0,
         "tip_cash":0,"tip_credit":0,"tip_voucher":0,"grand_total":0,"count":0}
    for r in recs:
        pm = (r.get("payment_method") or "").lower()
        tpm= (r.get("tip_payment_method") or "").lower()
        m  = float(r.get("meter_total") or 0); tip = float(r.get("tip") or 0)
        if pm=="cash":    t["meter_cash"]   +=m
        elif pm=="credit": t["meter_credit"] +=m
        elif pm=="voucher":t["meter_voucher"]+=m
        if tpm=="cash":    t["tip_cash"]   +=tip
        elif tpm=="credit": t["tip_credit"] +=tip
        elif tpm=="voucher":t["tip_voucher"]+=tip
        t["grand_total"]+=float(r.get("calculated_total") or 0); t["count"]+=1
    t["owed_driver"]=round(((t["meter_credit"]+t["meter_voucher"])-t["meter_cash"])/2+t["tip_credit"]+t["tip_voucher"],2)
    return {k:(round(v,2) if k!="count" else v) for k,v in t.items()}

@app.get("/api/report")
async def report(from_date: str = "", to_date: str = ""):
    pickups = _read(PICKUPS_F)
    if from_date: pickups = [p for p in pickups if p.get("pickup_date","") >= from_date]
    if to_date:   pickups = [p for p in pickups if p.get("pickup_date","") <= to_date]
    days_map = {}
    for p in pickups: days_map.setdefault(p.get("pickup_date",""), []).append(p)
    days = [{"date": d, "pickups": sorted(days_map[d], key=lambda x: x.get("pickup_time","")),
             "totals": day_totals(days_map[d])} for d in sorted(days_map)]
    return {"days": days, "summary": day_totals(pickups)}

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

@app.get("/api/backup/profile")
async def backup_profile():
    if not PROFILE_F.exists(): _write(PROFILE_F, {})
    return FileResponse(PROFILE_F, filename=f"profile_{date.today().isoformat()}.json", media_type="application/json")

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

@app.post("/api/restore/profile")
async def restore_profile(file: UploadFile = File(...)): return await _restore(file, PROFILE_F, False)

# ── requirements PDF ─────────────────────────────────────────────
@app.get("/api/requirements-pdf")
async def requirements_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib import colors
    from fastapi.responses import StreamingResponse
    import io
    profile = _read_profile(); driver = profile.get("driver_name", "Unknown Driver")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch)
    styles = getSampleStyleSheet(); amber = colors.HexColor("#D97706"); dark = colors.HexColor("#1C1917")
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=amber, fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=dark, fontSize=13, spaceBefore=12, spaceAfter=4)
    body = styles["BodyText"]
    story = [Paragraph("Taxi Pickup Daily Log", h1), Paragraph("Application Requirements Document", body),
             Paragraph(f"Driver: {driver} &nbsp;&nbsp; Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", body),
             HRFlowable(width="100%", color=amber, thickness=2, spaceAfter=12),
             Paragraph("1. Application Overview", h2),
             Paragraph("Web-based application for taxi drivers to record and manage passenger pickups. Data stored in JSON files.", body),
             Spacer(1,6), Paragraph("2. Technical Stack", h2)]
    td = [["Component","Technology","Notes"],["Backend","FastAPI","Async Python"],["Templating","Jinja2","Server-side HTML"],
          ["Frontend","Vanilla JS","No framework"],["Styling","Custom CSS","Amber theme"],
          ["Storage","JSON files","pickups/customers/profile"],["PDF","ReportLab","Server-side"],["Server","Uvicorn","ASGI"]]
    tbl = Table(td, colWidths=[1.5*inch, 1.5*inch, 3.5*inch])
    tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),amber),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#FEF3C7")]),
        ("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#D1D5DB")),("FONTSIZE",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story += [tbl, Spacer(1,6), Paragraph("3. Calculation Formulas", h2),
              Paragraph("<b>Calculated Total</b> = Meter Total + Tip", body), Spacer(1,4),
              Paragraph("<b>Owed Driver</b> = ((Credit + Voucher) − Cash) / 2 + Credit Tips + Voucher Tips", body)]
    doc.build(story); buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=requirements_{date.today().isoformat()}.pdf"})

# ── entry point ──────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
