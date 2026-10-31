"""Bounded recent-news discovery. Search hits are not verified incidents."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import os
import re
import time
from typing import Any
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


GDELT_DOC_URL = os.getenv("NAVIRA_GDELT_DOC_URL", "https://api.gdeltproject.org/api/v2/doc/doc")
CACHE_TTL_SECONDS = 15 * 60
STALE_MAX_SECONDS = 24 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 8
MAX_RESULTS = 20
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

CRIME_TERMS = (
    "woman", "women", "female", "harassment", "stalking", "molestation",
    "rape", "sexual assault", "assault", "snatching", "robbery", "murder",
)


def _category(headline: str) -> str:
    text = headline.casefold()
    if any(term in text for term in ("rape", "sexual assault", "sexual violence")):
        return "sexual_violence"
    if any(term in text for term in ("harassment", "molestation", "stalking", "eve teasing")):
        return "harassment_or_stalking"
    if any(term in text for term in ("snatching", "robbery", "looted")):
        return "robbery_or_snatching"
    if any(term in text for term in ("murder", "killed", "homicide")):
        return "murder_or_homicide"
    if any(term in text for term in ("assault", "attack", "beaten", "stabbed")):
        return "assault_or_attack"
    return "unknown_needs_review"


def _publication_time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _outside_recent_window(value: str | None) -> bool:
    if not value:
        return False
    try:
        published = datetime.fromisoformat(value)
        now = datetime.now(timezone.utc)
        return published < now - timedelta(days=93) or published > now + timedelta(hours=24)
    except (TypeError, ValueError, OverflowError):
        return False


def _parse_response(payload: Any, locality: str, retrieved_at: str) -> dict[str, Any]:
    raw_items = payload.get("articles", []) if isinstance(payload, dict) else []
    if not isinstance(raw_items, list):
        raise ValueError("GDELT response has an invalid articles list")
    items = []
    seen: set[str] = set()
    for article in raw_items[:MAX_RESULTS]:
        if not isinstance(article, dict):
            continue
        url = article.get("url")
        title = article.get("title")
        if not isinstance(url, str) or not isinstance(title, str) or not title.strip():
            continue
        published_at = _publication_time(article.get("seendate"))
        if _outside_recent_window(published_at):
            continue
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or url in seen:
            continue
        seen.add(url)
        items.append({
            "title": title[:500],
            "url": url,
            "publisher": str(article.get("domain") or parsed.hostname or "News source")[:200],
            "published_at": published_at,
            "headline_category_candidate": _category(title),
            "review_status": "needs_review",
            "locality_search_term": locality,
            "location_precision": "unverified_mention_match",
            "source_country": article.get("sourcecountry"),
            "language": article.get("language"),
        })
    return {
        "status": "available" if items else "no_results",
        "provider": "GDELT DOC 2.0",
        "retrieved_at": retrieved_at,
        "stale_after_seconds": CACHE_TTL_SECONDS,
        "search_window": "recent 3 months",
        "locality_search_term": locality,
        "items": items,
        "returned": len(items),
        "notice": "Discovery matches a locality term in indexed article text, not a verified incident location. Headlines are only category triage; open and review the publisher report. Results are selective and not crime rates.",
    }


def _parse_google_rss(xml_text: str, locality: str, retrieved_at: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    items = []
    seen: set[str] = set()
    for entry in root.findall("./channel/item")[:MAX_RESULTS]:
        title = (entry.findtext("title") or "").strip()
        url = (entry.findtext("link") or "").strip()
        source = (entry.findtext("source") or "Google News indexed source").strip()
        published_at = _publication_time(entry.findtext("pubDate"))
        if _outside_recent_window(published_at):
            continue
        parsed = urlparse(url)
        if not title or parsed.scheme not in {"http", "https"} or not parsed.netloc or url in seen:
            continue
        seen.add(url)
        items.append({
            "title": title[:500], "url": url, "publisher": source[:200],
            "published_at": published_at,
            "headline_category_candidate": _category(title), "review_status": "needs_review",
            "locality_search_term": locality, "location_precision": "unverified_mention_match",
            "source_country": "India", "language": "English",
        })
    return {
        "status": "available" if items else "no_results", "provider": "Google News RSS",
        "retrieved_at": retrieved_at, "stale_after_seconds": CACHE_TTL_SECONDS,
        "search_window": "recent 3 months", "locality_search_term": locality,
        "items": items, "returned": len(items),
        "notice": "Discovery matches a locality search term in indexed article text, not a verified incident location. Headlines are only category triage; open and review the publisher report. Results are selective and not crime rates.",
    }


def _discover_google_news(locality: str, retrieved_at: str) -> dict[str, Any]:
    terms = "woman OR women OR crime OR harassment OR stalking OR assault OR snatching OR robbery OR murder"
    query = f'"{locality}" Delhi ({terms}) when:3m'
    params = urlencode({"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    request = Request(
        f"https://news.google.com/rss/search?{params}",
        headers={"User-Agent": "Mozilla/5.0 NAVIRA locality-news-discovery/1.0", "Accept": "application/rss+xml, application/xml, text/xml"},
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"Google News RSS returned HTTP {response.status}")
        xml_text = response.read().decode("utf-8")
    return _parse_google_rss(xml_text, locality, retrieved_at)


def discover_locality_news(locality: str) -> dict[str, Any]:
    normalized = " ".join(locality.split())
    if len(normalized) < 2 or len(normalized) > 120 or re.search(r"\d{1,3}\.\d+\s*[, ]\s*\d{1,3}\.\d+", normalized):
        raise ValueError("Enter a Delhi locality or place name, not coordinates.")
    key = normalized.casefold()
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] <= CACHE_TTL_SECONDS:
        return {**cached[1], "cache_status": "cached"}

    safe_phrase = normalized.replace('"', " ").strip()
    query = f'"{safe_phrase}" AND Delhi AND sourcecountry:IN AND ("woman" OR "women" OR harassment OR stalking OR molestation OR rape OR assault OR snatching OR robbery OR murder)'
    params = urlencode({"query": query, "mode": "artlist", "format": "json", "sort": "datedesc", "timespan": "3m", "maxrecords": MAX_RESULTS})
    request = Request(f"{GDELT_DOC_URL}?{params}", headers={"User-Agent": "NAVIRA-news-discovery/1.0", "Accept": "application/json"})
    retrieved_at = datetime.now(timezone.utc).isoformat()
    gdelt_error = None
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RuntimeError(f"GDELT returned HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
        result = _parse_response(payload, normalized, retrieved_at)
        if result["items"]:
            _cache[key] = (now, result)
            return {**result, "cache_status": "fresh"}
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        gdelt_error = exc

    try:
        result = _discover_google_news(normalized, retrieved_at)
        if not result["items"] and cached and now - cached[0] <= STALE_MAX_SECONDS:
            return {**cached[1], "status": "stale", "cache_status": "stale_fallback", "provider_error": "Both live news indexes returned no candidates; showing a cached snapshot, not live results."}
        result["fallback_reason"] = "GDELT returned no matches." if gdelt_error is None else "GDELT was unavailable or rate-limited."
        _cache[key] = (now, result)
        return {**result, "cache_status": "fresh"}
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, ET.ParseError, RuntimeError, ValueError):
        if cached and now - cached[0] <= STALE_MAX_SECONDS:
            return {**cached[1], "status": "stale", "cache_status": "stale_fallback", "provider_error": "Live news indexes are unavailable; showing a cached snapshot, not live results."}
        return {
            "status": "unavailable", "provider": "GDELT DOC 2.0 + Google News RSS", "retrieved_at": retrieved_at,
            "stale_after_seconds": CACHE_TTL_SECONDS, "search_window": "recent 3 months",
            "locality_search_term": normalized, "items": [], "returned": 0,
            "cache_status": "miss", "provider_error": "Both news indexes are temporarily unavailable or rate-limited.",
            "notice": "No live news results are available. This is not evidence of zero crime.",
        }
