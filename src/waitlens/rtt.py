"""Read NHS England's monthly RTT "Full CSV data file" and aggregate it by provider.

Each monthly file has one row per provider x commissioner x treatment function x
pathway type ("RTT Part Type"), with the number of pathways in each weekly band.
WaitLens adds the commissioner rows together, so every number is about the
hospital provider that treats the patient.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .bands import Band, parse_band_columns

#: Pathway types published in the file, keyed by "RTT Part Type".
PART_TYPES = {
    "part_1a": "admitted",  # completed pathways that ended with admission (e.g. surgery)
    "part_1b": "nonadmitted",  # completed pathways that ended without admission
    "part_2": "incomplete",  # patients still waiting at the end of the month
    "part_2a": "incomplete_dta",  # still waiting, with a decision to admit
    "part_3": "new",  # new RTT periods (clock starts) in the month
}

# Used only if a part type code is missing or unfamiliar. Order matters:
# "non-admitted" contains "admitted", "with dta" is a kind of "incomplete".
_DESCRIPTION_HINTS = (
    ("non-admitted", "nonadmitted"),
    ("non admitted", "nonadmitted"),
    ("admitted", "admitted"),
    ("dta", "incomplete_dta"),
    ("incomplete", "incomplete"),
    ("new rtt period", "new"),
)

TOTAL_CODES = {"C_999", "999"}

_COLUMNS = {
    "period": "Period",
    "provider_code": "Provider Org Code",
    "provider_name": "Provider Org Name",
    "parent_code": "Provider Parent Org Code",
    "parent_name": "Provider Parent Name",
    "part_type": "RTT Part Type",
    "part_description": "RTT Part Description",
    "tf_code": "Treatment Function Code",
    "tf_name": "Treatment Function Name",
    "total": "Total",
    "total_all": "Total All",
}
_REQUIRED = ("provider_code", "provider_name", "tf_code", "tf_name")

_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}


@dataclass
class MonthData:
    """One month of RTT data, aggregated to provider x treatment function x part."""

    period: str  # "YYYY-MM"
    bands: list[Band]
    frame: pd.DataFrame
    source: str = ""

    @property
    def band_columns(self) -> list[str]:
        return [band.column for band in self.bands]


def parse_period(value: str) -> str:
    """Turn "RTT-September-2026" (or "September 2026") into "2026-09"."""
    text = str(value).strip().lower()
    match = re.search(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"[\s\-_]*(\d{4})",
        text,
    )
    if not match:
        raise ValueError(f"Cannot read a month and year from period {value!r}")
    return f"{int(match.group(2)):04d}-{_MONTHS[match.group(1)]:02d}"


def classify_part(part_type: str, description: str = "") -> str:
    """Map an RTT part type (and, as a fallback, its description) to a WaitLens key."""
    key = str(part_type).strip().lower().replace(" ", "_")
    if key in PART_TYPES:
        return PART_TYPES[key]
    text = str(description).strip().lower()
    for hint, part in _DESCRIPTION_HINTS:
        if hint in text:
            return part
    raise ValueError(f"Unrecognised RTT part type {part_type!r} ({description!r})")


def _find_columns(columns: list[str]) -> dict[str, str]:
    lookup = {str(column).strip().lower(): column for column in columns}
    found = {}
    for key, name in _COLUMNS.items():
        if name.lower() in lookup:
            found[key] = lookup[name.lower()]
    missing = [_COLUMNS[key] for key in _REQUIRED if key not in found]
    if "part_type" not in found and "part_description" not in found:
        missing.append("RTT Part Type")
    if missing:
        raise ValueError(
            "The RTT file is missing expected columns: "
            + ", ".join(missing)
            + ". Columns found: "
            + ", ".join(map(str, columns))
        )
    return found


def read_month(source, period: str | None = None, label: str = "") -> MonthData:
    """Read one monthly RTT CSV (path, buffer or ZIP) and aggregate it by provider."""
    frame = _read_csv(source)
    frame.columns = [str(column).strip() for column in frame.columns]
    columns = _find_columns(list(frame.columns))
    bands = parse_band_columns(frame.columns)
    band_columns = [band.column for band in bands]

    if period is None:
        if "period" not in columns:
            raise ValueError("The RTT file has no Period column; pass the period explicitly")
        periods = frame[columns["period"]].dropna().astype(str).map(parse_period).unique()
        if len(periods) != 1:
            raise ValueError(f"Expected one period in the file, found {sorted(periods)}")
        period = str(periods[0])

    parts = frame[columns["part_type"]] if "part_type" in columns else pd.Series("", index=frame.index)
    descriptions = (
        frame[columns["part_description"]]
        if "part_description" in columns
        else pd.Series("", index=frame.index)
    )
    lookup = {
        (part, description): classify_part(part, description)
        for part, description in set(zip(parts.astype(str), descriptions.astype(str), strict=True))
    }

    tidy = pd.DataFrame(
        {
            "provider_code": frame[columns["provider_code"]].astype(str).str.strip(),
            "provider_name": frame[columns["provider_name"]].astype(str).str.strip(),
            "parent_code": _text(frame, columns.get("parent_code")),
            "parent_name": _text(frame, columns.get("parent_name")),
            "part": [
                lookup[(part, description)]
                for part, description in zip(parts.astype(str), descriptions.astype(str), strict=True)
            ],
            "tf_code": frame[columns["tf_code"]].astype(str).str.strip(),
            "tf_name": frame[columns["tf_name"]].astype(str).str.strip(),
        }
    )
    numbers = frame[band_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0).astype(float)
    total_all_column = columns.get("total_all") or columns.get("total")
    if total_all_column is not None:
        total_all = pd.to_numeric(frame[total_all_column], errors="coerce").fillna(0.0).astype(float)
    else:
        total_all = numbers.sum(axis=1)
    tidy = pd.concat([tidy, pd.DataFrame(numbers.to_numpy(), columns=band_columns, index=tidy.index)], axis=1)
    tidy["total_all"] = total_all.to_numpy()

    tidy = tidy[tidy["provider_code"].ne("") & tidy["provider_code"].ne("nan")]
    keys = ["provider_code", "part", "tf_code"]
    names = (
        tidy.groupby(keys, sort=False)[["provider_name", "parent_code", "parent_name", "tf_name"]]
        .first()
        .reset_index()
    )
    sums = tidy.groupby(keys, sort=False)[band_columns + ["total_all"]].sum().reset_index()
    aggregated = names.merge(sums, on=keys, how="inner")
    aggregated = _add_missing_totals(aggregated, band_columns)
    return MonthData(period=period, bands=bands, frame=aggregated.reset_index(drop=True), source=label)


def _text(frame: pd.DataFrame, column: str | None) -> pd.Series:
    if column is None:
        return pd.Series("", index=frame.index)
    return frame[column].fillna("").astype(str).str.strip()


def _add_missing_totals(frame: pd.DataFrame, band_columns: list[str]) -> pd.DataFrame:
    """Add "all specialties" rows for providers whose file has no C_999 total."""
    has_total = frame["tf_code"].isin(TOTAL_CODES)
    covered = set(zip(frame.loc[has_total, "provider_code"], frame.loc[has_total, "part"], strict=True))
    detail = frame[~has_total]
    missing = detail[
        [
            (code, part) not in covered
            for code, part in zip(detail["provider_code"], detail["part"], strict=True)
        ]
    ]
    if missing.empty:
        return frame
    totals = (
        missing.groupby(["provider_code", "part"], sort=False)[band_columns + ["total_all"]]
        .sum()
        .reset_index()
    )
    first = missing.groupby(["provider_code", "part"], sort=False)[
        ["provider_name", "parent_code", "parent_name"]
    ]
    totals = totals.merge(first.first().reset_index(), on=["provider_code", "part"])
    totals["tf_code"] = "C_999"
    totals["tf_name"] = "Total"
    return pd.concat([frame, totals[frame.columns]], ignore_index=True)


_NUMERIC_NAMES = {"total", "total all", "patients with unknown clock start date"}


def _is_numeric_column(name: str) -> bool:
    text = str(name).strip()
    return text.lower() in _NUMERIC_NAMES or text.lower().startswith("gt ")


def _load_bytes(source) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if hasattr(source, "read"):
        data = source.read()
        return data.encode("utf-8") if isinstance(data, str) else data
    path = Path(source)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not members:
                raise ValueError(f"No CSV file inside {path}")
            member = max(members, key=lambda name: archive.getinfo(name).file_size)
            return archive.read(member)
    return path.read_bytes()


def _read_csv(source) -> pd.DataFrame:
    data = _load_bytes(source)
    options = {"encoding": "utf-8-sig", "encoding_errors": "replace"}
    header = pd.read_csv(io.BytesIO(data), nrows=0, **options)
    text_columns = {column: str for column in header.columns if not _is_numeric_column(column)}
    frame = pd.read_csv(io.BytesIO(data), dtype=text_columns, low_memory=False, **options)
    for column in text_columns:
        frame[column] = frame[column].fillna("")
    return frame
