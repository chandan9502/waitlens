"""Locate hospital providers: ODS (organisation postcode) then postcodes.io (lat/long)."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

ORD_URL = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations/{code}"
POSTCODES_URL = "https://api.postcodes.io"

_POSTCODE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$")


def normalise_postcode(value: str | None) -> str | None:
    """Upper-case a UK postcode and put a single space before the inward code."""
    if not value:
        return None
    text = re.sub(r"\s+", "", str(value).upper())
    match = _POSTCODE.match(text)
    return f"{match.group(1)} {match.group(2)}" if match else None


def ods_postcode(session, code: str) -> str | None:
    """Postcode of an organisation's registered address, from the ODS ORD API."""
    try:
        response = session.get(ORD_URL.format(code=quote(code)), timeout=30)
    except Exception:  # network trouble for one provider should not stop the build
        return None
    if response.status_code != 200:
        return None
    try:
        organisation = response.json().get("Organisation") or {}
    except ValueError:
        return None
    location = (organisation.get("GeoLoc") or {}).get("Location") or {}
    return normalise_postcode(location.get("PostCode"))


def ods_postcodes(session, codes: list[str], workers: int = 8) -> dict[str, str]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda code: (code, ods_postcode(session, code)), codes)
        return {code: postcode for code, postcode in results if postcode}


def geocode(session, postcodes: list[str]) -> dict[str, tuple[float, float]]:
    """Latitude/longitude for each postcode, falling back to terminated postcodes and outcodes."""
    found: dict[str, tuple[float, float]] = {}
    unique = sorted({postcode for postcode in postcodes if postcode})
    for start in range(0, len(unique), 100):
        chunk = unique[start : start + 100]
        response = session.post(f"{POSTCODES_URL}/postcodes", json={"postcodes": chunk}, timeout=60)
        response.raise_for_status()
        for item in response.json().get("result") or []:
            result = item.get("result")
            if result and result.get("latitude") is not None:
                found[normalise_postcode(item.get("query")) or item.get("query")] = (
                    float(result["latitude"]),
                    float(result["longitude"]),
                )
    for postcode in unique:
        if postcode in found:
            continue
        for path in (f"terminated_postcodes/{quote(postcode)}", f"outcodes/{quote(postcode.split()[0])}"):
            try:
                response = session.get(f"{POSTCODES_URL}/{path}", timeout=30)
                result = response.json().get("result") if response.status_code == 200 else None
            except Exception:
                result = None
            if result and result.get("latitude") is not None:
                found[postcode] = (float(result["latitude"]), float(result["longitude"]))
                break
    return found


def locate_providers(session, codes: list[str]) -> dict[str, dict]:
    """Return {code: {"postcode", "lat", "lon"}} for the providers that could be found."""
    postcodes = ods_postcodes(session, codes)
    coordinates = geocode(session, list(postcodes.values())) if postcodes else {}
    located = {}
    for code, postcode in postcodes.items():
        entry = {"postcode": postcode}
        if postcode in coordinates:
            lat, lon = coordinates[postcode]
            entry.update(lat=round(lat, 4), lon=round(lon, 4))
        located[code] = entry
    return located
