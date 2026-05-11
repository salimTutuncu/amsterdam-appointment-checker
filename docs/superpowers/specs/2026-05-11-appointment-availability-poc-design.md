# Amsterdam Municipality Appointment Availability — PoC Design

## Goal

Prove that available appointment dates can be discovered programmatically from
the Amsterdam municipality online-appointment form, without a login, for this
specific path:

1. `https://formulieren.amsterdam.nl/TriplEforms/DirectRegelen/formulier/nl-NL/evAmsterdam/afspraakmaken.aspx`
2. Click **Verder** (intro).
3. *Kies het onderwerp van uw afspraak:* **Burgerzaken**.
4. *Kies het onderwerp:* **Verklaring huwelijksbevoegdheid opvragen**.
5. *Bent u doof of slechthorend?* **Nee**.
6. Pick any location.
7. Read off the available dates from the calendar.

The script's success criterion: on a single run, print a non-empty list of
available appointment dates (or a clear "no availability" message), exit 0.

## Non-goals

- Notifications, scheduling, polling, persistence.
- Comparing availability across locations.
- Booking the appointment — the script stops at the date list.
- Retry/backoff, packaging, distribution.
- Any other form path or municipality.

## Background — what recon told us

The form is an Atabix TriplEforms 5.1.15.0 application on ASP.NET WebForms.
Empirically confirmed via `curl`:

- `GET /…/afspraakmaken.aspx` returns **302** to `/…/afspraakmaken.aspx/fSTD_Intro`
  and sets two cookies: `__AntiXsrfToken` and `ASP.NET_SessionId`. Hitting
  `/fSTD_Intro` directly returns the page with body "Er is geen sessie gevonden"
  — so the bootstrap GET is mandatory.
- Each step is a server-rendered HTML form. Hidden fields `__VIEWSTATE`,
  `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION` (plus empty `__EVENTTARGET`,
  `__EVENTARGUMENT`, `__VIEWSTATEENCRYPTED`) must be echoed back on every POST.
- The "Verder" button is `name="ctl01$CntWrapper$CntMain$ssm$btnNextStep"`
  with `value="Verder"`. Submitting that name=value pair advances the form.
- No CAPTCHA or anti-bot challenges were observed on the first step.
- Navigation works **without** running any JavaScript.

Unknowns (will be discovered while walking the form):

- The exact `name=` attributes for the four answer controls (Burgerzaken radio,
  subject dropdown, doof/slechthorend radio, location selector).
- Whether the location step uses a normal postback or an ASP.NET partial
  postback (`Sys.WebForms.PageRequestManager`).
- The HTML structure of the calendar — most likely jQuery UI datepicker, where
  available days are `<a>` tags inside `<td>` cells lacking the
  `ui-state-disabled` class. To be confirmed when we reach that step.

## Architecture

A single Python 3.11+ script, split across four small modules for clarity and
testability. ~150 LOC total.

```
amsterdam_appt/
├── check.py        # CLI entry point: walk the form, print dates
├── session.py      # requests.Session wrapper + bootstrap GET
├── form.py         # parse ASP.NET hidden fields + named inputs
└── calendar.py     # parse the calendar step into a list[date]
```

Dependencies: `requests`, `beautifulsoup4`, `lxml`. No async, no headless
browser.

### `session.py`

- One class `FormSession` wrapping a `requests.Session`.
- `bootstrap()` performs the `GET afspraakmaken.aspx` that primes cookies.
- `get(path)` / `post(path, data)` are thin wrappers that set a realistic
  `User-Agent` and `Referer`, and return `(response, parsed_html)`.

### `form.py`

- `extract_state(html) -> dict[str, str]` — returns the four ASP.NET hidden
  fields needed for the next POST.
- `extract_inputs(html) -> dict[str, str]` — every `<input>` / `<select>` /
  `<textarea>` under `#aspnetForm` with its current value, so we can echo
  unchanged controls.
- `find_control(html, label_text) -> str` — given the visible label of a
  question ("Kies het onderwerp van uw afspraak"), return the `name=`
  attribute of the associated form control. This is how we stay resilient to
  the framework's auto-generated `ctl01$…$id_<guid>` names.
- `find_option_value(html, control_name, option_label) -> str` — given a
  control and a human-readable option ("Burgerzaken"), return the `value`
  attribute to send.

### `check.py`

Hard-coded answer script, expressed as a list of `(question_label, answer_label)`
pairs:

```python
ANSWERS = [
    ("Kies het onderwerp van uw afspraak", "Burgerzaken"),
    ("Kies het onderwerp", "Verklaring huwelijksbevoegdheid opvragen"),
    ("Bent u doof of slechthorend", "Nee"),
    # Location: pick the first available option.
]
```

Algorithm:

1. `FormSession.bootstrap()` to land on step 1 with cookies.
2. Click Verder.
3. For each `(label, answer)` pair: locate the control, set its value, click
   Verder.
4. On the location step: enumerate options, pick the first one, click Verder.
5. On the calendar step: hand the HTML to `calendar.py`.

After each POST, log the new step's heading (`<h1>` or `<h2>`) so a human can
visually verify we're on the right step.

### `calendar.py`

- `parse_available_dates(html) -> list[date]`.
- Strategy: look for `<td>` elements inside the datepicker table that do
  **not** have `ui-state-disabled` and contain a clickable `<a>`. The `data-*`
  attributes on the cell (month, year, day) give the date.
- If the framework uses a JSON endpoint instead, this module is the only place
  that needs to change — the rest of the walker is unaffected.

## Error handling

Only at known failure points. No defensive try/except around everything.

- **Bootstrap failure** (no cookies set, or non-200 final response): print the
  HTTP status, exit 2.
- **"Er is geen sessie gevonden" body**: session was lost — print the message,
  exit 3.
- **`find_control` / `find_option_value` returns None**: print the label we
  looked for and the labels we *did* find on that step, exit 4. This is the
  main self-debugging hook.
- **Calendar has zero available dates**: that's a valid result — print "no
  availability for <location>", exit 0.

## Risks and fallbacks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Location step uses partial postback (`__ASYNCPOST=true`) | Medium | Detect by inspecting the response; if so, send the partial-postback content-type and parse the delta response. If too hairy, ask the user for a HAR capture. |
| Calendar is rendered client-side from a JSON endpoint | Medium | Inspect network requests via HAR if HTML parsing returns nothing usable; replace `calendar.py` with a call to that endpoint. |
| Server-side bot detection blocks plain `requests` | Low (none observed in recon) | Already using a browser-like UA and full cookie jar. If blocked, fall back to Playwright per the original brainstorm. |
| TriplEforms invalidates the session after N seconds of inactivity | Low | Walk the form in a single linear run; do not pause between steps. |

## Testing

- **Manual end-to-end**: run `python -m amsterdam_appt.check` and verify it
  prints step headings in the expected order and ends with a date list.
- **Unit tests** for `form.py` and `calendar.py` using saved HTML fixtures
  (one per step, captured during the first successful run). These let us
  iterate on parsing logic without re-hitting the live site.
- No tests for `session.py` — it's a thin wrapper.

## Out of scope (explicit)

Listed separately so future-me doesn't accidentally creep:

- Multiple subject paths.
- Caching, rate limiting, retries.
- Notifications (email, desktop, Telegram).
- Cron / scheduling.
- A web UI or API around the script.
- Booking the appointment.
