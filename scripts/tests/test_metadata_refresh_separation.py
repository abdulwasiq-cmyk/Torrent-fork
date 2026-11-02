import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "refresh_seed.py"
SPEC = importlib.util.spec_from_file_location("metadata_seed_refresh", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_refresh_seed_passes_search_off_and_does_not_copy_torrent_artifacts(
    tmp_path, monkeypatch
):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "hollywood.json").write_text(json.dumps({"section": "hollywood"}))
    (seed / "hollywood-torrents.json").write_text('{"records":[{"identity":"original"}]}')
    monkeypatch.setattr(MODULE, "SEED", seed)
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    monkeypatch.setattr(sys, "argv", ["refresh_seed.py", "hollywood-bollywood"])
    captured = {}

    def fake_refresh(_env, data_dir):
        captured.update(_env)
        (data_dir / "hollywood-torrents.json").write_text(
            '{"records":[{"identity":"should-not-publish"}]}'
        )

    monkeypatch.setattr(MODULE, "refresh_hollywood_bollywood", fake_refresh)
    MODULE.main()

    assert captured["TORRENT_SEARCH_ENABLED"] == "false"
    assert captured["REGIONAL_CACHE_TORRENT_SCAN"] == "false"
    assert (seed / "hollywood-torrents.json").read_text() == (
        '{"records":[{"identity":"original"}]}'
    )
    assert all(
        "torrent" not in name.casefold()
        for group in MODULE.GROUPS.values()
        for name in group["top"] + group["runtime"]
    )
