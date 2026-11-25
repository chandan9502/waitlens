"""Turn monthly RTT files into the JSON files read by the WaitLens site."""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import numpy as np
import pandas as pd

from .bands import Band, band_edges, count_over, percentiles, share_within
from .rtt import TOTAL_CODES, MonthData

#: Completed pathways are pooled over this many months so small services give stable estimates.
COMPLETED_WINDOW = 3
TOTAL = "C_999"
METRICS = ("n", "p18", "md", "p92", "o52")

#: Plain-English examples for the specialties people are most often referred to.
SPECIALTY_HINTS = {
    "C_100": "e.g. hernias, gallbladder",
    "C_101": "kidneys, bladder and prostate",
    "C_110": "bones and joints, e.g. hip and knee replacements",
    "C_120": "ears, nose and throat",
    "C_130": "eyes, e.g. cataracts",
    "C_140": "mouth, teeth and jaw",
    "C_150": "brain and spine surgery",
    "C_160": "reconstructive surgery",
    "C_170": "heart and lung surgery",
    "C_300": "general medicine",
    "C_301": "stomach, bowel and liver",
    "C_320": "heart",
    "C_330": "skin",
    "C_340": "lungs and breathing",
    "C_400": "brain and nerves",
    "C_410": "joints, muscles and autoimmune conditions",
    "C_430": "care of older people",
    "C_502": "women's reproductive health",
}

#: National 18-week targets, shown as reference lines. Sources are listed in the README.
TARGETS = [
    {
        "label": "Interim target, March 2026",
        "short": "interim target, Mar 2026",
        "date": "2026-03",
        "value": 65,
    },
    {"label": "National target, March 2027", "short": "target for Mar 2027", "date": "2027-03", "value": 70},
    {
        "label": "Constitutional standard, by March 2029",
        "short": "standard, by Mar 2029",
        "date": "2029-03",
        "value": 92,
    },
]

_UPPER_WORDS = {
    "NHS",
    "UK",
    "BMI",
    "ENT",
    "PLC",
    "LLP",
    "GP",
    "CIC",
    "ISTC",
    "BPAS",
    "ICB",
    "NHSFT",
    "HCA",
    "UCLH",
}
_LOWER_WORDS = {"and", "of", "the", "for", "in", "on", "at", "upon", "with", "by"}


def nice_name(raw: str) -> str:
    """Readable capitalisation for the upper-case names in NHS files."""
    text = " ".join(str(raw).split())
    if not text or text != text.upper():
        return text
    words = []
    for index, word in enumerate(text.split(" ")):
        bare = word.strip("()[],.")
        if bare in _UPPER_WORDS:
            words.append(word)
            continue
        lower = word.lower()
        if index > 0 and lower in _LOWER_WORDS:
            words.append(lower)
            continue
        pieces = re.split(r"([-/(])", lower)
        words.append(
            "".join(piece[:1].upper() + piece[1:] if piece not in "-/(" else piece for piece in pieces)
        )
    return " ".join(words)


def specialty_label(code: str, name: str) -> str:
    """Short label: "Trauma and Orthopaedic Service" -> "Trauma and orthopaedic"."""
    if code in TOTAL_CODES:
        return "All specialties"
    label = re.sub(r"\s+services?$", "", name.strip(), flags=re.IGNORECASE)
    label = re.sub(r"^other\s*-\s*", "Other ", label, flags=re.IGNORECASE)
    words = label.split()
    keep = {"ENT", "NHS"}
    return " ".join(w if (i == 0 or w in keep) else w.lower() for i, w in enumerate(words))


def provider_kind(code: str) -> str:
    """NHS trusts have codes starting with R; most other RTT providers are independent sector."""
    return "nhs" if code.upper().startswith("R") else "independent"


