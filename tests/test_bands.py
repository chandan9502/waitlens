import numpy as np
import pytest

from waitlens.bands import (
    Band,
    band_edges,
    count_over,
    parse_band_columns,
    percentile,
    percentiles,
    share_within,
)

THREE = [Band("a", 0, 1), Band("b", 1, 2), Band("c", 2, None)]


def test_parse_band_columns_sorts_and_ignores_other_columns():
    columns = ["Total", "Gt 01 To 02 Weeks SUM 1", "Gt 02 Weeks SUM 1", "Period", "Gt 00 To 01 Weeks SUM 1"]
    bands = parse_band_columns(columns)
    assert [(band.lower, band.upper) for band in bands] == [(0, 1), (1, 2), (2, None)]
    assert bands[0].column == "Gt 00 To 01 Weeks SUM 1"


def test_parse_band_columns_handles_three_digit_weeks():
    columns = [f"Gt {w:02d} To {w + 1:02d} Weeks SUM 1" for w in range(104)] + ["Gt 104 Weeks SUM 1"]
    bands = parse_band_columns(reversed(columns))
    assert len(bands) == 105
    assert bands[99].column == "Gt 99 To 100 Weeks SUM 1"
    assert bands[-1].upper is None


@pytest.mark.parametrize(
    "columns, message",
    [
        (["Total"], "No weekly band"),
        (["Gt 00 To 01 Weeks SUM 1", "Gt 02 To 03 Weeks SUM 1"], "not contiguous"),
        (["Gt 01 To 02 Weeks SUM 1"], "starts at 1"),
        (["Gt 00 To 01 Weeks SUM 1", "Gt 01 Weeks SUM 1", "Gt 01 To 02 Weeks SUM 1"], "not contiguous"),
    ],
)
def test_parse_band_columns_rejects_bad_layouts(columns, message):
    with pytest.raises(ValueError, match=message):
        parse_band_columns(columns)


def test_percentile_interpolates_inside_the_band():
    # 10 pathways in week 0-1, 10 in week 1-2. The median (10th of 20) is at the top of week 0-1.
    assert percentile([10, 10, 0], THREE, 0.5) == pytest.approx(1.0)
    # The 92nd percentile is pathway 18.4, which is 84% of the way through week 1-2.
    assert percentile([10, 10, 0], THREE, 0.92) == pytest.approx(1.84)


def test_percentile_in_open_band_returns_its_lower_bound():
    assert percentile([1, 1, 8], THREE, 0.92) == 2


def test_percentile_skips_empty_bands_and_handles_no_data():
    assert percentile([0, 4, 0], THREE, 0.5) == pytest.approx(1.5)
    assert percentile([0, 0, 0], THREE, 0.5) is None
    with pytest.raises(ValueError):
        percentile([1, 2, 3], THREE, 1.0)


def test_vectorised_percentiles_match_the_scalar_version():
    rng = np.random.default_rng(7)
    bands = parse_band_columns(
        [f"Gt {w:02d} To {w + 1:02d} Weeks SUM 1" for w in range(30)] + ["Gt 30 Weeks SUM 1"]
    )
    lowers, uppers = band_edges(bands)
    counts = rng.integers(0, 6, size=(200, len(bands))).astype(float)
    counts[rng.random(counts.shape) < 0.6] = 0
    counts[0] = 0  # a row with no pathways
    for p in (0.5, 0.92):
        vector = percentiles(counts, lowers, uppers, p)
        assert np.isnan(vector[0])
        for row in range(1, counts.shape[0]):
            assert vector[row] == pytest.approx(percentile(counts[row], bands, p))


def test_share_within_and_count_over():
    bands = parse_band_columns(
        [f"Gt {w:02d} To {w + 1:02d} Weeks SUM 1" for w in range(60)] + ["Gt 60 Weeks SUM 1"]
    )
    lowers, uppers = band_edges(bands)
    counts = np.zeros((2, len(bands)))
    counts[0, 17] = 3  # 17-18 weeks: within 18
    counts[0, 18] = 1  # 18-19 weeks: not within 18
    counts[0, 52] = 2  # 52-53 weeks: over 52
    counts[0, 60] = 4  # over 60 weeks
    assert share_within(counts, uppers, 18)[0] == pytest.approx(3 / 10)
    assert count_over(counts, lowers, 52)[0] == 6
    assert np.isnan(share_within(counts, uppers, 18)[1])
