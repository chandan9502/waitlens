import pytest
from conftest import BAND_COLUMNS, rtt_row, write_zip

from waitlens.rtt import classify_part, parse_period, read_month


@pytest.mark.parametrize(
    "value, expected",
    [("RTT-September-2026", "2026-09"), ("RTT-March-2025", "2025-03"), ("January 2027", "2027-01")],
)
def test_parse_period(value, expected):
    assert parse_period(value) == expected


def test_parse_period_rejects_unknown_text():
    with pytest.raises(ValueError):
        parse_period("Q3 2026")


@pytest.mark.parametrize(
    "part, description, expected",
    [
        ("Part_1A", "", "admitted"),
        ("Part_1B", "", "nonadmitted"),
        ("Part_2", "", "incomplete"),
        ("Part_2A", "", "incomplete_dta"),
        ("Part_3", "", "new"),
        ("", "Completed Pathways For Non-Admitted Patients", "nonadmitted"),
        ("", "Incomplete Pathways with DTA", "incomplete_dta"),
    ],
)
def test_classify_part(part, description, expected):
    assert classify_part(part, description) == expected


def test_classify_part_rejects_unknown_types():
    with pytest.raises(ValueError, match="Unrecognised"):
        classify_part("Part_9", "Something else")


def test_read_month_adds_commissioners_together_and_builds_totals(tmp_path):
    rows = [
        rtt_row("2026-09", "RR8", "LEEDS", "Part_2", "C_110", {0: 3, 20: 1}, "01A"),
        rtt_row("2026-09", "RR8", "LEEDS", "Part_2", "C_110", {0: 2}, "02B"),
        rtt_row("2026-09", "RR8", "LEEDS", "Part_2", "C_130", {5: 4}, "01A"),
        rtt_row("2026-09", "RR8", "LEEDS", "Part_3", "C_110", {}, "01A", total_all=9),
    ]
    month = read_month(write_zip(tmp_path / "m.zip", rows))
    assert month.period == "2026-09"
    assert len(month.bands) == len(BAND_COLUMNS)
    frame = month.frame.set_index(["provider_code", "part", "tf_code"])
    assert frame.loc[("RR8", "incomplete", "C_110"), "Gt 00 To 01 Weeks SUM 1"] == 5
    assert frame.loc[("RR8", "incomplete", "C_110"), "Gt 20 To 21 Weeks SUM 1"] == 1
    # No C_999 rows in the file, so the reader adds one per provider and part.
    assert frame.loc[("RR8", "incomplete", "C_999"), "Gt 05 To 06 Weeks SUM 1"] == 4
    assert frame.loc[("RR8", "incomplete", "C_999"), month.band_columns].sum() == 10
    assert frame.loc[("RR8", "new", "C_110"), "total_all"] == 9


def test_read_month_does_not_double_count_published_totals(tmp_path):
    rows = [
        rtt_row("2026-09", "RR8", "LEEDS", "Part_2", "C_110", {0: 3}),
        rtt_row("2026-09", "RR8", "LEEDS", "Part_2", "C_999", {0: 3}),
    ]
    month = read_month(write_zip(tmp_path / "m.zip", rows))
    totals = month.frame[(month.frame.tf_code == "C_999") & (month.frame.part == "incomplete")]
    assert len(totals) == 1
    assert totals[month.band_columns].to_numpy().sum() == 3


def test_read_month_reports_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Period,Gt 00 To 01 Weeks SUM 1\nRTT-September-2026,1\n")
    with pytest.raises(ValueError, match="Provider Org Code"):
        read_month(path)


def test_read_month_rejects_files_with_two_periods(tmp_path):
    rows = [
        rtt_row("2026-09", "RR8", "LEEDS", "Part_2", "C_110", {0: 1}),
        rtt_row("2026-08", "RR8", "LEEDS", "Part_2", "C_110", {0: 1}),
    ]
    with pytest.raises(ValueError, match="one period"):
        read_month(write_zip(tmp_path / "m.zip", rows))
