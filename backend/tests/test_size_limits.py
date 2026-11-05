"""TORRENT_MIN_SIZE_MB / TORRENT_MAX_SIZE_GB: one setting for every layer, applied before result caps."""

import importlib
import json
from pathlib import Path

import pytest

from catalogues import torrent_options as T

MB, GB = 1024**2, 1024**3


@pytest.fixture
def settings_with(monkeypatch):
    import core.settings as settings

    def load(**env):
        for name in ("TORRENT_MIN_SIZE_MB", "TORRENT_MAX_SIZE_GB"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(settings)

    yield load
    monkeypatch.delenv("TORRENT_MIN_SIZE_MB", raising=False)
    monkeypatch.delenv("TORRENT_MAX_SIZE_GB", raising=False)
    importlib.reload(settings)


def test_default_comes_from_search_limits_json(settings_with):
    s = settings_with()
    raw = json.loads((Path(__file__).resolve().parents[2] / "search_limits.json").read_text())
    assert s.MIN_SEARCH_RESULT_SIZE_BYTES == int(raw["minSizeMb"] * MB)
    assert s.MAX_SEARCH_RESULT_SIZE_BYTES == int(raw["maxSizeGb"] * GB)


def test_env_overrides_the_file_and_accepts_decimals(settings_with):
    s = settings_with(TORRENT_MAX_SIZE_GB="5", TORRENT_MIN_SIZE_MB="500")
    assert (s.MIN_SEARCH_RESULT_SIZE_BYTES, s.MAX_SEARCH_RESULT_SIZE_BYTES) == (500 * MB, 5 * GB)
    assert settings_with(TORRENT_MAX_SIZE_GB="3.5").MAX_SEARCH_RESULT_SIZE_BYTES == int(3.5 * GB)
    public = settings_with(TORRENT_MAX_SIZE_GB="5", TORRENT_MIN_SIZE_MB="250").SEARCH_SIZE_LIMITS_PUBLIC
    assert public == {"minSizeMb": 250.0, "maxSizeGb": 5.0}


@pytest.mark.parametrize("bad", ["", "abc", "-1", "0", "nan", "inf"])
def test_invalid_env_values_fall_back_to_the_file(settings_with, bad):
    base = settings_with()
    s = settings_with(TORRENT_MAX_SIZE_GB=bad, TORRENT_MIN_SIZE_MB=bad)
    assert s.MAX_SEARCH_RESULT_SIZE_BYTES == base.MAX_SEARCH_RESULT_SIZE_BYTES
    assert s.MIN_SEARCH_RESULT_SIZE_BYTES == base.MIN_SEARCH_RESULT_SIZE_BYTES


def test_max_never_drops_below_min(settings_with):
    s = settings_with(TORRENT_MIN_SIZE_MB="3000", TORRENT_MAX_SIZE_GB="1")
    assert s.MAX_SEARCH_RESULT_SIZE_BYTES == s.MIN_SEARCH_RESULT_SIZE_BYTES == 3000 * MB


def _write(directory, titles):
    doc = {"schemaVersion": 2, "kind": "torrent-options", "section": "hollywood", "trackers": [], "titles": titles}
    (directory / "hollywood-torrents.json").write_text(json.dumps(doc), encoding="utf-8")


def _rel(i, size_gb, seeders):
    return {"infoHash": f"{i:040x}", "title": f"Heat 1995 1080p {i}", "size": int(size_gb * GB), "seeders": seeders, "leechers": 0}


def test_window_is_applied_before_the_result_cap(tmp_path):
    """20 big releases out-seed 5 small ones; a 2 GB window must still show the small ones."""
    T.clear_memory_cache()
    releases = [_rel(i, 4.0, 1000 - i) for i in range(20)] + [_rel(100 + i, 1.5, 10 - i) for i in range(5)]
    _write(tmp_path, {"movie:1": {"title": "Heat", "year": 1995, "releases": releases}})
    at2 = T.lookup(("hollywood",), tmdb_id="1", seed_dir=tmp_path, min_size=250 * MB, max_size=2 * GB)
    assert len(at2) == 5 and all(r["size"] <= 2 * GB for r in at2)
    at5 = T.lookup(("hollywood",), tmdb_id="1", seed_dir=tmp_path, min_size=250 * MB, max_size=5 * GB)
    assert len(at5) == T.MAX_RESULTS and at5[0]["seeders"] == 1000, "a bigger window reveals what is already stored"
    assert len(T.lookup(("hollywood",), tmdb_id="1", seed_dir=tmp_path, min_size=2 * GB, max_size=5 * GB)) == T.MAX_RESULTS
    assert len(T.lookup(("hollywood",), tmdb_id="1", seed_dir=tmp_path)) == T.MAX_RESULTS     # no window passed: unfiltered


def test_series_packs_are_never_size_filtered(tmp_path):
    T.clear_memory_cache()
    pack = {"infoHash": "a" * 40, "title": "Reacher S01", "size": 40 * GB, "seeders": 5, "leechers": 0, "season": 1}
    _write(tmp_path, {"tv:9": {"title": "Reacher", "year": 2022, "releases": [pack]}})
    rows = T.lookup(("hollywood",), tmdb_id="9", seed_dir=tmp_path, media="tv", min_size=250 * MB, max_size=2 * GB)
    assert len(rows) == 1


def test_fullstack_index_carries_the_limits_without_an_extra_request(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    import fullstack_app as F

    index = tmp_path / "index.html"
    index.write_text("<html><head><title>x</title></head><body></body></html>", encoding="utf-8")
    monkeypatch.setattr(F, "INDEX_FILE", index)
    monkeypatch.setattr(F, "_index_cache", None)
    html = F._index_html()
    assert "window.__SEARCH_LIMITS__=" in html and html.index("__SEARCH_LIMITS__") < html.index("</head>")
    payload = html.split("window.__SEARCH_LIMITS__=")[1].split(";</script>")[0]
    assert set(json.loads(payload)) == {"minSizeMb", "maxSizeGb"}
    assert F._index_html() is F._index_cache[1], "patched once per file version, then served from memory"


def test_provider_size_gate_boundaries():
    pytest.importorskip("httpx")
    from core.settings import MAX_SEARCH_RESULT_SIZE_BYTES as hi, MIN_SEARCH_RESULT_SIZE_BYTES as lo
    from search.search_providers import _in_size_window

    assert _in_size_window(lo) and _in_size_window(hi) and _in_size_window(str(lo))
    assert not _in_size_window(lo - 1) and not _in_size_window(hi + 1)
    assert not _in_size_window(0) and not _in_size_window(None) and not _in_size_window("n/a")
