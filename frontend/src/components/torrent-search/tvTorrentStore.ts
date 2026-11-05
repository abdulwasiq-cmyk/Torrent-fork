import type { TorrentSearchResult } from '../../api/types.ts';
import { openWhenReady } from './franchiseJoin.ts';

/**
 * Season-pack torrents for TV / web series, looked up ONLY when a series card is tapped
 * (never on page load or pagination). One card is open at a time. The lookup is cached for the
 * session, hit or miss, so a second tap is instant.
 *
 * Tap flow (same "no flash" rule as the franchise cards): wait for the lookup (capped), then
 *   - packs found   -> open the second card (Play + Webtor)
 *   - none / slow   -> run the existing Play behaviour straight away, exactly as before.
 */
export const TV_LOOKUP_MAX_WAIT_MS = 800;

export type TvTorrentFetcher = (show: { id: number | string; title: string; year?: number | string | null }) => Promise<TorrentSearchResult[]>;

export const tvShowKey = (show: { id: number | string }) => 'tv:' + String(show.id);

export function createTvTorrentStore(fetcher: TvTorrentFetcher, maxWaitMs = TV_LOOKUP_MAX_WAIT_MS) {
  const cache = new Map<string, TorrentSearchResult[]>();
  const inflight = new Map<string, Promise<void>>();
  const listeners = new Set<() => void>();
  let openKey: string | null = null;
  const emit = () => listeners.forEach(listener => listener());

  const lookup = (show: Parameters<TvTorrentFetcher>[0]): Promise<void> => {
    const key = tvShowKey(show);
    const running = inflight.get(key);
    if (running) return running;
    const promise = fetcher(show)
      .then(rows => { cache.set(key, rows); })
      .catch(() => { /* network error: not cached, the next tap retries */ })
      .finally(() => { inflight.delete(key); });
    inflight.set(key, promise);
    return promise;
  };

  return {
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    getOpenKey: () => openKey,
    releasesFor: (show: { id: number | string }) => cache.get(tvShowKey(show)) ?? [],
    open(show: Parameters<TvTorrentFetcher>[0], play: () => void) {
      const key = tvShowKey(show);
      openWhenReady(!cache.has(key), () => lookup(show), () => {
        if ((cache.get(key)?.length ?? 0) > 0) { openKey = key; emit(); }
        else play();
      }, maxWaitMs);
    },
    close() { if (openKey !== null) { openKey = null; emit(); } },
  };
}

export type TvTorrentStore = ReturnType<typeof createTvTorrentStore>;

/** "Complete series" / "Season 2" label for one pack. */
export const packScopeLabel = (row: Pick<TorrentSearchResult, 'scope' | 'season'>) =>
  row.scope === 'complete' || !row.season ? 'Complete series' : 'Season ' + row.season;
