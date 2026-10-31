from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import time

import pytest

from backend.app.services import news_discovery as discovery
from backend.app import main


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeXmlResponse(FakeResponse):
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload.encode("utf-8")


def test_discovery_queries_recent_delhi_articles_and_parses_candidates(monkeypatch):
    discovery._cache.clear()
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        query = parse_qs(urlparse(request.full_url).query)
        assert query["mode"] == ["artlist"]
        assert query["timespan"] == ["3m"]
        assert '"CR Park"' in query["query"][0]
        return FakeResponse({"articles": [
            {"url": "https://news.example/story/1", "title": "Phone snatching reported in CR Park", "domain": "news.example", "seendate": "20261025T123000Z", "sourcecountry": "India", "language": "English"},
            {"url": "javascript:alert(1)", "title": "Unsafe link"},
            {"url": "https://news.example/story/1", "title": "Duplicate"},
        ]})

    monkeypatch.setattr(discovery, "urlopen", fake_urlopen)
    result = discovery.discover_locality_news("  CR Park  ")
    assert result["status"] == "available"
    assert result["search_window"] == "recent 3 months"
    assert result["returned"] == 1
    assert result["items"][0]["headline_category_candidate"] == "robbery_or_snatching"
    assert result["items"][0]["review_status"] == "needs_review"
    assert result["items"][0]["location_precision"] == "unverified_mention_match"
    assert len(calls) == 1 and calls[0][1] <= 10


def test_discovery_caches_repeat_queries(monkeypatch):
    discovery._cache.clear()
    calls = []
    def no_results(request, **_kwargs):
        calls.append(1)
        if "gdeltproject.org" in request.full_url:
            return FakeResponse({"articles": []})
        return FakeXmlResponse("<rss><channel></channel></rss>")
    monkeypatch.setattr(discovery, "urlopen", no_results)
    first = discovery.discover_locality_news("Test Locality")
    second = discovery.discover_locality_news("test locality")
    assert first["status"] == "no_results"
    assert second["cache_status"] == "cached"
    assert len(calls) == 2


def test_google_news_rss_is_used_when_gdelt_is_rate_limited(monkeypatch):
    discovery._cache.clear()

    def gdelt_limited_google_available(request, **_kwargs):
        if "gdeltproject.org" in request.full_url:
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)
        return FakeXmlResponse("""<rss><channel><item><title>Police probe robbery near CR Park - Example News</title><link>https://news.example/story/7</link><pubDate>Thu, 29 Oct 2026 10:00:00 GMT</pubDate><source>Example News</source></item></channel></rss>""")

    monkeypatch.setattr(discovery, "urlopen", gdelt_limited_google_available)
    result = discovery.discover_locality_news("CR Park")
    assert result["status"] == "available"
    assert result["provider"] == "Google News RSS"
    assert result["fallback_reason"] == "GDELT was unavailable or rate-limited."
    assert result["items"][0]["publisher"] == "Example News"
    assert result["items"][0]["url"] == "https://news.example/story/7"
    assert result["items"][0]["location_precision"] == "unverified_mention_match"


def test_google_news_rss_drops_publication_dates_far_in_the_future():
    future = format_datetime(datetime.now(timezone.utc) + timedelta(days=3))
    xml = f"<rss><channel><item><title>Delhi crime report</title><link>https://news.example/future</link><pubDate>{future}</pubDate><source>Example News</source></item></channel></rss>"
    result = discovery._parse_google_rss(xml, "CR Park", datetime.now(timezone.utc).isoformat())
    assert result["status"] == "no_results"
    assert result["items"] == []


def test_google_news_rss_drops_results_older_than_the_recent_window():
    old = format_datetime(datetime.now(timezone.utc) - timedelta(days=120))
    xml = f"<rss><channel><item><title>Delhi crime report</title><link>https://news.example/old</link><pubDate>{old}</pubDate><source>Example News</source></item></channel></rss>"
    result = discovery._parse_google_rss(xml, "CR Park", datetime.now(timezone.utc).isoformat())
    assert result["status"] == "no_results"
    assert result["items"] == []


def test_discovery_rate_limit_returns_explicit_unavailable_and_stale_fallback(monkeypatch):
    discovery._cache.clear()
    monkeypatch.setattr(discovery, "urlopen", lambda *_args, **_kwargs: FakeResponse({"articles": [{"url": "https://news.example/1", "title": "Delhi robbery"}]}))
    first = discovery.discover_locality_news("Cache locality")
    monkeypatch.setattr(discovery, "CACHE_TTL_SECONDS", 0)
    discovery._cache["cache locality"] = (time.monotonic() - 1, discovery._cache["cache locality"][1])

    def rate_limited(*_args, **_kwargs):
        raise HTTPError("https://gdelt.example", 429, "rate limited", {}, None)

    monkeypatch.setattr(discovery, "urlopen", rate_limited)
    fallback = discovery.discover_locality_news("Cache locality")
    assert fallback["status"] == "stale"
    assert fallback["cache_status"] == "stale_fallback"
    assert fallback["items"] == first["items"]

    discovery._cache.clear()
    unavailable = discovery.discover_locality_news("No-cache locality")
    assert unavailable["status"] == "unavailable"
    assert "not evidence of zero crime" in unavailable["notice"]


@pytest.mark.parametrize("value", ["", "A", "28.6139, 77.2090", "x" * 121])
def test_discovery_rejects_invalid_locality_terms(value):
    with pytest.raises(ValueError):
        discovery.discover_locality_news(value)


def test_api_groups_discovery_candidates_by_selected_locality(monkeypatch):
    monkeypatch.setattr(main, "discover_locality_news", lambda locality: {"locality_search_term": locality, "status": "unavailable", "items": []})
    response = main.discover_news(main.NewsDiscoveryIn(localities=["CR Park", "Welcome"]))
    assert [group["locality_search_term"] for group in response["groups"]] == ["CR Park", "Welcome"]
    assert "does not prove an incident occurred" in response["notice"]
