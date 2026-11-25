"""Find the monthly "Full CSV data file" downloads published by NHS England.

The statistics site is WordPress. Its HTML pages ask automated clients to pass a
browser challenge, but its public media API and the files themselves are served
directly, so WaitLens lists the ZIP files through the API and only falls back to
reading the yearly HTML pages if the API finds nothing.
"""

from __future__ import annotations

import datetime as dt
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

YEAR_PAGE = "https://www.england.nhs.uk/statistics/statistical-work-areas/rtt-waiting-times/rtt-data-{year}/"
MEDIA_API = "https://www.england.nhs.uk/statistics/wp-json/wp/v2/media"

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
_FILE_NAME = re.compile(
    r"full[-_ ]csv[-_ ]data[-_ ]file[-_ ]([a-z]{3})[a-z]*[-_ ]?(\d{2,4})(.*)", re.IGNORECASE
)


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
        period = _period(match.group(1), match.group(2))
        if period is None:
            continue
        revised = "revis" in match.group(3).lower() or "revis" in href.lower()
        url = urljoin(base_url, href)
        current = found.get(period)
        if current is None or (revised and not current[0]):
            found[period] = (revised, url)
    return {period: url for period, (_, url) in sorted(found.items())}


def _period(month_text: str, year_text: str) -> str | None:
    month = _MONTH_ABBR.get(month_text.lower())
    if month is None:
        return None
    year = int(year_text)
    year = year + 2000 if year < 100 else year
    return f"{year:04d}-{month:02d}"


def parse_media_items(items: list[dict]) -> dict[str, str]:
    """Return {"YYYY-MM": url} from WordPress media API items, preferring revised then newer uploads."""
    best: dict[str, tuple[bool, str, str]] = {}
    for item in items:
        url = str(item.get("source_url") or "")
        name = url.rsplit("/", 1)[-1]
        if not name.lower().endswith(".zip"):
            continue
        match = _FILE_NAME.search(name)
        if not match:
            continue
        period = _period(match.group(1), match.group(2))
        if period is None:
            continue
        rank = ("revis" in match.group(3).lower(), str(item.get("date") or ""), url)
        if period not in best or rank > best[period]:
            best[period] = rank
    return {period: rank[2] for period, rank in sorted(best.items())}


def discover_media(session, pages: int = 10) -> dict[str, str]:
    """List the Full CSV ZIPs through the statistics site's public WordPress media API."""
    items: list[dict] = []
    for page in range(1, pages + 1):
        params = {
            "search": "Full-CSV-data-file",
            "per_page": 100,
            "page": page,
            "orderby": "date",
            "order": "desc",
            "_fields": "id,date,source_url,title",
        }
        response = session.get(MEDIA_API, params=params, timeout=60)
        if response.status_code == 400:  # WordPress answers 400 past the last page
            break
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
    return parse_media_items(items)


def discover(session, years: int = 3, today: dt.date | None = None) -> dict[str, str]:
    """Return {"YYYY-MM": zip_url}, oldest first, from the media API or else the yearly pages."""
    notes = []
    try:
        links = discover_media(session)
        if links:
            return links
        notes.append(f"{MEDIA_API}: no Full CSV data files listed")
    except Exception as exc:  # fall back to the HTML pages
        notes.append(f"{MEDIA_API}: {exc}")
    today = today or dt.date.today()
    links = {}
    for year in financial_years(today, years):
        url = YEAR_PAGE.format(year=year)
        response = session.get(url, timeout=60)
        if response.status_code != 200:
            waf = response.headers.get("x-amzn-waf-action") if hasattr(response, "headers") else None
            notes.append(f"{url}: HTTP {response.status_code}" + (f" (WAF {waf})" if waf else ""))
            continue
        found = parse_full_csv_links(response.text, url)
        if not found:
            notes.append(f"{url}: {describe_page(response.text)}")
        for period, link in found.items():
            links.setdefault(period, link)
    if not links:
        raise RuntimeError("No 'Full CSV data file' links found on the RTT pages.\n" + "\n".join(notes))
    return dict(sorted(links.items()))


def describe_page(html: str) -> str:
    """A one-line summary of a page, to explain why no links were found."""
    parser = _Anchors()
    parser.feed(html)
    zips = [text for href, text in parser.links if href and ".zip" in href.lower()]
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    heading = " ".join(title.group(1).split())[:80] if title else "no title"
    sample = "; ".join(zips[:3]) or "none"
    return f"{len(html):,} characters, title {heading!r}, {len(parser.links)} links, ZIP links: {sample}"
