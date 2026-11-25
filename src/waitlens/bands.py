"""Weekly waiting-time bands: parse the column names and estimate percentiles.

NHS England publishes referral-to-treatment (RTT) waits as counts of pathways in
one-week bands ("Gt 00 To 01 Weeks SUM 1" ... "Gt 104 Weeks SUM 1"). There is no
patient-level data, so medians and 92nd percentiles are estimated by finding the
band that contains the target pathway and interpolating linearly inside it. NHS
England uses the same approach for its published figures.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

_CLOSED = re.compile(r"^Gt\s*(\d+)\s*To\s*(\d+)\s*Weeks\s*SUM\s*1$", re.IGNORECASE)
_OPEN = re.compile(r"^Gt\s*(\d+)\s*Weeks\s*SUM\s*1$", re.IGNORECASE)


@dataclass(frozen=True)
class Band:
    """One weekly band. ``upper`` is ``None`` for the open-ended last band."""

    column: str
    lower: float
    upper: float | None


def parse_band_columns(columns: Iterable[str]) -> list[Band]:
    """Return the weekly bands found in ``columns``, sorted and checked for gaps."""
    bands: list[Band] = []
    for column in columns:
        name = str(column).strip()
        closed = _CLOSED.match(name)
        if closed:
            lower, upper = int(closed.group(1)), int(closed.group(2))
            if upper <= lower:
                raise ValueError(f"Band {name!r} has an upper bound below its lower bound")
            bands.append(Band(column, float(lower), float(upper)))
            continue
        opened = _OPEN.match(name)
        if opened:
            bands.append(Band(column, float(opened.group(1)), None))

    if not bands:
        raise ValueError("No weekly band columns (e.g. 'Gt 00 To 01 Weeks SUM 1') were found")

    bands.sort(key=lambda band: (band.lower, float("inf") if band.upper is None else band.upper))
    if bands[0].lower != 0:
        raise ValueError(f"The first weekly band starts at {bands[0].lower:g} weeks, not 0")
    for previous, current in zip(bands, bands[1:], strict=False):
        if previous.upper is None or previous.upper != current.lower:
            raise ValueError(
                f"Weekly bands are not contiguous: {previous.column!r} is followed by {current.column!r}"
            )
    return bands


def band_edges(bands: Sequence[Band]) -> tuple[np.ndarray, np.ndarray]:
    """Lower and upper edges as arrays; the open-ended band has an upper edge of NaN."""
    lowers = np.array([band.lower for band in bands], dtype=float)
    uppers = np.array([np.nan if band.upper is None else band.upper for band in bands], dtype=float)
    return lowers, uppers


def percentile(counts: Sequence[float], bands: Sequence[Band], p: float) -> float | None:
    """Estimate the ``p`` quantile (0-1) of a banded distribution, in weeks.

    Returns ``None`` when there are no pathways. If the quantile falls in the
    open-ended last band, its lower bound is returned because there is nothing
    to interpolate towards.
    """
    if not 0 < p < 1:
        raise ValueError("p must be between 0 and 1")
    if len(counts) != len(bands):
        raise ValueError("counts and bands must be the same length")
    total = float(sum(counts))
    if total <= 0:
        return None
    target = p * total
    cumulative = 0.0
    for count, band in zip(counts, bands, strict=True):
        if count > 0 and cumulative + count >= target - 1e-9:
            if band.upper is None:
                return band.lower
            return band.lower + (target - cumulative) / count * (band.upper - band.lower)
        cumulative += count
    return bands[-1].lower


def percentiles(counts: np.ndarray, lowers: np.ndarray, uppers: np.ndarray, p: float) -> np.ndarray:
    """Vectorised :func:`percentile` for a 2-D array of shape (rows, bands).

    Rows with no pathways give NaN.
    """
    if not 0 < p < 1:
        raise ValueError("p must be between 0 and 1")
    counts = np.asarray(counts, dtype=float)
    if counts.ndim != 2 or counts.shape[1] != lowers.shape[0]:
        raise ValueError("counts must have shape (rows, number of bands)")
    if counts.shape[0] == 0:
        return np.empty(0)
    totals = counts.sum(axis=1)
    target = p * totals
    cumulative = np.cumsum(counts, axis=1)
    hits = (cumulative >= (target - 1e-9)[:, None]) & (counts > 0)
    index = hits.argmax(axis=1)
    rows = np.arange(counts.shape[0])
    in_band = counts[rows, index]
    before = cumulative[rows, index] - in_band
    lower = lowers[index]
    upper = uppers[index]
    safe = np.where(in_band > 0, in_band, 1.0)
    width = np.where(np.isnan(upper), 0.0, upper - lower)
    value = lower + (target - before) / safe * width
    value = np.where(np.isnan(upper), lower, value)
    return np.where((totals > 0) & hits.any(axis=1), value, np.nan)


def share_within(counts: np.ndarray, uppers: np.ndarray, weeks: float) -> np.ndarray:
    """Share (0-1) of pathways in bands that end at or before ``weeks``."""
    counts = np.asarray(counts, dtype=float)
    totals = counts.sum(axis=1)
    mask = ~np.isnan(uppers) & (uppers <= weeks)
    within = counts[:, mask].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(totals > 0, within / totals, np.nan)


def count_over(counts: np.ndarray, lowers: np.ndarray, weeks: float) -> np.ndarray:
    """Number of pathways in bands that start at or after ``weeks``."""
    counts = np.asarray(counts, dtype=float)
    return counts[:, lowers >= weeks].sum(axis=1)
