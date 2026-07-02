# Taxilog Refactoring Plan — Single-File Edition

**Status: PLAN ONLY — nothing in this document has been implemented.**
Date: 2026-07-01. Baseline commit at time of writing: `e34a0eb` on `master`.

## 1. Goal

Improve the internal organization, clarity, and duplication level of `main.py`
**while keeping the entire application in that one file**. The single-file design is
deliberate (one file to deploy, `Dockerfile` copies only `main.py`, assets generated
at startup) and is preserved. No package, no separate modules, no external template
files.

A user — or the deployed Cloud Run service — must not be able to tell the refactor
happened.

## 2. Hard invariants (what must NOT change)

These rules make rollback trivial: because the data layer is untouched, checking out
the old code automatically works with the current data.

1. **One file.** All Python, HTML, CSS, and JS stay in `main.py`. Assets are still
   written to `templates/` and `static/` on startup, exactly as now.
2. **Data files keep their exact names, paths, and JSON shapes**:
   `data/{driver_id}/pickups.json`, `customers.json`, `expenses.json`, `shifts.json`,
   `profile.json`, and root-level `users.json`. Same GCS blob names in prod.
3. **`_read` / `_write` / `_read_users` / `_write_users` keep identical semantics** —
   they remain the sole I/O primitives.
4. **No route path, method, query param, form field, or JSON response shape changes.**
5. **Cookie names (`txl_sess`, `txl_view`), signing scheme, and `SECRET_KEY` usage
   unchanged** — existing sessions survive a deploy.
6. **No new required environment variables**; `deploy.sh` and `Dockerfile` unchanged.
7. **No dependency version changes** in `requirements.txt`.
8. **Rendered output identical**: the bytes written to `templates/` and `static/`
   at startup must be byte-for-byte identical before and after (verified by diff).

## 3. Safety net — do ALL of this before touching any code

### 3.1 Code safety (git)

```bash
cd ~/A-taxilog
git push origin master                 # origin is currently 5 commits behind — sync it first
git tag pre-refactor-20260701          # immovable pointer to the known-good version
git push origin pre-refactor-20260701
git checkout -b refactor/tidy-mainpy   # ALL refactor work happens on this branch
```

`master` is never touched until the refactor is verified. The tag survives even if
branches get mangled.

### 3.2 Local data safety

`data/` is git-ignored, so git alone cannot restore it. Snapshot it:

```bash
mkdir -p backups
tar czf backups/data-pre-refactor-20260701.tar.gz data/
tar tzf backups/data-pre-refactor-20260701.tar.gz | head   # verify archive is readable
cp backups/data-pre-refactor-20260701.tar.gz ~/            # second copy outside the repo
```

The refactor itself never writes to `data/`, but manual smoke-testing will (test
pickups, etc.), so the snapshot matters.

### 3.3 Production data safety (GCS)

Production data lives in the GCS bucket, not the container, so redeploying old code
does not risk data — but snapshot anyway before the refactored version is deployed:

```bash
source .env.deploy
gsutil -m cp -r "gs://${GCS_BUCKET}/*" "gs://${GCS_BUCKET}-snapshot-20260701/" \
  || gsutil -m cp -r "gs://${GCS_BUCKET}" ./backups/gcs-pre-refactor-20260701/
```

Also download a fleet backup ZIP through the app itself (Admin → Fleet Backup →
`/api/admin/backup/all`) — that is the restore path the app natively supports.

Optional extra belt: `gsutil versioning set on gs://${GCS_BUCKET}` so any overwrite
is recoverable.

### 3.4 Production code safety (Cloud Run)

Cloud Run keeps previous revisions. Before deploying refactored code, record the
current serving revision:

```bash
gcloud run services describe taxilog --region us-central1 \
  --format 'value(status.latestReadyRevisionName)' > backups/cloudrun-revision-pre-refactor.txt
```

### 3.5 Baseline behavior capture (there are no tests)

Run the current app locally (`python main.py`) and record golden outputs to diff
against after each phase:

