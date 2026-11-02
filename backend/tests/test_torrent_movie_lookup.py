from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from catalogues import torrent_caches
from fastapi import HTTPException, Response


def _record(
    identity: str,
    *,
    media_type: str = "movie",
    tmdb_id: str | None = None,
    imdb_id: str | None = None,
    title: str = "Example Movie",
    year: int = 2020,
) -> dict[str, Any]:
    return {
        "identity": identity,
        "title": title,
        "mediaIdentities": [{
            "mediaType": media_type,
            "tmdbId": tmdb_id,
            "imdbId": imdb_id,
            "title": title,
            "year": year,
        }],
    }


def _indexed_store(monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]]):
    store = torrent_caches.TorrentCacheStore(
        Path("/unused/seed"),
        Path("/unused/runtime"),
    )
    loaded_sections: list[str] = []

    def initialize() -> dict[str, Any]:
        return {"generation": 7}

    def load_section(section: str):
        loaded_sections.append(section)
        return {"records": records}, 7

    monkeypatch.setattr(store, "initialize", initialize)
    monkeypatch.setattr(store, "load_section", load_section)
    return store, loaded_sections


def test_movie_lookup_prefers_stable_ids_and_reuses_generation_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _record("a" * 40, tmdb_id="101", imdb_id="tt0000101"),
        _record("b" * 40, tmdb_id="101", imdb_id="tt0000101", title="Example Movie 1080p"),
        _record("c" * 40, tmdb_id="202", imdb_id="tt0000202"),
        _record("d" * 40, media_type="tv", tmdb_id="101"),
    ]
    store, loaded_sections = _indexed_store(monkeypatch, records)

    matched, generation = store.movie_records(
        "marvel",
        tmdb_id="101",
        imdb_id="tt0000202",
        title="Example Movie",
        year=2020,
    )
    other_movie, other_generation = store.movie_records(
        "marvel",
        tmdb_id="202",
        imdb_id=None,
        title=None,
        year=None,
    )

    assert generation == other_generation == 7
    assert {record["identity"] for record in matched} == {"a" * 40, "b" * 40}
    assert [record["identity"] for record in other_movie] == ["c" * 40]
    assert loaded_sections == ["marvel"], "the section is loaded only once per generation"


def test_movie_lookup_uses_imdb_or_exact_normalized_title_and_year_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _record("a" * 40, tmdb_id=None, imdb_id="tt0000101", title="Amélie: Love & War (Extended)", year=2021),
        _record("b" * 40, tmdb_id=None, imdb_id=None, title="Amelie - Love and War", year=2021),
        _record("c" * 40, tmdb_id=None, imdb_id=None, title="Amelie - Love and War", year=2020),
        _record("d" * 40, media_type="tv", tmdb_id=None, title="Amelie - Love and War", year=2021),
    ]
    store, _ = _indexed_store(monkeypatch, records)

    by_imdb, _ = store.movie_records(
        "marvel",
        tmdb_id="not-present",
        imdb_id="TT0000101",
        title=None,
        year=None,
    )
    by_title_year, _ = store.movie_records(
        "marvel",
        tmdb_id=None,
        imdb_id=None,
        title="Amelie Love and War",
        year=2021,
    )

    assert [record["identity"] for record in by_imdb] == ["a" * 40]
    assert [record["identity"] for record in by_title_year] == ["b" * 40]


def test_movie_torrent_options_route_validates_and_returns_only_movie_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [_record("a" * 40, tmdb_id="101")]

    class Store:
        def movie_records(self, section: str, **identifiers):
            assert section == "marvel"
            assert identifiers["tmdb_id"] == "101"
            return records, 7

    monkeypatch.setattr(torrent_caches, "store", Store())

    with pytest.raises(HTTPException) as missing_identifier:
        asyncio.run(torrent_caches.api_get_movie_torrent_options(
            "marvel",
            Response(),
            tmdb_id=None,
            imdb_id=None,
            title=None,
            year=None,
        ))
    assert missing_identifier.value.status_code == 422

    response = Response()
    result = asyncio.run(
        torrent_caches.api_get_movie_torrent_options(
            "marvel",
            response,
            tmdb_id="101",
            imdb_id=None,
            title=None,
            year=None,
        )
    )

    assert result == {"schemaVersion": 1, "section": "marvel", "records": records}
    assert response.headers["X-Torrent-Cache-Generation"] == "7"
