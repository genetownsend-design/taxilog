# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## How to Work

**Think before coding.** Before writing any code, understand what is actually being asked and why. Identify the minimal change that achieves the goal. If the right approach is unclear, ask rather than guess.

**Simplicity first.** Prefer the simplest solution that works. Avoid abstractions, layers, or patterns that the current task does not require. Three similar lines of code is better than a premature helper.

**Surgical edits only.** Change only what is necessary to accomplish the goal. Do not refactor surrounding code, rename things for style, add comments, or clean up unrelated areas — even if they look improvable. Leave the code exactly as it was except for the targeted change.

**Goal-driven execution.** Every line written should serve the stated goal. Stop when the goal is met. Do not add features, defensive handling, or polish that was not asked for.

**Handle all outcomes.** Always research all potential return codes, status codes, and error responses for any API or service being integrated. Do not assume the happy path. Every distinct failure mode should produce a clear, accurate message — not a generic fallback that misleads the user about what went wrong.

## Running Locally

```bash
pip install -r requirements.txt
python main.py
```

The app starts on port 8000 by default. No database setup needed — data files are created automatically on first run under `data/`. For local dev, env vars can be put in a `.env` file (loaded via python-dotenv).

Tests (92, Anthropic client mocked throughout — no network):

```bash
pip install -r requirements-dev.txt
python -m pytest tests/
```

- `test_debrief.py` — stats math, period resolution, caching, the `ask_claude` helper
- `test_pickups.py` — create/update field handling (whitespace stripping)
- `test_quick_entry.py` — `/api/parse-pickup` field mapping, prompt contents, error paths

Coverage is deliberately partial: 10 of 53 routes. Auth/admin routes, expenses, shifts, reports, and backup/restore have no tests — see `planned.md` for which of those gaps are worth closing and why. There is no linter configuration and no coverage gate.

Note that mocked tests cannot catch wrong assumptions about the Anthropic API — the whole suite passed while `ask_claude` crashed on every live call, because the mock encoded the same mistake as the code. Live calls against real data are a separate, necessary check.

## Deployment

Targets Google Cloud Run. Requires `.env.deploy` (copy from `.env.deploy.example`).

```bash
./ship.sh "commit message"    # commit what's modified, then ship
./ship.sh                     # ship what's already committed
```

`ship.sh` is the deploy path: it runs the tests, commits, pushes, builds, then deploys the new revision with **no traffic** under the `next` tag and smoke-tests it on its own URL. Production keeps serving the old revision until those checks pass; only then is traffic promoted. It prints the rollback command on success and, on smoke-test failure, leaves the untrafficked revision up for inspection.

`deploy.sh` still exists and deploys straight to production with no smoke test. Prefer `ship.sh`.

## Architecture

**Everything lives in `main.py`** (~5000 lines). There is no package structure. This is a deliberate invariant, not a shortcut — the `Dockerfile` copies only `main.py`. See `REFACTOR_PLAN.md` before proposing a split.

The file opens with a table of contents (line 1) and is divided by banner comments — search the banner text to jump. Major sections, in order:
1. **HTML/CSS/JS string constants** (lines ~82–2449) — all templates, stylesheet, and frontend JS are Python string literals, each under its own `templates/…` or `static/…` banner. They are written to `templates/` and `static/` on every startup (~line 2450).
2. **Helpers** (lines ~2473–2801) — config, the Claude API helper, auth, storage, session, business logic, PDF building blocks.
3. **App + routes** (lines ~2802–end) — FastAPI app instantiation followed by all route handlers, grouped by banner (auth, admin, fleet, pages, pickups, expenses, shifts, report, AI, exports, backup).

Line numbers drift with every change; the banners don't. Prefer grepping for a banner or symbol over trusting a number here.

### Storage abstraction

Two mutually exclusive backends, selected at startup by whether `GCS_BUCKET` env var is set:

- **Local**: files at `data/{driver_id}/{filename}.json`
- **GCS**: blobs at `{driver_id}/{filename}` in the configured bucket

The functions `_read(path, driver_id)` and `_write(path, driver_id)` are the sole I/O primitives — every data access goes through them. `users.json` is the exception: it lives at the root (no driver namespace) and uses `_read_users()` / `_write_users()`.