```bash
mkdir -p baseline
cp -r templates static baseline/        # startup-generated assets, byte-exact reference

# after logging in with a test driver account (cookie in cookies.txt):
curl -s -b cookies.txt localhost:8080/api/pickups?date=2026-06-15      > baseline/pickups.json
curl -s -b cookies.txt localhost:8080/api/daily-totals?date=2026-06-15 > baseline/totals.json
curl -s -b cookies.txt "localhost:8080/api/report?from_date=2026-06-01&to_date=2026-06-30" > baseline/report.json
curl -s -b cookies.txt localhost:8080/api/backup/all -o baseline/backup.zip

# route inventory, to prove no endpoint is lost or altered:
python -c "from main import app; print('\n'.join(sorted(f'{sorted(r.methods)} {r.path}' for r in app.routes if hasattr(r,'methods'))))" > baseline/routes.txt
```

## 4. What the refactor actually does (all inside `main.py`)

The file keeps its current top-level shape — templates → assets-to-disk → helpers →
app + routes — but each area gets tightened. Target is roughly 3,900–4,000 lines
(modest shrink from 4,341; single-file + byte-identical assets caps how much can go).

### 4.1 Section map with a table of contents

A comment block at the top listing the major sections and their order, and consistent
`# ════` banners so navigation by search is reliable. (Line numbers in comments go
stale — use searchable section names instead.)

### 4.2 Deduplicate the backup/restore endpoints (~60 lines saved)

Ten near-identical handlers (`/api/backup/{pickups,customers,expenses,shifts,profile}`
and the matching `/api/restore/...`) collapse to two handlers with a path parameter
validated against a whitelist dict:

```python
_BACKUP_FILES = {"pickups": (PICKUPS_F, True), "customers": (CUSTOMERS_F, True),
                 "expenses": (EXPENSES_F, True), "shifts": (SHIFTS_F, True),
                 "profile": (PROFILE_F, False)}

@app.get("/api/backup/{name}")            # /api/backup/all keeps its own handler,
async def backup_file(name: str, ...):    # registered BEFORE this catch-all
```

URLs, methods, and responses stay identical (invariant 4). Care: `/api/backup/all`
and `/api/restore/all` must be registered before the parameterized routes, or the
whitelist check must route them — verify with `baseline/routes.txt`.

### 4.3 Auth guards become FastAPI dependencies — **DROPPED (2026-07-01)**

Skipped by decision: it would touch ~40 handlers (the widest blast radius of any
phase) for a purely stylistic gain, and a single `_auth`/`_auth_write` mix-up would
quietly weaken the impersonation write-block on one endpoint. The existing pattern
(`did = _auth(request)` as the first handler line) stays. Convention going forward:
new endpoints may use `Depends(...)`; existing ones are left untouched.

### 4.4 Consolidate request parsing per route group

Repeated `data = await request.json()` + field-by-field `.get()` blocks in
pickups/expenses/shifts get small shared coercion helpers (e.g. `_as_money(v)`,
`_req_str(data, key)`) so parsing and defaulting logic is written once per field type
instead of once per handler. **Not** switching to Pydantic models — that changes
error response shapes (422 vs current behavior) and violates invariant 4.

### 4.5 PDF code cleanup

`report_pdf`, `fleet_report_pdf`, `requirements_pdf`, and `admin_design_pdf` share
page-setup/styling boilerplate — extract common ReportLab helpers (`_pdf_doc()`,
`_pdf_table_style()`) within the file. Output PDFs need not be byte-identical
(timestamps), but visually identical.

### 4.6 Template constants: organization only

The HTML/CSS/JS string constants stay exactly as they are, byte-for-byte (invariant 8).
Only their surrounding organization improves: one clearly-banered block per template,
in the order they're written to disk. Any actual template refactoring (e.g. sharing
auth-page boilerplate) is out of scope because it would break byte-identity and with
it the cheap verification story.

### 4.7 Explicitly OUT of scope

