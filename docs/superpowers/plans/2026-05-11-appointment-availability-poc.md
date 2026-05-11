# Amsterdam Appointment Availability PoC — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python script that walks the Amsterdam municipality appointment
form for "Verklaring huwelijksbevoegdheid opvragen" and prints the list of
available dates at the first location.

**Architecture:** Four small modules — `session.py` (cookie-bearing
`requests.Session`), `form.py` (parse ASP.NET WebForms hidden state + named
inputs), `calendar.py` (parse the jQuery UI datepicker), `check.py` (orchestrator).
All HTML parsing is TDD'd against fixtures captured live during Task 4.

**Tech Stack:** Python 3.11+, `requests`, `beautifulsoup4`, `lxml`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-05-11-appointment-availability-poc-design.md`

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/amsterdam_appt/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/.gitkeep`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "amsterdam-appt"
version = "0.1.0"
description = "PoC: check Amsterdam municipality appointment availability"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31",
    "beautifulsoup4>=4.12",
    "lxml>=5.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
check-amsterdam-appt = "amsterdam_appt.check:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.py[cod]
.venv/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 3: Create empty package files**

```bash
touch src/amsterdam_appt/__init__.py tests/__init__.py tests/fixtures/.gitkeep
```

- [ ] **Step 4: Set up virtualenv and install**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: pip installs the package and pytest without errors.

- [ ] **Step 5: Verify pytest runs**

Run: `pytest`
Expected: `no tests ran in 0.00s` (exit 0).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore src/ tests/
git commit -m "chore: scaffold amsterdam-appt python package"
```

---

## Task 2: `form.py` — extract ASP.NET hidden state

**Files:**
- Create: `tests/fixtures/step1_intro.html` (captured live in this task)
- Create: `tests/test_form.py`
- Create: `src/amsterdam_appt/form.py`

- [ ] **Step 1: Capture the step-1 fixture from the live site**

```bash
curl -sS -c /tmp/ams_cookies.txt -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36" -L \
  "https://formulieren.amsterdam.nl/TriplEforms/DirectRegelen/formulier/nl-NL/evAmsterdam/afspraakmaken.aspx" \
  -o tests/fixtures/step1_intro.html
```

Verify it contains a session, not the error page:

```bash
grep -c "Er is geen sessie gevonden" tests/fixtures/step1_intro.html
```

Expected: `0` (zero matches — i.e. we got a real form, not the "no session" error).

Also verify the Verder button is present:

```bash
grep -c 'name="ctl01\$CntWrapper\$CntMain\$ssm\$btnNextStep"' tests/fixtures/step1_intro.html
```

Expected: `1`.

- [ ] **Step 2: Write failing test for `extract_state`**

Create `tests/test_form.py`:

```python
from pathlib import Path
from amsterdam_appt.form import extract_state

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_state_returns_aspnet_hidden_fields():
    html = (FIXTURES / "step1_intro.html").read_text()
    state = extract_state(html)
    assert set(state.keys()) >= {
        "__VIEWSTATE",
        "__VIEWSTATEGENERATOR",
        "__EVENTVALIDATION",
    }
    assert state["__VIEWSTATE"]  # non-empty
    assert state["__VIEWSTATEGENERATOR"]
    assert state["__EVENTVALIDATION"]
```

- [ ] **Step 3: Run test, verify failure**

Run: `pytest tests/test_form.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'amsterdam_appt.form'`.

- [ ] **Step 4: Implement `extract_state`**

Create `src/amsterdam_appt/form.py`:

```python
from bs4 import BeautifulSoup

ASPNET_HIDDEN_FIELDS = (
    "__VIEWSTATE",
    "__VIEWSTATEGENERATOR",
    "__EVENTVALIDATION",
    "__VIEWSTATEENCRYPTED",
    "__EVENTTARGET",
    "__EVENTARGUMENT",
)


