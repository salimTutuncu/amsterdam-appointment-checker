"""Walk the Amsterdam municipality appointment form and print available dates.

Path: Burgerzaken -> Verklaring huwelijksbevoegdheid opvragen -> Nee -> all locations.

Usage:
    python check.py                          # full listing, every location
    python check.py --alert-before 2026-05-16  # only print matching (location, date) pairs
"""
import argparse
import sys
from datetime import date

import requests
from bs4 import BeautifulSoup

FORM_ROOT = (
    "https://formulieren.amsterdam.nl/TriplEforms/DirectRegelen/"
    "formulier/nl-NL/evAmsterdam/afspraakmaken.aspx"
)
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

ANSWERS = [
    ("Kies het onderwerp van uw afspraak", "Burgerzaken"),
    ("Waarvoor wilt u een afspraak maken", "Huwelijk of geregistreerd partnerschap"),
    # next step's label will be discovered live — likely a sub-product selector
    (None, "Verklaring huwelijksbevoegdheid opvragen"),
    (None, "Nee"),  # doof/slechthorend
]


def _norm(text: str) -> str:
    return " ".join(text.split()).strip().lower().rstrip(":?")


def extract_inputs(html: str) -> dict[str, str]:
    """Extract hidden + filled form state. Excludes submit buttons — the caller
    must add exactly the one submit button it wants to click."""
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", id="aspnetForm") or soup
    data: dict[str, str] = {}
    for node in form.find_all(["input", "select", "textarea"]):
        name = node.get("name")
        if not name:
            continue
        node_type = node.get("type")
        if node_type in ("submit", "button", "image", "reset"):
            continue
        if node.name == "select":
            selected = node.find("option", selected=True)
            data[name] = selected["value"] if selected else ""
        elif node_type in ("checkbox", "radio"):
            if node.has_attr("checked"):
                data[name] = node.get("value", "on")
        else:
            data[name] = node.get("value", "")
    return data


def forward_button(html: str) -> tuple[str, str]:
    """Find the step's forward-navigation submit button (e.g. Verder, Volgende)."""
    soup = BeautifulSoup(html, "lxml")
    # Intro step's button.
    btn = soup.find("input", {"type": "submit", "name": "ctl01$CntWrapper$CntMain$ssm$btnNextStep"})
    if btn:
        return btn["name"], btn.get("value", "Verder")
    # Per-step "Volgende" button: class contains 'button--next' or 'next-step-button'.
    for cand in soup.find_all("input", {"type": "submit"}):
        classes = " ".join(cand.get("class") or [])
        name = cand.get("name", "")
        if "next" in classes.lower() and "previous" not in classes.lower() and name.startswith("ctl01$CntWrapper$"):
            return name, cand.get("value", "Volgende")
    raise RuntimeError("no forward button found on page")