def summarise(counts: np.ndarray, bands: list[Band]) -> dict[str, np.ndarray]:
    lowers, uppers = band_edges(bands)
    counts = np.asarray(counts, dtype=float)
    return {
        "n": counts.sum(axis=1),
        "p18": share_within(counts, uppers, 18) * 100,
        "md": percentiles(counts, lowers, uppers, 0.5),
        "p92": percentiles(counts, lowers, uppers, 0.92),
        "o52": count_over(counts, lowers, 52),
    }


def _part(month: MonthData, part: str) -> pd.DataFrame:
    frame = month.frame[month.frame["part"] == part]
    return frame.set_index(["provider_code", "tf_code"])[month.band_columns + ["total_all"]]


def _metrics_frame(frame: pd.DataFrame, month: MonthData) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=list(METRICS), index=frame.index)
    values = summarise(frame[month.band_columns].to_numpy(), month.bands)
    return pd.DataFrame(values, index=frame.index)


@dataclass
class MonthSummary:
    """The parts of one month that the outputs need (the raw bands are dropped early)."""

    period: str
    table: pd.DataFrame  # provider x specialty: n, p18, md, p92, o52, new
    national: pd.DataFrame  # specialty: incomplete metrics, a_* admitted, n_* non-admitted, new
    providers: pd.DataFrame  # provider_code -> provider_name, parent_name
    specialties: dict[str, str]
    bands: list[Band]
    completed: dict[str, pd.DataFrame] = field(default_factory=dict)
    source: str = ""


def summarise_month(month: MonthData, keep_completed: bool = True) -> MonthSummary:
    incomplete = _part(month, "incomplete")
    table = _metrics_frame(incomplete, month)
    new = _part(month, "new")["total_all"].rename("new")
    table = table.join(new, how="outer")

    national_parts = []
    for part, prefix in (("incomplete", ""), ("admitted", "a_"), ("nonadmitted", "n_")):
        frame = _part(month, part)
        sums = frame[month.band_columns].groupby(level="tf_code").sum()
        national_parts.append(
            pd.DataFrame(summarise(sums.to_numpy(), month.bands), index=sums.index).add_prefix(prefix)
        )
    national_new = _part(month, "new")["total_all"].groupby(level="tf_code").sum().rename("new")
    national = pd.concat(national_parts + [national_new], axis=1)

    providers = (
        month.frame.groupby("provider_code", sort=False)[["provider_name", "parent_name"]]
        .first()
        .sort_index()
    )
    specialties = dict(month.frame.groupby("tf_code", sort=False)["tf_name"].first().items())
    completed = {}
    if keep_completed:
        for part in ("admitted", "nonadmitted"):
            completed[part] = _part(month, part)[month.band_columns]
    return MonthSummary(
        period=month.period,
        table=table,
        national=national,
        providers=providers,
        specialties=specialties,
        bands=month.bands,
        completed=completed,
        source=month.source,
    )


def pooled_completed(window: list[MonthSummary], part: str) -> pd.DataFrame:
    """Completed-pathway metrics with the last few months' bands added together."""
    latest = window[-1]
    columns = [band.column for band in latest.bands]
    frames = [
        summary.completed[part]
        for summary in window
        if part in summary.completed and [band.column for band in summary.bands] == columns
    ]
    if not frames:
        return pd.DataFrame(columns=list(METRICS))
    total = pd.concat(frames).groupby(level=[0, 1]).sum()
    return pd.DataFrame(summarise(total[columns].to_numpy(), latest.bands), index=total.index)


def _num(value, digits: int = 1):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return int(round(number)) if digits == 0 else round(number, digits)


def _series(frame: pd.DataFrame, key, digits: int) -> list:
    if key not in frame.index:
        return [None] * frame.shape[1]
    return [_num(value, digits) for value in frame.loc[key].tolist()]


def load_anchors() -> dict:
    """Published national figures used to check that the pipeline reproduces NHS England."""
    text = resources.files("waitlens").joinpath("data/press_notices.json").read_text(encoding="utf-8")
    return json.loads(text)


