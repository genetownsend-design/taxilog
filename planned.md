# Planned Enhancements

- [x] Change menu to hamburger menu
- [x] Single-button full backup — downloads a zip of all data files (pickups, customers, profile, expenses, shifts) needed for complete recovery
- [x] Recovery feature — upload a backup zip to restore all data files to a known good state
- [x] Zero out Shift Log fields if the current day's shift has not been saved yet
- [x] Replace all time input fields with an analogue clock picker — 12-hour face, click hour then minute, AM/PM toggle buttons. Use **Clocklet** (MIT, ~7 kB, vanilla JS, no dependencies): https://github.com/luncheon/clocklet — include via CDN, attach to the pickup time, shift start, and shift end fields.

## Quick Entry — free-form pickup dictation — SHIPPED 2026-07-28

Live in production since revision `taxilog-00059-fv4`. Commits `005f375`, `506189e`,
`37b31b2`. The plan below is kept for the reasoning behind each decision; see
**"What shipped beyond this plan"** at the end of the section for what changed during
the build.

Type or dictate a sentence ("Pickup at 125 W. 3rd at 10:00, going to Palo Alto"), send it
to Claude, and fill the existing New Pickup form fields for review. **Nothing is saved** —
the driver corrects anything wrong and presses "Record Pickup" as today.

Filling the existing form rather than showing a separate preview card is the key
simplification: no new save path, no new data file, no duplicated validation. The existing
`POST /api/pickups`, payment-method checks, customer autocomplete, and totals bar all still
apply.

### Backend

- [x] Add `POST /api/parse-pickup` (near `/api/ask`, ~line 3562)
  - Guard with `_auth_write` — the feature exists only to create a record, so it should be
    blocked during admin impersonation like every other mutation path.
  - Request body: `{text, local_date, local_time}`. The browser sends its own clock so "at
    10:00" and "tomorrow" resolve in the driver's timezone — `datetime.utcnow()` is the
    wrong clock here, and that class of bug already bit us once (commit 4c94853).
  - Response: `{"fields": {…}}` keyed exactly by `_PICKUP_FIELDS`, or `{"error": "…"}`
    following the `/api/ask` convention.
- [x] Extract via **structured outputs**, not prose parsing — pass a JSON schema so the
      response is guaranteed-parseable instead of "please reply with JSON" plus a regex.
      Schema: all eleven `_PICKUP_FIELDS` as strings, `additionalProperties: false`, all
      listed in `required`, anything not stated in the text returned as `""` and never
      inferred. Empty string rather than `null` matches how the app already stores blank
      fields, so the mapping into the form is a straight copy.
- [x] Add `_PARSE_MODEL = "claude-opus-5"` — `_CLAUDE_MODEL` (`claude-sonnet-4-6`) does not
      support `output_config.format`. Haiku 4.5 is a reasonable opt-in downgrade later if
      the inline latency proves annoying, but default to Opus 5.
- [x] Extend `ask_claude` minimally rather than adding a second Anthropic call site (the
      Debrief work established that helper for exactly this reason): add optional `model`
      and `output_schema` params; when a schema is given, pass
      `output_config={"format": {"type": "json_schema", "schema": …}}`.
- [x] **Truncation must raise, not append.** `ask_claude` currently appends
      "(Response cut off — answer exceeded token limit.)" on `stop_reason == "max_tokens"`
      (main.py:2474). Appended to JSON that produces invalid JSON. When a schema is in
      play, raise `AskClaudeError` instead.
- [x] Prompt contents: the field glossary (mirroring main.py:3629), the driver's local date
      and time, bare times resolve to the nearest upcoming time, payment fields accept only
      Cash/Credit/Voucher, phone numbers keep the app's `(555) 555-5555` shape, and a
      dispatch call typically has no fare yet so money fields stay blank.

#### Local shorthand / dictation glossary

Drivers use nicknames for regular pickup spots ("Chope", "Chope ER", "Chope PES" for the
hospital) that speech-to-text will mangle. This is **not** a special case in code — it's a
per-driver vocabulary field. Every driver has jargon: airport terminals, "the Vet",
"county", regular bar names.

- [x] Add a free-text `places` key to `profile.json` — one new field in the
      `_write(PROFILE_F, {...})` dict at main.py:3319 and a matching `Form("")` param on
      `POST /setup`. No new storage path, no new file; `_read_profile()` already returns it
      and `/api/ask` already passes the whole profile to Claude (main.py:3647).