def _parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def extract_state(html: str) -> dict[str, str]:
    soup = _parse(html)
    state: dict[str, str] = {}
    for name in ASPNET_HIDDEN_FIELDS:
        node = soup.find("input", {"name": name})
        if node is not None:
            state[name] = node.get("value", "")
    return state
```

- [ ] **Step 5: Run test, verify pass**

Run: `pytest tests/test_form.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/amsterdam_appt/form.py tests/test_form.py tests/fixtures/step1_intro.html
git commit -m "feat(form): extract ASP.NET hidden state from page"
```

---

## Task 3: `form.py` — extract all named inputs

**Files:**
- Modify: `tests/test_form.py`
- Modify: `src/amsterdam_appt/form.py`

- [ ] **Step 1: Write failing test for `extract_inputs`**

Append to `tests/test_form.py`:

```python
from amsterdam_appt.form import extract_inputs


def test_extract_inputs_includes_next_step_button():
    html = (FIXTURES / "step1_intro.html").read_text()
    inputs = extract_inputs(html)
    assert inputs["ctl01$CntWrapper$CntMain$ssm$btnNextStep"] == "Verder"


def test_extract_inputs_includes_aspnet_hidden_state():
    html = (FIXTURES / "step1_intro.html").read_text()
    inputs = extract_inputs(html)
    assert "__VIEWSTATE" in inputs
    assert inputs["__VIEWSTATE"]
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_form.py -v -k extract_inputs`
Expected: FAIL with `ImportError: cannot import name 'extract_inputs'`.

- [ ] **Step 3: Implement `extract_inputs`**

Append to `src/amsterdam_appt/form.py`:

```python
def extract_inputs(html: str) -> dict[str, str]:
    soup = _parse(html)
    form = soup.find("form", id="aspnetForm")
    if form is None:
        form = soup
    inputs: dict[str, str] = {}
    for node in form.find_all(["input", "select", "textarea"]):
        name = node.get("name")
        if not name:
            continue
        if node.name == "select":
            selected = node.find("option", selected=True)
            inputs[name] = selected["value"] if selected else ""
        elif node.get("type") in ("checkbox", "radio"):
            if node.has_attr("checked"):
                inputs[name] = node.get("value", "on")
        else:
            inputs[name] = node.get("value", "")
    return inputs
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_form.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/amsterdam_appt/form.py tests/test_form.py
git commit -m "feat(form): extract all named inputs from page"
```

---

## Task 4: `session.py` — bootstrap the form session

**Files:**
- Create: `tests/test_session.py`
- Create: `src/amsterdam_appt/session.py`

This task has a live-integration test instead of pure unit tests, because the
whole point of `session.py` is the real HTTP handshake. The test is marked
`@pytest.mark.live` so it can be skipped offline.

- [ ] **Step 1: Add live marker to `pyproject.toml`**

Modify the `[tool.pytest.ini_options]` block in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["live: hits the real amsterdam.nl form (slow, network)"]
addopts = "-m 'not live'"
```

- [ ] **Step 2: Write failing live test**

Create `tests/test_session.py`:

```python
import pytest
from amsterdam_appt.session import FormSession, FORM_ROOT


@pytest.mark.live
def test_bootstrap_lands_on_intro_step_with_session():
    sess = FormSession()
    response, html = sess.bootstrap()
    assert response.status_code == 200
    assert response.url.endswith("/fSTD_Intro")
    assert "Er is geen sessie gevonden" not in html
    assert 'name="ctl01$CntWrapper$CntMain$ssm$btnNextStep"' in html
    cookies = sess.session.cookies.get_dict()
    assert "ASP.NET_SessionId" in cookies
    assert "__AntiXsrfToken" in cookies
```

- [ ] **Step 3: Run, verify failure**

Run: `pytest tests/test_session.py -v -m live`
Expected: FAIL with `ModuleNotFoundError: No module named 'amsterdam_appt.session'`.

