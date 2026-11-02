#!/usr/bin/env python3
"""Refresh part of backend/cache-seed with live provider data (run from CI or locally).

    python scripts/refresh_seed.py hollywood-bollywood   # weekly workflow
    python scripts/refresh_seed.py franchise             # manual workflow (Marvel, DC, classics)
    python scripts/refresh_seed.py classics              # only the Classics lists (new titles, ratings, streaming)
    python scripts/refresh_seed.py imdb-dataset          # IMDb ratings from IMDb's free dataset (no key)
    python scripts/refresh_seed.py tv-imdb               # only IMDb ratings for web series / anime

Needs TMDB / Watchmode / OMDb keys in the environment. It works on a temporary copy of the
seed, runs the backend with CACHE_FIRST=false so stale entries are really refreshed, and then
copies back only the files of that group that changed (and still parse as JSON). Nothing is
written to the seed if a step fails, so a bad run can never blank the bundled data.
"""
import json, os, shutil, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SEED = Path(os.getenv("REFRESH_SEED_DIR") or BACKEND / "cache-seed")  # VPS keeps its own working copy

# Files that live in runtime/ inside the seed (flat inside APP_DATA_DIR).
SHARED_RUNTIME = [
    "tmdb_movie_catalogue_cache.json", "tmdb_search_metadata_cache.json",
    "imdb_rating_cache.json", "tmdb_ott_availability_cache.json",
]
GROUPS = {
    "hollywood-bollywood": {
        "top": ["regional_tv_prebuilt_cache.json"],
        "runtime": SHARED_RUNTIME + [
            "regional_movie_prebuilt_cache.json", "regional_movie_trending_archive.json", "nexstream_cache.json",
        ],
    },
    "regional-tv-new": {"top": ["regional_tv_prebuilt_cache.json"], "runtime": ["imdb_rating_cache.json"]},  # only Korean, Pakistani and anime sections
    "tv-imdb": {"top": [], "runtime": ["imdb_rating_cache.json"]},   # only the OMDb ratings for web series/anime
    "imdb-dataset": {"top": [], "runtime": ["imdb_rating_cache.json"]},   # only IMDb ratings from the free dataset
    "classics": {
        "top": ["classics_catalogue.json", "classics_web_series_tv_catalogue.json", "classics_anime_tv_catalogue.json"],
        "runtime": SHARED_RUNTIME,
    },
    "franchise": {
        "top": [
            "marvel_catalogue.json", "marvel_hindi_catalogue.json", "marvel_web_series_catalogue.json",
            "dc_live_action_catalogue.json", "dc_live_action_hindi_catalogue.json",
            "dc_animated_catalogue.json", "classics_catalogue.json",
            "classics_web_series_tv_catalogue.json", "classics_anime_tv_catalogue.json",
        ],
        "runtime": SHARED_RUNTIME + ["marvel_tv_catalogue_cache.json", "dc_tv_catalogue_cache.json"],
    },
}


def stage(data_dir: Path) -> None:
    for f in SEED.glob("*.json"):
        shutil.copy2(f, data_dir / f.name)
    for f in (SEED / "runtime").glob("*.json"):
        shutil.copy2(f, data_dir / f.name)


def run(cmd, env, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, env=env, check=True, **kw)


def port_is_free(port):
    import socket
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def free_port():
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(base, proc, seconds=180):
    for _ in range(seconds):
        if proc.poll() is not None:
            raise SystemExit("backend exited early")
        try:
            urllib.request.urlopen(base + "/api/health", timeout=3).read()
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("backend did not become healthy")


def refresh_hollywood_bollywood(env, data_dir):
    port = env.setdefault("PORT", "10111")
    if not port_is_free(int(port)):
        # A leftover backend from an earlier, killed run would otherwise answer our health check and
        # we would build against it (stale code and environment). Use a free port instead.
        port = env["PORT"] = str(free_port())
        print(f"Port in use by another process; using {port} for this run's backend.", flush=True)
    base = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fullstack_app:app", "--host", "127.0.0.1", "--port", port],
        cwd=BACKEND, env=env)
    try:
        wait_ready(base, server)
        env = {**env, "HOME_DATA_DIR": str(data_dir), "HOME_API_BASE": base}
        run([sys.executable, "maintenance/pull_nexstream_reports.py", str(data_dir)], env, cwd=BACKEND)
        run([sys.executable, str(ROOT / "scripts" / "build_regional_movie_cache.py")], env)
        warm_regional_tv_catalogues(base, include_existing=True)
        warm_imdb_dataset(env)
        warm_tv_imdb(env)
    finally:
        server.terminate()
        try:
            server.wait(20)
        except subprocess.TimeoutExpired:
            server.kill()