- [x] Inject that field into the parse prompt as the candidate list, plus the instruction
      that makes it work: *"This text may come from speech-to-text. Place names are
      frequently mangled phonetically — match them against the glossary by sound, not
      spelling."* Fuzzy phonetic matching against a short known list is reliable; guessing
      blind is not.
- [x] Whatever the driver writes on the right of each glossary line is exactly what lands in
      the form field — the driver owns the canonical form, not the model. Example content:

      ```
      Chope = Chope Main
      Chope ER = Chope ER
      Chope PES = Chope PES
      errands and back = Errands and Back

      Chope — dictation often renders this as "chop", "choke", "show pea"
      ```

      Treat it as a living file: add mis-hearings as they turn up.

      **Corrected during the build:** the first draft put the full postal address and the
      city on the right-hand side. Wrong on both counts. `street_address` holds whatever
      the driver would type there — "121 Wildwood" or just "Chope" — and the city is its
      own field, so a city inside a glossary entry landed in *both* fields. Entries are
      bare names now, optionally with a street ("Chope ER 121 W. 4th") if the driver wants
      it in the log. Either form is copied verbatim; the app never reshapes it.
- [x] **Consequence worth knowing:** `upsert_customer` feeds `street_address` into the
      address book and `/api/customers/lookup` matches addresses exactly, so distinct
      shorthand values become distinct address-book entries. That's the desired behaviour
      here (Main / ER / PES are operationally different pickups), and it means they also
      start appearing in the manual-entry autocomplete — type "cho" and the existing
      typeahead offers them.

### Frontend

All in the `main.py` string constants — `templates/` and `static/` are regenerated at startup.

- [x] Markup before the New Pickup form (~line 344), gated on the existing
      `{% if ask_enabled %}` so it disappears when `ANTHROPIC_API_KEY` is absent:
      a "🎙️ Quick Entry" panel with a 2-row textarea, Parse and Clear buttons, and a
      status line.
- [x] `parseQuickEntry()` (~line 1688, near `submitPickup`): posts the text plus
      `new Date()` values, then on success calls `resetForm()` and writes each returned
      field. Every form input's `id` already equals its field name, so it's a loop over
      `setValue(k, v)` — with two special cases: `pickup_time` goes through the existing
      `to12h()` before display (the input is the readonly clock-picker showing 12-hour),
      and `updateCalcTotal()` runs at the end. Then a toast: "Review and save."
- [x] Full-reset-then-fill rather than merging into whatever is already typed — one
      sentence in, one predictable form state out.
- [x] **No voice library.** Phone keyboards have a dictation button that works in any
      textarea, which is how this gets used in the cab anyway. A Web Speech API mic button
      would add a Chrome-only dependency for something the OS already does free — and see
      the Clocklet lesson about short leashes on third-party JS.
- [x] Add a "Common places & shorthand" textarea to the Setup page (`setup.html` constant).
      Shipped hint: *"How you say places out loud, and exactly what should land in the
      address field. One per line. Used by Quick Entry to understand dictated calls."*
      Placeholder is a format hint rather than a sample address — an invented street number
      in a placeholder reads as real data.

### Error handling

Every failure mode gets an accurate message, not a generic fallback:

- [x] Empty/whitespace input → client-side guard, no API call.
- [x] API failures → `ask_claude`'s existing branches already cover auth, permission,
      missing model, rate limit (with retry-after), timeout, connection, and 5xx distinctly.
- [x] Truncation → the new raise branch above.
- [x] Refusal → existing message.
- [x] Malformed JSON → shouldn't occur under a schema, but guard anyway:
      "Couldn't read the AI response — try rephrasing."
- [x] **All fields blank** → its own message, because this is the likeliest real-world
      outcome for a garbled dictation: "Couldn't find pickup details in that — try
      including a pickup address."
- [x] Network failure on the `fetch` → try/catch. Note `submitAsk()` (main.py:2011) doesn't
      do this today; don't copy that gap.

### Tests

Follow the `tests/test_debrief.py` precedent — mocked Anthropic client, no network.

- [x] JSON → field mapping
- [x] Blank fields stay blank
- [x] `local_date` / `local_time` reach the prompt
- [x] Profile `places` glossary reaches the prompt, and is omitted cleanly when empty
- [x] Truncation raises rather than returning partial text
- [x] Malformed JSON errors rather than half-filling a record