_CHECKS = (
    ("incomplete_total", "Patients waiting (incomplete pathways)", "n", 0),
    ("pct_within_18", "% waiting 18 weeks or less", "p18", 1),
    ("median_weeks", "Median wait, weeks", "md", 1),
    ("p92_weeks", "92nd percentile wait, weeks", "p92", 1),
    ("completed_admitted", "Completed admitted pathways", "a_n", 0),
    ("completed_nonadmitted", "Completed non-admitted pathways", "n_n", 0),
    ("new_periods", "New RTT periods", "new", 0),
)


def validate(summaries: dict[str, MonthSummary], anchors: dict) -> list[dict]:
    """Compare national totals with the figures NHS England printed in its press notices."""
    results = []
    for period, anchor in sorted(anchors.items()):
        summary = summaries.get(period)
        if summary is None or TOTAL not in summary.national.index:
            continue
        row = summary.national.loc[TOTAL]
        checks = []
        for key, label, column, digits in _CHECKS:
            if key not in anchor:
                continue
            published = anchor[key]
            computed = _num(row.get(column), 3)
            if computed is None:
                ok = False
            elif digits == 0:
                ok = abs(computed - published) <= max(1.0, 0.002 * published)
            else:
                ok = abs(computed - published) <= 0.15
            checks.append(
                {
                    "measure": label,
                    "published": published,
                    "computed": _num(computed, digits),
                    "ok": bool(ok),
                }
            )
        results.append({"period": period, "source": anchor.get("source", ""), "checks": checks})
    return results