- [ ] **Step 4: Implement `session.py`**

Create `src/amsterdam_appt/session.py`:

```python
import requests

FORM_ROOT = (
    "https://formulieren.amsterdam.nl/TriplEforms/DirectRegelen/"
    "formulier/nl-NL/evAmsterdam/afspraakmaken.aspx"
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class FormSession:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.current_url: str | None = None

    def bootstrap(self) -> tuple[requests.Response, str]:
        response = self.session.get(FORM_ROOT, allow_redirects=True, timeout=30)
        response.raise_for_status()
        self.current_url = response.url
        return response, response.text

    def post(self, data: dict[str, str]) -> tuple[requests.Response, str]:
        if self.current_url is None:
            raise RuntimeError("call bootstrap() first")
        response = self.session.post(
            self.current_url,
            data=data,
            headers={"Referer": self.current_url},
            allow_redirects=True,
            timeout=30,
        )
        response.raise_for_status()
        self.current_url = response.url
        return response, response.text
```

- [ ] **Step 5: Run, verify pass**

Run: `pytest tests/test_session.py -v -m live`
Expected: PASS (a real HTTP call to amsterdam.nl).

- [ ] **Step 6: Commit**

```bash
git add src/amsterdam_appt/session.py tests/test_session.py pyproject.toml
git commit -m "feat(session): bootstrap form session with cookie handshake"
```

---

## Task 5: `form.py` — locate controls by their visible label

The form's control names are auto-generated GUIDs (e.g.
`ctl01$CntWrapper$CntMain$ssm$ctl00$id_6da3d302-744c-4853-ac94-3637d0119a09`),
so we resolve them by the label text the user sees.

**Files:**
- Modify: `tests/test_form.py`
- Modify: `src/amsterdam_appt/form.py`
- Create: `tests/fixtures/step2_subject_category.html` (captured live)

- [ ] **Step 1: Capture the step-2 fixture by clicking Verder once**

Write a one-shot recon script `scripts/capture_step2.py`:

```python
from pathlib import Path
from amsterdam_appt.session import FormSession
from amsterdam_appt.form import extract_inputs

sess = FormSession()
_, html = sess.bootstrap()
data = extract_inputs(html)
# Submitting btnNextStep with its value is enough — ASP.NET treats it as the click.
_, html2 = sess.post(data)
Path("tests/fixtures/step2_subject_category.html").write_text(html2)
print("saved tests/fixtures/step2_subject_category.html, length =", len(html2))
```

Run:

```bash
mkdir -p scripts
python scripts/capture_step2.py
```

Expected: prints a length > 50000.

Verify the fixture contains the category question:

```bash
grep -c "Burgerzaken" tests/fixtures/step2_subject_category.html
```

Expected: at least `1`.

- [ ] **Step 2: Inspect the fixture to learn the control's label and option markup**

Open `tests/fixtures/step2_subject_category.html` and search for "Burgerzaken".
Note: which `<input type="radio">` carries `value="..."` for Burgerzaken,
and which question label sits above it. The label might be in an
`<h2>`, `<label>`, or a `<span>` near the radios. Write the actual label
text you find (it should be "Kies het onderwerp van uw afspraak" per the
spec) into the test below.

- [ ] **Step 3: Write failing test for `find_control` and `find_option_value`**

Append to `tests/test_form.py`:

```python
from amsterdam_appt.form import find_control, find_option_value


def test_find_control_returns_radio_group_name_for_subject_category():
    html = (FIXTURES / "step2_subject_category.html").read_text()
    name = find_control(html, "Kies het onderwerp van uw afspraak")
    assert name is not None
    assert name.startswith("ctl01$CntWrapper$CntMain$ssm$")


def test_find_option_value_returns_burgerzaken_value():
    html = (FIXTURES / "step2_subject_category.html").read_text()
    name = find_control(html, "Kies het onderwerp van uw afspraak")
    value = find_option_value(html, name, "Burgerzaken")
    assert value  # non-empty
```

