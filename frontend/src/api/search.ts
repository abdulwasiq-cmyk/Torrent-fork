import type { TorrentSearchResult, MarvelCatalogueResponse, TvCataloguePage, MovieCatalogueKey, SearchMediaMetadata, SearchMediaMetadataResponse, ImdbRatingResult, MovieCataloguePage, MovieOttAvailability, SectionCacheDocument } from './types.ts';
import { API_BASE, apiFetch } from './http.ts';

const sectionCacheRequests = new Map<string, Promise<SectionCacheDocument>>();

export const searchApi = {
  async getSectionCache(section: string): Promise<SectionCacheDocument> {
    const key = String(section || '').trim().toLowerCase();
    const existing = sectionCacheRequests.get(key);
    if (existing) return existing;
    const request = (async () => {
      const res = await apiFetch('/api/sections/' + encodeURIComponent(key), {
        cache: 'no-store',
      });
      const body = await res.text();
      let data: unknown;
      try {
        data = body ? JSON.parse(body) : null;
      } catch {
        throw new Error('Section cache response is not valid JSON.');
      }
      const record = data && typeof data === 'object' && !Array.isArray(data)
        ? data as Record<string, unknown>
        : null;
      if (!res.ok) {
        const detail = typeof record?.detail === 'string' ? record.detail : '';
        throw new Error(detail || body || ('Section cache failed (HTTP ' + res.status + ')'));
      }
      if (
        !record ||
        record.section !== key ||
        record.metadataSelfContained !== true ||
        !record.subsections ||
        typeof record.subsections !== 'object' ||
        Array.isArray(record.subsections)
      ) {
        throw new Error('Section cache response has an invalid document shape.');
      }
      return record as unknown as SectionCacheDocument;
    })();
    sectionCacheRequests.set(key, request);
    try {
      return await request;
    } catch (error) {
      if (sectionCacheRequests.get(key) === request) sectionCacheRequests.delete(key);
      throw error;
    }
  },

  async searchMediaMetadata(query: string, signal?: AbortSignal): Promise<SearchMediaMetadataResponse> {
    const params = new URLSearchParams({ q: query });
    const res = await fetch(API_BASE + '/api/search/metadata?' + params.toString(), {
      signal, credentials: 'include', cache: 'no-store',
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) throw new Error(data?.detail || body || ('TMDB metadata lookup failed (HTTP ' + res.status + ')'));
    return data as SearchMediaMetadataResponse;
  },

  async searchMediaMetadataBatch(titles: string[], signal?: AbortSignal): Promise<{
    status: string;
    source?: string;
    requested?: number;
    matched?: number;
    results: SearchMediaMetadata[];
  }> {
    const params = new URLSearchParams();
    [...new Set(titles.map(title => String(title || '').trim()).filter(Boolean))]
      .slice(0, 80)
      .forEach(title => params.append('titles', title));
    const res = await fetch(API_BASE + '/api/search/metadata/batch?' + params.toString(), {
      signal, credentials: 'include', cache: 'no-store',
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) throw new Error(data?.detail || body || ('Cached search metadata lookup failed (HTTP ' + res.status + ')'));
    return data;
  },

  async getImdbRatings(
    titles: string[],
    mediaTypes: Array<'movie' | 'tv'> = [],
    tmdbIds: Array<number | string | null | undefined> = [],
    signal?: AbortSignal,
  ): Promise<{
    status: string;
    requested?: number;
    matched?: number;
    results: ImdbRatingResult[];
  }> {
    const params = new URLSearchParams();
    const seen = new Set<string>();
    titles.forEach((rawTitle, index) => {
      const title = String(rawTitle || '').trim();
      if (!title) return;
      const mediaType = mediaTypes[index] === 'tv' ? 'tv' : 'movie';
      const key = mediaType + '|' + title.toLowerCase();
      if (seen.has(key) || seen.size >= 80) return;
      seen.add(key);
      params.append('titles', title);
      params.append('media_types', mediaType);
      const tmdbId = Number(tmdbIds[index] || 0);
      params.append('tmdb_ids', String(Number.isFinite(tmdbId) && tmdbId > 0 ? tmdbId : 0));
    });
    const res = await fetch(API_BASE + '/api/catalogue/imdb-ratings?' + params.toString(), {
      signal, credentials: 'include', cache: 'no-store',
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) throw new Error(data?.detail || body || ('IMDb rating lookup failed (HTTP ' + res.status + ')'));
    return data;
  },

  async searchSavedOtt(titles: string[], signal?: AbortSignal): Promise<{
    status: string;
    results: Array<{ query: string; found: boolean; entries: Array<{
      title: string;
      year?: string | null;
      tmdbId?: number | string;
      ottAvailability: {
        region?: string;
        status?: string;
        streamingProviders?: unknown[];
        rentProviders?: unknown[];
        buyProviders?: unknown[];
        providerLink?: string;
        source?: string;
      };
    }> }>;
  }> {
    const params = new URLSearchParams();
    titles.slice(0, 80).forEach(title => params.append('titles', title));
    const res = await fetch(API_BASE + '/api/catalogue/ott/search?' + params.toString(), {
      signal, credentials: 'include', cache: 'no-store',
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) throw new Error(data?.detail || body || ('Saved OTT lookup failed (HTTP ' + res.status + ')'));
    return data;
  },

  async getMarvelCatalogue(signal?: AbortSignal, paging?: { page: number; pageSize: number }): Promise<MarvelCatalogueResponse> {
    const res = await fetch(API_BASE + '/api/catalogue/marvel' + (paging ? '?page=' + paging.page + '&page_size=' + paging.pageSize : ''), {
      signal,
      credentials: 'include',
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      throw new Error(data?.detail || data?.error || body || ('Marvel catalogue failed (HTTP ' + res.status + ')'));
    }
    return data as MarvelCatalogueResponse;
  },

  async getCatalogue(key: string, signal?: AbortSignal, paging?: { page: number; pageSize: number }): Promise<MarvelCatalogueResponse> {
    const res = await fetch(API_BASE + '/api/catalogue/extra/' + encodeURIComponent(key) + (paging ? '?page=' + paging.page + '&page_size=' + paging.pageSize : ''), {
      signal,
      credentials: 'include',
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      throw new Error(data?.detail || data?.error || body || ('Movie catalogue failed (HTTP ' + res.status + ')'));
    }
    return data as MarvelCatalogueResponse;
  },

  async resolveYenimeMalId(title: string, year?: number | null, malId?: number | string | null, tmdbId?: number | string | null): Promise<{
    status: 'resolved' | 'ambiguous' | 'missing' | 'unavailable';
    malId?: number | null;
    source?: string;
    title?: string;
    message?: string;
    matches?: Array<{ malId: number; title?: string | null; year?: number | null }>;
  }> {
    const params = new URLSearchParams({ title: String(title || '').trim() });
    if (year) params.set('year', String(year));
    const numericMalId = Number(malId || 0);
    if (Number.isInteger(numericMalId) && numericMalId > 0) params.set('malId', String(numericMalId));
    const numericTmdbId = Number(tmdbId || 0);
    if (Number.isInteger(numericTmdbId) && numericTmdbId > 0) params.set('tmdbId', String(numericTmdbId));
    const res = await fetch(API_BASE + '/api/yenime/resolve-mal?' + params.toString(), { credentials: 'include', cache: 'no-store' });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) throw new Error(data?.detail || body || 'Yenime MAL ID lookup failed');
    return data;
  },

  async getTvCatalogue(key: string, page = 1, signal?: AbortSignal): Promise<TvCataloguePage> {
    const params = new URLSearchParams({ page: String(Math.min(Math.max(page, 1), 500)) });
    const res = await fetch(API_BASE + '/api/tv/catalogue/' + encodeURIComponent(key) + '?' + params.toString(), {
      signal, credentials: 'include', cache: 'no-store',
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) throw new Error(data?.detail || data?.error || body || ('TV catalogue failed (HTTP ' + res.status + ')'));
    return data as TvCataloguePage;
  },

  async getMovieCatalogue(
    key: MovieCatalogueKey,
    page = 1,
    releasedOnly = true,
    signal?: AbortSignal,
    maxSizeGb = 5,
    basic = false,
  ): Promise<MovieCataloguePage> {
    const params = new URLSearchParams({
      page: String(Math.min(Math.max(page, 1), 500)),
      released_only: String(releasedOnly),
    });
    if (basic) params.set('basic', 'true');
    if (key === 'bollywood-library') params.set('max_size_gb', String(Math.min(5, Math.max(1, maxSizeGb))));
    const res = await fetch(API_BASE + '/api/movies/catalogue/' + encodeURIComponent(key) + '?' + params.toString(), {
      signal,
      credentials: 'include',
      cache: 'no-store',
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      throw new Error(data?.detail || data?.error || body || ('Movie catalogue failed (HTTP ' + res.status + ')'));
    }
    return data as MovieCataloguePage;
  },

  async clearTmdbMovieCaches(): Promise<{ status: string; cacheTypes?: string[]; refetchRequired?: boolean }> {
    const res = await apiFetch('/api/movies/catalogue/cache/clear', {
      method: 'POST',
      cache: 'no-store',
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      throw new Error(data?.detail || data?.error || body || ('TMDB cache clear failed (HTTP ' + res.status + ')'));
    }
    return data;
  },

  async getMovieOttAvailability(
    movieId: number,
    region = 'IN',
    signal?: AbortSignal,
  ): Promise<MovieOttAvailability> {
    const params = new URLSearchParams({ region: region.toUpperCase() });
    const res = await fetch(
      API_BASE + '/api/movies/ott/' + encodeURIComponent(String(movieId)) + '?' + params.toString(),
      { signal, credentials: 'include', cache: 'no-store' },
    );
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      throw new Error(data?.detail || data?.error || body || ('OTT availability failed (HTTP ' + res.status + ')'));
    }
    return data as MovieOttAvailability;
  },

  async searchAvailability(query: string, signal?: AbortSignal): Promise<{
    status: 'ready' | 'not_found' | 'not_confirmed' | 'unavailable';
    query: string;
    title?: string;
    year?: number | string;
    matches?: Array<{
      id: string;
      title: string;
      year?: number | string;
      type?: string;
      tmdbId?: number | string;
      status: 'ready' | 'not_found' | 'not_confirmed' | 'unavailable';
      providers: Array<{ name: string; region: string; type: string; webUrl?: string; logoUrl?: string; providerId?: number | string }>;
    }>;
    providers: Array<{ name: string; region: string; type: string; webUrl?: string; logoUrl?: string; providerId?: number | string }>;
    message?: string;
  }> {
    const params = new URLSearchParams({ q: query });
    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 14000);
    const forwardAbort = () => controller.abort();
    if (signal?.aborted) controller.abort();
    else signal?.addEventListener('abort', forwardAbort, { once: true });
    try {
      const res = await fetch(API_BASE + '/api/search/availability?' + params.toString(), {
        signal: controller.signal, credentials: 'include', cache: 'no-store',
      });
      const body = await res.text();
      let data: any = null;
      try { data = body ? JSON.parse(body) : null; } catch {}
      if (!res.ok) throw new Error(data?.detail || data?.message || body || ('Availability lookup failed (HTTP ' + res.status + ')'));
      return data;
    } catch (error: any) {
      if (timedOut) throw new Error('Streaming availability check timed out.');
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
      signal?.removeEventListener('abort', forwardAbort);
    }
  },

  // Torrents (qBittorrent WebAPI)
  async searchTorrents(query: string, limit = 50, signal?: AbortSignal, prepareTrace?: { id: string; intent: 'explicit-card-click' }): Promise<TorrentSearchResult[]> {
    const params = new URLSearchParams({
      q: query,
      limit: String(Math.min(Math.max(limit, 1), 50))
    });

    // Search is served by the Render backend alongside the Seedr API.
    // Use the same API base in development and production so the frontend
    // can be hosted independently as a Render Static Site.
    const searchBase = API_BASE;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 12000);
    let res: Response;
    try {
      res = await fetch(searchBase + '/api/search?' + params.toString(), {
        signal: signal || controller.signal,
        headers: prepareTrace ? {
          'X-Prepare-Intent': prepareTrace.intent,
          'X-Prepare-Trace': prepareTrace.id,
        } : undefined,
      });
    } catch (error: any) {
      if (error?.name === 'AbortError') {
        throw new Error('Search timed out. Please try again.');
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }
    const body = await res.text();

    let data: any = null;
    try {
      data = body ? JSON.parse(body) : null;
    } catch {
      // Keep raw response for the error below.
    }

    if (!res.ok) {
      throw new Error(data?.error || data?.message || body || ('Torrent search failed (HTTP ' + res.status + ')'));
    }

    return Array.isArray(data) ? data : (Array.isArray(data?.results) ? data.results : []);
  },

  async resolveSearchMagnet(infoUrl: string, indexer = ''): Promise<{ magnet: string; infoHash: string }> {
    const res = await apiFetch('/api/search/resolve-magnet', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ infoUrl, indexer })
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      throw new Error(data?.detail || data?.error || body || 'Could not resolve the magnet link.');
    }
    return data as { magnet: string; infoHash: string };
  },

  async addSearchTorrent(source: string, size: number, infoHash?: string, torrentName?: string): Promise<any> {
    const magnet = source.trim();
    const resolvedMagnet =
      magnet.toLowerCase().startsWith('magnet:?')
        ? magnet
        : infoHash
          ? 'magnet:?xt=urn:btih:' + infoHash.trim()
          : magnet;

    const res = await apiFetch('/api/search/torrents/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: resolvedMagnet, size, infoHash, torrent_name: torrentName || undefined })
    });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) throw new Error(data?.error || body || 'Failed to add search result');
    return data;
  }
};