def build_outputs(
    summaries: list[MonthSummary],
    locations: dict[str, dict] | None = None,
    sources: dict[str, str] | None = None,
    anchors: dict | None = None,
    generated_at: str | None = None,
) -> dict[str, object]:
    """Return {relative path: JSON payload} for the site."""
    if not summaries:
        raise ValueError("No months to build from")
    summaries = sorted(summaries, key=lambda summary: summary.period)
    periods = [summary.period for summary in summaries]
    if len(set(periods)) != len(periods):
        raise ValueError(f"Duplicate months in input: {periods}")
    by_period = {summary.period: summary for summary in summaries}
    latest = summaries[-1]
    locations = locations or {}
    window = summaries[-COMPLETED_WINDOW:]

    long = pd.concat({summary.period: summary.table for summary in summaries}, names=["period"])
    wide = {}
    for metric in METRICS:
        wide[metric] = long[metric].unstack("period").reindex(columns=periods)
    admitted = pooled_completed(window, "admitted")
    nonadmitted = pooled_completed(window, "nonadmitted")
    present_keys = set(latest.table.index.tolist())
    for frame in (admitted, nonadmitted):
        if isinstance(frame.index, pd.MultiIndex):
            present_keys.update(frame.index.tolist())
    present = sorted(present_keys)

    specialty_names: dict[str, str] = {}
    for summary in summaries:
        specialty_names.update(summary.specialties)
    provider_names = pd.concat([summary.providers for summary in summaries])
    provider_names = provider_names[~provider_names.index.duplicated(keep="last")]

    national = {}
    for code in specialty_names:
        entry = {}
        for column in (
            "n",
            "p18",
            "md",
            "p92",
            "o52",
            "a_n",
            "a_md",
            "a_p92",
            "a_p18",
            "n_n",
            "n_md",
            "n_p92",
            "n_p18",
            "new",
        ):
            digits = 0 if column in ("n", "o52", "a_n", "n_n", "new") else 1
            values = []
            for period in periods:
                frame = by_period[period].national
                values.append(
                    _num(frame.at[code, column], digits) if code in frame.index and column in frame else None
                )
            entry[column] = values
        national[code] = entry

    latest_codes = sorted({code for code, _ in present})
    specialty_codes = [code for code in specialty_names if any(tf == code for _, tf in present)]

    spec_files = {}
    provider_detail: dict[str, list] = {code: [] for code in latest_codes}
    groups: dict[str, list] = {code: [] for code in specialty_codes}
    for key in present:
        groups.setdefault(key[1], []).append(key)
    for code in specialty_codes:
        rows = []
        for key in sorted(groups.get(code, [])):
            provider = key[0]
            row = {
                "c": provider,
                "w": _series(wide["n"], key, 0),
                "p18": _series(wide["p18"], key, 1),
                "md": _series(wide["md"], key, 1),
                "p92": _series(wide["p92"], key, 1),
                "o52": _series(wide["o52"], key, 0),
                "new": _num(latest.table.at[key, "new"], 0) if key in latest.table.index else None,
            }
            for prefix, frame in (("a_", admitted), ("n_", nonadmitted)):
                if key in frame.index:
                    record = frame.loc[key]
                    row[prefix + "n"] = _num(record["n"], 0)
                    row[prefix + "md"] = _num(record["md"], 1)
                    row[prefix + "p92"] = _num(record["p92"], 1)
                    row[prefix + "p18"] = _num(record["p18"], 1)
                else:
                    row.update(
                        {prefix + "n": 0, prefix + "md": None, prefix + "p92": None, prefix + "p18": None}
                    )
            rows.append(row)
            provider_detail[provider].append(
                {
                    "s": code,
                    "w": row["w"][-1],
                    "p18": row["p18"][-1],
                    "md": row["md"][-1],
                    "p92": row["p92"][-1],
                    "o52": row["o52"][-1],
                    "a_n": row["a_n"],
                    "a_md": row["a_md"],
                    "n_n": row["n_n"],
                    "n_md": row["n_md"],
                }
            )
        spec_files[f"spec/{code}.json"] = {"code": code, "periods": periods, "rows": rows}

    providers = []
    for code in latest_codes:
        name, parent = ("", "")
        if code in provider_names.index:
            name = provider_names.at[code, "provider_name"]
            parent = provider_names.at[code, "parent_name"]
        location = locations.get(code, {})
        total_key = (code, TOTAL)
        waiting = wide["n"].at[total_key, periods[-1]] if total_key in wide["n"].index else None
        kind = provider_kind(code)
        providers.append(
            {
                "code": code,
                "name": nice_name(name) or code,
                "area": nice_name(parent),
                "kind": kind,
                "multi_site": kind == "independent" and len(code) == 3,
                "postcode": location.get("postcode"),
                "lat": location.get("lat"),
                "lon": location.get("lon"),
                "w": _num(waiting, 0),
            }
        )

    specialties = []
    for code in specialty_codes:
        name = specialty_names[code]
        series = national.get(code, {}).get("n", [])
        specialties.append(
            {
                "code": code,
                "name": name,
                "label": specialty_label(code, name),
                "hint": SPECIALTY_HINTS.get(code, ""),
                "w": series[-1] if series else None,
            }
        )

    meta = {
        "version": 1,
        "generated_at": generated_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest": latest.period,
        "periods": periods,
        "completed_window": [summary.period for summary in window],
        "specialties": specialties,
        "national": national,
        "providers": providers,
        "targets": TARGETS,
        "validation": validate(by_period, anchors or {}),
        "sources": [
            {"period": period, "url": (sources or {}).get(period, by_period[period].source)}
            for period in periods
        ],
    }
    outputs: dict[str, object] = {"meta.json": meta, "providers.json": provider_detail}
    outputs.update(spec_files)
    return outputs


def write_outputs(outputs: dict[str, object], directory: Path) -> list[Path]:
    directory = Path(directory)
    written = []
    for relative, payload in outputs.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        written.append(path)
    return written


def format_validation(results: Iterable[dict]) -> str:
    lines = []
    for result in results:
        lines.append(f"Check against NHS England press notice for {result['period']}:")
        for check in result["checks"]:
            mark = "OK  " if check["ok"] else "DIFF"
            lines.append(
                f"  {mark} {check['measure']}: published {check['published']}, computed {check['computed']}"
            )
    return "\n".join(lines) if lines else "No press-notice months in range to check against."