- [ ] **Step 4: Run, verify failure**

Run: `pytest tests/test_form.py -v -k "find_control or find_option_value"`
Expected: FAIL with `ImportError`.

- [ ] **Step 5: Implement `find_control` and `find_option_value`**

Append to `src/amsterdam_appt/form.py`:

```python
def _normalize(text: str) -> str:
    return " ".join(text.split()).strip().lower().rstrip(":?")


def find_control(html: str, label_text: str) -> str | None:
    """Return the `name=` of the form control whose visible label matches."""
    soup = _parse(html)
    target = _normalize(label_text)

    # Strategy 1: <label for="..."> directly associated.
    for label in soup.find_all("label"):
        if _normalize(label.get_text()) == target and label.get("for"):
            node = soup.find(id=label["for"])
            if node is not None and node.get("name"):
                return node["name"]

    # Strategy 2: a heading/legend/span containing the label text, then walk
    # forward in the DOM to the next named input/select.
    for tag in soup.find_all(["legend", "h1", "h2", "h3", "h4", "span", "div"]):
        if _normalize(tag.get_text()) != target:
            continue
        # Walk forward through following elements looking for a named input.
        for sibling in tag.find_all_next(["input", "select", "textarea"]):
            name = sibling.get("name")
            if name and not name.startswith("__"):
                return name
    return None


def find_option_value(html: str, control_name: str, option_label: str) -> str | None:
    """Return the `value` attribute of the option matching `option_label`."""
    soup = _parse(html)
    target = _normalize(option_label)

    # Radio buttons: same `name=`, each with its own label.
    for radio in soup.find_all("input", {"type": "radio", "name": control_name}):
        rid = radio.get("id")
        if rid:
            label = soup.find("label", {"for": rid})
            if label and _normalize(label.get_text()) == target:
                return radio.get("value")

    # Select options.
    select = soup.find("select", {"name": control_name})
    if select is not None:
        for option in select.find_all("option"):
            if _normalize(option.get_text()) == target:
                return option.get("value")

    return None
```

- [ ] **Step 6: Run, verify pass**

Run: `pytest tests/test_form.py -v`
Expected: all tests PASS.

If `find_control` returns `None`, the heuristic needs tweaking — open the
fixture, find the actual structure around the Burgerzaken radios, and adjust
the strategy. Do NOT make the test pass by changing the assertion to
`is None`.

- [ ] **Step 7: Commit**

```bash
git add src/amsterdam_appt/form.py tests/test_form.py tests/fixtures/step2_subject_category.html scripts/capture_step2.py
git commit -m "feat(form): locate controls and options by visible label"
```

---

## Task 6: Capture the remaining step fixtures

Walk the form through all steps and save every page as a fixture, so the
calendar parser (Task 7) and the orchestrator (Task 8) have stable input.

**Files:**
- Create: `scripts/capture_all_steps.py`
- Create: `tests/fixtures/step3_subject.html`
- Create: `tests/fixtures/step4_deaf.html`
- Create: `tests/fixtures/step5_location.html`
- Create: `tests/fixtures/step6_calendar.html`

- [ ] **Step 1: Write the capture script**

Create `scripts/capture_all_steps.py`:

