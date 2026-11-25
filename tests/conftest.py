"""Helpers that write small RTT files with the same layout as NHS England's Full CSV data file.

The numbers are made up. Only the column names and structure follow the real file.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pytest

BAND_COLUMNS = [f"Gt {week:02d} To {week + 1:02d} Weeks SUM 1" for week in range(104)] + [
    "Gt 104 Weeks SUM 1"
]
HEADER = [
    "Period",
    "Provider Parent Org Code",
    "Provider Parent Name",
    "Provider Org Code",
    "Provider Org Name",
    "Commissioner Parent Org Code",
    "Commissioner Parent Name",
    "Commissioner Org Code",
    "Commissioner Org Name",
    "RTT Part Type",
    "RTT Part Description",
    "Treatment Function Code",
    "Treatment Function Name",
    *BAND_COLUMNS,
    "Total",
    "Patients with unknown clock start date",
    "Total All",
]
PART_DESCRIPTIONS = {
    "Part_1A": "Completed Pathways For Admitted Patients",
    "Part_1B": "Completed Pathways For Non-Admitted Patients",
    "Part_2": "Incomplete Pathways",
    "Part_2A": "Incomplete Pathways with DTA",
    "Part_3": "New RTT Periods - All Patients",
}
TF_NAMES = {
    "C_110": "Trauma and Orthopaedic Service",
    "C_130": "Ophthalmology Service",
    "C_999": "Total",
}
MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def period_label(period: str) -> str:
    year, month = period.split("-")
    return f"RTT-{MONTH_NAMES[int(month) - 1]}-{year}"


def rtt_row(period, provider, name, part, tf, weeks=None, commissioner="01A", total_all=None, unknown=0):
    """One CSV row. ``weeks`` maps a week index (0 = 'Gt 00 To 01') to a count."""
    weeks = weeks or {}
    counts = [0] * len(BAND_COLUMNS)
    for week, count in weeks.items():
        counts[week] += count
    total = sum(counts)
    return [
        period_label(period),
        "QWO",
        "NHS WEST YORKSHIRE INTEGRATED CARE BOARD",
        provider,
        name,
        "QWO",
        "NHS WEST YORKSHIRE INTEGRATED CARE BOARD",
        commissioner,
        "NHS LEEDS",
        part,
        PART_DESCRIPTIONS[part],
        tf,
        TF_NAMES.get(tf, tf),
        *counts,
        total,
        unknown,
        total + unknown if total_all is None else total_all,
    ]


def write_zip(path: Path, rows: list[list], member: str = "extract.csv") -> Path:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADER)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, buffer.getvalue())
    return path


def month_rows(period: str, scale: int = 1) -> list[list]:
    """A small month: two NHS trusts, one independent provider, two specialties.

    Only the per-specialty rows are written; the reader adds the C_999 totals.
    """
    rows = []
    for provider, name, base in (
        ("RR8", "LEEDS TEACHING HOSPITALS NHS TRUST", 0),
        ("RAE", "BRADFORD TEACHING HOSPITALS NHS FOUNDATION TRUST", 4),
        ("NT3", "SPIRE HEALTHCARE", -3),
    ):
        for tf, extra in (("C_110", 6), ("C_130", 0)):
            shift = max(0, base + extra)
            for commissioner in ("01A", "02B"):
                waiting = {shift: 10 * scale, shift + 10: 6 * scale, shift + 20: 3 * scale, 60: 1 * scale}
                rows.append(rtt_row(period, provider, name, "Part_2", tf, waiting, commissioner, unknown=1))
                rows.append(rtt_row(period, provider, name, "Part_2A", tf, {shift + 5: 2}, commissioner))
                rows.append(
                    rtt_row(
                        period, provider, name, "Part_1A", tf, {shift + 8: 4, shift + 30: 2}, commissioner
                    )
                )
                rows.append(
                    rtt_row(
                        period, provider, name, "Part_1B", tf, {shift + 2: 8, shift + 12: 4}, commissioner
                    )
                )
                rows.append(rtt_row(period, provider, name, "Part_3", tf, {}, commissioner, total_all=15))
    return rows


@pytest.fixture
def make_month(tmp_path):
    def factory(period: str, rows: list[list] | None = None, scale: int = 1) -> Path:
        return write_zip(tmp_path / f"{period}.zip", rows if rows is not None else month_rows(period, scale))

    return factory
