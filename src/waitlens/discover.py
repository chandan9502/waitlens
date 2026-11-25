"""Find the monthly "Full CSV data file" downloads on NHS England's RTT pages."""

from __future__ import annotations

import datetime as dt
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

YEAR_PAGE = "https://www.england.nhs.uk/statistics/statistical-work-areas/rtt-waiting-times/rtt-data-{year}/"

_MONTH_ABBR = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_LINK_TEXT = re.compile(r"full\s+csv\s+data\s+file\s+([a-z]{3})[a-z]*[\s\-]*(\d{2,4})(.*)", re.IGNORECASE)


class _Anchors(HTMLParser):
    """Collect (href, text) for every link on a page."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def financial_years(today: dt.date, count: int) -> list[str]:
    """NHS financial-year labels ("2026-27") ending with the one containing ``today``."""
    start = today.year if today.month >= 4 else today.year - 1
    return [f"{year}-{(year + 1) % 100:02d}" for year in range(start, start - count, -1)]


def parse_full_csv_links(html: str, base_url: str) -> dict[str, str]:
    """Return {"YYYY-MM": url} for each "Full CSV data file" ZIP linked from ``html``.

    When a month appears twice (original and revised), the revised file wins.
    """
    parser = _Anchors()
    parser.feed(html)
    found: dict[str, tuple[bool, str]] = {}
    for href, text in parser.links:
        if not href or not href.lower().split("?")[0].endswith(".zip"):
            continue
        match = _LINK_TEXT.search(text)
        if not match:
            continue
        month = _MONTH_ABBR.get(match.group(1).lower())
        if month is None:
            continue
        year = int(match.group(2))
        year = year + 2000 if year < 100 else year
        period = f"{year:04d}-{month:02d}"
        revised = "revis" in match.group(3).lower() or "revis" in href.lower()
        url = urljoin(base_url, href)
        current = found.get(period)
        if current is None or (revised and not current[0]):
            found[period] = (revised, url)
    return {period: url for period, (_, url) in sorted(found.items())}


def discover(session, years: int = 3, today: dt.date | None = None) -> dict[str, str]:
    """Fetch the yearly RTT pages and return {"YYYY-MM": zip_url}, oldest first."""
    today = today or dt.date.today()
    links: dict[str, str] = {}
    errors = []
    for year in financial_years(today, years):
        url = YEAR_PAGE.format(year=year)
        response = session.get(url, timeout=60)
        if response.status_code == 404:
            errors.append(f"{url}: 404")
            continue
        response.raise_for_status()
        for period, link in parse_full_csv_links(response.text, url).items():
            links.setdefault(period, link)
    if not links:
        raise RuntimeError("No 'Full CSV data file' links found on the RTT pages. " + "; ".join(errors))
    return dict(sorted(links.items()))