### Out of scope for v1

Auto-feeding the ~20 most-used distinct `street_address` values from `pickups.json` into the
prompt alongside the glossary. Costs the driver no typing and would catch regular spots they
never wrote a glossary line for — but add it only if the glossary alone proves insufficient.

(Matching against `customers.json` was considered and dropped: that file holds *passenger*
names and addresses, so it was never going to know the driver's nickname for a place. The
profile glossary is where the vocabulary actually lives.)

### Size

~45 lines of Python (endpoint + schema + prompt + profile field), ~10 added to `ask_claude`,
~20 HTML (Quick Entry panel + Setup textarea), ~25 JS, plus tests. No new dependency, no new
data file, no changes to the storage layer or `_PICKUP_FIELDS`.

### What shipped beyond this plan

Four things the plan did not anticipate, all found by calling the real API rather than by
running the mocked tests — which passed throughout:

- **`ask_claude` read `msg.content[0].text`.** Opus 5 thinks by default, so `content[0]` is
  a thinking block and the call raised `AttributeError`. Now takes the first *text* block.
  This was a latent bug in shipped code: pointing `_CLAUDE_MODEL` at any current model
  would have broken Ask and Debrief the same way.
- **`effort: "low"` on the parse call.** 5.0s → ~2.7s with no loss of accuracy, including
  on the phonetic matching. Extraction from one sentence is easy and the driver is waiting
  on it.
- **Whitespace stripped on save** (`_trim` in create/update pickup). Live data had
  `'San Mateo '` on 86 pickups and `'San Mateo'` on 8 — two different cities to every
  grouping, report and address-book lookup. Dictation was about to add a third variant.
  A one-off `migrate_whitespace.py` (gitignored, like `migrate_sfo.py`) normalised 363
  existing field values across 176 records; revenue verified unchanged at $8,638.36.
- **Known-city list in the prompt.** Distinct cities from `pickups.json`, most frequent
  first, so dictated "san mateo" comes back spelled the way the rest of the log spells it.
  Two live bugs while getting this right, both worth remembering: the list first bled into
  `destination_address` (saying "East Palo Alto" produced `EPA`, an abbreviation from one
  old record), and the fix for *that* made destinations transcribe lowercase, recreating
  the fragmentation the migration had just removed. Scoping the list to the city field and
  making capitalisation a separate rule fixed both.

## CLOSED — cheaper model for Quick Entry: tested, staying on Opus 5 (2026-08-18)

Tested `claude-haiku-4-5` against the shipped `claude-opus-5`, both driving the real
`_parse_system` prompt with the production glossary and city list pulled from GCS. Roughly
90 live calls, 3 runs per phrasing per model.

**Haiku is faster and cheaper than the plan predicted.** Median 1.37s vs 3.63s — a 2.6×
speedup, not the 3s→2s guessed above. The assumption that fixed costs dominate was wrong.
Pricing is 5× lower ($1/$5 per MTok vs $5/$25). Phonetic glossary matching, city
capitalisation, and the known-city list staying out of `street_address` /
`destination_address` all held up — the risks this plan was most worried about were not
where it broke.

**It breaks Due Now calls, which is why we're not switching.** Given an address whose digits
came through split and *no stated time*, Haiku joins the street number correctly and then
also writes those digits into `pickup_time` — "10 45 chestnut going to belmont" yields
`1045 Chestnut` **and** `10:45`. Reproduced 3/3 on three separate phrasings; Opus leaves the
time blank 3/3 on all of them.

That matters because of how the form works, not because of the parse itself. `resetForm()`
deliberately leaves `pickup_time` alone, so a blank time from the parser means the now+20
default survives — which is exactly what a Due Now call wants. Haiku's phantom overwrites
that default with a plausible-looking wrong time (`10:45 AM` reads like an ordinary morning
pickup) on the most common call type. **State a time and the phantom disappears entirely** —
Haiku matched Opus exactly on every time-stated phrasing.

**The swap was never a one-constant change.** `effort` is not supported on Haiku 4.5;
`ask_claude` raises "This model does not support the effort parameter." on every call. A
switch would also have to drop `effort="low"` — itself a confound, since the Opus baseline
keeps it. (That message is only legible because of the `BadRequestError` branch in
`692bae3`; before it, this surfaced as "API error 400.")

