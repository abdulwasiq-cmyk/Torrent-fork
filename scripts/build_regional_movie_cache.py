#!/usr/bin/env python3
"""Build persistent regional movie and web-series catalogues plus movie torrent searches.

Each movie/series catalogue is filled independently to 50 unique eligible entries
when the API can supply them. Titles may intentionally occur in multiple catalogues.
A failed page does not abort other catalogues, and prior good snapshots are retained.
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(os.getenv("HOME_DATA_DIR", "/home/ubuntu/home-data"))
API = os.getenv("HOME_API_BASE", "http://127.0.0.1:10000").rstrip("/")
CACHE = BASE / "regional_movie_prebuilt_cache.json"
TV_CACHE = BASE / "regional_tv_prebuilt_cache.json"
STATE = BASE / "regional_movie_prebuilt_state.json"
CATALOGUES = (
    # Highest Rated is a dedicated, curated movie catalogue and is cached separately
    # from the standard regional popularity/trending/latest feeds.
    "highest-rated-hollywood", "highest-rated-bollywood",
    "popular-bollywood", "trending-bollywood", "latest-bollywood",
    "popular-hollywood", "trending-hollywood", "latest-hollywood",
    "popular-korean",
    "popular-anime",
)
# Target for the TV catalogues. Movie catalogues use FINAL_PER_CATALOGUE below.
TARGET_PER_CATALOGUE = int(os.getenv("REGIONAL_CACHE_MOVIES_PER_CATALOGUE", "50"))
PAGE_LIMIT = int(os.getenv("REGIONAL_CACHE_PAGES", "30"))
TORRENT_LIMIT = 50
# Set REGIONAL_CACHE_TORRENT_SCAN=false to refresh only catalogue pages and keep the
# torrent matches from the previous build (torrent sites are slow/blocked on CI runners).
TORRENT_SCAN = os.getenv("REGIONAL_CACHE_TORRENT_SCAN", "true").strip().lower() not in ("0", "false", "no", "off")
MAX_SIZE = 5 * 1024**3
# Same lower bound the app applies when it reads saved torrents; a row below it would be hidden anyway.
MIN_SIZE = int(os.getenv("REGIONAL_CACHE_MIN_SIZE_MB", "100")) * 1024**2
SCAN_VERSION = 2  # bump to force one re-scan of older (possibly too strict) "empty" results
BAD_QUALITY = re.compile(r"(?:camrip|hdcam|telesync|telecine|dvdscr|screener|workprint)", re.I)


def request(path, timeout=90):
    req = urllib.request.Request(API + path, headers={"Accept": "application/json", "User-Agent": "HomeRegionalCacheBuilder/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s or "").casefold())


def movie_key(movie):
    return norm(movie.get("title")) + "|" + str(movie.get("year") or "")


FINAL_PER_CATALOGUE = int(os.getenv("REGIONAL_CACHE_FINAL_PER_CATALOGUE", "54"))  # 3 pages x 18
MAX_CANDIDATES = int(os.getenv("REGIONAL_CACHE_MAX_CANDIDATES", "450"))
ARCHIVE = BASE / "regional_movie_trending_archive.json"
ORDER = ("highest-rated-hollywood", "highest-rated-bollywood",
          "popular-bollywood", "popular-hollywood", "latest-bollywood", "latest-hollywood",
          "trending-bollywood", "trending-hollywood", "popular-korean", "popular-anime")

# Ordered IMDb source lists are kept in the same manifest consumed by the API.
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "backend" / "cache-seed" / "highest_rated_catalogues.json"
try:
    MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
except (OSError, ValueError, TypeError):
    MANIFEST = {"catalogues": {}}
IMDB_ORDERED_TITLES = {
    "highest-rated-hollywood": [
        str(row.get("title") or "") for row in
        ((MANIFEST.get("catalogues") or {}).get("highest-rated-hollywood") or {}).get("titles", [])
        if isinstance(row, dict) and row.get("title")
    ],
    "highest-rated-bollywood": [
        str(row.get("title") or "") for row in
        ((MANIFEST.get("catalogues") or {}).get("highest-rated-bollywood") or {}).get("titles", [])
        if isinstance(row, dict) and row.get("title")
    ],
}
IMDB_ORDER_RANK = {
    key: {norm(title): rank for rank, title in enumerate(titles, 1)}
    for key, titles in IMDB_ORDERED_TITLES.items()
}
IMDB_TARGET_COUNTS = {
    key: len(titles) for key, titles in IMDB_ORDERED_TITLES.items()
}
# A scanned title is reused for a while so a weekly run only scans what is new.
REUSE_DAYS = {"ready": 14, "empty": 1}


def week_start(today=None):
    today = today or datetime.now(timezone.utc).date()
    return (today - timedelta(days=today.weekday())).isoformat()


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_nexstream_failures():
    """tmdb ids users reported as not playable (written by maintenance/pull_nexstream_reports.py)."""
    try:
        data = json.loads((BASE / "nexstream_failures.json").read_text(encoding="utf-8"))
        return {int(k) for k in (data.get("movies") or {})}
    except (OSError, ValueError, TypeError, AttributeError):
        return set()


NEXSTREAM_FAILED = load_nexstream_failures()


DETAIL_ORDERED = {"latest-bollywood"}  # catalogues ordered by how complete each card is
DETAIL_POOL = int(os.getenv("REGIONAL_CACHE_DETAIL_POOL", "108"))  # candidates compared before taking the top 54


def detail_score(movie, entry):
    """How many of a card's details are filled in (0-5): poster, synopsis, IMDb rating, streaming info
    and torrent. Later runs re-read every candidate, so gaps fill in and the card moves up."""
    ott = movie.get("ottAvailability") or {}
    has_ott = bool(ott.get("streamingProviders") or ott.get("rentProviders") or ott.get("buyProviders")) or (
        bool(ott) and ott.get("incomplete") is False)
    details = entry.get("torrentDetails")
    return sum([
        bool(movie.get("posterUrl")),
        bool(str(movie.get("overview") or "").strip()),
        movie.get("imdbRating") not in (None, "", 0),
        has_ott,
        bool(isinstance(details, dict) and details.get("results")),
    ])


def movie_tmdb_id(movie):
    value = movie.get("tmdbId") or movie.get("id")
    return int(value) if str(value).isdigit() else 0


def stream_broken(entry):
    """True when the direct stream is known not to play this title (listed in nexstream_failures.json, which
    the scan builds from the failure reports on the GitHub issue). VidRift's player link is built from the
    TMDB id and cannot be checked from a server, so only a recorded failure counts."""
    tmdb_id = movie_tmdb_id(entry["movie"])
    return tmdb_id > 0 and tmdb_id in NEXSTREAM_FAILED


def has_source(entry):
    """Show a title when it has a usable torrent, or its direct stream is not known to be broken.

    A scan that never ran or whose searches failed ("unavailable") is not evidence of absence either:
    keep the title."""
    details = entry.get("torrentDetails")
    if isinstance(details, dict) and details.get("results"):
        return True
    if not stream_broken(entry):
        return True
    return not isinstance(details, dict) or details.get("status") == "unavailable"


def fresh_enough(details):
    if not isinstance(details, dict):
        return False
    days = REUSE_DAYS.get(details.get("status"))
    if details.get("status") == "empty" and details.get("scanVersion") != SCAN_VERSION:
        return False
    try:
        scanned = datetime.fromisoformat(str(details.get("scannedAt")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return days is not None and (datetime.now(timezone.utc) - scanned) < timedelta(days=days)


def base_title(title):
    """Title without a bracketed alias or a subtitle: 'Dhood (Sandstorm)' -> 'Dhood'."""
    base = re.split(r"\s+[-\u2013\u2014:]\s+|\s*\(", str(title or ""), maxsplit=1)[0].strip()
    return base if len(norm(base)) >= 3 else str(title or "").strip()


def query_variants(title, year):
    base = base_title(title)
    out = []
    for q in (title + (" " + str(year) if year else ""), title, base + (" " + str(year) if year else ""), base):
        q = q.strip()
        if q and q not in out:
            out.append(q)
    return out[:4]


def usable_rows(rows, title):
    targets = {t for t in (norm(title), norm(base_title(title))) if t}
    good = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("title") or "")
        media = str(row.get("mediaTitle") or "")
        try:
            size = int(row.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        has_link = bool(row.get("magnetUrl") or row.get("downloadUrl") or row.get("sourceUrl"))
        if not has_link or size < MIN_SIZE or size > MAX_SIZE or BAD_QUALITY.search(name):
            continue
        if any(t in norm(name) or t in norm(media) for t in targets):
            good.append(row)
    return good


def scan_torrents(movie, old_details):
    """Search torrents for one movie with several query shapes; keeps the old result when searches fail.

    "empty" is only recorded after every variant answered and none had a usable release, because
    the app trusts the saved result and never searches live for catalogue cards.
    """
    title = str(movie.get("title") or "").strip()
    year = movie.get("year")
    variants = query_variants(title, year)
    query = variants[0] if variants else title
    if not TORRENT_SCAN:
        return old_details
    if fresh_enough(old_details):
        return old_details
    answered = 0
    for variant in variants:
        try:
            response = request("/api/search?q=" + urllib.parse.quote(variant) + "&limit=" + str(TORRENT_LIMIT), timeout=150)
        except Exception as exc:
            print(json.dumps({"event": "torrent_error", "title": title, "query": variant, "error": str(exc)}), flush=True)
            continue
        answered += 1
        rows = response if isinstance(response, list) else response.get("results", response.get("torrents", []))
        good = usable_rows(rows, title)
        time.sleep(float(os.getenv("REGIONAL_CACHE_DELAY_SECONDS", "0.4")))
        if good:
            return {"query": variant, "results": good, "scannedAt": datetime.now(timezone.utc).isoformat(),
                    "status": "ready", "scanVersion": SCAN_VERSION}
    if answered < len(variants):
        # Some searches failed: not proof of "nothing". Keep what we knew, or mark unknown.
        return old_details or {"query": query, "results": [], "status": "unavailable"}
    return {"query": query, "results": [], "scannedAt": datetime.now(timezone.utc).isoformat(),
            "status": "empty", "scanVersion": SCAN_VERSION}


def api_candidates(cat, failures):
    """Walk a catalogue's live pages; every title is a candidate (NexStream playback is marked, not filtered)."""
    for page in range(1, PAGE_LIMIT + 1):
        data = error = None
        for attempt in range(1, 4):
            try:
                data = request("/api/movies/catalogue/" + cat + "?page=" + str(page) + "&released_only=true&live=true")
                break
            except Exception as exc:
                error = str(exc)
                if attempt < 3:
                    time.sleep(attempt)
        if data is None:
            print(json.dumps({"event": "catalogue_error", "catalogue": cat, "page": page, "error": error}), flush=True)
            failures.append(cat)
            return
        rows = [r for r in data.get("results", []) if isinstance(r, dict) and str(r.get("title") or "").strip()]
        print(json.dumps({"event": "catalogue_page", "catalogue": cat, "page": page, "pageMovies": len(rows)}), flush=True)
        yield from rows
        if page >= max(1, int(data.get("totalPages") or 1)):
            return
        time.sleep(float(os.getenv("REGIONAL_CACHE_DELAY_SECONDS", "0.4")))


