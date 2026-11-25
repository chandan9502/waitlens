import json

import pytest

from waitlens.build import (
    build_outputs,
    load_anchors,
    nice_name,
    specialty_label,
    summarise_month,
    write_outputs,
)
from waitlens.rtt import read_month

PERIODS = ["2026-06", "2026-07", "2026-08", "2026-09"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("LEEDS TEACHING HOSPITALS NHS TRUST", "Leeds Teaching Hospitals NHS Trust"),
        ("KING'S COLLEGE HOSPITAL NHS FOUNDATION TRUST", "King's College Hospital NHS Foundation Trust"),
        ("NHS WEST YORKSHIRE INTEGRATED CARE BOARD", "NHS West Yorkshire Integrated Care Board"),
        ("WESTON-SUPER-MARE CLINIC", "Weston-Super-Mare Clinic"),
        ("Already Mixed Case", "Already Mixed Case"),
    ],
)
def test_nice_name(raw, expected):
    assert nice_name(raw) == expected


@pytest.mark.parametrize(
    "code, name, expected",
    [
        ("C_110", "Trauma and Orthopaedic Service", "Trauma and orthopaedic"),
        ("C_120", "Ear Nose and Throat Service", "Ear nose and throat"),
        ("X02", "Other - Medical Services", "Other medical"),
        ("C_999", "Total", "All specialties"),
    ],
)
def test_specialty_label(code, name, expected):
    assert specialty_label(code, name) == expected


@pytest.fixture
def outputs(make_month):
    summaries = []
    for index, period in enumerate(PERIODS):
        month = read_month(make_month(period, scale=index + 1), label=f"{period}.zip")
        summaries.append(summarise_month(month, keep_completed=True))
    locations = {"RR8": {"postcode": "LS9 7TF", "lat": 53.8, "lon": -1.52}}
    anchors = {
        "2026-09": {"source": "test", "incomplete_total": 480, "pct_within_18": 50.0, "new_periods": 1},
    }
    return build_outputs(summaries, locations=locations, anchors=anchors, generated_at="2026-11-25T00:00:00Z")


def test_meta_describes_periods_specialties_and_providers(outputs):
    meta = outputs["meta.json"]
    assert meta["periods"] == PERIODS
    assert meta["latest"] == "2026-09"
    assert meta["completed_window"] == PERIODS[-3:]
    assert {spec["code"] for spec in meta["specialties"]} == {"C_110", "C_130", "C_999"}
    providers = {provider["code"]: provider for provider in meta["providers"]}
    assert providers["RR8"]["name"] == "Leeds Teaching Hospitals NHS Trust"
    assert providers["RR8"]["area"] == "NHS West Yorkshire Integrated Care Board"
    assert providers["RR8"]["lat"] == 53.8
    assert providers["NT3"]["kind"] == "independent" and providers["NT3"]["multi_site"] is True
    assert providers["RAE"]["kind"] == "nhs" and providers["RAE"]["lat"] is None


def test_national_series_adds_up_all_providers(outputs):
    national = outputs["meta.json"]["national"]["C_999"]
    # Each provider x specialty x commissioner row has 20 waiting at scale 1.
    # 3 providers x 2 specialties x 2 commissioners = 12 rows -> 240 in month 1, 960 in month 4.
    assert national["n"] == [240, 480, 720, 960]
    assert national["new"][-1] == 3 * 2 * 2 * 15
    assert all(value is not None for value in national["md"])


def test_specialty_file_has_series_and_pooled_completed_metrics(outputs):
    spec = outputs["spec/C_110.json"]
    assert spec["periods"] == PERIODS
    rows = {row["c"]: row for row in spec["rows"]}
    leeds = rows["RR8"]
    assert leeds["w"] == [40, 80, 120, 160]
    # Leeds orthopaedics: 10/20 wait in week 6-7, 6/20 in 16-17, 3/20 in 26-27, 1/20 in 60-61.
    assert leeds["p18"][-1] == pytest.approx(80.0)
    assert leeds["o52"][-1] == 8
    # Completed admitted pathways (6 per commissioner per month) are pooled over the last three months.
    assert leeds["a_n"] == (4 + 2) * 2 * 3
    assert leeds["a_md"] is not None and leeds["a_p92"] > leeds["a_md"]


def test_provider_detail_lists_each_specialty(outputs):
    detail = outputs["providers.json"]["RR8"]
    assert {entry["s"] for entry in detail} == {"C_110", "C_130", "C_999"}


def test_validation_flags_matches_and_differences(outputs):
    [result] = outputs["meta.json"]["validation"]
    checks = {check["measure"]: check for check in result["checks"]}
    assert checks["Patients waiting (incomplete pathways)"]["ok"] is False
    assert checks["Patients waiting (incomplete pathways)"]["computed"] == 960
    assert checks["New RTT periods"]["ok"] is False


def test_outputs_are_strict_json(outputs, tmp_path):
    written = write_outputs(outputs, tmp_path)
    assert (tmp_path / "meta.json") in written
    for path in written:
        json.loads(path.read_text())  # write_outputs refuses NaN, so this only checks the round trip


def test_bundled_press_notice_figures_load():
    anchors = load_anchors()
    assert anchors["2026-09"]["incomplete_total"] == 7074324
    assert anchors["2026-09"]["median_weeks"] == 12.2