### Multi-tenancy

Each driver is identified by a UUID (`driver_id`). Data files are:
- `pickups.json` — list of pickup records
- `customers.json` — customer address book (auto-populated from pickups)
- `expenses.json` — daily expenses
- `shifts.json` — shift logs with odometer and hours
- `profile.json` — driver profile (name, vehicle, gate fee rate, and `places`, the free-text shorthand glossary Quick Entry uses)
- `debriefs.json` — cached AI shift debriefs, keyed by `period:start:end` with a sha256 hash of the range's pickups for invalidation

### Auth

Sessions use signed cookies (`itsdangerous.URLSafeTimedSerializer`). Cookie name: `txl_sess`. Payload contains `uid` and `role` (`"driver"` or `"admin"`). Passwords are bcrypt-hashed.

`_get_auth_ctx(request) → AuthCtx` is the central auth parser. Route guards:
- `_auth(request)` — returns `effective_id`, allows impersonation reads
- `_auth_write(request)` — raises 403 if impersonating (read-only views can't mutate data)
- `_require_admin(request)` — raises 403 if not admin role

**Admin impersonation**: admin can view any driver's account via `/admin/view/{driver_id}`. This sets a secondary cookie `txl_view` (4-hour TTL). The banner and read-only enforcement are driven by `AuthCtx.is_impersonating`.

**Password reset**: tokens are generated by admin at `/admin/reset`, stored in the in-memory dict `_reset_tokens` (token → user_id, lost on restart), and consumed at `/reset-password`.

### AI features

Three features call Claude, all through the single shared `ask_claude()` helper. Extend that helper rather than adding another Anthropic call site.

- **Ask About Your Data** (`/api/ask`) — free-form questions over the driver's records.
- **Shift Debrief** (`/debrief`, `/api/debrief`) — AI analysis of a period, cached in `debriefs.json`.
- **Quick Entry** (`/api/parse-pickup`) — parses a dictated sentence into New Pickup form fields. Nothing is saved; the driver reviews and presses Record Pickup as usual, so there is no new save path or validation.

Two model constants: `_CLAUDE_MODEL` (`claude-sonnet-4-6`) for Ask and Debrief, and `_PARSE_MODEL` (`claude-opus-5`, `effort: "low"`) for Quick Entry. They differ because Quick Entry uses **structured outputs** (`output_config.format`) to guarantee parseable JSON, which Sonnet 4.6 does not support. When `ask_claude` is given an `output_schema` it raises on truncation instead of appending a notice — appending to JSON produces invalid JSON.

Lessons that cost real debugging, worth respecting in new work here:

- **Don't ask the model to do arithmetic** over raw records. Pre-compute sums and aggregates server-side and hand it the totals. This was tried, removed, and reinstated after answers came out wrong.
- **`max_tokens` will be wrong on the first guess** (this project went 1024 → 4096 → 8192). Always detect truncation and surface it rather than returning a silently cut-off answer.
- **Read the first *text* block of a response, not `content[0]`.** Current models think by default, so `content[0]` is a thinking block.
- **Prompt scope leaks between fields.** The known-city list added for `city` bled into `destination_address`, and the fix for that broke capitalisation elsewhere. Scope a list to the field it serves and keep formatting rules separate.

### Modifying templates or frontend

Since templates and static files are string constants in `main.py`, edit them there — the files in `templates/` and `static/` are overwritten on every startup and are git-ignored. Do not edit the files on disk directly.

### Environment variables

| Variable | Required in prod | Purpose |
|---|---|---|
| `GCS_BUCKET` | Yes | Switches storage to GCS; absence means local filesystem |
| `SECRET_KEY` | Yes | Signs session cookies (defaults to insecure dev key) |
| `ADMIN_SECRET` | Yes | Required to access `/admin/register` to create admin accounts |
| `GOOGLE_MAPS_KEY` | No | Google Maps Embed API key — enables inline map overlay in pickup cards; if absent, Map button opens Google Maps in a new tab |
| `ANTHROPIC_API_KEY` | No | Enables the "Ask About Your Data" panel, the Shift Debrief page (`/debrief`), and the Quick Entry dictation panel; if absent, both panels are hidden and the debrief page shows a not-configured message. See **AI features** above |