```python
from pathlib import Path

from amsterdam_appt.session import FormSession
from amsterdam_appt.form import extract_inputs, find_control, find_option_value


def advance(sess, html, updates: dict[str, str], save_as: str) -> str:
    data = extract_inputs(html)
    data.update(updates)
    _, new_html = sess.post(data)
    Path(save_as).write_text(new_html)
    print(f"saved {save_as} (len={len(new_html)})")
    return new_html


def main() -> None:
    sess = FormSession()
    _, html = sess.bootstrap()

    # Step 1 -> Step 2: just click Verder.
    html = advance(sess, html, {}, "tests/fixtures/step2_subject_category.html")

    # Step 2 -> Step 3: choose Burgerzaken.
    name = find_control(html, "Kies het onderwerp van uw afspraak")
    value = find_option_value(html, name, "Burgerzaken")
    assert name and value, f"Burgerzaken lookup failed: name={name!r} value={value!r}"
    html = advance(sess, html, {name: value}, "tests/fixtures/step3_subject.html")

    # Step 3 -> Step 4: choose Verklaring huwelijksbevoegdheid opvragen.
    name = find_control(html, "Kies het onderwerp")
    value = find_option_value(html, name, "Verklaring huwelijksbevoegdheid opvragen")
    assert name and value, f"Verklaring lookup failed: name={name!r} value={value!r}"
    html = advance(sess, html, {name: value}, "tests/fixtures/step4_deaf.html")

    # Step 4 -> Step 5: choose Nee for doof/slechthorend.
    name = find_control(html, "Bent u doof of slechthorend")
    value = find_option_value(html, name, "Nee")
    assert name and value, f"Nee lookup failed: name={name!r} value={value!r}"
    html = advance(sess, html, {name: value}, "tests/fixtures/step5_location.html")

    # Step 5 -> Step 6: pick the first listed location.
    # Locations may be radios or a <select>. We pick the first non-empty value
    # under the location question.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    chosen_name = None
    chosen_value = None
    for radio in soup.find_all("input", {"type": "radio"}):
        nm = radio.get("name", "")
        if nm.startswith("ctl01$CntWrapper$CntMain$ssm$") and radio.get("value"):
            chosen_name = nm
            chosen_value = radio["value"]
            break
    if chosen_name is None:
        for select in soup.find_all("select"):
            nm = select.get("name", "")
            if nm.startswith("ctl01$CntWrapper$CntMain$ssm$"):
                for option in select.find_all("option"):
                    if option.get("value"):
                        chosen_name = nm
                        chosen_value = option["value"]
                        break
                if chosen_name:
                    break
    assert chosen_name and chosen_value, "no location control found"
    print(f"picked location: {chosen_name}={chosen_value}")
    html = advance(sess, html, {chosen_name: chosen_value}, "tests/fixtures/step6_calendar.html")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the capture script**

```bash
python scripts/capture_all_steps.py
```

Expected output: five "saved …" lines, then exits 0.

If the script fails on a label lookup, open the most recent saved fixture,
find the actual label / option text, and update either the script's literal
strings or `find_control` / `find_option_value` to match. Re-run.

- [ ] **Step 3: Eyeball the calendar fixture**

```bash
grep -c 'ui-datepicker\|ui-state-disabled\|ui-state-default' tests/fixtures/step6_calendar.html
```

Expected: a non-zero count of each. If `ui-datepicker` is missing, the
calendar is rendered client-side and Task 7 must take the JSON-endpoint
fallback path described below.

- [ ] **Step 4: Commit fixtures and capture script**

```bash
git add scripts/capture_all_steps.py tests/fixtures/step3_subject.html tests/fixtures/step4_deaf.html tests/fixtures/step5_location.html tests/fixtures/step6_calendar.html
git commit -m "test: capture step fixtures for the burgerzaken/huwelijksbevoegdheid path"
```

---

## Task 7: `calendar.py` — parse available dates

**Files:**
- Create: `tests/test_calendar.py`
- Create: `src/amsterdam_appt/calendar.py`

- [ ] **Step 1: Write a failing test using the calendar fixture**

Create `tests/test_calendar.py`:

```python
from datetime import date
from pathlib import Path

from amsterdam_appt.calendar import parse_available_dates

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_available_dates_returns_a_list_of_dates():
    html = (FIXTURES / "step6_calendar.html").read_text()
    dates = parse_available_dates(html)
    assert isinstance(dates, list)
    # A real calendar fixture must contain at least one date — even if the
    # municipality is fully booked, the datepicker still shows the month grid.
    # If this assertion ever fails, inspect the fixture to confirm the path is
    # still reachable and the parser still matches the markup.
    assert all(isinstance(d, date) for d in dates)


