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

## OPEN — try a cheaper model for Quick Entry (deferred 2026-07-28)

Shipped on `_PARSE_MODEL = "claude-opus-5"` at `effort: "low"`, measured 2.5–3.1s per parse.
Extraction from one sentence is an easy task, so a smaller model may well do it — worth
testing once real dictation has proved the feature works at all. **Not before that:** if
accuracy is being judged, it should be judged on the model that shipped, or a regression
can't be told apart from the feature never having worked.

- [ ] Candidate: `claude-haiku-4-5` — supports structured outputs (`output_config.format`),
      which is the constraint that ruled out `claude-sonnet-4-6`.
- [ ] **Cheaper is certain; faster is a guess — measure it.** The 2.5–3.1s is not mostly
      generation. Network round-trip, processing a system prompt carrying the field rules
      plus the glossary plus 40 city names, and ~150 tokens of JSON out are fixed costs
      that do not shrink with model size, so the win may be 3s→2s rather than 3s→0.5s.
      Discard the first call after any switch: a new schema compiles once, then caches.
      Note the easy latency is already spent — `effort: "low"` took 5.0s down to 2.7s.
- [ ] The hard part is **not** field extraction, it's phonetic glossary matching. Test
      "chop" / "choke" / "show pea" → the right Chope entry. Also test that a place absent
      from the glossary passes through untouched rather than being forced onto an entry.
- [ ] Also check city capitalisation against the known-city list ("san mateo" → "San Mateo",
      an unseen city → postal capitalisation) and that the list does not leak into
      `street_address` / `destination_address`. Both were live bugs on Opus 5 during the
      build; a different model can reintroduce either.
- [ ] Compare against the Opus 5 baseline on the same notes before switching. `ask_claude`
      already takes `model`, so the change is the `_PARSE_MODEL` constant and nothing else.

## OPEN — cover the expensive-to-get-wrong paths with tests (raised 2026-07-28)

Measured 2026-07-28: **10 of 53 routes** have any test. All 10 are pickups, Ask, or
Debrief — whatever we happened to be building. Untouched: all 10 auth/account routes, all
18 admin routes, expenses, shifts, daily-totals, customer autocomplete, and every
report / CSV / PDF / backup path.

The goal is not 100%. Most of that code has been stable for months and a failure in it is
visible immediately. The goal is the handful of places where a regression is **silent,
or only discovered when you are already in trouble**. Roughly a day's work, in this order:

- [ ] **Backup / restore round-trip.** `POST /api/restore/all` is what you reach for after
      a bad day and it has never been executed by a test. Write data → back up → delete →
      restore → assert byte-identical. Cover the admin variants too
      (`/api/admin/backup/all`, `/api/admin/restore/all`).
- [ ] **Auth and impersonation guards.** That `_auth_write` rejects an impersonating admin,
      that `_require_admin` rejects a driver, and that one driver cannot read another's
      data. `REFACTOR_PLAN.md` dropped Phase 3 precisely because a single `_auth` /
      `_auth_write` mix-up could quietly weaken this — and there are no tests holding it.
      A regression here is invisible until it matters.
- [ ] **Report math.** Same class of bug as the June Debrief arithmetic errors, and reports
      are what the money decisions come from. Assert `/api/report` and `/api/daily-totals`
      against hand-computed fixtures, including each `pay_mode` branch.

Lower priority, failure is loud and immediate: expenses, shifts, PDF generation.

### A gap tests of this shape cannot close

Every mocked test passed while `ask_claude` crashed on a live call, because the mock
returned `content[0].text` — encoding the same wrong assumption the code did. Mocks
verify that the code does what was intended; they cannot verify the intention. The
things that caught the real bugs on 2026-07-28 were live calls against real data. Budget
for that separately from the suite: it is not a coverage number that fixes it.
