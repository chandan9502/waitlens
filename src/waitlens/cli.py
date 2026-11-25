"""Command line: ``waitlens build`` downloads RTT data and writes the site's JSON."""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
from pathlib import Path

from . import __version__
from .build import (
    COMPLETED_WINDOW,
    build_outputs,
    format_validation,
    load_anchors,
    summarise_month,
    write_outputs,
)
from .discover import discover
from .rtt import read_month

USER_AGENT = f"WaitLens/{__version__} (+https://github.com/chandan9502/waitlens)"


def make_session():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    retry = Retry(
        total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET", "POST")
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
    return session


def download(session, url: str, period: str, cache: Path) -> Path:
    """Download a monthly ZIP once; revised files have new URLs, so they get new names."""
    cache.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    path = cache / f"rtt-{period}-{digest}.zip"
    if path.exists() and path.stat().st_size > 0:
        return path
    partial = path.with_suffix(".part")
    with session.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 16):
                handle.write(chunk)
    partial.rename(path)
    return path


def cmd_discover(args) -> int:
    links = discover(make_session(), years=args.years)
    for period, url in links.items():
        print(f"{period}  {url}")
    return 0


def cmd_build(args) -> int:
    session = None
    sources: dict[str, str] = {}
    if args.zip:
        paths = [Path(path) for path in args.zip]
        jobs = [(None, path) for path in paths]
    else:
        session = make_session()
        years = args.years or max(2, math.ceil(args.months / 12) + 1)
        links = discover(session, years=years)
        chosen = list(links.items())[-args.months :]
        print(f"Found {len(links)} months; using {len(chosen)} ({chosen[0][0]} to {chosen[-1][0]})")
        jobs = []
        for period, url in chosen:
            sources[period] = url
            jobs.append((period, download(session, url, period, Path(args.cache))))

    keep_from = max(0, len(jobs) - COMPLETED_WINDOW)
    summaries = []
    for index, (period, path) in enumerate(jobs):
        try:
            month = read_month(path, label=sources.get(period, Path(path).name))
        except (ValueError, KeyError) as exc:
            print(f"warning: skipping {period or path}: {exc}", file=sys.stderr)
            continue
        if period and month.period != period:
            print(f"warning: {path.name} says {month.period}, the page said {period}", file=sys.stderr)
        summaries.append(summarise_month(month, keep_completed=index >= keep_from))
        providers = month.frame["provider_code"].nunique()
        bands = len(month.bands)
        print(f"  {month.period}: {len(month.frame):,} rows, {providers} providers, {bands} weekly bands")

    if not summaries:
        print("error: no month could be read", file=sys.stderr)
        return 1
    summaries.sort(key=lambda summary: summary.period)
    locations = {}
    if args.geo:
        from .geo import locate_providers

        session = session or make_session()
        latest_codes = sorted(summaries[-1].providers.index)
        locations = locate_providers(session, latest_codes)
        with_coordinates = sum(1 for entry in locations.values() if "lat" in entry)
        print(f"Located {with_coordinates} of {len(latest_codes)} providers")

    outputs = build_outputs(summaries, locations=locations, sources=sources, anchors=load_anchors())
    written = write_outputs(outputs, Path(args.out))
    print(f"Wrote {len(written)} files to {args.out}")
    validation = outputs["meta.json"]["validation"]
    print(format_validation(validation))
    if args.strict and any(not check["ok"] for result in validation for check in result["checks"]):
        print("error: computed national figures differ from the published press notice", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="waitlens", description=__doc__)
    parser.add_argument("--version", action="version", version=f"waitlens {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="download RTT data and write the site's JSON files")
    build.add_argument("--out", default="site/data", help="output directory (default: site/data)")
    build.add_argument("--months", type=int, default=25, help="number of months to include (default: 25)")
    build.add_argument(
        "--years", type=int, help="financial-year pages to search (default: enough for --months)"
    )
    build.add_argument("--cache", default=".cache/rtt", help="where downloaded ZIP files are kept")
    build.add_argument("--zip", nargs="+", help="build from local Full CSV ZIP files instead of downloading")
    build.add_argument("--no-geo", dest="geo", action="store_false", help="skip provider location lookups")
    build.add_argument("--strict", action="store_true", help="exit 2 if the press-notice check fails")
    build.set_defaults(func=cmd_build)

    disc = sub.add_parser("discover", help="list the monthly files available on NHS England's site")
    disc.add_argument("--years", type=int, default=2, help="financial-year pages to search (default: 2)")
    disc.set_defaults(func=cmd_discover)

    args = parser.parse_args(argv)
    if getattr(args, "months", 1) < 1:
        parser.error("--months must be at least 1")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
