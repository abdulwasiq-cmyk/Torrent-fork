import React from 'react';
import { api, ImdbRatingResult, MarvelCatalogueResponse, TorrentSearchResult } from '../../../api/client.ts';
import { setHighQualityPostersReady } from '../../MovieCards.tsx';
import { episodeSeriesTitle, groupTorrentResults, imdbRatingKey, mergeSearchMetadataItems, normalizeGroupTitle, normalizeSavedOttTitle, releaseDateSortValue, torrentMediaIdentity, torrentResultKey } from '../grouping.ts';
import { franchiseCatalogueSection, franchiseRowsFromSection, franchiseSectionDocumentFromCache, sectionRowTmdbId } from '../../../api/sectionCache.ts';
import { normalizeSavedOttProviders } from '../ottProviders.ts';
import { readFranchisePageCache, readPersistentSearchAvailability, readPersistentSearchMetadata, writeFranchisePageCache } from '../persistentCaches.ts';
import { useNexStreamState } from './useNexStreamState.ts';
import { useSearchMetadataState } from './useSearchMetadataState.ts';
import { useMoviePreviewState } from './useMoviePreviewState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useWebSeriesState } from './useWebSeriesState.ts';
import { useSearchInputState } from './useSearchInputState.ts';
import { usePosterState } from './usePosterState.ts';
import { useNexStreamFlow } from './useNexStreamFlow.ts';
import { useRecentSearches } from './useRecentSearches.ts';

