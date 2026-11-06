"""Nuvio Streams add-on client: parsing, https-only links, caching, and "unavailable" fallbacks (no network)."""

import asyncio

import pytest

from catalogues import nuvio_streams as N

PAYLOAD = {"streams": [
    {"name": "4KHDHub [FSL] - 4K | DV | HDR | BluRay | REMUX",
     "title": "The Shawshank Redemption (1994) 2160p REMUX.mkv\n53.36GB",
     "url": "https://a.workers.dev/tok::1/1398/The Shawshank [Hindi] (1994).mkv"},
    {"name": "4KHDHub [FSL] - 1080p | BluRay", "title": "S 1080p.mkv\n2.37GB", "url": "https://b.workers.dev/p/S 1080p.mkv"},
    {"name": "4KHDHub [FSL] - 1080p | BluRay", "title": "S 1080p v2.mkv\n10.79GB", "url": "https://c.workers.dev/p/S2.mkv"},
    {"name": "x", "title": "insecure\n1GB", "url": "http://plain.example/x.mkv"},
    {"name": "x", "title": "dup\n1GB", "url": "https://b.workers.dev/p/S 1080p.mkv"},
    "junk",
]}


@pytest.fixture(autouse=True)
def _clean():
    N.clear_cache()
    yield
    N.clear_cache()


def test_parse_orders_by_quality_then_size_and_labels_options():
    options = N.parse_streams(PAYLOAD)
    assert [o["quality"] for o in options] == ["2160p", "1080p", "1080p"]
    assert [o["label"] for o in options] == ["4K · 53.4 GB · REMUX HDR DV", "1080p · 2.4 GB", "1080p · 10.8 GB"]
    assert [o["key"] for o in options] == ["0", "1", "2"]


def test_links_are_https_only_deduplicated_and_percent_encoded():
    urls = [o["url"] for o in N.parse_streams(PAYLOAD)]
    assert all(u.startswith("https://") for u in urls) and len(urls) == 3
    assert not any(c in u for u in urls for c in " []")
    assert urls[0].endswith("/The%20Shawshank%20%5BHindi%5D%20(1994).mkv") and "::" in urls[0]


@pytest.mark.parametrize("payload", [None, {}, {"streams": []}, {"streams": "no"}, {"streams": [{"url": ""}]}])
def test_parse_handles_empty_or_odd_answers(payload):
    assert N.parse_streams(payload) == []


def test_lookup_is_unavailable_without_a_configured_add_on_or_valid_id():
    async def boom(url):
        raise AssertionError("must not be called")
    assert asyncio.run(N.lookup("", 278, fetcher=boom)) == []
    assert asyncio.run(N.lookup("http://x:7777", "abc", fetcher=boom)) == []


def test_lookup_calls_the_tmdb_stream_route_and_shares_one_scrape_between_clicks():
    calls: list[str] = []

    async def fetcher(url):
        calls.append(url)
        await asyncio.sleep(0.02)
        return PAYLOAD

    async def main():
        first, second = await asyncio.gather(N.lookup("http://x:7777/", 278, fetcher=fetcher), N.lookup("http://x:7777", 278, fetcher=fetcher))
        third = await N.lookup("http://x:7777", 278, fetcher=fetcher)
        return first, second, third

    first, second, third = asyncio.run(main())
    assert calls == ["http://x:7777/stream/movie/tmdb:278.json"]
    assert len(first) == len(second) == len(third) == 3


def test_empty_answers_are_remembered_briefly_then_retried():
    clock = [0.0]
    calls = []

    async def fetcher(url):
        calls.append(url)
        return {"streams": []}

    async def run():
        await N.lookup("http://x", 1, fetcher=fetcher, now=lambda: clock[0])
        await N.lookup("http://x", 1, fetcher=fetcher, now=lambda: clock[0])
        clock[0] += N.EMPTY_TTL_S + 1
        await N.lookup("http://x", 1, fetcher=fetcher, now=lambda: clock[0])

    asyncio.run(run())
    assert len(calls) == 2


def test_a_failing_add_on_gives_no_options_not_an_error():
    async def fetcher(url):
        return None
    assert asyncio.run(N.lookup("http://x", 5, fetcher=fetcher)) == []
