import datetime as dt

import pytest

from waitlens.discover import (
    MEDIA_API,
    YEAR_PAGE,
    discover,
    discover_media,
    financial_years,
    parse_full_csv_links,
    parse_media_items,
)

PAGE = """
<html><body>
<h3>September 2026</h3>
<p><a href="https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/11/Full-CSV-data-file-Sep26-ZIP-3M-ab12.zip">Full CSV data file Sep26 (ZIP, 3M)</a></p>
<p><a href="/statistics/wp-content/uploads/sites/2/2026/11/Incomplete-Provider-Sep26-XLSX.xlsx">Incomplete Provider Sep26 (XLSX, 7M)</a></p>
<h3>August 2026</h3>
<p><a href="/statistics/wp-content/uploads/sites/2/2026/10/Full-CSV-data-file-Aug26-ZIP-3M-cd34.zip">Full CSV data file
   Aug26 (ZIP, 3M)</a></p>
<p><a href="/statistics/wp-content/uploads/sites/2/2026/11/Full-CSV-data-file-Aug26-revised-ZIP-3M-ef56.zip">Full CSV data file Aug26 revised (ZIP, 3M)</a></p>
<p><a href="/statistics/other.zip">Commissioner list (ZIP)</a></p>
</body></html>
"""


def test_financial_years():
    assert financial_years(dt.date(2026, 11, 25), 3) == ["2026-27", "2025-26", "2024-25"]
    assert financial_years(dt.date(2026, 2, 1), 1) == ["2025-26"]
    assert financial_years(dt.date(2026, 4, 1), 1) == ["2026-27"]


def test_parse_full_csv_links_prefers_revised_files():
    links = parse_full_csv_links(PAGE, "https://www.england.nhs.uk/statistics/x/")
    assert list(links) == ["2026-08", "2026-09"]
    assert links["2026-08"].endswith("Aug26-revised-ZIP-3M-ef56.zip")
    assert links["2026-08"].startswith("https://www.england.nhs.uk/statistics/wp-content/")
    assert links["2026-09"].endswith("Sep26-ZIP-3M-ab12.zip")


UPLOADS = "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2"
MEDIA = [
    {
        "id": 3,
        "date": "2026-11-12T09:30:00",
        "source_url": f"{UPLOADS}/2026/11/Full-CSV-data-file-Sep26-ZIP-3M-ojyW5x.zip",
    },
    {
        "id": 2,
        "date": "2026-10-09T09:30:00",
        "source_url": f"{UPLOADS}/2026/10/Full-CSV-data-file-Aug26-ZIP-3M-aa11.zip",
    },
    {
        "id": 4,
        "date": "2026-11-12T09:31:00",
        "source_url": f"{UPLOADS}/2026/11/Full-CSV-data-file-Aug26-revised-ZIP-3M-bb22.zip",
    },
    {
        "id": 5,
        "date": "2026-11-12T09:32:00",
        "source_url": f"{UPLOADS}/2026/11/Incomplete-Provider-Sep26-XLSX-9M.xlsx",
    },
    {
        "id": 1,
        "date": "2025-03-13T08:00:41",
        "source_url": f"{UPLOADS}/2025/03/Full-CSV-data-file-Jan25-ZIP-3M-cc33.zip",
    },
]


class FakeResponse:
    def __init__(self, text="", status=200, payload=None, headers=None):
        self.text = text
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, pages=None, media=None, media_status=200):
        self.pages = pages or {}
        self.media = media
        self.media_status = media_status
        self.requested = []

    def get(self, url, timeout=None, params=None):
        self.requested.append(url)
        if url == MEDIA_API:
            if self.media_status != 200:
                return FakeResponse(status=self.media_status)
            page = params["page"]
            batch = (self.media or [])[(page - 1) * 100 : page * 100]
            return FakeResponse(payload=batch) if batch or page == 1 else FakeResponse(status=400)
        if url in self.pages:
            return FakeResponse(self.pages[url])
        return FakeResponse(status=202, headers={"x-amzn-waf-action": "challenge"})


def test_parse_media_items_prefers_revised_files_and_ignores_others():
    links = parse_media_items(MEDIA)
    assert list(links) == ["2025-01", "2026-08", "2026-09"]
    assert links["2026-08"].endswith("Aug26-revised-ZIP-3M-bb22.zip")
    assert links["2026-09"].endswith("Sep26-ZIP-3M-ojyW5x.zip")


def test_discover_uses_the_media_api_first():
    session = FakeSession(media=MEDIA)
    links = discover(session, years=1, today=dt.date(2026, 11, 25))
    assert list(links) == ["2025-01", "2026-08", "2026-09"]
    assert session.requested == [MEDIA_API]


def test_discover_media_pages_through_results():
    many = [
        {
            "id": i,
            "date": f"2026-01-{i % 28 + 1:02d}",
            "source_url": f"{UPLOADS}/x/Full-CSV-data-file-Jan{i:02d}-ZIP.zip",
        }
        for i in range(10, 99)
    ] + [{"id": 999, "date": "2026", "source_url": f"{UPLOADS}/x/other-{i}.zip"} for i in range(60)]
    links = discover_media(FakeSession(media=many))
    assert len(links) == 89
    assert links["2010-01"].endswith("Jan10-ZIP.zip")


def test_discover_falls_back_to_the_yearly_pages():
    session = FakeSession(pages={YEAR_PAGE.format(year="2026-27"): PAGE}, media=[])
    links = discover(session, years=2, today=dt.date(2026, 11, 25))
    assert list(links) == ["2026-08", "2026-09"]
    assert session.requested[1:] == [YEAR_PAGE.format(year="2026-27"), YEAR_PAGE.format(year="2025-26")]


def test_discover_explains_what_went_wrong():
    with pytest.raises(
        RuntimeError, match=r"(?s)No 'Full CSV data file' links.*media: 500.*HTTP 202 \(WAF challenge\)"
    ):
        discover(FakeSession(media_status=500), years=1, today=dt.date(2026, 11, 25))