Re-open only if parse latency becomes a real complaint. To reproduce: pull `profile.json`
and `pickups.json` from GCS, build the prompt via `_parse_system`, run both models over the
same notes, and discard one warm-up call per model so schema-compile time isn't counted.

### Left alone deliberately

- **Bare hours are unreliable on both models.** With the driver's clock at 14:30, "at 7 30"
  came back `19:30` from Opus (3/3) and `07:30`/`19:30` from Haiku. Real pickups run
  05:00–17:00 (232 of 236 records), so evening readings are essentially always wrong. Not
  fixed: Quick Entry fills the form and the driver reviews before saving, so a wrong time is
  visible and editable, and stating "9am" avoids it. Worth revisiting only if it turns out
  to be a frequent correction in practice.
- **"show pea" is ambiguous in the glossary.** Listed as a mis-hearing of bare *Chope*
  (→ "Chope Main"), but it is phonetically closer to *PES*: Haiku returns `Chope PES` 3/3
  and Opus flipped on one run of three. If it matters, add an explicit
  `show pea = Chope Main` line rather than changing models.

## OPEN — cover the expensive-to-get-wrong paths with tests (raised 2026-07-28)

Measured 2026-07-28: **10 of 53 routes** have any test. All 10 are pickups, Ask, or
Debrief — whatever we happened to be building. Untouched: all 10 auth/account routes, all
18 admin routes, expenses, shifts, daily-totals, customer autocomplete, and every
report / CSV / PDF / backup path.

The goal is not 100%. Most of that code has been stable for months and a failure in it is
visible immediately. The goal is the handful of places where a regression is **silent,
or only discovered when you are already in trouble**. Roughly a day's work, in this order:

- [x] **Backup / restore round-trip.** Done 2026-08-18 — `tests/test_backup_restore.py`,
      10 tests. Covers the driver round-trip (seed → back up → wipe → restore → compare),
      partial zips leaving untouched files alone, the three rejection paths (not a zip,
      wrong JSON shape, malformed JSON) each asserting nothing was written, auth, the
      impersonation split (backup allowed, restore 403), and the admin fleet round-trip
      across two drivers plus `users.json`. Verified by mutation: dropping the shape check,
      skipping the write, and disabling the impersonation guard each fail the matching test.

      **Setting this up surfaced a live hazard.** `_BACKUP_FILES` is built at import time
      from the path constants, and `_local()` resolves a file as
      `path.parent/<driver>/path.name` — so the `data_dir` fixture's monkeypatches did not
      reach it, and a naive test of `/api/restore/all` writes into the developer's real
      `data/` directory. `conftest.data_dir` now rebuilds `_BACKUP_FILES` against `tmp_path`
      and asserts nothing escapes it.

      **Still uncovered: the five per-file pairs** (`/api/backup/pickups`,
      `/api/restore/pickups`, …). `_register_backup_restore` captures each `Path` in a
      closure at import, so no fixture can redirect them — testing them means changing
      `main.py` (making `_local()` resolve against `DATA_DIR`, which is what the constants
      already mean in production). Left alone rather than reshaping the storage layer for
      testability without asking; the `/all` endpoints are what a real recovery uses.
