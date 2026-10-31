"""Discover source-linked candidates from the public Delhi Police press archive.

The archive listing is selective and may be paginated or changed by the site.
Its rows are candidate evidence only; they are not a complete FIR register.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import re
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


ARCHIVE_URL = "https://scrb.delhipolice.gov.in/newpressrelease"
CACHE_SECONDS = 30 * 60
STALE_CACHE_SECONDS = 7 * 24 * 60 * 60
TIMEOUT_SECONDS = 10
CRIME_TERMS = (
    "rape", "molestation", "sexual assault", "harassment", "stalking", "woman",
    "women", "snatching", "robbery", "murder", "assault", "kidnap", "abduct",
    "theft", "crime", "arrest", "accused", "criminal", "gang", "fraud",
)
_cache: tuple[float, dict[str, Any]] | None = None
_lock = threading.Lock()


def _text(value: str) -> str:
    return " ".join(value.split()).strip()


class _ArchiveTableParser(HTMLParser):
    """Extract table rows from Delhi Police's archive listing without dependencies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._anchor: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {"text": "", "links": []}
        elif tag == "a" and self._cell is not None:
            self._anchor = {"href": attrs_map.get("href") or "", "text": ""}
        elif tag == "br" and self._cell is not None:
            self._cell["text"] += " "

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor["text"] += data
        if self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor is not None:
            if self._cell is not None:
                self._cell["links"].append(self._anchor)
            self._anchor = None
        elif tag in {"td", "th"} and self._cell is not None:
            self._cell["text"] = _text(self._cell["text"])
            if self._row is not None:
                self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _header_key(value: str) -> str:
    return re.sub(r"[^a-z]+", "", value.casefold())


