import asyncio

from fastapi.testclient import TestClient

from catalogues import catalogues_extra
from main import app
from metadata import search_metadata


def test_search_api_fails_closed_when_torrent_search_is_disabled(monkeypatch):
    calls = []

    async def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("torrent provider search was called")

    monkeypatch.setattr(search_metadata, "TORRENT_SEARCH_ENABLED", False)
    monkeypatch.setattr(search_metadata, "search_1337x", forbidden)

    response = TestClient(app).get("/api/search?q=Example")

    assert response.status_code == 503
    assert calls == []


def test_catalogue_builders_skip_all_torrent_searches_when_disabled(monkeypatch):
    calls = []

    async def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("torrent provider search was called")

    monkeypatch.setattr(catalogues_extra, "TORRENT_SEARCH_ENABLED", False)
    monkeypatch.setattr(catalogues_extra, "search_1337x", forbidden)
    monkeypatch.setattr(catalogues_extra, "search_1337x_direct", forbidden)
    monkeypatch.setattr(catalogues_extra, "search_yts_movies", forbidden)
    monkeypatch.setattr(catalogues_extra, "search_limetorrents", forbidden)

    asyncio.run(catalogues_extra._build_extra_catalogue("classics"))
    asyncio.run(catalogues_extra._build_marvel_catalogue())
    asyncio.run(catalogues_extra._ensure_extra_catalogue_refresh("classics"))

    assert calls == []


def test_classics_metadata_rebuild_only_refreshes_tv_metadata(monkeypatch):
    from maintenance import rebuild_classics

    calls = []

    async def rebuild_tv():
        calls.append("tv-metadata")

    monkeypatch.setattr(rebuild_classics, "rebuild_tv", rebuild_tv)
    asyncio.run(rebuild_classics.main())

    assert calls == ["tv-metadata"]