- [x] **Auth and impersonation guards.** Done 2026-08-18 — `tests/test_route_guards.py`
      (the sweep) and `tests/test_auth_guards.py` (the specifics).

      **It found a live unauthenticated account takeover.** `GET`/`POST /admin/reset` had
      no guard at all: the page listed every driver username to anyone, the POST minted a
      password-reset token for any username — admins included, since only the *displayed*
      list filters them out — and returned the reset URL in the response body. Feeding that
      to `/reset-password` completed the takeover. Verified end to end against a temp data
      directory, never against production. Present since `4cf0280` (2026-05-31), roughly
      eleven weeks on a `--allow-unauthenticated` service. Fixed in `c2966de` by adding the
      `_require_admin(request)` that every neighbouring admin route already had.

      **The sweep is the part worth keeping.** It enumerates `app.routes`, classifies each
      as public / driver-read / driver-write / admin-only / self-service, and **fails on any
      route it does not recognise** — so a new endpoint cannot ship without someone deciding
      its guard. A spot-check suite would never have found `/admin/reset`, because nobody
      thought to spot-check it. Two details that keep it honest: dummy payloads for the
      `Form`/`File` endpoints so body validation cannot 422 ahead of the guard, and
      redirects left unfollowed so a 303 to `/login` reads as the refusal it is.

      Also covered: `/api/change-password` acts on `ctx.user_id`, which is why it correctly
      skips `_auth_write` — pinned so that switching to `effective_id` (which would let an
      admin rewrite a viewed driver's password) fails two tests. And cross-driver isolation:
      listing, fetch-by-id, delete, update, backup contents, and customer autocomplete all
      stay within one driver. Removing the driver namespace from `_local()` fails all six.
- [x] **Report math.** Done 2026-08-18 — `tests/test_report_math.py`, 15 tests. All four
      `pay_mode` branches (standard, gate, commission incl. the 50% default, owner) plus
      `/api/daily-totals` and `/api/report`: day grouping, inclusive date bounds, expenses,
      expense-only days surviving into the report, and the `owed_driver` /
      `driver_earnings` split (what the company owes vs. that plus the cash already in the
      driver's pocket). Every expected value is worked out by hand in a comment, so a
      formula change has to disagree with arithmetic rather than with a recorded output.

      The one that would have been expensive: **gate fee is charged per day, not per
      range.** `/api/report` re-sums the per-day `owed_driver` for gate mode instead of
      computing across the range — the naive version charges one fee for a whole week and
      overstates the driver by a day's gate for every extra day. Pinned, and the mutation
      that removes the re-sum fails it.

      Mutation-checked: removing the per-day gate re-sum, flipping the cash sign in the
      standard split, and dropping cash-in-hand from `driver_earnings` each fail the
      matching tests.

      **Gate mode: raised, and deliberately held.** It computes
      `(meter_credit + meter_voucher)/2 + tips - gate_fee`. A gate lease usually means the
      driver pays a flat fee and keeps *all* fares, which would be no halving — so the `/2`
      may be standard-mode logic that leaked across.

      **Do not change it on that reasoning alone.** Decided 2026-08-18: gate, commission and
      owner modes were built for drivers on those plans, none of whom use the app yet; Gene
      is on `standard`. No real user has ever exercised the gate branch, so there is nothing
      to check the formula against, and guessing at someone else's pay arrangement is worse
      than leaving it. Revisit only when a driver on a gate plan can say what their
      settlement actually looks like. The tests pin current behaviour so any future change
      is a deliberate one.

Lower priority, failure is loud and immediate: expenses, shifts, PDF generation.

### A gap tests of this shape cannot close

Every mocked test passed while `ask_claude` crashed on a live call, because the mock
returned `content[0].text` — encoding the same wrong assumption the code did. Mocks
verify that the code does what was intended; they cannot verify the intention. The
things that caught the real bugs on 2026-07-28 were live calls against real data. Budget
for that separately from the suite: it is not a coverage number that fixes it.

## OPEN — self-service password recovery (raised 2026-08-18)

**Discuss the approach before building any of it.** Raised as a want, not a spec.

Today a driver who forgets their password has to ask an admin, who generates a link at
`/admin/reset`. That is fine at one user and gets tiresome at three. The goal is a driver
resetting their own password without anyone else being involved — the "email me a reset
link" shape.

**What makes it more than an afternoon:** no email address is stored for anyone.
Registration collects username and password only (`POST /register`), and the admin
bootstrap the same. So this needs an email on the user record, a way to collect it from
people who already registered without one, and a decision about verifying it at signup —
an unverified address is a way to send reset links to the wrong person. Sending mail at
all also means a provider, a secret to hold, and a bounce/failure path. **Explicitly not
being designed now**; the point of this entry is that it was raised deliberately, not that
the work is queued.

**Not a lockout risk in the meantime.** If Gene loses his own password, `/admin/register`
plus `ADMIN_SECRET` (in `.env.deploy`) creates a fresh admin account — under a different
username, since the existing one is taken — and signs in directly. `/admin/reset` then
recovers the driver account. Worth knowing offline, since it is needed exactly when you
cannot log in to look it up.

Note this path narrowed on 2026-08-18: `/admin/reset` had no guard at all, so a locked-out
admin could have used it unauthenticated. That was an account-takeover hole (`c2966de`) and
closing it was right, but it did remove an accidental escape hatch — the `ADMIN_SECRET`
route above is now the only one.