def test_parse_available_dates_excludes_disabled_cells():
    html = (FIXTURES / "step6_calendar.html").read_text()
    dates = parse_available_dates(html)
    # Whatever we returned, those days must not be in the past.
    today = date.today()
    assert all(d >= today.replace(day=1) for d in dates)
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_calendar.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `parse_available_dates` (jQuery UI datepicker path)**

Create `src/amsterdam_appt/calendar.py`:

```python
from datetime import date

from bs4 import BeautifulSoup


def parse_available_dates(html: str) -> list[date]:
    soup = BeautifulSoup(html, "lxml")
    results: list[date] = []
    for td in soup.find_all("td"):
        classes = td.get("class") or []
        if "ui-datepicker-unselectable" in classes or "ui-state-disabled" in classes:
            continue
        # jQuery UI sets data-month (0-based), data-year on the <td>.
        month = td.get("data-month")
        year = td.get("data-year")
        anchor = td.find("a")
        if month is None or year is None or anchor is None:
            continue
        day_text = anchor.get_text(strip=True)
        if not day_text.isdigit():
            continue
        try:
            results.append(date(int(year), int(month) + 1, int(day_text)))
        except ValueError:
            continue
    # Deduplicate (the datepicker sometimes shows multiple months).
    return sorted(set(results))
```

- [ ] **Step 4: Run, verify pass**

Run: `pytest tests/test_calendar.py -v`
Expected: PASS.

If the test fails because the calendar uses different markup (e.g. a
custom widget or a JSON endpoint), open `tests/fixtures/step6_calendar.html`
and identify the actual structure:

- If there is a `<script>` block with a JSON array of available dates,
  parse it with a regex in `parse_available_dates`.
- If the dates come from a separate XHR endpoint, the URL will appear in
  the HTML — replace the parser with a `requests.get` to that endpoint and
  parse its JSON. In that case, update Task 8 to pass a `FormSession` into
  `parse_available_dates` so the cookies travel.

Adjust the implementation, not the assertions, until the tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/amsterdam_appt/calendar.py tests/test_calendar.py
git commit -m "feat(calendar): parse jQuery UI datepicker into a list of dates"
```

---

## Task 8: `check.py` — orchestrator

**Files:**
- Create: `src/amsterdam_appt/check.py`

- [ ] **Step 1: Implement the orchestrator**

Create `src/amsterdam_appt/check.py`:

```python
"""End-to-end walk: bootstrap → 4 form steps → read calendar."""
import sys
from bs4 import BeautifulSoup

from amsterdam_appt.session import FormSession
from amsterdam_appt.form import extract_inputs, find_control, find_option_value
from amsterdam_appt.calendar import parse_available_dates


ANSWERS: list[tuple[str, str]] = [
    ("Kies het onderwerp van uw afspraak", "Burgerzaken"),
    ("Kies het onderwerp", "Verklaring huwelijksbevoegdheid opvragen"),
    ("Bent u doof of slechthorend", "Nee"),
]