def find_control(html: str, label_text: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    target = _norm(label_text)
    for label in soup.find_all("label"):
        if _norm(label.get_text()) == target and label.get("for"):
            node = soup.find(id=label["for"])
            if node and node.get("name"):
                return node["name"]
    for tag in soup.find_all(["legend", "h1", "h2", "h3", "h4", "span", "div"]):
        if _norm(tag.get_text()) != target:
            continue
        for sibling in tag.find_all_next(["input", "select", "textarea"]):
            name = sibling.get("name")
            if name and not name.startswith("__"):
                return name
    return None


def find_option_value(html: str, control_name: str, option_label: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    target = _norm(option_label)
    for radio in soup.find_all("input", {"type": "radio", "name": control_name}):
        rid = radio.get("id")
        if rid:
            label = soup.find("label", {"for": rid})
            if label and _norm(label.get_text()) == target:
                return radio.get("value")
    select = soup.find("select", {"name": control_name})
    if select:
        for option in select.find_all("option"):
            if _norm(option.get_text()) == target:
                return option.get("value")
    return None


def find_option_anywhere(html: str, option_label: str) -> tuple[str, str] | None:
    """Search every radio/select on the page for an option matching the label.

    Returns (control_name, option_value) or None.
    """
    soup = BeautifulSoup(html, "lxml")
    target = _norm(option_label)
    main = soup.find("div", id="ctl01_CntWrapper_CntMain_ssm") or soup
    for radio in main.find_all("input", {"type": "radio"}):
        rid = radio.get("id")
        name = radio.get("name", "")
        if not name.startswith("ctl01$CntWrapper$"):
            continue
        if rid:
            label = soup.find("label", {"for": rid})
            if label and _norm(label.get_text()) == target:
                return name, radio.get("value", "")
    for select in main.find_all("select"):
        name = select.get("name", "")
        if not name.startswith("ctl01$CntWrapper$"):
            continue
        for option in select.find_all("option"):
            if _norm(option.get_text()) == target:
                return name, option.get("value", "")
    return None


def all_locations(html: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (control_name, [(value, label), ...]) for every non-placeholder
    location option on the DatumTijd page."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("div", id="ctl01_CntWrapper_CntMain_ssm") or soup
    for select in main.find_all("select"):
        name = select.get("name", "")
        if not name.startswith("ctl01$CntWrapper$CntMain$ssm$"):
            continue
        opts = [
            (o["value"], o.get_text(strip=True))
            for o in select.find_all("option")
            if o.get("value")
        ]
        if opts:
            return name, opts
    raise RuntimeError("no location control found")


DUTCH_MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}


def parse_available_dates(html: str) -> list[date]:
    """Parse the Kodision calendar control. Enabled days have class='enabled'
    and an <a title='DD month'> child. The displayed month header is used to
    pick the year and to detect month rollover."""
    soup = BeautifulSoup(html, "lxml")
    cal = soup.find("table", class_="appointmentControlCalendar")
    if not cal:
        return []
    # Header like "juli 2026" — look for the unique non-link <td> containing year.
    header_month: int | None = None
    header_year: int | None = None
    for td in cal.find_all("td"):
        text = td.get_text(strip=True)
        parts = text.split()
        if len(parts) == 2 and parts[0].lower() in DUTCH_MONTHS and parts[1].isdigit():
            header_month = DUTCH_MONTHS[parts[0].lower()]
            header_year = int(parts[1])
            break
    if header_year is None or header_month is None:
        return []

    out: list[date] = []
    for td in cal.find_all("td", class_="enabled"):
        a = td.find("a")
        if not a:
            continue
        title = a.get("title", "")
        parts = title.split()
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        day = int(parts[0])
        month_name = parts[1].lower()
        if month_name not in DUTCH_MONTHS:
            continue
        month = DUTCH_MONTHS[month_name]
        # Cells from the trailing days of the next month appear at the bottom
        # of the grid (e.g. 3 augustus shown in juli 2026's view).
        if month >= header_month:
            year = header_year
        else:
            year = header_year + 1
        try:
            out.append(date(year, month, day))
        except ValueError:
            continue
    return sorted(set(out))


def step_label(url: str, html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("div", id="ctl01_CntWrapper_CntMain_ssm")
    first_question = ""
    if main:
        for tag in main.find_all(["h2", "h3", "label", "span"]):
            text = tag.get_text(strip=True)
            if text and len(text) > 10 and "Vergeet niet" not in text:
                first_question = text
                break
    return f"{url.rsplit('/', 2)[-2]}/{url.rsplit('/', 1)[-1]}  —  {first_question}"


def walk_to_datumtijd(verbose: bool = False) -> tuple[requests.Session, str, str]:
    """Run a fresh session through intro + the 4 answer steps. Returns
    (session, current_url, current_html) — sitting on the DatumTijd page,
    before any location has been picked."""
    s = requests.Session()
    s.headers["User-Agent"] = UA

    r = s.get(FORM_ROOT, allow_redirects=True, timeout=30)
    r.raise_for_status()
    url, html = r.url, r.text
    if "Er is geen sessie gevonden" in html:
        raise RuntimeError("session bootstrap failed")

    def post(updates: dict[str, str]) -> None:
        nonlocal url, html
        data = extract_inputs(html)
        data.update(updates)
        btn_name, btn_value = forward_button(html)
        data[btn_name] = btn_value
        rr = s.post(url, data=data, headers={"Referer": url}, allow_redirects=True, timeout=30)
        rr.raise_for_status()
        url, html = rr.url, rr.text
        if "Er is geen sessie gevonden" in html:
            raise RuntimeError("session lost mid-walk")

    post({})  # intro -> Categorie

    for label, answer in ANSWERS:
        if label:
            name = find_control(html, label)
            if not name:
                raise RuntimeError(f"no control for {label!r}")
            value = find_option_value(html, name, answer)
            if not value:
                raise RuntimeError(f"no option {answer!r} under {label!r}")
        else:
            found = find_option_anywhere(html, answer)
            if not found:
                raise RuntimeError(f"no option {answer!r} on page")
            name, value = found
        post({name: value})
        if verbose:
            print(f"  after {answer!r}: {step_label(url, html)}", file=sys.stderr)

    if "/DatumTijd" not in url:
        raise RuntimeError(f"expected to land on DatumTijd, got {url}")
    return s, url, html


def availability_for_location(loc_name: str, loc_value: str) -> list[date]:
    """Fresh session: walk to DatumTijd, pick this location, parse the calendar."""
    s, url, html = walk_to_datumtijd()
    data = extract_inputs(html)
    data[loc_name] = loc_value
    btn_name, btn_value = forward_button(html)
    data[btn_name] = btn_value
    rr = s.post(url, data=data, headers={"Referer": url}, timeout=30)
    rr.raise_for_status()
    return parse_available_dates(rr.text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--alert-before",
        metavar="YYYY-MM-DD",
        type=date.fromisoformat,
        help="Print only (location, date) pairs strictly before this date. "
             "When set, the script is silent unless a match is found.",
    )
    args = parser.parse_args(argv)

    print("walking the form once to enumerate locations...", file=sys.stderr)
    _s, _url, html = walk_to_datumtijd(verbose=True)
    loc_name, locations = all_locations(html)
    print(f"found {len(locations)} locations\n", file=sys.stderr)

    matches: list[tuple[str, date]] = []
    for value, label in locations:
        dates = availability_for_location(loc_name, value)
        if args.alert_before is None:
            if not dates:
                print(f"{label}: no availability")
            else:
                first, last = dates[0].isoformat(), dates[-1].isoformat()
                print(f"{label}: {len(dates)} dates ({first} … {last})")
                for d in dates:
                    print(f"    {d.isoformat()}")
        else:
            for d in dates:
                if d < args.alert_before:
                    matches.append((label, d))

    if args.alert_before is not None:
        for label, d in matches:
            print(f"{d.isoformat()}\t{label}")
        print(f"{len(matches)} match(es) before {args.alert_before.isoformat()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