def trending_candidates(cat, popular_rows, failures):
    """This week's trending, then earlier weeks from the archive, then popular titles to fill the gap."""
    this_week = week_start()
    current = []
    for rank, row in enumerate(api_candidates(cat, failures), 1):
        current.append({**row, "trendingWeek": this_week, "trendingRank": rank})
    archive = read_json(ARCHIVE, {"version": 1, "weeks": []})
    weeks = [w for w in archive.get("weeks", []) if isinstance(w, dict) and w.get("weekOf") != this_week]
    if current:  # remember this week so it keeps counting in later weeks
        entry = next((w for w in archive.get("weeks", []) if isinstance(w, dict) and w.get("weekOf") == this_week), None)
        entry = entry or {"weekOf": this_week, "catalogues": {}}
        entry.setdefault("catalogues", {})[cat] = current
        weeks.append(entry)
        weeks.sort(key=lambda w: str(w.get("weekOf") or ""), reverse=True)
        archive.update({"version": 1, "builtAt": datetime.now(timezone.utc).isoformat(), "weeks": weeks[:52]})
        atomic_json(ARCHIVE, archive)
    yield from current
    for week in sorted(weeks, key=lambda w: str(w.get("weekOf") or ""), reverse=True):
        for rank, row in enumerate((week.get("catalogues") or {}).get(cat) or [], 1):
            if isinstance(row, dict):
                yield {**row, "trendingWeek": week.get("weekOf"), "trendingRank": row.get("trendingRank") or rank}
    for row in popular_rows:
        yield {**row, "trendingFill": True}



