import json

import pytest

from waitlens import cli
from waitlens.geo import geocode, locate_providers, normalise_postcode, ods_postcode


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.posts = []

    def get(self, url, timeout=None):
        if "organisations/RR8" in url:
            return FakeResponse({"Organisation": {"GeoLoc": {"Location": {"PostCode": "ls97tf"}}}})
        if "organisations/" in url:
            return FakeResponse({}, 404)
        if "terminated_postcodes/AB1%200AA" in url:
            return FakeResponse({"result": {"latitude": 57.1, "longitude": -2.1}})
        if "outcodes/" in url:
            return FakeResponse({"result": {"latitude": 51.0, "longitude": -1.0}})
        return FakeResponse({}, 404)

    def post(self, url, json=None, timeout=None):
        self.posts.append(json)
        results = []
        for postcode in json["postcodes"]:
            found = {"latitude": 53.8, "longitude": -1.52} if postcode == "LS9 7TF" else None
            results.append({"query": postcode, "result": found})
        return FakeResponse({"status": 200, "result": results})


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ls97tf", "LS9 7TF"),
        ("SW1A  1AA", "SW1A 1AA"),
        ("M1 1AE", "M1 1AE"),
        ("not a postcode", None),
        (None, None),
    ],
)
def test_normalise_postcode(raw, expected):
    assert normalise_postcode(raw) == expected


def test_ods_postcode_reads_the_registered_address():
    session = FakeSession()
    assert ods_postcode(session, "RR8") == "LS9 7TF"
    assert ods_postcode(session, "XXX") is None


def test_geocode_falls_back_to_terminated_postcodes_and_outcodes():
    found = geocode(FakeSession(), ["LS9 7TF", "AB1 0AA", "ZZ9 9ZZ"])
    assert found["LS9 7TF"] == (53.8, -1.52)
    assert found["AB1 0AA"] == (57.1, -2.1)
    assert found["ZZ9 9ZZ"] == (51.0, -1.0)


def test_locate_providers_skips_unknown_codes():
    located = locate_providers(FakeSession(), ["RR8", "XXX"])
    assert located == {"RR8": {"postcode": "LS9 7TF", "lat": 53.8, "lon": -1.52}}


def test_cli_build_from_local_zips(make_month, tmp_path, capsys):
    zips = [str(make_month(period)) for period in ("2026-08", "2026-09")]
    out = tmp_path / "site-data"
    assert cli.main(["build", "--zip", *zips, "--no-geo", "--out", str(out)]) == 0
    meta = json.loads((out / "meta.json").read_text())
    assert meta["periods"] == ["2026-08", "2026-09"]
    assert (out / "spec" / "C_110.json").exists()
    printed = capsys.readouterr().out
    assert "2026-09:" in printed and "Wrote" in printed


def test_cli_rejects_zero_months():
    with pytest.raises(SystemExit):
        cli.main(["build", "--months", "0", "--no-geo"])