export function useSearchRunner({ setFranchiseGridPage, setActiveFranchiseSearchMode, franchisePageRequestRef, franchisePageGenerationRef, franchiseLoadedPagesRef, posterFirstPageReadyRef, setPosterFirstPageReady, setIsPresetCatalogueAction, setIsMarvelEnglishResults, setIsDcLiveActionEnglishResults, setShowMarvelWebSeries, setError, setSearched, setIsSearching, setCatalogueBuildProgress, setCatalogueExpectedTitles, setMovieCatalogue, franchiseGridPageSize, franchiseGridPage, setShowDcWebSeries, setMovieTorrentSearchError, setMovieTorrentPreviewCatalogueId, movieTorrentSearchControllerRef, movieTorrentSearchGenerationRef, setMovieTorrentSearchLoading, setMovieTorrentPickerGroups, setMovieTorrentPreviewGroup, setExpandedSearchGroupKey, query, setResults, searchGenerationRef, searchRequestRef, setShowRecentSearches, setQuery, setSearchMetadata, setSearchMetadataStatus, setImdbRatingsByKey, setSearchAvailabilityByGroup, setSelectedQualityByGroup, setPosterOverrides, posterMetadataFailedRef, posterLoadedRef, posterBackgroundQueueRef, posterBackgroundQueuedRef, posterBackgroundAttemptsRef, posterBackgroundGenerationRef, saveRecentSearch, searchNexStreamTitles, nexStreamSearchGenerationRef, nexStreamSearchControllerRef, setNexStreamLoading, setNexStreamSearchMode, setNexStreamResults, setNexStreamError, setNexStreamPlayer }: Pick<ReturnType<typeof useCatalogueNavigationState>, 'setFranchiseGridPage' | 'setActiveFranchiseSearchMode' | 'franchisePageRequestRef' | 'franchisePageGenerationRef' | 'franchiseLoadedPagesRef' | 'posterFirstPageReadyRef' | 'setPosterFirstPageReady' | 'setIsPresetCatalogueAction' | 'setIsMarvelEnglishResults' | 'setIsDcLiveActionEnglishResults' | 'setShowMarvelWebSeries' | 'setError' | 'setSearched' | 'setIsSearching' | 'setCatalogueBuildProgress' | 'setCatalogueExpectedTitles' | 'setMovieCatalogue' | 'franchiseGridPageSize' | 'franchiseGridPage'> & Pick<ReturnType<typeof useWebSeriesState>, 'setShowDcWebSeries'> & Pick<ReturnType<typeof useMoviePreviewState>, 'setMovieTorrentSearchError' | 'setMovieTorrentPreviewCatalogueId' | 'movieTorrentSearchControllerRef' | 'movieTorrentSearchGenerationRef' | 'setMovieTorrentSearchLoading' | 'setMovieTorrentPickerGroups' | 'setMovieTorrentPreviewGroup' | 'setExpandedSearchGroupKey'> & Pick<ReturnType<typeof useSearchInputState>, 'query' | 'setResults' | 'searchGenerationRef' | 'searchRequestRef' | 'setShowRecentSearches' | 'setQuery'> & Pick<ReturnType<typeof useSearchMetadataState>, 'setSearchMetadata' | 'setSearchMetadataStatus' | 'setImdbRatingsByKey' | 'setSearchAvailabilityByGroup' | 'setSelectedQualityByGroup'> & Pick<ReturnType<typeof usePosterState>, 'setPosterOverrides' | 'posterMetadataFailedRef' | 'posterLoadedRef' | 'posterBackgroundQueueRef' | 'posterBackgroundQueuedRef' | 'posterBackgroundAttemptsRef' | 'posterBackgroundGenerationRef'> & Pick<ReturnType<typeof useRecentSearches>, 'saveRecentSearch'> & Pick<ReturnType<typeof useNexStreamFlow>, 'searchNexStreamTitles'> & Pick<ReturnType<typeof useNexStreamState>, 'nexStreamSearchGenerationRef' | 'nexStreamSearchControllerRef' | 'setNexStreamLoading' | 'setNexStreamSearchMode' | 'setNexStreamResults' | 'setNexStreamError' | 'setNexStreamPlayer'>) {
  const runSearch = async (event?: React.FormEvent, searchOverride?: string, searchMode?: 'marvel' | 'marvel-hindi' | 'dc-live-action' | 'dc-live-action-hindi' | 'dc-animated' | 'classics') => {
    event?.preventDefault();
    setHighQualityPostersReady(false);
    setFranchiseGridPage(1);
    setActiveFranchiseSearchMode(searchMode || null);
    franchisePageRequestRef.current?.abort();
    franchisePageRequestRef.current = null;
    franchisePageGenerationRef.current += 1;
    franchiseLoadedPagesRef.current.clear();
    posterFirstPageReadyRef.current = false;
    setPosterFirstPageReady(false);
    setIsPresetCatalogueAction(Boolean(searchMode));
    setIsMarvelEnglishResults(searchMode === 'marvel');
    setIsDcLiveActionEnglishResults(searchMode === 'dc-live-action');
    setShowDcWebSeries(false);
    setIsDcLiveActionEnglishResults(searchMode === 'dc-live-action');
    setShowMarvelWebSeries(false);
    setShowDcWebSeries(false);
    const chronologicalFranchiseModes = new Set(['marvel', 'marvel-hindi', 'dc-live-action', 'dc-live-action-hindi', 'dc-animated', 'classics']);
    setMovieTorrentSearchError('');
    setMovieTorrentPreviewCatalogueId(null);
    movieTorrentSearchControllerRef.current?.abort();
    movieTorrentSearchGenerationRef.current += 1;
    setMovieTorrentSearchLoading(false);
    setMovieTorrentPickerGroups(null);
    setMovieTorrentPreviewGroup(null);

    const trimmed = (searchOverride ?? query).trim();
    if (!searchMode) setIsPresetCatalogueAction(false);
    if (trimmed.length < 2) {
      setError('Enter at least 2 characters to search.');
      setResults([]);
      setSearched(false);
      return;
    }

    const generation = ++searchGenerationRef.current;
    searchRequestRef.current?.abort();
    const controller = new AbortController();
    searchRequestRef.current = controller;

    try {
      setIsSearching(true);
      setCatalogueBuildProgress('');
      setCatalogueExpectedTitles(0);
      setMovieCatalogue(null);
      setShowRecentSearches(false);
      setError('');
      setResults([]);
      setSearchMetadata(readPersistentSearchMetadata());
      setSearchMetadataStatus('idle');
      setSearchAvailabilityByGroup(readPersistentSearchAvailability());
      setSelectedQualityByGroup({});
      setExpandedSearchGroupKey(null);
      setSearched(false);
      setPosterOverrides({});
      posterMetadataFailedRef.current.clear();
      posterLoadedRef.current.clear();
      posterBackgroundQueueRef.current = [];
      posterBackgroundQueuedRef.current.clear();
      posterBackgroundAttemptsRef.current.clear();
      posterBackgroundGenerationRef.current += 1;
      // Preset catalogue searches are actions, not user-entered queries.
      // Keep the input empty and never add these labels to local or server history.
      if (searchMode) {
        setQuery('');
      } else {
        saveRecentSearch(trimmed);
      }
      setCatalogueBuildProgress('');

      // Normal search also searches NexStream movies in parallel; neither source blocks cached torrent cards.
      if (!searchMode && trimmed.length >= 2) void searchNexStreamTitles(trimmed, 'movie');
      else {
        nexStreamSearchGenerationRef.current += 1;
        nexStreamSearchControllerRef.current?.abort();
        nexStreamSearchControllerRef.current = null;
        setNexStreamLoading(false);
        setNexStreamSearchMode(null);
        setNexStreamResults([]);
        setNexStreamError('');
        setNexStreamPlayer(null);
      }

      // Start TMDB metadata immediately and let it load alongside cached/live torrent
      // search. The first cards and Seedr preparation do not wait for this request.
      if (!searchMode && trimmed.length >= 2) {
        setSearchMetadataStatus('loading');
        void api.searchMediaMetadata(trimmed, controller.signal).then(metadataResponse => {
          if (generation !== searchGenerationRef.current) return;
          setSearchMetadata(previous => mergeSearchMetadataItems(
            previous,
            Array.isArray(metadataResponse.results) ? metadataResponse.results : [],
          ));
          setSearchMetadataStatus(metadataResponse.status || 'unavailable');
        }).catch(() => {
          if (generation !== searchGenerationRef.current) return;
          // The VPS catalogue lookup may already have supplied saved synopses.
          // A failed live TMDB request must not erase those successful cache hits.
          setSearchMetadataStatus('unavailable');
        });
      }

      // Search the persistent torrent catalogues in parallel with live indexers.
      // Cached matches are shown as soon as they arrive; live results are merged in later.
      const cachedSearchPromise: Promise<TorrentSearchResult[]> = searchMode
        ? Promise.resolve([])
        : Promise.allSettled([
            api.getMarvelCatalogue(controller.signal),
            ...[
              'marvel-hindi',
              'dc-live-action',
              'dc-live-action-hindi',
              'dc-animated',
            ].map(key => api.getCatalogue(key, controller.signal)),
          ].map(request => request.then(response => {
            // Publish each ready catalogue immediately instead of waiting for all seven.
            if (generation !== searchGenerationRef.current || response.status !== 'ready') return response;
            const compactQuery = normalizeGroupTitle(trimmed).replace(/\\s+/g, '');
            const seen = new Set<string>();
            const matches = response.results.filter(row => {
              const titleKey = torrentMediaIdentity(row).normalized.replace(/\\s+/g, '');
              if (!titleKey.includes(compactQuery) && !compactQuery.includes(titleKey)) return false;
              const key = torrentResultKey(row);
              if (seen.has(key)) return false;
              seen.add(key);
              return true;
            });
            if (matches.length) {
              setResults(previous => {
                const byKey = new Map<string, TorrentSearchResult>();
                [...matches, ...previous].forEach(row => {
                  const key = torrentResultKey(row);
                  if (!byKey.has(key)) byKey.set(key, row);
                });
                return Array.from(byKey.values());
              });
              setSearched(true);
              // Keep poster resolution independent of the search response.
            }
            return response;
          }))).then(responses => {
            const compactQuery = normalizeGroupTitle(trimmed).replace(/\\s+/g, '');
            const cachedRows = responses.flatMap(response =>
              response.status === 'fulfilled' && response.value.status === 'ready'
                ? response.value.results
                : []
            );
            const seen = new Set<string>();
            return cachedRows.filter(row => {
              const titleKey = torrentMediaIdentity(row).normalized.replace(/\\s+/g, '');
              if (!titleKey.includes(compactQuery) && !compactQuery.includes(titleKey)) return false;
              const key = torrentResultKey(row);
              if (seen.has(key)) return false;
              seen.add(key);
              return true;
            });
          }).catch(() => []);

      if (!searchMode) {
        void cachedSearchPromise.then(cached => {
          if (generation !== searchGenerationRef.current || !cached.length) return;
          setResults(previous => {
            const byKey = new Map<string, TorrentSearchResult>();
            [...cached, ...previous].forEach(row => byKey.set(torrentResultKey(row), row));
            return Array.from(byKey.values());
          });
          setSearched(true);
        });
      }

      let data: TorrentSearchResult[];
      if (searchMode) {
        const sectionCache = await franchiseSectionDocumentFromCache(
          section => api.getSectionCache(section),
          searchMode,
        );
        if (sectionCache) {
          const { location: sectionLocation, document } = sectionCache;
          if (generation !== searchGenerationRef.current || controller.signal.aborted) return;
          const subsection = document.subsections[sectionLocation.subsection];
          const allResults = franchiseRowsFromSection(document, sectionLocation.subsection);
          if (!subsection || !allResults) {
            throw new Error('The requested subsection is missing from its section cache.');
          }
          setSearchAvailabilityByGroup({});
          const pageSize = Math.max(1, Number(subsection.pageSize) || franchiseGridPageSize);
          data = allResults.slice(0, pageSize);
          const totalResults = Number(subsection.totalResults) || allResults.length;
          setCatalogueExpectedTitles(totalResults > pageSize ? totalResults : 0);
          franchiseLoadedPagesRef.current.set(searchMode, new Set([1]));
          setCatalogueBuildProgress('');
          setSearchMetadata(previous => mergeSearchMetadataItems(previous, subsection.results.map(row => {
            const tmdbId = sectionRowTmdbId(row);
            return {
              id: tmdbId ?? row.id ?? row.title,
              tmdbId,
              title: row.title,
              year: Number(row.year) || null,
              mediaType: 'movie' as const,
              overview: row.overview || undefined,
              posterUrl: row.posterUrl || undefined,
              backdropUrl: row.backdropUrl || undefined,
              rating: row.rating ?? undefined,
              tmdbUrl: row.tmdbUrl || (tmdbId
                ? 'https://www.themoviedb.org/movie/' + tmdbId
                : ''),
              source: row.source || 'self-contained-section-cache',
            };
          })));
          setImdbRatingsByKey(previous => {
            const next = { ...previous };
            const cacheKeys = subsection.results.map(row => imdbRatingKey(row.title, row.year));
            cacheKeys.forEach(key => { delete next[key]; });
            subsection.results.forEach(row => {
              if (!row.imdbRatingStatus && !(Number(row.imdbRating) > 0)) return;
              const status = row.imdbRatingStatus || 'found';
              const rating: ImdbRatingResult = {
                query: row.title,
                title: row.title,
                year: Number(row.year) || null,
                mediaType: 'movie',
                status,
                imdbId: row.imdbId || undefined,
                imdbRating: row.imdbRating,
                imdbVotes: row.imdbVotes == null ? null : String(row.imdbVotes),
                imdbUrl: row.imdbUrl || undefined,
              };
              next[imdbRatingKey(row.title, row.year)] = rating;
            });
            return next;
          });
          setSearchMetadataStatus('ready');
        } else {
          // Legacy franchise modes remain available for catalogues without a
          // corresponding subsection in the self-contained section documents.
          const CATALOGUE_PAGE_SIZE = franchiseGridPageSize;
          const fetchCataloguePage = (page: number) => searchMode === 'marvel'
            ? api.getMarvelCatalogue(controller.signal, { page, pageSize: CATALOGUE_PAGE_SIZE })
            : api.getCatalogue(searchMode, controller.signal, { page, pageSize: CATALOGUE_PAGE_SIZE });

          const browserCachedPage = readFranchisePageCache(searchMode, 1);
          let catalogue: MarvelCatalogueResponse = browserCachedPage
            ? {
                status: 'ready' as const,
                results: browserCachedPage.results,
                completed: browserCachedPage.totalMovies,
                total: browserCachedPage.totalMovies,
                totalMovies: browserCachedPage.totalMovies,
                totalPages: browserCachedPage.totalPages,
                refreshing: false,
              }
            : await fetchCataloguePage(1);
          let catalogueAttempts = 0;
          while (
            (catalogue.status === 'building' || catalogue.status === 'idle') &&
            catalogueAttempts < 8
          ) {
            if (generation !== searchGenerationRef.current || controller.signal.aborted) return;
            setCatalogueBuildProgress(
              'Building shared ' + searchMode.replace(/-/g, ' ') + ' catalogue: ' +
              catalogue.completed + ' of ' + catalogue.total + ' searches completed.'
            );
            await new Promise<void>(resolve => window.setTimeout(resolve, 2200));
            catalogueAttempts += 1;
            catalogue = await fetchCataloguePage(1);
          }
          if (generation !== searchGenerationRef.current || controller.signal.aborted) return;
          if (catalogue.status !== 'ready' || !Array.isArray(catalogue.results)) {
            throw new Error(catalogue.error || 'Could not load the first catalogue page.');
          }
          data = catalogue.results;
          const totalCataloguePages = Number(catalogue.totalPages) || 1;
          const expectedTitles = Number(catalogue.totalMovies) || (totalCataloguePages * CATALOGUE_PAGE_SIZE);
          setCatalogueExpectedTitles(totalCataloguePages > 1 ? expectedTitles : 0);
          if (!browserCachedPage) {
            writeFranchisePageCache(searchMode, 1, data, expectedTitles, totalCataloguePages);
          }
          franchiseLoadedPagesRef.current.set(searchMode, new Set([1]));
          setCatalogueBuildProgress(
            catalogue.refreshing
              ? 'Showing the cached first page; newer catalogue data will be used on a later visit.'
              : ''
          );
        }
      } else {
        const livePromise = api.searchTorrents(trimmed, 50, controller.signal);
        // Do not make live torrent results wait for the seven catalogue lookups.
        // Cached catalogue matches are merged independently as each search completes.
        const liveResults = await livePromise;
        data = [...liveResults];
        const unique = new Map<string, TorrentSearchResult>();
        data.forEach(row => {
          const key = torrentResultKey(row);
          if (!unique.has(key)) unique.set(key, row);
        });
        data = Array.from(unique.values());
      }

      // The backend owns low-result TV/season fallback. Keeping that logic
      // server-side avoids launching duplicate season searches from the browser.

      // Keep the cached franchise/favourites catalogues in full release-date
      // order even if an older cache snapshot or API response is unsorted.
      if (searchMode && !franchiseCatalogueSection(searchMode) && chronologicalFranchiseModes.has(searchMode)) {
        data = [...data].sort((a, b) => {
          const dateOrder = releaseDateSortValue(b) - releaseDateSortValue(a);
          if (dateOrder !== 0) return dateOrder;

          const aIdentity = torrentMediaIdentity(a);
          const bIdentity = torrentMediaIdentity(b);
          const titleOrder = aIdentity.normalized.localeCompare(
            bIdentity.normalized,
            undefined,
            { numeric: true },
          );
          if (titleOrder !== 0) return titleOrder;

          return (Number(b.seeders) || 0) - (Number(a.seeders) || 0);
        });
      }

      // Never let an older request overwrite a newer search. This matters
      // when a slow 1337x fallback finishes after a later click.
      if (generation !== searchGenerationRef.current) return;

      // Preserve any catalogue matches that arrived while live indexers were running.
      setResults(previous => {
        const byKey = new Map<string, TorrentSearchResult>();
        [...previous, ...data].forEach(row => {
          const key = torrentResultKey(row);
          if (!byKey.has(key)) byKey.set(key, row);
        });
        return Array.from(byKey.values());
      });
      setSearched(true);
      if (searchMode) setIsSearching(false);

      void (async () => {
        if (generation !== searchGenerationRef.current || controller.signal.aborted) return;
        // Prefilled catalogue pages (Marvel/DC/Classics) never run live provider lookups.
        // Saved streaming info is hydrated independently; torrent/NexStream info loads
        // only when a card is clicked.
        if (searchMode) return;
        {
        // Process every catalogue group so saved enrichment is available even when the
        // UI reorders results by quality/seeds. Only live lookups remain capped below.
        const availabilityGroups = groupTorrentResults(data).slice(
          (franchiseGridPage - 1) * franchiseGridPageSize,
          franchiseGridPage * franchiseGridPageSize,
        );
        const pendingLiveLookups: typeof availabilityGroups = [];
        // Titles with no provider info are re-checked live (3 at a time, bounded per search),
        // and the backend stores each answer, so every card ends up with streaming info.
        let liveLookupCount = 0;
        const liveLookupLimit = 150;
        const pendingLiveTmdbIds = new Map<string, number>();
        const recheckAfterMs = 6 * 60 * 60 * 1000;

        // The torrent-search cache and enriched OTT cache are separate files.
        // Fetch saved OTT entries by title once, so normal text searches can use
        // Marvel/DC enrichment too instead of starting a provider scan per card.
        const savedOttByTitle = new Map<string, any>();
        try {
          const savedOttResponse = await api.searchSavedOtt(
            availabilityGroups.map(group => group.title),
            controller.signal
          );
          if (generation === searchGenerationRef.current) {
            const savedProviderCount = (candidate: any): number => {
              const saved = candidate?.ottAvailability || candidate || {};
              return ['streamingProviders', 'rentProviders', 'buyProviders'].reduce(
                (total, key) => total + (Array.isArray(saved[key]) ? saved[key].length : 0),
                0,
              );
            };
            for (const result of savedOttResponse.results || []) {
              for (const entry of result.entries || []) {
                if (!entry.ottAvailability) continue;
                // Index by both the canonical saved title and the exact search
                // query. The latter guarantees a hit even when year/title labels differ.
                const keys = Array.from(new Set(
                  [entry.title, result.query]
                    .map(value => normalizeSavedOttTitle(String(value || '')))
                    .filter(Boolean)
                ));
                for (const key of keys) {
                  const existing = savedOttByTitle.get(key);
                  if (!existing || savedProviderCount(entry) > savedProviderCount(existing)) {
                    savedOttByTitle.set(key, entry);
                  }
                }
              }
            }
          }
        } catch {
          // A saved-cache lookup failure must not block torrent preparation.
        }

        for (const group of availabilityGroups) {
          const cachedTorrentRow = group.variants.find(variant => {
            const row = variant as TorrentSearchResult & {
              ottAvailability?: any;
              streamingProviders?: unknown;
              rentProviders?: unknown;
              buyProviders?: unknown;
            };
            const saved = row.ottAvailability && typeof row.ottAvailability === 'object'
              ? row.ottAvailability
              : row;
            return ['streamingProviders', 'rentProviders', 'buyProviders'].some(key =>
              Array.isArray((saved as any)[key]) && (saved as any)[key].length > 0
            ) || ['streamingProviders', 'rentProviders', 'buyProviders'].some(key =>
              Array.isArray((row as any)[key]) && (row as any)[key].length > 0
            );
          }) as (TorrentSearchResult & {
            tmdbId?: number | string;
            ottAvailability?: any;
            streamingProviders?: unknown;
            rentProviders?: unknown;
            buyProviders?: unknown;
            catalogueTitle?: string;
            marvelCatalogueTitle?: string;
          }) | undefined;
          const savedOttRow = savedOttByTitle.get(normalizeSavedOttTitle(group.title));
          const cachedRow = cachedTorrentRow || (savedOttRow as (TorrentSearchResult & {
            tmdbId?: number | string;
            ottAvailability?: any;
            streamingProviders?: unknown;
            rentProviders?: unknown;
            buyProviders?: unknown;
            catalogueTitle?: string;
            marvelCatalogueTitle?: string;
          }) | undefined);

          if (cachedRow) {
            const saved = cachedRow.ottAvailability && typeof cachedRow.ottAvailability === 'object'
              ? cachedRow.ottAvailability
              : cachedRow;
            const region = String(saved.region || 'IN');
            const providers = [
              ...normalizeSavedOttProviders(saved.streamingProviders, 'streaming', region),
              ...normalizeSavedOttProviders(saved.rentProviders, 'rent', region),
              ...normalizeSavedOttProviders(saved.buyProviders, 'buy', region),
            ];
            const title = String(cachedRow.catalogueTitle || cachedRow.marvelCatalogueTitle || cachedRow.mediaTitle || group.title)
              .replace(/\s*\(?(?:19|20)\d{2}\)?\s*$/, '').trim();
            const hasProviders = providers.length > 0;
            setSearchAvailabilityByGroup(previous => ({
              ...previous,
              [group.key]: {
                status: hasProviders ? 'ready' : 'not_confirmed',
                query: title,
                title,
                year: group.year,
                providers,
                matches: hasProviders ? [{
                  id: String(cachedRow.tmdbId || ''),
                  tmdbId: cachedRow.tmdbId,
                  title,
                  year: group.year,
                  type: 'movie',
                  status: 'ready',
                  providers,
                }] : [],
                message: hasProviders ? undefined : (
                  ['no_providers', 'no_streaming_provider_reported'].includes(String(saved.status || '').toLowerCase())
                    ? 'No providers were reported in the saved enrichment.'
                    : 'Saved enrichment has no provider names.'
                ),
              }
            }));
            if (hasProviders) continue;
            // No provider names saved: re-check live unless the saved miss is recent.
            const checkedMs = Date.parse(String(saved.checkedAt || ''));
            if (!saved.incomplete && Number.isFinite(checkedMs) && Date.now() - checkedMs < recheckAfterMs) continue;
            if (liveLookupCount >= liveLookupLimit) continue;
            liveLookupCount += 1;
            const savedTmdbId = Number(cachedRow.tmdbId);
            if (Number.isInteger(savedTmdbId) && savedTmdbId > 0) pendingLiveTmdbIds.set(group.key, savedTmdbId);
            pendingLiveLookups.push(group);
            continue;
          }

          // Keep live searches bounded so this path cannot fan out
          // provider queries for an unlimited result set.
          if (liveLookupCount >= liveLookupLimit) continue;
          liveLookupCount += 1;
          setSearchAvailabilityByGroup(previous => ({
            ...previous,
            [group.key]: { status: 'loading', query: group.title, providers: [] }
          }));
          pendingLiveLookups.push(group);
        }

        const runLiveLookup = async (group: typeof availabilityGroups[number]) => {
          const tmdbId = pendingLiveTmdbIds.get(group.key);
          const lookup = async () => {
            if (tmdbId) {
              const value = await api.getMovieOttAvailability(tmdbId, 'IN');
              const region = String(value.region || 'IN');
              const providers = [
                ...normalizeSavedOttProviders(value.streamingProviders, 'streaming', region),
                ...normalizeSavedOttProviders(value.rentProviders, 'rent', region),
                ...normalizeSavedOttProviders(value.buyProviders, 'buy', region),
              ];
              const title = group.title.replace(/\s*\(?(?:19|20)\d{2}\)?\s*$/, '').trim();
              return {
                status: providers.length ? 'ready' : 'not_confirmed',
                query: title,
                title,
                year: group.year,
                providers,
                matches: providers.length ? [{
                  id: String(tmdbId), tmdbId, title, year: group.year, type: 'movie', status: 'ready', providers,
                }] : [],
                message: providers.length ? undefined : 'No streaming providers were found when re-checked.',
              } as any;
            }
            const providerLookupTitle = episodeSeriesTitle(group.title) || group.title;
            const availabilityQuery = providerLookupTitle
              .replace(/\s+\(\d{4}\)\s*$/, '')
              .trim();
            return await api.searchAvailability(availabilityQuery);
          };
          for (let attempt = 0; attempt < 2; attempt += 1) {
            if (generation !== searchGenerationRef.current) return;
            try {
              const value = await lookup();
              if (generation === searchGenerationRef.current) {
                setSearchAvailabilityByGroup(previous => {
                  // A re-check that finds nothing must not erase saved info.
                  const existing = previous[group.key] as any;
                  if (existing?.providers?.length && !(value as any)?.providers?.length) return previous;
                  return { ...previous, [group.key]: value };
                });
              }
              return;
            } catch {
              if (attempt === 0) await new Promise<void>(resolve => window.setTimeout(resolve, 8000));
            }
          }
          if (generation === searchGenerationRef.current) {
            setSearchAvailabilityByGroup(previous => {
              const existing = previous[group.key] as any;
              // Keep a saved "no details" card as is; only a pending lookup becomes unavailable.
              if (existing && existing.status !== 'loading') return previous;
              return { ...previous, [group.key]: { status: 'unavailable', query: group.title, providers: [] } };
            });
          }
        };
        const liveQueue = [...pendingLiveLookups];
        void Promise.allSettled(Array.from({ length: Math.min(3, liveQueue.length) }, async () => {
          while (liveQueue.length > 0 && generation === searchGenerationRef.current) {
            const group = liveQueue.shift();
            if (group) await runLiveLookup(group);
          }
        }));
        }
      })();

      if (data.length === 0) {
        setError('No matching torrent results were found.');
      }
    } catch (err: any) {
      if (generation !== searchGenerationRef.current) return;
      if (err?.name === 'AbortError') return;
      setResults([]);
      setSearched(true);
      setCatalogueBuildProgress('');
      setError(err?.message || 'Torrent search failed.');
    } finally {
      if (generation === searchGenerationRef.current) {
        setIsSearching(false);
        if (searchRequestRef.current === controller) {
          searchRequestRef.current = null;
        }
      }
    }
  };

  return {
    runSearch,
  };
}
