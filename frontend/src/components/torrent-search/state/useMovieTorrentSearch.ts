import { API_BASE, MovieCatalogueItem, TorrentSearchResult } from '../../../api/client.ts';
import searchLimits from '../../../../search_limits.json';
import { TorrentQualityGroup, groupTorrentResults, normalizeGroupTitle, torrentGroupReleaseYear, torrentResultKey } from '../grouping.ts';
import { cataloguePosterSource } from '../cataloguePosters.ts';
import { catalogueMovieIdentity } from '../helpers.ts';
import { useSearchMetadataState } from './useSearchMetadataState.ts';
import { useMoviePreviewState } from './useMoviePreviewState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useSearchInputState } from './useSearchInputState.ts';
import { MOVIE_TORRENT_CACHE_STORAGE_KEY, MOVIE_TORRENT_CACHE_TTL_MS } from '../constants.ts';
import { usePosterWorkers } from './usePosterWorkers.ts';
import { readLocalCache } from '../localCache.ts';
import { useMovieTorrentCache } from './useMovieTorrentCache.ts';

export function useMovieTorrentSearch({ prepareClickIntentRef, prepareTraceIdRef, setExpandedSearchGroupKey, movieTorrentSearchControllerRef, movieTorrentSearchGenerationRef, setMovieTorrentSearchTitle, setMovieTorrentPreviewCatalogueId, setMovieTorrentPreviewPosterUrl, cataloguePosterUrlsRef, setMovieTorrentSearchLoading, setMovieTorrentSearchError, setMovieTorrentPreviewGroup, setMovieTorrentPickerGroups, setSelectedMovieTorrentQualityByGroup, movieTorrentDetailsCacheRef, prepareBuildPendingRef, movieCatalogue, setSearched, error, setResults, setQuery, setSelectedQualityByGroup, startPosterBackgroundSearch, persistMovieTorrentCache }: Pick<ReturnType<typeof useMoviePreviewState>, 'prepareClickIntentRef' | 'prepareTraceIdRef' | 'setExpandedSearchGroupKey' | 'movieTorrentSearchControllerRef' | 'movieTorrentSearchGenerationRef' | 'setMovieTorrentSearchTitle' | 'setMovieTorrentPreviewCatalogueId' | 'setMovieTorrentPreviewPosterUrl' | 'cataloguePosterUrlsRef' | 'setMovieTorrentSearchLoading' | 'setMovieTorrentSearchError' | 'setMovieTorrentPreviewGroup' | 'setMovieTorrentPickerGroups' | 'setSelectedMovieTorrentQualityByGroup' | 'movieTorrentDetailsCacheRef'> & Pick<ReturnType<typeof useCatalogueNavigationState>, 'prepareBuildPendingRef' | 'movieCatalogue' | 'setSearched' | 'error'> & Pick<ReturnType<typeof useSearchInputState>, 'setResults' | 'setQuery'> & Pick<ReturnType<typeof useSearchMetadataState>, 'setSelectedQualityByGroup'> & Pick<ReturnType<typeof usePosterWorkers>, 'startPosterBackgroundSearch'> & Pick<ReturnType<typeof useMovieTorrentCache>, 'persistMovieTorrentCache'>) {
  const searchMovieTorrents = async (movie: MovieCatalogueItem) => {
    // Torrent lookup and Prepare state are user-initiated only. Background cache/metadata
    // work must never be able to open a Prepare card.
    if (!prepareClickIntentRef.current || !prepareTraceIdRef.current || prepareBuildPendingRef.current) {
      console.warn('[PREPARE_TRACE]', JSON.stringify({
        event: 'blocked-prepare-search',
        title: movie.title,
        year: movie.year || null,
        reason: 'missing-explicit-click-intent',
        at: new Date().toISOString(),
      }));
      return;
    }
    const traceId = prepareTraceIdRef.current;
    const previewIdentity = catalogueMovieIdentity(movie, movieCatalogue?.catalogue);
    prepareBuildPendingRef.current = true;
    prepareClickIntentRef.current = false;

    console.info('[PREPARE_TRACE]', JSON.stringify({
      event: 'prepare-search-start',
      traceId,
      title: movie.title,
      year: movie.year || null,
      at: new Date().toISOString(),
    }));
    setExpandedSearchGroupKey(null);
    const titleQuery = movie.title + (movie.year ? ' ' + movie.year : '');
    movieTorrentSearchControllerRef.current?.abort();
    const controller = new AbortController();
    movieTorrentSearchControllerRef.current = controller;
    const generation = ++movieTorrentSearchGenerationRef.current;

    // A constructible unverified VidRift URL is not a provider-verified result; it only enables manual playback.
    const openNexStreamOnlyCard = (): boolean => {
      if (movie.directStreamBroken === true || !Number(movie.tmdbId || movie.id)) return false;
      const stub = { title: movie.title, mediaTitle: movie.title, posterUrl: movie.posterUrl || undefined, tmdbId: movie.tmdbId || movie.id, id: movie.tmdbId || movie.id, year: movie.year || undefined } as unknown as TorrentSearchResult;
      const group: TorrentQualityGroup = { key: 'nexstream-only:' + String(movie.id), title: movie.title, year: String(movie.year || ''), variants: [], posterResult: stub };
      setSelectedMovieTorrentQualityByGroup({});
      setMovieTorrentPreviewGroup(group);
      setMovieTorrentPreviewCatalogueId(previewIdentity);
      setMovieTorrentPickerGroups(null);
      return true;
    };
    setMovieTorrentSearchTitle(titleQuery);
    setMovieTorrentPreviewCatalogueId(previewIdentity);
    setMovieTorrentPreviewPosterUrl(
      cataloguePosterUrlsRef.current[String(movie.id)] || cataloguePosterSource(movie)
    );
    setMovieTorrentSearchLoading(true);
    setMovieTorrentSearchError('');
    setMovieTorrentPreviewGroup(null);
    setMovieTorrentPickerGroups(null);
    setSelectedMovieTorrentQualityByGroup({});
    setResults([]);
    setSearched(false);
    setQuery(titleQuery);
    setSelectedQualityByGroup({});
    prepareBuildPendingRef.current = false;

    const cacheKey = normalizeGroupTitle(movie.title) + '|' + String(movie.year || '');
    const cachedDetails = movieTorrentDetailsCacheRef.current.get(cacheKey);
    const persistedDetails = cachedDetails || readLocalCache<{ groups: TorrentQualityGroup[]; savedAt: number }>(MOVIE_TORRENT_CACHE_STORAGE_KEY, cacheKey);
    if (persistedDetails && Date.now() - persistedDetails.savedAt < MOVIE_TORRENT_CACHE_TTL_MS) {
      movieTorrentDetailsCacheRef.current.set(cacheKey, persistedDetails);
      const groups = persistedDetails.groups.map(group => ({
        ...group,
        posterResult: {
          ...group.posterResult,
          posterUrl: group.posterResult?.posterUrl || movie.posterUrl || undefined,
          mediaTitle: group.posterResult?.mediaTitle || movie.title,
          tmdbId: group.posterResult?.tmdbId || movie.tmdbId || movie.id,
          id: group.posterResult?.id || movie.tmdbId || movie.id,
          year: group.posterResult?.year || movie.year || group.year,
        },
      }));
      if (groups.length > 0) {
        const expectedTitle = normalizeGroupTitle(movie.title);
        const expectedYear = String(movie.year || '');
        const selectedGroup = [...groups].sort((a, b) => {
          const score = (group: TorrentQualityGroup) => {
            const title = normalizeGroupTitle(group.title.replace(/\s*\((?:19|20)\d{2}\)\s*$/, ''));
            let value = title === expectedTitle ? 100 : title.includes(expectedTitle) ? 20 : 0;
            if (expectedYear && torrentGroupReleaseYear(group) === Number(expectedYear)) value += 25;
            if (/\b(?:making of|behind the scenes|soundtrack|interview|trailer)\b/i.test(group.title)) value -= 100;
            return value;
          };
          return score(b) - score(a);
        })[0];
        console.info('[PREPARE_TRACE]', JSON.stringify({
          event: 'prepare-card-open',
          traceId,
          source: 'prebuilt-cache',
          title: movie.title,
          year: movie.year || null,
          variants: selectedGroup.variants.length,
          at: new Date().toISOString(),
        }));
        setSelectedMovieTorrentQualityByGroup({ [selectedGroup.key]: torrentResultKey(selectedGroup.variants[0]) });
        setMovieTorrentPreviewGroup(selectedGroup);
        setMovieTorrentPreviewCatalogueId(previewIdentity);
        if (!/^(popular|trending|latest)-(bollywood|hollywood)$/.test(String(movieCatalogue?.catalogue || ''))) {
          startPosterBackgroundSearch(selectedGroup.variants);
        }
      } else if (!openNexStreamOnlyCard()) {
        setMovieTorrentSearchError('No usable torrent releases were found for ' + titleQuery + '. Try again later or use a shorter title.');
      }
      setMovieTorrentSearchLoading(false);
      return;
    }

    try {
      const embeddedMatches = [
        ...(Array.isArray(movie.torrentMatches) ? movie.torrentMatches : []),
        ...(movie.torrentMatch ? [movie.torrentMatch] : []),
      ];
      let data: TorrentSearchResult[] | null = embeddedMatches
        .filter(match => Boolean(match && (match.magnetUrl || match.infoHash || match.infoUrl)))
        .map((match, index): TorrentSearchResult => ({
          guid: String(match.infoHash || match.magnetUrl || match.infoUrl || movie.title + '-' + index),
          title: String(match.title || movie.title),
          mediaTitle: movie.title,
          size: Number(match.size) || 0,
          seeders: Number(match.seeders) || 0,
          leechers: Number(match.leechers) || 0,
          indexer: match.indexer,
          infoHash: match.infoHash,
          magnetUrl: match.magnetUrl,
          infoUrl: match.infoUrl,
          sourceUrl: match.infoUrl,
          year: movie.year,
          posterUrl: movie.posterUrl,
          quality: '',
        }));
      if (data.length === 0) data = null;

      // Prefer the movie's bundled torrent matches; query the shared VPS snapshot
      // only when this catalogue row does not already include a release.
      if (!data) {
        try {
          const params = new URLSearchParams({ title: movie.title, year: String(movie.year || '') });
          console.info('[PREPARE_TRACE]', JSON.stringify({
            event: 'prebuilt-request',
            traceId,
            title: movie.title,
            year: movie.year || null,
            at: new Date().toISOString(),
          }));
          const response = await fetch(API_BASE + '/api/regional-movies/prebuilt?' + params.toString(), {
            signal: controller.signal,
            credentials: 'include',
            cache: 'no-store',
            headers: {
              'X-Prepare-Intent': 'explicit-card-click',
              'X-Prepare-Trace': traceId,
            },
          });
          console.info('[PREPARE_TRACE]', JSON.stringify({
            event: 'prebuilt-response',
            traceId,
            status: response.status,
            ok: response.ok,
            at: new Date().toISOString(),
          }));
          if (response.ok) {
            const cached = await response.json();
            const rows = cached?.torrentDetails?.results;
            if (cached?.status === 'ready' && Array.isArray(rows) && rows.length > 0) data = rows as TorrentSearchResult[];
          }
        } catch { /* The bundled catalogue details remain the fallback. */ }
      }
      if (generation !== movieTorrentSearchGenerationRef.current) return;
      // Prefilled catalogues are cache-only. A missing VPS/GitHub-seeded
      // cache entry must never trigger a live provider/indexer search, even
      // after an explicit Get click. Cache refreshes happen in the separate
      // VPS-to-GitHub workflow, not in the user's request path.
      if (!data) data = [];
      if (generation !== movieTorrentSearchGenerationRef.current) return;

      // Prefer active swarms, but don't let missing seeder metadata hide every
      // release. The regular search can display results from indexers that do
      // not report seed counts reliably.
      const minSeedrFriendlySize = searchLimits.minSizeMb * 1024 * 1024;
      const maxSeedrFriendlySize = searchLimits.maxSizeGb * 1024 * 1024 * 1024;
      const lowQualityRelease = /(?:^|[\s._()[\]-])(?:cam(?:rip)?|hdcam|hd[ ._-]?cam|telesync|tele[ ._-]?sync|ts[ ._-]?(?:md|ac3|hd)?|telecine|dvdscr|dvd[ ._-]?scr|screener|workprint)(?:$|[\s._()[\]-])/i;
      // Indexers often return loose keyword matches. Keep a result only when the
      // actual release title contains the selected movie title as a phrase, so a
      // movie called "Only Me" won't show unrelated releases containing "Only"
      // and "Me" far apart in their titles.
      const expectedTitle = normalizeGroupTitle(movie.title);
      // 'Dhood (Sandstorm)' is released as plain 'Dhood': also accept the title without a
      // bracketed alias or subtitle.
      const baseTitle = normalizeGroupTitle(String(movie.title || '').split(/\s+[-\u2013\u2014:]\s+|\s*\(/)[0]);
      const expectedTitles = [expectedTitle, baseTitle.length >= 3 ? baseTitle : ''].filter(Boolean);
      const groupUsableResults = (items: TorrentSearchResult[], requireActiveSeeders: boolean) => {
        const usable = items.filter(result => {
          const releaseTitle = normalizeGroupTitle(String(result.title || ''));
          const mediaTitle = normalizeGroupTitle(String(result.mediaTitle || ''));
          const titleMatches = expectedTitles.some(expected =>
            releaseTitle.includes(expected) || mediaTitle === expected || mediaTitle.includes(expected));
          if (!titleMatches) return false;
          const rawSize = Number(result.size);
          const size = Number.isFinite(rawSize) && rawSize > 0 ? rawSize : 0;
          const seeders = Number(result.seeders);
          const hasSource = Boolean(
            String(result.magnetUrl || '').trim() ||
            String(result.downloadUrl || '').trim() ||
            String(result.sourceUrl || '').trim()
          );
          if (!hasSource || size < minSeedrFriendlySize || size > maxSeedrFriendlySize) return false;
          if (requireActiveSeeders && (!Number.isFinite(seeders) || seeders <= 0)) return false;
          return !lowQualityRelease.test(String(result.title || '') + ' ' + String(result.quality || ''));
        });
        return groupTorrentResults(usable);
      };

      let groups = groupUsableResults(data, true);

      // Year tags aren't always present in torrent filenames. When the strict
      // title+year search yields nothing, retry the movie's plain title before
      // concluding that the provider has no releases.
      const titleOnlyQuery = String(movie.title || '').trim();
      // Do not retry a cache miss with a title-only live search. This UI is
      // deliberately cache-only; refreshes belong to the external cache builder.

      // Some indexers omit seeder counts. If no actively seeded releases
      // survived, show linked, non-CAM releases within the size limit rather
      // than reporting a false "no releases" failure.
      if (groups.length === 0) {
        groups = groupUsableResults(data, false);
      }

      // Cache the complete grouped release details (quality variants, sources,
      // seed/leech counts and file sizes) so a later Prepare-card open is instant.
      // Cache empty results briefly too, avoiding repeated indexer scans for titles
      // that currently have no usable releases.
      movieTorrentDetailsCacheRef.current.set(cacheKey, { groups, savedAt: Date.now() });
      persistMovieTorrentCache();
      if (movieTorrentDetailsCacheRef.current.size > 250) {
        const oldestKey = movieTorrentDetailsCacheRef.current.keys().next().value;
        if (oldestKey) movieTorrentDetailsCacheRef.current.delete(oldestKey);
      }

      if (groups.length === 0) {
        if (openNexStreamOnlyCard()) return;
        if (movieCatalogue?.catalogue === 'popular-bollywood') {
          setMovieTorrentSearchError('Coming soon on OTT — this title is not available to prepare right now. Check back later for a streaming release.');
        } else {
          setMovieTorrentSearchError('No usable torrent releases were found for ' + titleQuery + '. Try again later or use a shorter title.');
        }
        return;
      }

      // Regional catalogue posters are authoritative; avoid separate torrent-title poster lookups.
      const isRegionalMovieCatalogue = /^(popular|trending|latest)-(bollywood|hollywood)$/.test(String(movieCatalogue?.catalogue || ''));
      if (!isRegionalMovieCatalogue) {
        startPosterBackgroundSearch(groups.flatMap(group => group.variants));
      }
      if (groups.length > 0) {
        // Open the normal Prepare card immediately instead of showing a
        // separate release-selection modal. Prefer an exact movie title/year
        // match so extras such as "The Making of..." are not selected first.
        const catalogueGroups = groups.map(group => ({
          ...group,
          posterResult: {
            ...group.posterResult,
            posterUrl: group.posterResult?.posterUrl || movie.posterUrl || undefined,
            mediaTitle: group.posterResult?.mediaTitle || movie.title,
            tmdbId: group.posterResult?.tmdbId || movie.tmdbId || movie.id,
            id: group.posterResult?.id || movie.tmdbId || movie.id,
            year: group.posterResult?.year || movie.year || group.year,
          },
        }));
        const expectedTitle = normalizeGroupTitle(movie.title);
        const expectedYear = String(movie.year || '');
        const groupScore = (group: TorrentQualityGroup) => {
          const title = normalizeGroupTitle(group.title.replace(/\s*\((?:19|20)\d{2}\)\s*$/, ''));
          let score = title === expectedTitle ? 100 : title.includes(expectedTitle) ? 20 : 0;
          if (expectedYear && torrentGroupReleaseYear(group) === Number(expectedYear)) score += 25;
          if (/\b(?:making of|behind the scenes|soundtrack|interview|trailer)\b/i.test(group.title)) score -= 100;
          return score;
        };
        const group = [...catalogueGroups].sort((a, b) => groupScore(b) - groupScore(a))[0];
        console.info('[PREPARE_TRACE]', JSON.stringify({
          event: 'prepare-card-open',
          traceId,
          source: 'live-torrent-search',
          title: movie.title,
          year: movie.year || null,
          variants: group.variants.length,
          at: new Date().toISOString(),
        }));
        setSelectedMovieTorrentQualityByGroup({ [group.key]: torrentResultKey(group.variants[0]) });
        setMovieTorrentPreviewGroup(group);
        setMovieTorrentPreviewCatalogueId(previewIdentity);
        setMovieTorrentPickerGroups(null);
      }
    } catch (error: any) {
      if (generation !== movieTorrentSearchGenerationRef.current || error?.name === 'AbortError') return;
      setMovieTorrentSearchError(String(error?.message || 'Torrent search failed for ' + titleQuery + '.'));
    } finally {
      if (generation === movieTorrentSearchGenerationRef.current) {
        setMovieTorrentSearchLoading(false);
        if (movieTorrentSearchControllerRef.current === controller) {
          movieTorrentSearchControllerRef.current = null;
        }
      }
    }
  };
  const selectMovieTorrentGroup = (group: TorrentQualityGroup) => {
    setSelectedMovieTorrentQualityByGroup({ [group.key]: torrentResultKey(group.variants[0]) });
    setMovieTorrentPreviewGroup(group);
    setMovieTorrentPreviewCatalogueId(null);
    setMovieTorrentPickerGroups(null);
    setMovieTorrentSearchError('');
    if (!/^(popular|trending|latest)-(bollywood|hollywood)$/.test(String(movieCatalogue?.catalogue || ''))) {
      startPosterBackgroundSearch(group.variants);
    }
  };
  // Returns a selected catalogue card from its prepare card back to the compact card.
  const closeMoviePrepareCard = () => {
    movieTorrentSearchControllerRef.current?.abort();
    movieTorrentSearchGenerationRef.current += 1;
    setMovieTorrentSearchLoading(false);
    setMovieTorrentPreviewGroup(null);
    setMovieTorrentPreviewCatalogueId(null);
    setMovieTorrentPreviewPosterUrl('');
    setMovieTorrentSearchError('');
  };

  return {
    searchMovieTorrents,
    selectMovieTorrentGroup,
    closeMoviePrepareCard,
  };
}