def warm_regional_tv_catalogues(base, include_existing=False):
    """Prebuild only the requested regional web-series sections for the cache bundle."""
    import json
    import urllib.error
    import urllib.request

    catalogues = [
        "korean-popular", "korean-trending", "korean-latest",
        "pakistani-popular", "pakistani-trending", "pakistani-latest",
        "anime-popular", "anime-trending", "anime-latest",
    ]
    if include_existing:
        catalogues = [
            "indian-popular", "indian-trending", "indian-latest",
            "hollywood-popular", "hollywood-trending", "hollywood-latest",
            *catalogues,
        ]
    failures = []
    for key in catalogues:
        url = f"{base}/api/tv/catalogue/{key}?page=1"
        try:
            with urllib.request.urlopen(url, timeout=180) as response:
                payload = json.loads(response.read().decode("utf-8"))
            results = payload.get("results")
            if not isinstance(results, list) or not results:
                failures.append(f"{key}: empty or invalid results")
                print(f"WARNING: regional TV cache warm returned no results for {key}", flush=True)
                continue
            print(f"Regional TV cache warmed: {key} ({len(results)} rows, {payload.get('totalPages', 1)} pages)", flush=True)
        except Exception as exc:
            failures.append(f"{key}: {exc}")
            print(f"WARNING: regional TV cache warm failed for {key}: {exc}", flush=True)
    if failures:
        raise RuntimeError("Regional TV cache refresh incomplete: " + "; ".join(failures))


def refresh_regional_tv_new(env, data_dir):
    """Refresh only Korean, Pakistani and anime regional TV cache entries."""
    port = env.setdefault("PORT", "10112")
    if not port_is_free(int(port)):
        port = env["PORT"] = str(free_port())
        print(f"Port in use by another process; using {port} for this run's backend.", flush=True)
    base = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fullstack_app:app", "--host", "127.0.0.1", "--port", port],
        cwd=BACKEND, env=env)
    try:
        wait_ready(base, server)
        warm_regional_tv_catalogues(base)
    finally:
        server.terminate()
        try:
            server.wait(20)
        except subprocess.TimeoutExpired:
            server.kill()


def warm_tv_imdb(env):
    # Ratings are a bonus: a bad OMDb key must not throw away a finished catalogue refresh.
    try:
        run([sys.executable, "maintenance/warm_tv_imdb.py"], env, cwd=BACKEND)
    except subprocess.CalledProcessError as exc:
        print(f"WARNING: TV IMDb ratings step failed ({exc}); continuing.", flush=True)


def warm_imdb_dataset(env):
    # Free, no daily limit: runs before the OMDb step so OMDb only has to cover what is left.
    try:
        run([sys.executable, "maintenance/warm_imdb_dataset.py"], env, cwd=BACKEND)
    except subprocess.CalledProcessError as exc:
        print(f"WARNING: IMDb dataset step failed ({exc}); continuing.", flush=True)


def refresh_classics(env):
    """Quick run for the Classics lists only (minutes, not hours)."""
    run([sys.executable, "maintenance/rebuild_classics.py"], env, cwd=BACKEND)
    run([sys.executable, "maintenance/refresh_franchise_ott.py", "--region", "IN"], env, cwd=BACKEND)
    warm_imdb_dataset(env)
    warm_tv_imdb(env)


def refresh_franchise(env, data_dir):
    # Titles added to the Classics lists get searched/resolved first; everything already stored is kept.
    run([sys.executable, "maintenance/rebuild_classics.py"], env, cwd=BACKEND)
    run([sys.executable, "maintenance/refresh_franchise_ott.py", "--region", "IN"], env, cwd=BACKEND)
    run([sys.executable, "-c",
         "import asyncio; from catalogues import catalogues_extra as c; asyncio.run(c._enrich_catalogue_synopses())"],
        env, cwd=BACKEND)
    warm_imdb_dataset(env)
    warm_tv_imdb(env)


def valid_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in GROUPS:
        raise SystemExit(__doc__)
    group = sys.argv[1]
    if not any(k.startswith("TMDB_") and v.strip() for k, v in os.environ.items()):
        raise SystemExit("No TMDB key in the environment; refusing to run (nothing would be refreshed).")
    with tempfile.TemporaryDirectory(prefix="seed-refresh-") as tmp:
        data_dir = Path(tmp) / "data"
        data_dir.mkdir()
        stage(data_dir)
        env = {
            **os.environ,
            "APP_DATA_DIR": str(data_dir),
            "CACHE_SEED_DIR": str(Path(tmp) / "no-seed"),  # already staged; do not re-seed
            "CACHE_ONLY_MODE": "false",
            "CACHE_FIRST": "false",  # stale entries must really be refreshed here
            "BACKFILL_MISSING_METADATA": "true",
            "PYTHONPATH": str(BACKEND),
        }
        if group == "imdb-dataset":
            warm_imdb_dataset(env)
        elif group == "tv-imdb":
            warm_tv_imdb(env)
        elif group == "hollywood-bollywood":
            refresh_hollywood_bollywood(env, data_dir)
        elif group == "regional-tv-new":
            refresh_regional_tv_new(env, data_dir)
        elif group == "classics":
            refresh_classics(env)
        else:
            refresh_franchise(env, data_dir)

        changed = []
        spec = GROUPS[group]
        for sub, names in (("", spec["top"]), ("runtime", spec["runtime"])):
            for name in names:
                new, old = data_dir / name, SEED / sub / name
                if not new.is_file() or not valid_json(new):
                    continue
                if old.is_file() and old.read_bytes() == new.read_bytes():
                    continue
                shutil.copy2(new, old)
                changed.append(str((old).relative_to(SEED)))
        print("CHANGED:", json.dumps(changed))


if __name__ == "__main__":
    main()