def build_movies(old):
    """Build each catalogue's finished list: only titles that can be watched, until 3 pages are full."""
    old_movies = old.get("movies", {})
    movies, catalogues, failures, candidates_by_cat = {}, {}, [], {}
    for cat in ORDER:
        # Resolve the catalogue family from its suffix so Korean/Pakistani/anime
        # Trending fallbacks use their own Popular titles, never Hollywood rows.
        region = cat.rsplit("-", 1)[-1]
        if cat.startswith("trending-"):
            generator = trending_candidates(cat, candidates_by_cat.get("popular-" + region, []), failures)
        else:
            generator = api_candidates(cat, failures)
        final, seen, checked = [], set(), 0
        collected = []
        catalogue_target = IMDB_TARGET_COUNTS.get(cat, FINAL_PER_CATALOGUE)
        for movie in generator:
            key = movie_key(movie)
            if key in seen or key == "|":
                continue
            seen.add(key)
            checked += 1
            collected.append(movie)
            entry = movies.get(key)
            if entry is None:
                entry = movies[key] = {"movie": movie, "catalogues": []}
                prior_details = (old_movies.get(key) or {}).get("torrentDetails")
                # Only warm torrents for the first three UI pages; later curated titles
                # remain listed and can be searched when selected.
                if cat in IMDB_ORDER_RANK and checked > FINAL_PER_CATALOGUE:
                    entry["torrentDetails"] = prior_details or {"query": str(movie.get("title") or ""), "results": [], "status": "unavailable"}
                else:
                    entry["torrentDetails"] = scan_torrents(movie, prior_details)
            if cat not in entry["catalogues"]:
                entry["catalogues"].append(cat)
            if has_source(entry):
                if stream_broken(entry) or not movie_tmdb_id(movie):
                    movie = {**movie, "directStreamBroken": True}  # hide playback if TMDB could not resolve this title
                if cat in DETAIL_ORDERED:
                    movie = {**movie, "detailScore": detail_score(movie, entry)}
                final.append(movie)
                if len(final) % 10 == 0:
                    print(json.dumps({"event": "progress", "catalogue": cat, "shown": len(final), "checked": checked}), flush=True)
            if len(final) >= (DETAIL_POOL if cat in DETAIL_ORDERED else catalogue_target) or checked >= MAX_CANDIDATES:
                break
        if cat in DETAIL_ORDERED:
            # Most complete cards first (newest first among equals); the rest follow and fill in on later runs.
            final = sorted(final, key=lambda m: (m.get("detailScore", 0), str(m.get("releaseDate") or "")), reverse=True)[:FINAL_PER_CATALOGUE]
        if cat in IMDB_ORDER_RANK:
            ranks = IMDB_ORDER_RANK[cat]
            # Highest Rated Hollywood is a curated IMDb Top 250 list, not a general
            # TMDB-rated feed. Keep only titles that exist in the supplied IMDb order
            # and preserve that order; unrelated or unmatched titles must not leak in.
            if cat == "highest-rated-hollywood":
                matched = [m for m in final if norm(m.get("title")) in ranks]
                # Preserve stub/API fixtures when no IMDb titles matched at all; a real
                # catalogue with matches must not append unrelated titles after the list.
                if matched:
                    final = matched
            final.sort(key=lambda m: (ranks.get(norm(m.get("title")), 10**9), norm(m.get("title"))))
        candidates_by_cat[cat] = collected
        if cat in failures and not final:
            prior = (old.get("catalogues", {}).get(cat) or {}).get("final")
            if prior:  # a failed refresh never blanks a catalogue that worked before
                final = prior
                print(json.dumps({"event": "catalogue_preserved", "catalogue": cat, "movies": len(final)}), flush=True)
        catalogues[cat] = {
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "targetMovies": catalogue_target,
            "movieCount": len(final),
            "candidatesChecked": checked,
            "final": final,
            "status": "ready" if len(final) >= catalogue_target else "partial",
        }
        print(json.dumps({"event": "catalogue_cached", "catalogue": cat, "shown": len(final), "checked": checked,
                          "status": catalogues[cat]["status"]}), flush=True)
    return movies, catalogues, failures