- Splitting into modules or external template/static files (rejected — single file).
- Pydantic request models (changes error semantics).
- Moving `_reset_tokens` out of process memory (existing behavior, kept).
- Any behavior fix or feature, however tempting. If a bug is found mid-refactor,
  note it in `planned.md` and leave the behavior as-is.

## 5. Phases — one commit each, app fully working after every commit

| Phase | Change | Verification |
|---|---|---|
| 0 | Safety net (§3) | Baselines captured |
| 1 | Section banners + TOC comment (§4.1) | `diff -r templates baseline/templates` & `static` clean; routes.txt identical |
| 2 | Backup/restore dedupe (§4.2) | routes.txt identical; download each backup file + `all`; restore round-trip on scratch data |
| 3 | ~~Auth guards → `Depends` (§4.3)~~ **DROPPED** | — |
| 4 | Request-parsing helpers (§4.4) | Pickup/expense/shift CRUD against `baseline/*.json` |
| 5 | PDF helpers (§4.5) | Generate all four PDFs, eyeball against pre-refactor copies |

After each phase: `python main.py` starts clean, asset diff (invariant 8) passes,
route inventory matches `baseline/routes.txt`.

## 6. Smoke checklist (full pass before merge and before deploy)

- [ ] `python main.py` starts clean, no tracebacks
- [ ] Startup-written `templates/` and `static/` are byte-identical to `baseline/`
- [ ] Route inventory matches `baseline/routes.txt`
- [ ] Login as driver; login as admin; logout; bad password rejected
- [ ] Create pickup → appears in Daily Log → edit it → delete it
- [ ] Daily totals correct for a known date (compare `baseline/totals.json`)
- [ ] Expenses: add, list by date, delete
- [ ] Shifts: save, reload same date shows saved values
- [ ] Report generate + CSV export + PDF download for a known range (compare baseline)
- [ ] Customer autocomplete suggests on address/phone/name
- [ ] Backup ZIP downloads with all 5 files; restore that ZIP into a scratch copy and
      confirm data round-trips
- [ ] Admin dashboard: fleet overview numbers, today's totals table
- [ ] Admin impersonation: view driver, banner shows, writes blocked (403), exit view
- [ ] Password change + admin-generated reset link flow
- [ ] Ask panel answers (if `ANTHROPIC_API_KEY` set locally)
- [ ] `docker build .` succeeds and the container serves on 8080

## 7. Rollback playbook

### 7.1 Roll back code locally

```bash
git checkout master                          # abandon branch, or:
git reset --hard pre-refactor-20260701       # nuke master back to the tag if merged
```

Because of the §2 invariants, old code runs against current `data/` with no migration.

### 7.2 Roll back local data (only if smoke-testing polluted it)

```bash
rm -rf data.broken && mv data data.broken    # keep the bad state for inspection
tar xzf backups/data-pre-refactor-20260701.tar.gz
```

### 7.3 Roll back production code (instant, no rebuild)

```bash
gcloud run services update-traffic taxilog --region us-central1 \
  --to-revisions "$(cat backups/cloudrun-revision-pre-refactor.txt)=100"
```

Or rebuild from the tag: `git checkout pre-refactor-20260701 && ./deploy.sh`.

### 7.4 Roll back production data (only if something wrote bad data)

Preferred: Admin → Fleet Restore with the ZIP from §3.3.
Alternative: `gsutil -m cp -r "gs://${GCS_BUCKET}-snapshot-20260701/*" "gs://${GCS_BUCKET}/"`.

### 7.5 Combined "get me back to exactly how it was"

1. §7.3 (or §7.1 locally) — old code serving again.
2. §7.4 (or §7.2 locally) — data restored to the pre-refactor snapshot.
3. Sessions: unchanged `SECRET_KEY` means users stay logged in through the rollback.

## 8. Estimated effort

Phase 0: ~15 min. Phase 1: ~30 min. Phase 2: ~1 h. Phase 3: ~1.5 h (many call sites,
mechanical). Phases 4–5: ~1.5 h. Verification throughout: ~1 h. Total: roughly half a
focused day.
