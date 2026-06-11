# Taxi Pickup Daily Log

A web app for taxi drivers to log pickups, track expenses, manage shift records, and view earnings summaries. Supports multiple drivers with per-driver data isolation and an admin dashboard.

## Features

- **Pickup logging** — record fares with customer, amount, time, and origin/destination
- **Customer address book** — auto-populated from pickup history
- **Expense tracking** — daily expense entries by category
- **Shift log** — odometer and hours per shift
- **Reports** — earnings summaries with CSV export and PDF generation
- **Backup / restore** — one-click ZIP download of all data; upload to restore
- **Admin dashboard** — create drivers, reset passwords, impersonate (read-only) any driver account
- **AI data panel** — ask questions about your own data (requires `ANTHROPIC_API_KEY`)
- **Maps integration** — inline driving directions overlay on pickup cards (requires `GOOGLE_MAPS_KEY`)

## Running Locally

```bash
pip install -r requirements.txt
python main.py
```

The app starts on `http://localhost:8080`. Data files are created automatically under `data/` on first run.

## Deployment

Targets Google Cloud Run. Copy `.env.deploy.example` to `.env.deploy`, fill in the required values, then:

```bash
./deploy.sh
```

This builds a Docker image via `gcloud builds submit` and deploys to Cloud Run.

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `GCS_BUCKET` | Yes (prod) | Switches storage to GCS; absence uses local filesystem under `data/` |
| `SECRET_KEY` | Yes (prod) | Signs session cookies |
| `ADMIN_SECRET` | Yes (prod) | Required to access `/admin/register` to create admin accounts |
| `GOOGLE_MAPS_KEY` | No | Google Maps Embed API key — enables inline map overlay; without it the Map button opens Google Maps in a new tab |
| `ANTHROPIC_API_KEY` | No | Enables the "Ask About Your Data" AI panel; panel is hidden if absent |

## Architecture

Everything lives in `main.py` (~3500 lines). No package structure.

The file has three sections in order:
1. **HTML/CSS/JS constants** — all templates and frontend assets as Python string literals, written to `templates/` and `static/` on every startup
2. **Helpers** — storage, auth, session, and business-logic utilities
3. **App + routes** — FastAPI app and all route handlers

Storage is abstracted through `_read()` / `_write()` — local filesystem when `GCS_BUCKET` is unset, Google Cloud Storage otherwise. Each driver's data lives under their UUID namespace.
