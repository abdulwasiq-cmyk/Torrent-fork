import { useEffect } from 'react';
import { TorrentQualityGroup } from '../grouping.ts';
import { useMoviePreviewState } from './useMoviePreviewState.ts';
import { MOVIE_TORRENT_CACHE_STORAGE_KEY, MOVIE_TORRENT_CACHE_TTL_MS } from '../constants.ts';

export function useMovieTorrentCache({ movieTorrentDetailsCacheRef }: Pick<ReturnType<typeof useMoviePreviewState>, 'movieTorrentDetailsCacheRef'>) {
  const persistMovieTorrentCache = () => {
    try {
      const entries = Array.from(movieTorrentDetailsCacheRef.current.entries())
        .filter(([, value]) => Date.now() - value.savedAt < MOVIE_TORRENT_CACHE_TTL_MS)
        .slice(-250);
      localStorage.setItem(MOVIE_TORRENT_CACHE_STORAGE_KEY, JSON.stringify(entries));
    } catch { /* Storage can be unavailable or full; in-memory caching still works. */ }
  };
  useEffect(() => {
    try {
      const entries = JSON.parse(localStorage.getItem(MOVIE_TORRENT_CACHE_STORAGE_KEY) || '[]') as Array<[string, { groups: TorrentQualityGroup[]; savedAt: number }]>;
      for (const [key, value] of entries) {
        if (value && Array.isArray(value.groups) && Date.now() - value.savedAt < MOVIE_TORRENT_CACHE_TTL_MS) {
          movieTorrentDetailsCacheRef.current.set(key, value);
        }
      }
    } catch {}
  }, []);

  return {
    persistMovieTorrentCache,
  };
}
