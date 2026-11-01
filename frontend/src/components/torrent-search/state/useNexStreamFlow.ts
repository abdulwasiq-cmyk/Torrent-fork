import { fetchNexStreamEpisodeMetadata, nexStreamEpisodeCache, nexStreamEpisodeCacheKey } from '../nexstream.ts';
import { writeLocalCache } from '../helpers.ts';
import { NexStreamTitle } from '../types.ts';
import { useNexStreamState } from './useNexStreamState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { NEXSTREAM_SEARCH_CACHE_KEY } from '../constants.ts';
import { useRef } from 'react';
import { readLocalCache } from '../localCache.ts';
import { buildVidRiftMovieUrl, buildVidRiftTvUrl, validTmdbId } from '../vidrift.ts';

export function useNexStreamFlow({ nexStreamSearchControllerRef, nexStreamSearchGenerationRef, setNexStreamSearchMode, setNexStreamLoadingTitle, setNexStreamLoading, setNexStreamError, setNexStreamResults, setNexStreamPlayer, setNexStreamEpisodePrefetchStatus, setNexStreamSeasons, setNexStreamEpisodes, setNexStreamSelectedSeason, setNexStreamEpisodesError, setNexStreamEpisodesStatus, setNexStreamEpisodesLoading, setNexStreamEpisodePicker, setNexStreamResolvingId, error }: Pick<ReturnType<typeof useNexStreamState>, 'nexStreamSearchControllerRef' | 'nexStreamSearchGenerationRef' | 'setNexStreamSearchMode' | 'setNexStreamLoadingTitle' | 'setNexStreamLoading' | 'setNexStreamError' | 'setNexStreamResults' | 'setNexStreamPlayer' | 'setNexStreamEpisodePrefetchStatus' | 'setNexStreamSeasons' | 'setNexStreamEpisodes' | 'setNexStreamSelectedSeason' | 'setNexStreamEpisodesError' | 'setNexStreamEpisodesStatus' | 'setNexStreamEpisodesLoading' | 'setNexStreamEpisodePicker' | 'setNexStreamResolvingId'> & Pick<ReturnType<typeof useCatalogueNavigationState>, 'error'>) {
  const episodeLoadGenerationRef = useRef(0);
  const searchNexStreamTitles = async (titleQuery: string, mediaType: 'movie' | 'tv' = 'movie', forceRefresh = false) => {
    nexStreamSearchControllerRef.current?.abort();
    const controller = new AbortController();
    nexStreamSearchControllerRef.current = controller;
    const generation = ++nexStreamSearchGenerationRef.current;
    setNexStreamSearchMode(mediaType);
    setNexStreamLoadingTitle(String(titleQuery || '').trim());
    setNexStreamLoading(true);
    setNexStreamError('');
    setNexStreamResults([]);
    setNexStreamEpisodePrefetchStatus({});
    setNexStreamPlayer(null);
    try {
      const types: Array<'movie' | 'tv'> = [mediaType];
      const cachedNexResults = readLocalCache<NexStreamTitle[]>(NEXSTREAM_SEARCH_CACHE_KEY, mediaType + ':' + String(titleQuery || '').trim().toLowerCase());
      if (cachedNexResults && !forceRefresh) {
        setNexStreamResults(cachedNexResults);
        setNexStreamLoading(false);
        setNexStreamLoadingTitle('');
        return;
      }
      const responses = await Promise.allSettled(types.map(async type => {
        const params = new URLSearchParams({ query: titleQuery, type, ...(forceRefresh ? { force_refresh: 'true' } : {}) });
        const response = await fetch('/api/nexstream/search?' + params.toString(), {
          headers: { Accept: 'application/json' },
          credentials: 'same-origin',
          signal: controller.signal,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
          throw new Error(data.detail || 'NexStream title search failed.');
        }
        return (Array.isArray(data.results) ? data.results : []) as NexStreamTitle[];
      }));
      if (generation !== nexStreamSearchGenerationRef.current) return;
      const successfulResults = responses
        .filter((response): response is PromiseFulfilledResult<NexStreamTitle[]> => response.status === 'fulfilled')
        .flatMap(response => response.value);
      const failedSearches = responses.filter(response => response.status === 'rejected');
      const unique = new Map<string, NexStreamTitle>();
      for (const item of successfulResults) {
        unique.set(item.type + ':' + item.id, item);
      }
      const resolvedTitles = Array.from(unique.values());
      writeLocalCache(NEXSTREAM_SEARCH_CACHE_KEY, mediaType + ':' + String(titleQuery || '').trim().toLowerCase(), resolvedTitles);
      setNexStreamResults(resolvedTitles);
      if (failedSearches.length === types.length) {
        const firstFailure = failedSearches[0] as PromiseRejectedResult;
        throw firstFailure.reason instanceof Error ? firstFailure.reason : new Error('TMDB title search failed.');
      }
      if (failedSearches.length > 0) {
        setNexStreamError('Some NexStream results could not be loaded. Try searching again to refresh them.');
      }
    } catch (error: any) {
      if (generation !== nexStreamSearchGenerationRef.current || error?.name === 'AbortError') return;
      setNexStreamError(String(error?.message || 'NexStream search is temporarily unavailable.'));
    } finally {
      if (generation === nexStreamSearchGenerationRef.current) {
        setNexStreamLoading(false);
        setNexStreamLoadingTitle('');
        if (nexStreamSearchControllerRef.current === controller) nexStreamSearchControllerRef.current = null;
      }
    }
  };
  const loadNexStreamEpisodes = async (item: NexStreamTitle, season: number) => {
    const generation = ++episodeLoadGenerationRef.current;
    const cached = nexStreamEpisodeCache.get(nexStreamEpisodeCacheKey(item.id, season));
    if (cached) {
      setNexStreamSeasons(cached.seasons);
      setNexStreamEpisodes(cached.episodes);
      setNexStreamSelectedSeason(cached.selectedSeason);
      setNexStreamEpisodesStatus(cached.status || (!cached.seasons.length ? 'no_seasons' : cached.episodes.length ? 'ready' : 'no_episodes'));
      setNexStreamEpisodesError('');
      setNexStreamEpisodesLoading(false);
      return;
    }

    setNexStreamEpisodesLoading(true);
    setNexStreamEpisodesError('');
    setNexStreamEpisodesStatus(null);
    try {
      const data = await fetchNexStreamEpisodeMetadata(item.id, season);
      if (generation !== episodeLoadGenerationRef.current) return;
      setNexStreamSeasons(data.seasons);
      setNexStreamEpisodes(data.episodes);
      setNexStreamSelectedSeason(data.selectedSeason);
      setNexStreamEpisodesStatus(data.status || (!data.seasons.length ? 'no_seasons' : data.episodes.length ? 'ready' : 'no_episodes'));
    } catch (error: any) {
      if (generation !== episodeLoadGenerationRef.current) return;
      setNexStreamEpisodesError(String(error?.message || 'Could not load episode list.'));
      setNexStreamEpisodes([]);
      setNexStreamEpisodesStatus(null);
    } finally {
      if (generation === episodeLoadGenerationRef.current) setNexStreamEpisodesLoading(false);
    }
  };
  const playWithNexStream = async (item: NexStreamTitle, chosenSeason?: number, chosenEpisode?: number, openInNewWindow = false, provider: 'vidrift' | 'nexstream' = 'vidrift') => {
    if (!validTmdbId(item.id)) {
      setNexStreamError('This title has no valid TMDB ID for VidRift playback.');
      return;
    }
    if (item.type === 'tv' && (chosenSeason === undefined || chosenEpisode === undefined)) {
      setNexStreamEpisodePicker(item);
      setNexStreamEpisodes([]);
      setNexStreamSeasons([]);
      setNexStreamEpisodesError('');
      setNexStreamEpisodesStatus(null);
      await loadNexStreamEpisodes(item, 1);
      return;
    }
    const season = chosenSeason;
    const episode = chosenEpisode;

    const resolvingId = item.type + ':' + item.id;
    setNexStreamResolvingId(resolvingId);
    setNexStreamError('');
    try {
      // VidRift is embed-only: construction does not verify availability.
      const tmdbId = Number(item.id);
      const useNexStream = provider === 'nexstream' && !openInNewWindow;
      const sourceUrl = useNexStream
        ? await resolveNexStreamUrl(item.type, tmdbId, season, episode)
        : item.type === 'tv'
          ? buildVidRiftTvUrl(tmdbId, season, episode)
          : buildVidRiftMovieUrl(tmdbId);
      if (!sourceUrl) throw new Error('This title has an invalid VidRift playback ID or episode.');
      const popup = openInNewWindow ? window.open('about:blank', '_blank') : null;
      if (popup) {
        popup.location.href = sourceUrl;
      } else if (openInNewWindow) {
        setNexStreamError('Your browser blocked the new window. Allow pop-ups and try again.');
      } else {
        setNexStreamPlayer({
          title: item.title,
          year: String(item.date || '').slice(0, 4),
          sourceName: useNexStream ? 'NexStream' : 'VidRift',
          url: sourceUrl,
          type: item.type,
          tmdbId,
          season,
          episode,
          anime: item.anime,
        });
      }
      setNexStreamError('');
    } catch (error: any) {
      setNexStreamError(String(error?.message || 'Could not start VidRift playback.'));
    } finally {
      setNexStreamResolvingId(null);
    }
  };
  // Ask the server for the NexStream player URL of a movie / episode.
  const resolveNexStreamUrl = async (type: 'movie' | 'tv', tmdbId: number, season?: number, episode?: number): Promise<string> => {
    const params = new URLSearchParams({ provider: 'nexstream', type, tmdb_id: String(tmdbId) });
    if (type === 'tv') {
      params.set('season', String(season || 1));
      params.set('episode', String(episode || 1));
    }
    const response = await fetch('/api/nexstream/resolve?' + params.toString(), { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
    const data = await response.json().catch(() => ({}));
    const url = String(data?.sources?.[0]?.url || '');
    if (!response.ok || !data.success || !url) throw new Error(data?.detail || 'NexStream could not load this title.');
    return url;
  };
  type NexStreamPlayerState = NonNullable<ReturnType<typeof useNexStreamState>['nexStreamPlayer']>;
  // Switch the open player between the two stream sources for the same title/episode.
  const switchNexStreamProvider = async (player: NexStreamPlayerState, provider: 'vidrift' | 'nexstream') => {
    const tmdbId = Number(player.tmdbId);
    if (!validTmdbId(tmdbId)) {
      setNexStreamError('This title has no valid TMDB ID for ' + (provider === 'nexstream' ? 'NexStream' : 'VidRift') + ' playback.');
      return;
    }
    setNexStreamError('');
    if (provider === 'vidrift') {
      const url = player.type === 'tv' ? buildVidRiftTvUrl(tmdbId, player.season, player.episode) : buildVidRiftMovieUrl(tmdbId);
      if (!url) { setNexStreamError('This title has an invalid VidRift playback ID or episode.'); return; }
      setNexStreamPlayer({ ...player, sourceName: 'VidRift', url });
      return;
    }
    const resolvingId = 'switch:' + player.type + ':' + tmdbId;
    setNexStreamResolvingId(resolvingId);
    try {
      const url = await resolveNexStreamUrl(player.type, tmdbId, player.season, player.episode);
      setNexStreamPlayer({ ...player, sourceName: 'NexStream', url });
    } catch (error: any) {
      setNexStreamError(String(error?.message || 'NexStream could not load this title.'));
    } finally {
      setNexStreamResolvingId(null);
    }
  };
  const playCatalogueTvWithNexStream = (show: {
    id: number | string;
    title: string;
    year?: number | null;
    releaseDate?: string;
    overview?: string;
    posterUrl?: string;
  }) => {
    // Catalogue IDs come directly from the cached TMDB TV catalogue. Do not
    // title-search these shows: pass the exact series ID into the episode flow.
    const tmdbId = Number(show.id);
    if (!Number.isInteger(tmdbId) || tmdbId <= 0) {
      setNexStreamSearchMode('tv');
      setNexStreamError('This TV catalogue entry has no valid TMDB series ID.');
      return;
    }

    // The episode picker is rendered inside the NexStream panel, which is
    // hidden unless a NexStream search mode is active. Activate the TV panel
    // before opening the picker so catalogue buttons work without title search.
    setNexStreamSearchMode('tv');
    setNexStreamResults([]);
    setNexStreamLoading(false);
    setNexStreamLoadingTitle('');
    setNexStreamError('');
    void playWithNexStream({
      id: tmdbId,
      title: show.title,
      date: show.releaseDate || (show.year ? String(show.year) : ''),
      overview: show.overview || '',
      poster: show.posterUrl || null,
      type: 'tv',
    });
  };

  return {
    searchNexStreamTitles,
    loadNexStreamEpisodes,
    playWithNexStream,
    switchNexStreamProvider,
    playCatalogueTvWithNexStream,
  };
}
