import datetime as dt

import pytest

from waitlens.discover import YEAR_PAGE, discover, financial_years, parse_full_csv_links

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


class FakeResponse:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        return FakeResponse(self.pages.get(url, ""), 200 if url in self.pages else 404)


def test_discover_reads_each_financial_year_page():
    session = FakeSession({YEAR_PAGE.format(year="2026-27"): PAGE})
    links = discover(session, years=2, today=dt.date(2026, 11, 25))
    assert list(links) == ["2026-08", "2026-09"]
    assert session.requested == [YEAR_PAGE.format(year="2026-27"), YEAR_PAGE.format(year="2025-26")]


def test_discover_fails_clearly_when_nothing_is_found():
    with pytest.raises(RuntimeError, match="No 'Full CSV data file' links"):
        discover(FakeSession({}), years=1, today=dt.date(2026, 11, 25))
