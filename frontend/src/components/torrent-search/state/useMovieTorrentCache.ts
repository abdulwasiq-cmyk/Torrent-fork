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

  return {
    persistMovieTorrentCache,
  };
}