def _parse_date(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value.strip())
    for pattern in ("%d %b, %Y", "%d %b %Y", "%d %B, %Y", "%d %B %Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _crime_category(text: str) -> str | None:
    lowered = text.casefold()
    rules = (
        ("sexual_violence", ("rape", "sexual assault", "sexual violence")),
        ("harassment_or_stalking", ("molestation", "harassment", "stalking", "eve teasing")),
        ("robbery_or_snatching", ("snatching", "robbery", "dacoity")),
        ("murder_or_homicide", ("murder", "homicide")),
        ("assault_or_attack", ("assault", "attack", "beaten", "stabbed")),
        ("kidnapping_or_abduction", ("kidnap", "abduct", "trafficking")),
        ("theft_or_burglary", ("theft", "burglary", "house break")),
        ("fraud_or_cybercrime", ("fraud", "cheat", "cyber crime", "cybercrime")),
    )
    for category, terms in rules:
        if any(term in lowered for term in terms):
            return category
    return None


def _archive_rows(html: str, retrieved_at: str) -> list[dict[str, Any]]:
    parser = _ArchiveTableParser()
    parser.feed(html)
    rows = parser.rows
    header_index = next((i for i, row in enumerate(rows) if {"title", "policestation"}.issubset({_header_key(cell["text"]) for cell in row}) and ({"issuedate", "pressdate", "date", "published"} & {_header_key(cell["text"]) for cell in row})), None)
    if header_index is None:
        raise ValueError("Delhi Police archive table headers were not recognized")
    header = {_header_key(cell["text"]): i for i, cell in enumerate(rows[header_index])}

    def cell_value(row: list[dict[str, Any]], *keys: str) -> str:
        index = next((header[key] for key in keys if key in header), None)
        return row[index]["text"] if index is not None and index < len(row) else ""

    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_fingerprints: set[tuple[str, str, str]] = set()
    for row in rows[header_index + 1:]:
        title = cell_value(row, "title", "subject", "heading")
        if not title:
            continue
        archive_category = cell_value(row, "category", "type")
        category = _crime_category(f"{title} {archive_category}")
        if not category and not any(term in f"{title} {archive_category}".casefold() for term in CRIME_TERMS):
            continue
        station = cell_value(row, "policestation", "station", "ps")
        district = cell_value(row, "district", "policedistrict")
        issue_date_text = cell_value(row, "issuedate", "pressdate", "date", "published")
        issue_date = _parse_date(issue_date_text)
        links = [link for cell in row for link in cell["links"] if link.get("href")]
        link = next((candidate for candidate in links if "view" in candidate["text"].casefold() or "download" in candidate["text"].casefold()), links[0] if links else None)
        # Some archive rows do not expose a direct item URL. Keep the official
        # archive as the source instead of inventing a record URL.
        canonical_url = urljoin(ARCHIVE_URL, link["href"]) if link else ARCHIVE_URL
        parsed = urlparse(canonical_url)
        if parsed.scheme != "https" or parsed.netloc.casefold() not in {"www.delhipolice.gov.in", "delhipolice.gov.in", "scrb.delhipolice.gov.in"}:
            canonical_url = ARCHIVE_URL
            link = None
        fingerprint = (title.casefold(), issue_date or issue_date_text.casefold(), station.casefold())
        if (link and canonical_url in seen_urls) or fingerprint in seen_fingerprints:
            continue
        if link:
            seen_urls.add(canonical_url)
        seen_fingerprints.add(fingerprint)
        items.append({
            "id": re.sub(r"[^a-z0-9]+", "-", f"dp-{issue_date or 'undated'}-{station}-{title}".casefold()).strip("-")[:160],
            "title": title[:500], "url": canonical_url, "publisher": "Delhi Police",
            "source_link_precision": "record_link" if link else "archive_listing_only",
            "published_at": issue_date, "published_date_text": issue_date_text or None,
            "police_station": station or None, "district": district or None,
            "archive_category": archive_category or "Press Release",
            "headline_category_candidate": category or "needs_review",
            "review_status": "needs_review", "source_kind": "official_press_release",
            "location_precision": "police_station_metadata_only" if station else "unknown",
            "retrieved_at": retrieved_at,
            "notice": "Official press-release listing candidate. It is selective, not a complete FIR register; headline classification and route relevance need human review.",
        })
    return items


def _fetch_archive() -> dict[str, Any]:
    global _cache
    now = time.monotonic()
    with _lock:
        if _cache and now - _cache[0] < CACHE_SECONDS:
            return {**_cache[1], "cache_status": "cached"}
    retrieved_at = datetime.now(timezone.utc).isoformat()
    request = Request(ARCHIVE_URL, headers={"User-Agent": "NAVIRA/1.0 (+https://github.com/singhxagauri-jpg/Navira)", "Accept": "text/html"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"Delhi Police archive returned HTTP {response.status}")
        html = response.read().decode("utf-8", errors="replace")
    items = _archive_rows(html, retrieved_at)
    today = datetime.now(timezone.utc).date()
    try:
        from_date = today.replace(year=today.year - 10)
    except ValueError:  # Feb 29 on a leap day
        from_date = today.replace(year=today.year - 10, day=28)
    from_year, to_year = from_date.year, today.year
    target_items = [item for item in items if item.get("published_at") and from_date.isoformat() <= item["published_at"] <= today.isoformat()]
    years = sorted({int(item["published_at"][:4]) for item in items if item.get("published_at")})
    result = {
        "status": "available" if items else "no_candidates",
        "provider": "Delhi Police press-release archive",
        "archive_url": ARCHIVE_URL,
        "retrieved_at": retrieved_at,
        "items": items,
        "returned": len(items),
        "observed_years": years,
        "target_window": {"from_date": from_date.isoformat(), "to_date": today.isoformat(), "from_year": from_year, "to_year": to_year},
        "target_items": target_items,
        "coverage_note": f"The public listing page returned {len(items)} matching crime-related candidates in the {from_date.isoformat()} to {today.isoformat()} window. Years visible in this response: {', '.join(map(str, years)) or 'none'}. The listing is paginated; the full ten-year archive has not been imported, so missing years or matches are coverage gaps, not zero-crime findings.",
        "notice": "Press releases are official communications but selective. These records are report candidates, not a complete list of registered crimes or locality crime rates.",
        "cache_status": "fresh",
    }
    with _lock:
        _cache = (time.monotonic(), result)
    return result


def _normalized_station(value: str) -> str:
    value = re.sub(r"\b(?:police station|police|p\.s\.|ps)\b", " ", value.casefold())
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def discover_press_release_candidates(
    localities: list[str] | None = None,
    police_stations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Match route police-station names to the archive's Police Station field."""
    localities = localities or []
    police_stations = police_stations or []
    if not police_stations and not localities:
        return {
            "status": "unavailable", "provider": "Delhi Police press-release archive",
            "archive_url": ARCHIVE_URL, "groups": [], "candidate_count": 0,
            "notice": "No route police stations were resolved; archive entries cannot be matched.",
        }
    try:
        archive = _fetch_archive()
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, RuntimeError, ValueError) as exc:
        cached = _cache
        if cached and time.monotonic() - cached[0] <= STALE_CACHE_SECONDS:
            archive = {**cached[1], "status": "stale", "cache_status": "stale_fallback"}
        else:
            return {
                "status": "unavailable", "provider": "Delhi Police press-release archive",
                "archive_url": ARCHIVE_URL, "items": [], "returned": 0,
                "provider_error": "Delhi Police press-release archive could not be read right now.",
                "diagnostic": str(exc)[:240],
                "notice": "Archive unavailable is not evidence of zero incidents.",
            }
    groups = []
    stations = police_stations if police_stations else [{"name": locality} for locality in localities]
    for station in stations:
        locality = str(station.get("name") or "").strip()
        needle = _normalized_station(locality)
        matching = []
        if needle:
            for item in archive["target_items"]:
                listed_station = _normalized_station(item.get("police_station") or "")
                if listed_station and listed_station not in {"several", "unknown", "several police stations"} and listed_station == needle:
                    matching.append({**item, "route_match": "exact police-station field match", "route_match_status": "candidate_only"})
        groups.append({
            "locality": locality,
            "police_station": locality,
            "district": station.get("district"),
            "first_sample_distance_m": station.get("first_sample_distance_m"),
            "status": "available" if matching else "stale" if archive.get("status") == "stale" else ("no_matches" if archive.get("status") != "unavailable" else "unavailable"),
            "items": matching,
            "returned": len(matching),
            "notice": "Exact match against the archive Police Station field and the route-crossed station name. Press releases are selective; they are not registered-case totals and do not prove the incident location.",
        })
    return {
        "status": archive["status"], "provider": archive["provider"],
        "archive_url": archive["archive_url"], "retrieved_at": archive["retrieved_at"],
        "cache_status": archive["cache_status"], "observed_years": archive["observed_years"],
        "target_window": archive["target_window"], "coverage_note": archive["coverage_note"], "groups": groups,
        "candidate_count": sum(group["returned"] for group in groups),
        "notice": archive["notice"],
    }