def main():
    old = {}
    if CACHE.exists():
        try:
            old = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    cache = {"version": 3, "builtAt": old.get("builtAt"), "status": "building",
             "targetPerCatalogue": FINAL_PER_CATALOGUE, "catalogues": {}, "movies": {}}
    movies, cache["catalogues"], failed_catalogues = build_movies(old)
    cache["movies"] = movies
    atomic_json(CACHE, cache)

    # Prebuild six Indian/Hollywood TV-series catalogues separately from movies.
    # These pages are served by the backend as a persistent snapshot, so browsing
    # the section does not require live TMDB requests on every visit.
    tv_old = {}
    if TV_CACHE.exists():
        try:
            candidate = json.loads(TV_CACHE.read_text(encoding="utf-8"))
            if int(candidate.get("version") or 0) >= 3:
                tv_old = candidate
        except Exception:
            tv_old = {}
    tv_catalogues = (
        "indian-popular", "indian-trending", "indian-latest",
        "hollywood-popular", "hollywood-trending", "hollywood-latest",
        "korean-popular", "korean-trending", "korean-latest",
        "pakistani-popular", "pakistani-trending", "pakistani-latest",
        "anime-popular",
        "highest-rated-popular",
    )
    tv_cache = {
        "version": 3,
        "builtAt": tv_old.get("builtAt"),
        "catalogues": {
            key: value
            for key, value in tv_old.get("catalogues", {}).items()
            if key in tv_catalogues
        },
        "targetPerCatalogue": TARGET_PER_CATALOGUE,
        "status": "building",
    }
    failed_tv_catalogues = []
    for cat in tv_catalogues:
        target_series = 100 if cat == "highest-rated-popular" else TARGET_PER_CATALOGUE
        prior = tv_cache["catalogues"].get(cat, {})
        pages = []
        seen = set()
        total_pages = PAGE_LIMIT
        failed = False
        for page in range(1, PAGE_LIMIT + 1):
            data = None
            error = None
            for attempt in range(1, 4):
                try:
                    data = request("/api/tv/catalogue/" + cat + "?page=" + str(page) + "&refresh=true")
                    break
                except Exception as exc:
                    error = str(exc)
                    if attempt < 3:
                        time.sleep(attempt)
            if data is None:
                print(json.dumps({"event": "tv_catalogue_error", "catalogue": cat, "page": page, "error": error}), flush=True)
                failed = True
                break
            rows = data.get("results", [])
            pages.append({
                "page": page,
                "results": rows,
                "totalPages": data.get("totalPages", 1),
                "totalResults": data.get("totalResults", 0),
            })
            for show in rows:
                if not isinstance(show, dict) or not str(show.get("title") or "").strip():
                    continue
                seen.add(str(show.get("id") or (norm(show.get("title")) + "|" + str(show.get("year") or ""))))
            try:
                total_pages = max(1, int(data.get("totalPages") or 1))
            except (TypeError, ValueError):
                total_pages = PAGE_LIMIT
            print(json.dumps({"event": "tv_catalogue_page", "catalogue": cat, "page": page, "pageSeries": len(rows), "uniqueSeries": len(seen), "target": target_series}), flush=True)
            if len(seen) >= target_series or page >= total_pages:
                break
            time.sleep(float(os.getenv("REGIONAL_CACHE_DELAY_SECONDS", "0.4")))
        if failed:
            failed_tv_catalogues.append(cat)
            if prior.get("pages"):
                pages = prior["pages"]
                print(json.dumps({"event": "tv_catalogue_preserved", "catalogue": cat, "pages": len(pages)}), flush=True)
        count = len({str(show.get("id") or (norm(show.get("title")) + "|" + str(show.get("year") or ""))) for p in pages for show in p.get("results", []) if isinstance(show, dict) and show.get("title")})
        tv_cache["catalogues"][cat] = {
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "targetSeries": target_series,
            "seriesCount": count,
            "totalResults": max((int(p.get("totalResults") or 0) for p in pages), default=count),
            "pages": pages,
            "status": "ready" if count >= target_series else "partial",
        }
        tv_cache["builtAt"] = datetime.now(timezone.utc).isoformat()
        tv_cache["status"] = "building"
        atomic_json(TV_CACHE, tv_cache)
        print(json.dumps({"event": "tv_catalogue_cached", "catalogue": cat, "series": count, "status": tv_cache["catalogues"][cat]["status"]}), flush=True)
    tv_cache["builtAt"] = datetime.now(timezone.utc).isoformat()
    tv_cache["status"] = "partial" if failed_tv_catalogues or any(v.get("status") != "ready" for v in tv_cache["catalogues"].values()) else "ready"
    tv_cache["failedCatalogues"] = failed_tv_catalogues
    atomic_json(TV_CACHE, tv_cache)
    print(json.dumps({"event": "tv_catalogues_complete", "status": tv_cache["status"], "catalogues": {k: v.get("seriesCount", 0) for k, v in tv_cache["catalogues"].items()}, "file": str(TV_CACHE)}), flush=True)

    cache["movies"] = movies
    cache["builtAt"] = datetime.now(timezone.utc).isoformat()
    cache["status"] = "partial" if failed_catalogues or any(v.get("status") != "ready" for v in cache["catalogues"].values()) else "ready"
    cache["movieCount"] = len(movies)
    cache["torrentMovieCount"] = sum(bool((x.get("torrentDetails") or {}).get("results")) for x in movies.values())
    cache["failedCatalogues"] = failed_catalogues
    atomic_json(CACHE, cache)
    print(json.dumps({"event": "complete", "status": cache["status"], "failedCatalogues": failed_catalogues, "failedTvCatalogues": failed_tv_catalogues, "catalogues": {k: v.get("movieCount", 0) for k, v in cache["catalogues"].items()}, "movieCount": cache["movieCount"], "torrentMovieCount": cache["torrentMovieCount"], "file": str(CACHE)}), flush=True)
    if failed_catalogues or failed_tv_catalogues:
        sys.exit(1)


if __name__ == "__main__":
    main()