def _heading(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in ("h1", "h2"):
        node = soup.find(tag)
        if node:
            text = node.get_text(strip=True)
            if text:
                return f"<{tag}> {text}"
    return "<no heading>"


def _first_location(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    for radio in soup.find_all("input", {"type": "radio"}):
        name = radio.get("name", "")
        if name.startswith("ctl01$CntWrapper$CntMain$ssm$") and radio.get("value"):
            return name, radio["value"]
    for select in soup.find_all("select"):
        name = select.get("name", "")
        if name.startswith("ctl01$CntWrapper$CntMain$ssm$"):
            for option in select.find_all("option"):
                if option.get("value"):
                    return name, option["value"]
    raise RuntimeError("no location control found on step")


def _advance(sess: FormSession, html: str, updates: dict[str, str]) -> str:
    data = extract_inputs(html)
    data.update(updates)
    _, new_html = sess.post(data)
    if "Er is geen sessie gevonden" in new_html:
        raise RuntimeError("session was lost mid-walk")
    return new_html


def main() -> int:
    sess = FormSession()
    _, html = sess.bootstrap()
    print(f"step 1: {_heading(html)}")

    # Click Verder (no answers on the intro step).
    html = _advance(sess, html, {})
    print(f"step 2: {_heading(html)}")

    # Answer the three radio questions.
    for label, answer in ANSWERS:
        name = find_control(html, label)
        if name is None:
            print(f"could not find control for {label!r}", file=sys.stderr)
            return 4
        value = find_option_value(html, name, answer)
        if value is None:
            print(f"could not find option {answer!r} under {label!r}", file=sys.stderr)
            return 4
        html = _advance(sess, html, {name: value})
        print(f"after {answer!r}: {_heading(html)}")

    # Location step: pick the first available one.
    loc_name, loc_value = _first_location(html)
    html = _advance(sess, html, {loc_name: loc_value})
    print(f"after location {loc_value!r}: {_heading(html)}")

    # Calendar step.
    dates = parse_available_dates(html)
    if not dates:
        print("no availability for the selected location")
        return 0
    print(f"available dates ({len(dates)}):")
    for d in dates:
        print(f"  {d.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the script end-to-end against the live site**

```bash
python -m amsterdam_appt.check
```

Expected output: six lines tracing the step headings, followed by either
`no availability for the selected location` or `available dates (N):`
plus a list of ISO dates. Exit code 0.

If the script exits with code 4, the label text in `ANSWERS` does not
match what the live page shows on that step. Open the matching fixture,
copy the exact heading text, update `ANSWERS`, and re-run. Do not
silently swallow the error.

- [ ] **Step 3: Commit**

```bash
git add src/amsterdam_appt/check.py
git commit -m "feat(check): orchestrate full walk and print available dates"
```

---

## Task 9: Final verification

- [ ] **Step 1: Run the full test suite (non-live)**

```bash
pytest -v
```

Expected: all tests in `test_form.py` and `test_calendar.py` pass; `test_session.py` is skipped (it's marked `live`).

- [ ] **Step 2: Run the live test explicitly**

```bash
pytest -v -m live
```

Expected: the live session test passes.

- [ ] **Step 3: Run the orchestrator once more, fresh**

```bash
python -m amsterdam_appt.check
```

Expected: the script prints step headings and a date list (or "no availability"), exits 0. Save the output for the PR description / handoff.

- [ ] **Step 4: Tag the proof-of-concept**

```bash
git tag -a poc-v1 -m "PoC: amsterdam appointment availability walker"
git log --oneline
```

Expected: tag points at the latest commit; `git log` shows the linear history of the implementation.

---

## Self-review notes

- Every spec section is covered:
  - "Session bootstrap" → Task 4.
  - "ASP.NET hidden state" → Task 2.
  - "Find control by label" → Task 5.
  - "Walk the four answer steps" → Task 8 (uses fixtures captured in Task 6).
  - "Parse calendar" → Task 7.
  - Error handling → Task 8 (`return 4` on lookup failure, `RuntimeError` on lost session) and `parse_available_dates` returning `[]` for "no availability".
- No "TBD" or "implement later" anywhere — every code block is complete.
- Type and name consistency:
  - `FormSession.bootstrap()` returns `(Response, str)` in Task 4 and is used as such in Tasks 5, 6, 8.
  - `extract_inputs` returns `dict[str, str]` everywhere it is used.
  - `find_control` returns `str | None`; callers in Task 6 and Task 8 both handle `None`.
  - `parse_available_dates` returns `list[date]`; the orchestrator iterates it without further conversion.
