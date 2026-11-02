import { MovieOttAvailability } from '../../api/client.ts';
import { normalizeGroupTitle } from './grouping.ts';

export type MovieOttCardState = MovieOttAvailability | { status: 'loading'; message?: string } | { status: 'error'; message?: string };

export type NexStreamEpisode = { episodeNumber: number; name: string; overview: string; airDate: string; still: string | null };

export type NexStreamSeason = { seasonNumber: number; name: string; episodeCount: number };

export type NexStreamEpisodePayload = {
  seasons: NexStreamSeason[];
  episodes: NexStreamEpisode[];
  selectedSeason: number;
  status?: 'ready' | 'no_seasons' | 'no_episodes';
};

// Episode metadata is prefetched after TV search results appear. Keep it in a
// module cache so opening the picker and revisiting a title is usually instant.
export const nexStreamEpisodeCache = new Map<string, NexStreamEpisodePayload>();

export const nexStreamEpisodeRequests = new Map<string, Promise<NexStreamEpisodePayload>>();

export const NEXSTREAM_EPISODE_CACHE_STORAGE_KEY = 'home_nexstream_episode_metadata_v1';

export const nexStreamEpisodeCacheKey = (id: number, season: number) => String(id) + ':' + String(season);

export function readPersistentNexStreamEpisodeCache(key: string): NexStreamEpisodePayload | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(NEXSTREAM_EPISODE_CACHE_STORAGE_KEY) || '{}');
    const payload = parsed && typeof parsed === 'object' ? parsed[key] : null;
    if (
      payload &&
      Array.isArray(payload.seasons) &&
      Array.isArray(payload.episodes) &&
      Number.isFinite(Number(payload.selectedSeason))
    ) {
      return payload as NexStreamEpisodePayload;
    }
  } catch {}
  return null;
}

export function writePersistentNexStreamEpisodeCache(key: string, payload: NexStreamEpisodePayload): void {
  try {
    const parsed = JSON.parse(localStorage.getItem(NEXSTREAM_EPISODE_CACHE_STORAGE_KEY) || '{}');
    const cache = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    cache[key] = payload;
    localStorage.setItem(NEXSTREAM_EPISODE_CACHE_STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Storage can be unavailable or full. In-memory caching still works.
  }
}

export async function fetchNexStreamEpisodeMetadata(tmdbId: number, season: number): Promise<NexStreamEpisodePayload> {
  const key = nexStreamEpisodeCacheKey(tmdbId, season);
  const cached = nexStreamEpisodeCache.get(key);
  if (cached) return cached;
  const persistentCached = readPersistentNexStreamEpisodeCache(key);
  if (persistentCached) {
    nexStreamEpisodeCache.set(key, persistentCached);
    return persistentCached;
  }
  const pending = nexStreamEpisodeRequests.get(key);
  if (pending) return pending;

  const request = (async () => {
    let lastError: unknown = null;
    // Transient network errors / TMDB 429s happen occasionally. Retry in the
    // background and on demand instead of leaving the picker permanently empty.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const params = new URLSearchParams({ tmdb_id: String(tmdbId), season: String(season) });
        const response = await fetch('/api/nexstream/episodes?' + params.toString(), {
          headers: { Accept: 'application/json' }, credentials: 'same-origin',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
          const error = new Error(data.detail || 'Could not load episode list.');
          if (response.status < 500) throw Object.assign(error, { permanent: true });
          throw error;
        }
        const seasons = Array.isArray(data.seasons) ? data.seasons : [];
        const episodes = Array.isArray(data.episodes) ? data.episodes : [];
        const status = data.status === 'no_seasons' || data.status === 'no_episodes'
          ? data.status
          : !seasons.length
            ? 'no_seasons'
            : episodes.length
              ? 'ready'
              : 'no_episodes';
        const payload: NexStreamEpisodePayload = {
          seasons,
          episodes,
          selectedSeason: Number(data.selectedSeason) || season,
          status,
        };
        nexStreamEpisodeCache.set(nexStreamEpisodeCacheKey(tmdbId, payload.selectedSeason), payload);
        nexStreamEpisodeCache.set(key, payload);
        writePersistentNexStreamEpisodeCache(key, payload);
        writePersistentNexStreamEpisodeCache(nexStreamEpisodeCacheKey(tmdbId, payload.selectedSeason), payload);
        return payload;
      } catch (error: any) {
        lastError = error;
        if (error?.permanent || attempt === 2) break;
        await new Promise(resolve => window.setTimeout(resolve, 400 * (attempt + 1)));
      }
    }
    throw lastError instanceof Error ? lastError : new Error('Could not load episode list after retries.');
  })();
  nexStreamEpisodeRequests.set(key, request);
  try {
    return await request;
  } finally {
    nexStreamEpisodeRequests.delete(key);
  }
}

export function prefetchNexStreamEpisodeMetadata(
  items: NexStreamTitleLike[],
  onStatus: (id: number, status: 'loading' | 'ready' | 'error') => void,
) {
  const queue = items.slice();
  let active = 0;
  const pump = () => {
    while (active < 3 && queue.length) {
      const item = queue.shift();
      if (!item) continue;
      const key = nexStreamEpisodeCacheKey(item.id, 1);
      if (nexStreamEpisodeCache.has(key)) {
        onStatus(item.id, 'ready');
        continue;
      }
      if (nexStreamEpisodeRequests.has(key)) {
        onStatus(item.id, 'loading');
        void fetchNexStreamEpisodeMetadata(item.id, 1).then(
          () => onStatus(item.id, 'ready'),
          () => onStatus(item.id, 'error'),
        );
        continue;
      }
      onStatus(item.id, 'loading');
      active += 1;
      void fetchNexStreamEpisodeMetadata(item.id, 1).then(
        () => onStatus(item.id, 'ready'),
        () => onStatus(item.id, 'error'),
      ).finally(() => {
        active -= 1;
        pump();
      });
    }
  };
  pump();
}

export type NexStreamTitleLike = { id: number; type: 'movie' | 'tv' };

export function normalizeTorrentTitleForNexStream(value: string): string {
  return normalizeGroupTitle(String(value || '')
    .replace(/\\b(?:19|20)\\d{2}\\b/g, ' ')
    .replace(/\\b(?:s\\d{1,2}(?:e\\d{1,2})?|season\\s*\\d+|complete\\s*(?:series|season)?|all\\s*episodes|episodes?)\\b/gi, ' ')
    .replace(/\\b(?:2160p|1080p|720p|480p|4k|uhd|hdr|bluray|blu[ -]?ray|brrip|bdrip|web[ -]?dl|webrip|hdtv|x264|x265|hevc|aac|proper|repack|extended|remastered)\\b/gi, ' ')
    .replace(/\\[[^\\]]*\\]|\\([^)]*\\)/g, ' '));
}
