import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { api, MovieCatalogueKey, TorrentSearchResult } from '../../api/client.ts';
import { movieCataloguePageFromSection, movieCatalogueSection, tvCataloguePageFromSectionCache } from '../../api/sectionCache.ts';
import { setHighQualityPostersReady } from '../MovieCards.tsx';
import { imdbRatingKey, torrentResultKey } from './grouping.ts';
import { CachedFranchiseSearchMode, persistImdbRatings, persistSearchAvailability, persistSearchMetadata, readFranchisePageCache, writeFranchisePageCache } from './persistentCaches.ts';
import { readPosterTitleCache } from './posterCache.ts';
import { lowQualityPosterUrl } from './posterUrls.ts';
import { isDefaultClassicsSort } from './classicsSort.ts';
import { franchiseCatalogueSection, franchiseRowsFromSection, franchiseSectionDocumentFromCache } from '../../api/sectionCache.ts';
import { CachedFranchiseKey, FranchiseTmdbKey, RegionalCatalogueGroup, RegionalCatalogueMode, RegionalTvGroup, RegionalTvMode } from './types.ts';
import { useNexStreamState } from './state/useNexStreamState.ts';
import { useSearchMetadataState } from './state/useSearchMetadataState.ts';
import { useMoviePreviewState } from './state/useMoviePreviewState.ts';
import { useCatalogueNavigationState } from './state/useCatalogueNavigationState.ts';
import { useWebSeriesState } from './state/useWebSeriesState.ts';
import { useSearchInputState } from './state/useSearchInputState.ts';
import { usePosterState } from './state/usePosterState.ts';
import { TorrentSearchPanelProps } from './props.ts';
import { usePrepareState } from './state/usePrepareState.ts';
import { usePosterWorkers } from './state/usePosterWorkers.ts';
import { useNexStreamFlow } from './state/useNexStreamFlow.ts';
import { useWebSeriesLoaders } from './state/useWebSeriesLoaders.ts';
import { usePrepareActions } from './state/usePrepareActions.ts';
import { useMovieTorrentCache } from './state/useMovieTorrentCache.ts';
import { useRecentSearches } from './state/useRecentSearches.ts';
import { useMovieTorrentSearch } from './state/useMovieTorrentSearch.ts';
import { useSearchRunner } from './state/useSearchRunner.ts';
import { useGroupedResults } from './state/useGroupedResults.ts';
import { usePosterEffects } from './state/usePosterEffects.ts';
import { useSynopsisPrefetch } from './state/useSynopsisPrefetch.ts';
import { useFranchisePageEffect } from './state/useFranchisePageEffect.ts';
import { useVisibleMovieCatalogue } from './state/useVisibleMovieCatalogue.ts';
import { useCatalogueDetailsPrefetch } from './state/useCatalogueDetailsPrefetch.ts';
import { useTorrentTitleBubble } from './state/useTorrentTitleBubble.ts';
import { useCancelSearch } from './state/useCancelSearch.ts';
import { usePosterReadyGate } from './state/usePosterReadyGate.ts';
import { useYenimePlayer } from './state/useYenimePlayer.ts';

const NO_RATINGS: Record<string, undefined> = {};

export function useTorrentSearchPanel({ seedrFiles, seedrDeletedFolderIds, onPrepare, onPlaySeedrFile, onOpenProgress, onCancelPrepare }: Pick<TorrentSearchPanelProps, 'onPrepare' | 'onPlaySeedrFile' | 'onOpenProgress' | 'onCancelPrepare'> & Required<Pick<TorrentSearchPanelProps, 'seedrFiles' | 'seedrDeletedFolderIds'>>) {
  const yenime = useYenimePlayer();
  const { query, setQuery, results, setResults, resolutionFilter, setResolutionFilter, sizeSort, setSizeSort, timeSort, setTimeSort, showRecentSearches, setShowRecentSearches, metadataCacheRef, recentSearchRef, searchRequestRef, searchGenerationRef } = useSearchInputState();
  const { nexStreamResults, setNexStreamResults, nexStreamSearchMode, setNexStreamSearchMode, nexStreamLoading, setNexStreamLoading, nexStreamLoadingTitle, setNexStreamLoadingTitle, nexStreamEpisodePrefetchStatus, setNexStreamEpisodePrefetchStatus, nexStreamSearchControllerRef, nexStreamSearchGenerationRef, nexStreamError, setNexStreamError, nexStreamPlayer, setNexStreamPlayer, nexStreamResolvingId, setNexStreamResolvingId, nexStreamEpisodePicker, setNexStreamEpisodePicker, nexStreamSeasons, setNexStreamSeasons, nexStreamEpisodes, setNexStreamEpisodes, nexStreamSelectedSeason, setNexStreamSelectedSeason, nexStreamEpisodesLoading, setNexStreamEpisodesLoading, nexStreamEpisodesError, setNexStreamEpisodesError, nexStreamEpisodesStatus, setNexStreamEpisodesStatus } = useNexStreamState();
  const { searchMetadata, setSearchMetadata, searchMetadataStatus, setSearchMetadataStatus, imdbRatingsByKey, setImdbRatingsByKey, imdbRatingRequestedRef, imdbRetryTick, setImdbRetryTick, imdbInFlightRef, imdbRetryCountRef, tvMetadataRequestedRef, searchAvailabilityByGroup, setSearchAvailabilityByGroup, selectedQualityByGroup, setSelectedQualityByGroup } = useSearchMetadataState();
  const { expandedSearchGroupKey, setExpandedSearchGroupKey, movieTorrentPreviewGroup, setMovieTorrentPreviewGroup, movieTorrentPreviewCatalogueId, setMovieTorrentPreviewCatalogueId, pendingPosterAction, setPendingPosterAction, movieTorrentPreviewPosterUrl, setMovieTorrentPreviewPosterUrl, cataloguePosterUrlsRef, searchPosterUrlsRef, movieTorrentPickerGroups, setMovieTorrentPickerGroups, movieTorrentSearchLoading, setMovieTorrentSearchLoading, movieTorrentSearchTitle, setMovieTorrentSearchTitle, movieTorrentSearchError, setMovieTorrentSearchError, selectedMovieTorrentQualityByGroup, setSelectedMovieTorrentQualityByGroup, movieTorrentSearchControllerRef, movieTorrentSearchGenerationRef, prepareClickIntentRef, prepareTraceIdRef, movieTorrentDetailsCacheRef } = useMoviePreviewState();
  const { persistMovieTorrentCache } = useMovieTorrentCache({ movieTorrentDetailsCacheRef });

  const { isSearching, setIsSearching, isPresetCatalogueAction, setIsPresetCatalogueAction, searched, setSearched, error, setError, catalogueBuildProgress, setCatalogueBuildProgress, movieCatalogue, setMovieCatalogue, movieCatalogueSearchText, setMovieCatalogueSearchText, releasedOnly, tmdbFranchiseKey, setTmdbFranchiseKey, openCachedLanguageMenu, setOpenCachedLanguageMenu, activeTopSection, setActiveTopSection, dcContentTab, setDcContentTab, regionalContentTabs, setRegionalContentTabs, marvelContentTab, setMarvelContentTab, classicsContentTab, setClassicsContentTab, classicsSort, setClassicsSort, catalogueSort, setCatalogueSort, activeFranchiseSearchMode, setActiveFranchiseSearchMode, franchisePageRequestRef, franchisePageGenerationRef, franchiseLoadedPagesRef, franchiseGridPage, setFranchiseGridPage, prepareBuildPendingRef, previousPosterPageRef, posterFirstPageReady, setPosterFirstPageReady, posterFirstPageReadyRef, catalogueExpectedTitles, setCatalogueExpectedTitles, franchiseGridPageSize, openRegionalCatalogueMenu, setOpenRegionalCatalogueMenu, regionalCatalogueModes, setRegionalCatalogueModes, openRegionalTvMenu, setOpenRegionalTvMenu, regionalTvModes, setRegionalTvModes, isClearingTmdbCache, setIsClearingTmdbCache, tmdbCacheMessage, setTmdbCacheMessage, streamingOnly, ottAvailability, setOttAvailability, ottAvailabilityRef, ottQueueRef, ottQueuedIdsRef, ottLookupGenerationRef, ottLiveCheckedRef, ottRetryAttemptsRef, queueOttLookups, ottAvailabilityForMovie, marvelFilmFilter, setMarvelFilmFilter, isMarvelEnglishResults, setIsMarvelEnglishResults, showMarvelWebSeries, setShowMarvelWebSeries, isDcLiveActionEnglishResults, setIsDcLiveActionEnglishResults } = useCatalogueNavigationState();
  useEffect(() => persistSearchMetadata(searchMetadata), [searchMetadata]);
  useEffect(() => persistSearchAvailability(searchAvailabilityByGroup), [searchAvailabilityByGroup]);
  useEffect(() => persistImdbRatings(imdbRatingsByKey), [imdbRatingsByKey]);
  const renderFranchisePagination = (total: number) => total > franchiseGridPageSize ? <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900 px-3 py-2"><button type="button" disabled={franchiseGridPage <= 1} onClick={() => navigateFranchisePage(Math.max(1, franchiseGridPage - 1))} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-200 disabled:opacity-40">← Previous</button><span className="text-xs text-slate-400">Page {franchiseGridPage} of {Math.max(1, Math.ceil(total / franchiseGridPageSize))} · {total} titles</span><button type="button" disabled={franchiseGridPage >= Math.ceil(total / franchiseGridPageSize)} onClick={() => navigateFranchisePage(Math.min(Math.ceil(total / franchiseGridPageSize), franchiseGridPage + 1))} className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-40">Next →</button></div> : null;
  const { regionalWebSeriesCatalogue, setRegionalWebSeriesCatalogue, regionalWebSeriesLoading, setRegionalWebSeriesLoading, regionalWebSeriesError, setRegionalWebSeriesError, showDcWebSeries, setShowDcWebSeries, dcWebSeriesCatalogue, setDcWebSeriesCatalogue, dcWebSeriesLoading, setDcWebSeriesLoading, dcWebSeriesError, setDcWebSeriesError, dcWebSeriesRequestGenerationRef, marvelWebSeriesCatalogue, setMarvelWebSeriesCatalogue, marvelWebSeriesLoading, setMarvelWebSeriesLoading, marvelWebSeriesError, setMarvelWebSeriesError } = useWebSeriesState();
  // Keep meaningful Search-panel screens in the native browser history. The
  // snapshot contains navigation state only; catalogue/search caches remain in
  // React memory, so Back restores the exact view without repeating API calls.
  const restoringNavigationRef = useRef(false);
  const previousPlayerRef = useRef(false);
  const navigationSnapshot = {
    activeTopSection,
    movieCatalogue,
    results,
    searched,
    regionalWebSeriesCatalogue,
    dcWebSeriesCatalogue,
    marvelWebSeriesCatalogue,
    dcContentTab,
    regionalContentTabs,
    marvelContentTab,
    classicsContentTab,
    activeFranchiseSearchMode,
    showMarvelWebSeries,
    showDcWebSeries,
    regionalCatalogueModes,
    regionalTvModes,
    franchiseGridPage,
    expandedSearchGroupKey,
    nexStreamEpisodePicker,
    nexStreamPlayer,
    nexStreamSelectedSeason,
    nexStreamSeasons,
    nexStreamEpisodes,
    nexStreamEpisodesError,
    nexStreamEpisodesStatus,
    yenimeEpisodePicker: yenime.yenimeEpisodePicker,
    yenimePlayer: yenime.yenimePlayer,
    yenimeSelectedSeason: yenime.yenimeSelectedSeason,
    yenimeSeasons: yenime.yenimeSeasons,
    yenimeEpisodes: yenime.yenimeEpisodes,
    yenimeEpisodesError: yenime.yenimeEpisodesError,
    yenimeEpisodesStatus: yenime.yenimeEpisodesStatus,
  };
  useEffect(() => {
    const hasPlayer = Boolean(nexStreamPlayer || yenime.yenimePlayer);
    const hadPlayer = previousPlayerRef.current;
    previousPlayerRef.current = hasPlayer;
    if (hadPlayer && !hasPlayer && !restoringNavigationRef.current) {
      // Closing playback returns to the picker/section entry already in the
      // stack, rather than adding a new entry that would reopen the player.
      window.history.back();
      return;
    }
    const current = window.history.state || {};
    if (current.tab && current.tab !== 'search') return;
    if (!current.torrentStudio) {
      window.history.replaceState({ ...current, torrentStudio: true, tab: current.tab || 'search', searchView: navigationSnapshot }, '', window.location.href);
    } else if (!current.searchView) {
      window.history.replaceState({ ...current, tab: current.tab || 'search', searchView: navigationSnapshot }, '', window.location.href);
    } else if (restoringNavigationRef.current) {
      restoringNavigationRef.current = false;
      window.history.replaceState({ ...current, tab: current.tab || 'search', searchView: navigationSnapshot }, '', window.location.href);
    } else {
      window.history.pushState({ ...current, torrentStudio: true, tab: 'search', searchView: navigationSnapshot }, '', window.location.href);
    }
  }, [
    activeTopSection, movieCatalogue, results, searched,
    regionalWebSeriesCatalogue, dcWebSeriesCatalogue, marvelWebSeriesCatalogue,
    dcContentTab, regionalContentTabs, marvelContentTab,
    classicsContentTab, activeFranchiseSearchMode, showMarvelWebSeries,
    showDcWebSeries, regionalCatalogueModes, regionalTvModes,
    franchiseGridPage, expandedSearchGroupKey,
    nexStreamEpisodePicker, nexStreamPlayer, nexStreamSelectedSeason,
    yenime.yenimeEpisodePicker, yenime.yenimePlayer, yenime.yenimeSelectedSeason,
  ]);
  useEffect(() => {
    const restore = (event: PopStateEvent) => {
      const view = event.state?.torrentStudio ? event.state.searchView : null;
      if (!view) return;
      restoringNavigationRef.current = true;
      previousPlayerRef.current = false;
      setActiveTopSection(view.activeTopSection ?? null);
      setMovieCatalogue(view.movieCatalogue ?? null);
      setResults(view.results ?? []);
      setSearched(view.searched ?? false);
      setRegionalWebSeriesCatalogue(view.regionalWebSeriesCatalogue ?? null);
      setDcWebSeriesCatalogue(view.dcWebSeriesCatalogue ?? null);
      setMarvelWebSeriesCatalogue(view.marvelWebSeriesCatalogue ?? null);
      setDcContentTab(view.dcContentTab ?? 'movies');
      setRegionalContentTabs(view.regionalContentTabs ?? { bollywood: null, hollywood: null, korean: null, pakistani: null, anime: null });
      setMarvelContentTab(view.marvelContentTab ?? null);
      setClassicsContentTab(view.classicsContentTab ?? 'movies');
      setActiveFranchiseSearchMode(view.activeFranchiseSearchMode ?? null);
      setShowMarvelWebSeries(view.showMarvelWebSeries ?? false);
      setShowDcWebSeries(view.showDcWebSeries ?? false);
      setRegionalCatalogueModes(view.regionalCatalogueModes ?? regionalCatalogueModes);
      setRegionalTvModes(view.regionalTvModes ?? regionalTvModes);
      setFranchiseGridPage(view.franchiseGridPage ?? 1);
      setExpandedSearchGroupKey(view.expandedSearchGroupKey ?? null);
      setNexStreamEpisodePicker(view.nexStreamEpisodePicker ?? null);
      setNexStreamPlayer(view.nexStreamPlayer ?? null);
      setNexStreamSelectedSeason(view.nexStreamSelectedSeason ?? 1);
      setNexStreamSeasons(view.nexStreamSeasons ?? []);
      setNexStreamEpisodes(view.nexStreamEpisodes ?? []);
      setNexStreamEpisodesError(view.nexStreamEpisodesError ?? '');
      setNexStreamEpisodesStatus(view.nexStreamEpisodesStatus ?? null);
      yenime.setYenimeEpisodePicker(view.yenimeEpisodePicker ?? null);
      yenime.setYenimePlayer(view.yenimePlayer ?? null);
      yenime.setYenimeSelectedSeason(view.yenimeSelectedSeason ?? 1);
      yenime.setYenimeSeasons(view.yenimeSeasons ?? []);
      yenime.setYenimeEpisodes(view.yenimeEpisodes ?? []);
      yenime.setYenimeEpisodesError(view.yenimeEpisodesError ?? '');
      yenime.setYenimeEpisodesStatus(view.yenimeEpisodesStatus ?? null);
    };
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => {
    if (!openCachedLanguageMenu) return;

    const handleOutsidePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && !target.closest('[data-cached-language-menu="true"]')) {
        setOpenCachedLanguageMenu(null);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenCachedLanguageMenu(null);
    };

    document.addEventListener('pointerdown', handleOutsidePointerDown);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('pointerdown', handleOutsidePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [openCachedLanguageMenu]);
  useEffect(() => {
    if (!openRegionalCatalogueMenu) return;
    const handleOutsidePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && !target.closest('[data-regional-catalogue-menu="true"]')) {
        setOpenRegionalCatalogueMenu(null);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenRegionalCatalogueMenu(null);
    };
    document.addEventListener('pointerdown', handleOutsidePointerDown);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('pointerdown', handleOutsidePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [openRegionalCatalogueMenu]);
  useEffect(() => {
    if (!openRegionalTvMenu) return;
    const handleOutsidePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && !target.closest('[data-regional-tv-menu="true"]')) {
        setOpenRegionalTvMenu(null);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenRegionalTvMenu(null);
    };
    document.addEventListener('pointerdown', handleOutsidePointerDown);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('pointerdown', handleOutsidePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [openRegionalTvMenu]);
  const openRegionalTvCatalogue = async (group: RegionalTvGroup, mode: RegionalTvMode, page = 1, resetSort = true) => {
    const key = group + '-' + mode;
    if (resetSort) setCatalogueSort('popularity');
    setRegionalTvModes(previous => ({ ...previous, [group]: mode }));
    setOpenRegionalTvMenu(null);
    setShowMarvelWebSeries(false);
    setShowDcWebSeries(false);
    setRegionalWebSeriesCatalogue(null);
    setRegionalWebSeriesError('');
    setRegionalWebSeriesLoading(true);
    setMovieCatalogue(null);
    setResults([]);
    setSearched(false);
    setIsSearching(false);
    setShowRecentSearches(false);
    // A newer section action bumps this counter, so a late answer cannot reappear after switching away.
    const generation = ++searchGenerationRef.current;
    searchRequestRef.current?.abort();
    try {
      const cataloguePage = await tvCataloguePageFromSectionCache(
        section => api.getSectionCache(section),
        key,
        page,
      ) || await api.getTvCatalogue(key, page);
      if (!cataloguePage) throw new Error('The requested TV subsection is missing from its section cache.');
      if (generation === searchGenerationRef.current) setRegionalWebSeriesCatalogue(cataloguePage);
    } catch (error: any) {
      if (generation === searchGenerationRef.current) setRegionalWebSeriesError(String(error?.message || 'Could not load web series.'));
    } finally {
      setRegionalWebSeriesLoading(false);
    }
  };
  const openRegionalCatalogue = (group: RegionalCatalogueGroup, mode: RegionalCatalogueMode) => {
    setCatalogueSort('popularity');
    setRegionalWebSeriesCatalogue(null);
    setRegionalWebSeriesError('');
    setRegionalWebSeriesLoading(false);
    setShowMarvelWebSeries(false);
    setShowDcWebSeries(false);
    const key = (mode + '-' + group) as MovieCatalogueKey;
    const label = (mode.charAt(0).toUpperCase() + mode.slice(1)) + ' ' + ({ bollywood: 'Bollywood', hollywood: 'Hollywood', korean: 'Korean', pakistani: 'Pakistani', anime: 'Anime' } as Record<RegionalCatalogueGroup, string>)[group];
    setRegionalCatalogueModes(previous => ({ ...previous, [group]: mode }));
    setOpenRegionalCatalogueMenu(null);
    setResolutionFilter(null);
    setSizeSort(null);
    setTimeSort(null);
    void openMovieCatalogue(key, label, 1);
  };
  const selectHighestRatedSection = () => {
    setActiveTopSection('highest-rated');
    setFranchiseGridPage(1);
    setCatalogueSort('popularity');
    // Load the curated TV catalogue immediately so Highest Rated is never an
    // empty panel after the top-level section is selected. The Hollywood and
    // Bollywood buttons remain available to switch to their movie catalogues.
    void openRegionalTvCatalogue('highest-rated', 'popular', 1);
  };
  const tmdbFranchiseLabels: Record<FranchiseTmdbKey, string> = {
    marvel: 'Marvel',
    'dc-live-action': 'DC',
    'dc-animated': 'DC Animated',
  };
  const { visibleMovieCatalogueItems, ottPendingCount } = useVisibleMovieCatalogue({ movieCatalogue, isMarvelEnglishResults, showMarvelWebSeries, marvelFilmFilter, isDcLiveActionEnglishResults, streamingOnly, ottAvailabilityForMovie, ottAvailability });
  const { preparingTorrentKey, setPreparingTorrentKey, playingTorrentKey, setPlayingTorrentKey, copiedTorrentKey, setCopiedTorrentKey, prepareWaitTitle, setPrepareWaitTitle, prepareWaitOpen, setPrepareWaitOpen, prepareError, setPrepareError, setFullTorrentTitle, setFullTorrentTitleKey, setFullTorrentTitleFading, fullTorrentTitleFadeTimerRef, fullTorrentTitleHideTimerRef, preparedByKeyRef } = usePrepareState();
  const { posterOverrides, setPosterOverrides, metadataPosterFailed, setMetadataPosterFailed, posterTitleCacheLoadedRef, posterLoadedRef, posterMetadataFailedRef, posterBackgroundQueueRef, posterBackgroundQueuedRef, posterBackgroundActiveRef, posterBackgroundActiveKeysRef, posterBackgroundGenerationRef, posterBackgroundAttemptsRef, posterResolveCacheRef } = usePosterState();
  if (!posterTitleCacheLoadedRef.current) {
    readPosterTitleCache();
    posterTitleCacheLoadedRef.current = true;
  }
  useTorrentTitleBubble({ query, fullTorrentTitleFadeTimerRef, fullTorrentTitleHideTimerRef, setFullTorrentTitleKey, setFullTorrentTitle, setFullTorrentTitleFading });
  const { startPosterBackgroundWorkers, startPosterBackgroundSearch, enqueuePosterBackgroundJobs, posterUrlFor } = usePosterWorkers({ posterBackgroundGenerationRef, posterResolveCacheRef, posterBackgroundActiveRef, posterBackgroundQueueRef, posterBackgroundQueuedRef, posterBackgroundActiveKeysRef, posterLoadedRef, setPosterOverrides, posterBackgroundAttemptsRef, posterOverrides });
  const { preparedForResult, prepareMovieTorrent, prepareStateFor, preparedActionsFor } = usePrepareActions({ preparedByKeyRef, preparingTorrentKey, setPrepareError, setPreparingTorrentKey, setPrepareWaitTitle, setPrepareWaitOpen, playingTorrentKey, copiedTorrentKey, setPlayingTorrentKey, setCopiedTorrentKey, setMovieTorrentSearchError, metadataCacheRef, error, seedrFiles, seedrDeletedFolderIds, onPrepare, onPlaySeedrFile });
  const { recentSearches, setRecentSearches, saveRecentSearch } = useRecentSearches();
  useEffect(() => {
    if (!showRecentSearches) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && !recentSearchRef.current?.contains(target)) {
        setShowRecentSearches(false);
      }
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [showRecentSearches]);
  const { cancelSearch } = useCancelSearch({ searchGenerationRef, searchRequestRef, setShowRecentSearches, setResults, movieTorrentSearchGenerationRef, movieTorrentSearchControllerRef, nexStreamSearchGenerationRef, nexStreamSearchControllerRef, setNexStreamLoading, setNexStreamSearchMode, setNexStreamResults, setNexStreamError, setIsSearching, setCatalogueBuildProgress, setError, setMovieCatalogue, setSearched, setSearchAvailabilityByGroup });
  const { searchNexStreamTitles, loadNexStreamEpisodes, playWithNexStream, switchNexStreamProvider, playCatalogueTvWithNexStream } = useNexStreamFlow({ nexStreamSearchControllerRef, nexStreamSearchGenerationRef, setNexStreamSearchMode, setNexStreamLoadingTitle, setNexStreamLoading, setNexStreamError, setNexStreamResults, setNexStreamPlayer, setNexStreamEpisodePrefetchStatus, setNexStreamSeasons, setNexStreamEpisodes, setNexStreamSelectedSeason, setNexStreamEpisodesError, setNexStreamEpisodesStatus, setNexStreamEpisodesLoading, setNexStreamEpisodePicker, setNexStreamResolvingId, error });
  // Warm the episode metadata cache while the franchise TV catalogue is
  // open, so selecting a series usually opens with its season/episodes ready.
  useEffect(() => {
    const catalogue = showDcWebSeries ? dcWebSeriesCatalogue
      : showMarvelWebSeries ? marvelWebSeriesCatalogue
        : null;
    if (!catalogue?.results?.length) return;

    const items = catalogue.results
      .map(show => ({ id: Number(show.id), type: 'tv' as const }))
      .filter(item => Number.isInteger(item.id) && item.id > 0);
    if (!items.length) return;

    // Episode metadata is only fetched when the user opens a series card; prefetching
    // here competed with the initial cards and posters for the page.
    return;
  }, [
    showDcWebSeries,
    showMarvelWebSeries,
    dcWebSeriesCatalogue,
    marvelWebSeriesCatalogue,
  ]);
  const { runSearch: runSearchRaw } = useSearchRunner({
    setFranchiseGridPage, setActiveFranchiseSearchMode, franchisePageRequestRef,
    franchisePageGenerationRef, franchiseLoadedPagesRef, posterFirstPageReadyRef,
    setPosterFirstPageReady, setIsPresetCatalogueAction, setIsMarvelEnglishResults,
    setIsDcLiveActionEnglishResults, setShowMarvelWebSeries, setError, setSearched,
    setIsSearching, setCatalogueBuildProgress, setCatalogueExpectedTitles, setMovieCatalogue,
    franchiseGridPageSize, franchiseGridPage, setShowDcWebSeries, setMovieTorrentSearchError,
    setMovieTorrentPreviewCatalogueId, movieTorrentSearchControllerRef,
    movieTorrentSearchGenerationRef, setMovieTorrentSearchLoading, setMovieTorrentPickerGroups,
    setMovieTorrentPreviewGroup, setExpandedSearchGroupKey, query, setResults,
    searchGenerationRef, searchRequestRef, setShowRecentSearches, setQuery, setSearchMetadata,
    setSearchMetadataStatus, setImdbRatingsByKey, setSearchAvailabilityByGroup,
    setSelectedQualityByGroup, setPosterOverrides, posterMetadataFailedRef, posterLoadedRef,
    posterBackgroundQueueRef, posterBackgroundQueuedRef, posterBackgroundAttemptsRef,
    posterBackgroundGenerationRef, saveRecentSearch, searchNexStreamTitles,
    nexStreamSearchGenerationRef, nexStreamSearchControllerRef, setNexStreamLoading,
    setNexStreamSearchMode, setNexStreamResults, setNexStreamError, setNexStreamPlayer,
  });
  const { searchMovieTorrents, selectMovieTorrentGroup, closeMoviePrepareCard } = useMovieTorrentSearch({ prepareClickIntentRef, prepareTraceIdRef, setExpandedSearchGroupKey, movieTorrentSearchControllerRef, movieTorrentSearchGenerationRef, setMovieTorrentSearchTitle, setMovieTorrentPreviewCatalogueId, setMovieTorrentPreviewPosterUrl, cataloguePosterUrlsRef, setMovieTorrentSearchLoading, setMovieTorrentSearchError, setMovieTorrentPreviewGroup, setMovieTorrentPickerGroups, setSelectedMovieTorrentQualityByGroup, movieTorrentDetailsCacheRef, prepareBuildPendingRef, movieCatalogue, setSearched, error, setResults, setQuery, setSelectedQualityByGroup, startPosterBackgroundSearch, persistMovieTorrentCache });
  // Opening any Marvel/DC/Classics/search view must close a Hollywood/Bollywood web-series list, otherwise it
  // stays on screen and the new results appear below it.
  const runSearch: typeof runSearchRaw = (...args) => {
    setRegionalWebSeriesCatalogue(null);
    setRegionalWebSeriesError('');
    setRegionalWebSeriesLoading(false);
    return runSearchRaw(...args);
  };
  const { loadDcWebSeries, loadDcWebSeriesPage, loadClassicsTvCatalogue, loadMarvelWebSeries } = useWebSeriesLoaders({
    searchGenerationRef,
    dcWebSeriesRequestGenerationRef,
    searchRequestRef,
    franchisePageRequestRef,
    setShowDcWebSeries,
    setDcWebSeriesLoading,
    setDcWebSeriesError,
    setDcWebSeriesCatalogue,
    setShowMarvelWebSeries,
    setClassicsContentTab,
    marvelWebSeriesCatalogue,
    marvelWebSeriesLoading,
    setMarvelWebSeriesCatalogue,
    setMarvelWebSeriesLoading,
    setMarvelWebSeriesError,
    setIsSearching,
    setSearched,
    setError,
    setMovieCatalogue,
    setActiveFranchiseSearchMode,
    setFranchiseGridPage,
    setCatalogueExpectedTitles,
    setResults,
  });
  const openMovieCatalogue = async (
    key: MovieCatalogueKey,
    searchText: string,
    page = 1,
    onlyReleased = releasedOnly,
  ) => {
    setRegionalWebSeriesCatalogue(null);
    setRegionalWebSeriesError('');
    setRegionalWebSeriesLoading(false);
    setHighQualityPostersReady(false);
    setFranchiseGridPage(1);
    setActiveFranchiseSearchMode(null);
    franchisePageRequestRef.current?.abort();
    franchisePageRequestRef.current = null;
    franchisePageGenerationRef.current += 1;
    posterFirstPageReadyRef.current = false;
    setPosterFirstPageReady(false);
    movieTorrentSearchControllerRef.current?.abort();
    movieTorrentSearchGenerationRef.current += 1;
    setMovieTorrentSearchLoading(false);
    setMovieTorrentPickerGroups(null);
    setMovieTorrentPreviewGroup(null);
    setMovieTorrentPreviewCatalogueId(null);
    setMovieTorrentSearchError('');
    const generation = ++searchGenerationRef.current;
    searchRequestRef.current?.abort();
    const controller = new AbortController();
    searchRequestRef.current = controller;

    try {
      setIsPresetCatalogueAction(true);
      setIsSearching(true);
      setCatalogueBuildProgress('Loading the ' + searchText.replace(/Movies?$/i, '').trim() + ' movie catalogue…');
      setMovieCatalogueSearchText(searchText);
      setShowRecentSearches(false);
      setQuery('');
      setError('');
      setResults([]);
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

      const section = movieCatalogueSection(key);
      if (section) {
        const document = await api.getSectionCache(section.section);
        const data = movieCataloguePageFromSection(document, key, section.subsection, page);
        if (!data) throw new Error('The requested movie subsection is missing from its section cache.');
        if (generation !== searchGenerationRef.current) return;
        setMovieCatalogue(data);
        setCatalogueBuildProgress('');
        return;
      }

      // Regional catalogues (Hollywood/Bollywood) paint the stored rows first, exactly like the
      // Marvel/DC pages, and the enriched page replaces them a moment later.
      const isRegionalCatalogue = /^(popular|trending|latest)-(bollywood|hollywood|korean|pakistani|anime)$/.test(String(key));
      if (page > 3 || isRegionalCatalogue) {
        // Deep pages paint quickly with source metadata and lightweight posters.
        // The full eligibility/provider/details response replaces this in the background.
        const basic = await api.getMovieCatalogue(key, page, onlyReleased, controller.signal, 5, true);
        if (generation !== searchGenerationRef.current) return;
        const basicPage = {
          ...basic,
          results: (basic.results || []).map(movie => ({
            ...movie,
            posterUrl: lowQualityPosterUrl(movie.posterUrl || '', 'w185'),
          })),
        };
        setMovieCatalogue(basicPage);
        setCatalogueBuildProgress('');
        void api.getMovieCatalogue(key, page, onlyReleased, undefined, 5, false).then(fullPage => {
          if (generation !== searchGenerationRef.current) return;
          setMovieCatalogue(fullPage);
        }).catch(error => {
          if (generation === searchGenerationRef.current) {
            setError(String(error?.message || 'Could not load full catalogue details.'));
          }
        });
        return;
      }
      const data = await api.getMovieCatalogue(key, page, onlyReleased, controller.signal);
      if (generation !== searchGenerationRef.current) return;
      setMovieCatalogue(data);
      setCatalogueBuildProgress('');
    } catch (err: any) {
      if (generation !== searchGenerationRef.current) return;
      if (err?.name === 'AbortError') return;

      const message = String(err?.message || 'Movie catalogue failed.');
      setMovieCatalogue(null);
      setError(message);
    } finally {
      if (generation === searchGenerationRef.current) {
        setIsSearching(false);
        setCatalogueBuildProgress('');
        if (searchRequestRef.current === controller) {
          searchRequestRef.current = null;
        }
      }
    }
  };
  // background: used to fetch the other pages for a section-wide sort. It must never abort the page the
  // user asked for, touch the loading state, or bump the request generation (that made "Next" crawl).
  async function loadCachedFranchisePage(mode: CachedFranchiseSearchMode, page: number, background = false): Promise<void> {
    if (!background) {
      franchisePageRequestRef.current?.abort();
      franchisePageRequestRef.current = null;
      franchisePageGenerationRef.current += 1;
    }
    const loaded = franchiseLoadedPagesRef.current.get(mode);
    if (loaded?.has(page)) {
      if (!background) {
        setIsSearching(false);
        setCatalogueBuildProgress('');
      }
      return;
    }
    const sectionLocation = franchiseCatalogueSection(mode);
    const browserCachedPage = sectionLocation ? null : readFranchisePageCache(mode, page);
    if (browserCachedPage) {
      setResults(previous => {
        const byKey = new Map<string, TorrentSearchResult>();
        [...previous, ...browserCachedPage.results].forEach(row => {
          const key = torrentResultKey(row);
          if (!byKey.has(key)) byKey.set(key, row);
        });
        return Array.from(byKey.values());
      });
      const nowLoaded = loaded || new Set<number>();
      nowLoaded.add(page);
      franchiseLoadedPagesRef.current.set(mode, nowLoaded);
      if (browserCachedPage.totalMovies > 0) setCatalogueExpectedTitles(browserCachedPage.totalMovies);
      if (!background) {
        setSearched(true);
        setError('');
        setCatalogueBuildProgress('');
        setIsSearching(false);
      }
      return;
    }
    const controller = new AbortController();
    if (!background) franchisePageRequestRef.current = controller;
    const generation = background ? franchisePageGenerationRef.current : ++franchisePageGenerationRef.current;
    const isStale = () => controller.signal.aborted || (!background && generation !== franchisePageGenerationRef.current);
    if (!background) {
      setIsSearching(true);
      setError('');
      setCatalogueBuildProgress(`Loading page ${page} of the ${mode.replace(/-/g, ' ')} catalogue…`);
    }
    try {
      const sectionCache = await franchiseSectionDocumentFromCache(
        section => api.getSectionCache(section),
        mode,
      );
      if (sectionCache) {
        const { location: sectionLocation, document } = sectionCache;
        if (isStale()) return;
        const subsection = document.subsections[sectionLocation.subsection];
        const allResults = franchiseRowsFromSection(document, sectionLocation.subsection);
        if (!subsection || !allResults) {
          throw new Error('The requested subsection is missing from its section cache.');
        }
        const pageSize = Math.max(1, Number(subsection.pageSize) || franchiseGridPageSize);
        const pageRows = allResults.slice((page - 1) * pageSize, page * pageSize);
        setResults(previous => {
          const byKey = new Map<string, TorrentSearchResult>();
          [...previous, ...pageRows].forEach(row => {
            const key = torrentResultKey(row);
            if (!byKey.has(key)) byKey.set(key, row);
          });
          return Array.from(byKey.values());
        });
        const nowLoaded = franchiseLoadedPagesRef.current.get(mode) || new Set<number>();
        nowLoaded.add(page);
        franchiseLoadedPagesRef.current.set(mode, nowLoaded);
        const totalTitles = Number(subsection.totalResults) || allResults.length;
        if (totalTitles > 0) setCatalogueExpectedTitles(totalTitles);
        if (!background) {
          setSearched(true);
          setError('');
          setCatalogueBuildProgress('');
        }
        return;
      }

      const fetchPage = () => mode === 'marvel'
        ? api.getMarvelCatalogue(controller.signal, { page, pageSize: franchiseGridPageSize })
        : api.getCatalogue(mode, controller.signal, { page, pageSize: franchiseGridPageSize });
      let catalogue = await fetchPage();
      let attempts = 0;
      while ((catalogue.status === 'building' || catalogue.status === 'idle') && attempts < 8) {
        if (isStale()) return;
        if (!background) setCatalogueBuildProgress(
          'Building shared ' + mode.replace(/-/g, ' ') + ' catalogue: ' +
          catalogue.completed + ' of ' + catalogue.total + ' searches completed.'
        );
        await new Promise<void>(resolve => window.setTimeout(resolve, 2200));
        attempts += 1;
        catalogue = await fetchPage();
      }
      if (isStale()) return;
      if (catalogue.status !== 'ready' || !Array.isArray(catalogue.results)) {
        throw new Error(catalogue.error || ('Could not load page ' + page + ' of the catalogue.'));
      }
      const pageRows = catalogue.results;
      setResults(previous => {
        const byKey = new Map<string, TorrentSearchResult>();
        [...previous, ...pageRows].forEach(row => {
          const key = torrentResultKey(row);
          if (!byKey.has(key)) byKey.set(key, row);
        });
        return Array.from(byKey.values());
      });
      const nowLoaded = franchiseLoadedPagesRef.current.get(mode) || new Set<number>();
      nowLoaded.add(page);
      franchiseLoadedPagesRef.current.set(mode, nowLoaded);
      const totalTitles = Number(catalogue.totalMovies) || Number(catalogue.total) || 0;
      const totalPages = Number(catalogue.totalPages) || Math.max(1, Math.ceil(totalTitles / franchiseGridPageSize));
      writeFranchisePageCache(mode, page, pageRows, totalTitles, totalPages);
      if (totalTitles > 0) setCatalogueExpectedTitles(totalTitles);
      if (!background) {
        setSearched(true);
        setCatalogueBuildProgress(
          catalogue.refreshing
            ? 'Showing cached catalogue results; a refreshed page will appear on a later visit.'
            : ''
        );
      }
    } catch (error: any) {
      if (background || isStale()) return;
      setError(String(error?.message || 'Could not load this catalogue page.'));
      setCatalogueBuildProgress('');
    } finally {
      if (!background && generation === franchisePageGenerationRef.current) {
        setIsSearching(false);
        if (franchisePageRequestRef.current === controller) franchisePageRequestRef.current = null;
      }
    }
  }
  function navigateFranchisePage(page: number): void {
    setHighQualityPostersReady(false);
    setFranchiseGridPage(page);
    if (activeFranchiseSearchMode) void loadCachedFranchisePage(activeFranchiseSearchMode, page);
  }
  // Rating sort: pull every stored IMDb rating in one request (the VPS refresh keeps them current),
  // so sorting does not wait for per-title lookups page by page.
  const storedRatingsLoadedRef = useRef(false);
  useEffect(() => {
    if (
      classicsSort.key !== 'rating' ||
      storedRatingsLoadedRef.current ||
      (activeFranchiseSearchMode && franchiseCatalogueSection(activeFranchiseSearchMode))
    ) return;
    storedRatingsLoadedRef.current = true;
    void fetch('/api/catalogue/imdb-ratings/stored', { headers: { Accept: 'application/json' } })
      .then(response => (response.ok ? response.json() : null))
      .then(data => {
        const rows: any[] = Array.isArray(data?.results) ? data.results : [];
        if (!rows.length) { storedRatingsLoadedRef.current = false; return; }
        setImdbRatingsByKey(previous => {
          const next = { ...previous };
          for (const rating of rows) {
            const key = imdbRatingKey(rating.title, rating.year, rating.mediaType === 'tv' ? 'tv' : 'movie');
            if (!next[key]) next[key] = rating;
          }
          return next;
        });
      })
      .catch(() => { storedRatingsLoadedRef.current = false; });
  }, [classicsSort.key, activeFranchiseSearchMode]);
  const { sortedResults, groupedResults } = useGroupedResults({ results, resolutionFilter, sizeSort, timeSort, isMarvelEnglishResults, showMarvelWebSeries, marvelFilmFilter, activeFranchiseSearchMode, classicsSort, imdbRatingsByKey: activeFranchiseSearchMode && classicsSort.key === 'rating' ? imdbRatingsByKey : NO_RATINGS });
  useFranchisePageEffect({ activeFranchiseSearchMode, franchiseGridPage, franchiseGridPageSize, error, groupedResults, searchAvailabilityByGroup, setSearchAvailabilityByGroup });
  useSynopsisPrefetch({ franchiseGridPage, franchiseGridPageSize, groupedResults, searchMetadata, setSearchMetadata, tvMetadataRequestedRef, activeFranchiseSearchMode });
  usePosterEffects({ groupedResults, franchiseGridPage, franchiseGridPageSize, posterFirstPageReadyRef, setPosterFirstPageReady, previousPosterPageRef, movieCatalogue, posterFirstPageReady, queueOttLookups, activeFranchiseSearchMode, posterBackgroundGenerationRef, posterBackgroundQueueRef, posterBackgroundQueuedRef, posterBackgroundAttemptsRef, posterBackgroundActiveKeysRef, enqueuePosterBackgroundJobs, pendingPosterAction, setPendingPosterAction, prepareClickIntentRef, prepareTraceIdRef, setExpandedSearchGroupKey, searchMovieTorrents });
  usePosterReadyGate({ posterFirstPageReady, activeFranchiseSearchMode, imdbInFlightRef });
  // Sorting the Classics by rating or oldest-first needs every page, not just the visible one:
  // fetch the remaining cached pages one after another (cheap, they are stored files).
  useEffect(() => {
    if (!activeFranchiseSearchMode || isDefaultClassicsSort(classicsSort)) return;
    const totalPages = Math.ceil(catalogueExpectedTitles / franchiseGridPageSize);
    if (totalPages <= 1) return;
    let cancelled = false;
    void (async () => {
      for (let page = 1; page <= totalPages && !cancelled; page += 1) {
        await loadCachedFranchisePage(activeFranchiseSearchMode, page, true);
      }
    })();
    return () => { cancelled = true; };
  }, [activeFranchiseSearchMode, classicsSort.key, classicsSort.direction, catalogueExpectedTitles]);
  // Every web series / anime row currently loaded, so their cards can show an IMDb rating too.
  const tvItemsForImdb = useMemo(() => {
    const fromCatalogue = [regionalWebSeriesCatalogue, dcWebSeriesCatalogue, marvelWebSeriesCatalogue]
      .flatMap(catalogue => catalogue?.results || [])
      .map(show => ({
        title: show.title,
        year: show.year,
        tmdbId: Number(show.id) || undefined,
        imdbRating: show.imdbRating,
        imdbRatingStatus: show.imdbRatingStatus,
        sectionCacheRecord: show.sectionCacheRecord,
      }));
    const fromNexStream = (nexStreamResults || [])
      .map((item: any) => ({ title: item.title, year: item.date ? String(item.date).slice(0, 4) : null }));
    return [...fromCatalogue, ...fromNexStream].filter(item => item.title);
  }, [regionalWebSeriesCatalogue, dcWebSeriesCatalogue, marvelWebSeriesCatalogue, nexStreamResults]);
  useCatalogueDetailsPrefetch({
    rateAllGroups: Boolean(activeFranchiseSearchMode) && classicsSort.key === 'rating',
    selfContainedSectionMetadata: Boolean(
      movieCatalogue?.curatedOrder ||
      regionalWebSeriesCatalogue?.curatedOrder ||
      (activeFranchiseSearchMode && franchiseCatalogueSection(activeFranchiseSearchMode))
    ),
    activeFranchiseSearchMode,
    tvItems: tvItemsForImdb,
    franchiseGridPage,
    franchiseGridPageSize,
    movieCatalogue,
    groupedResults,
    searchMetadata,
    imdbRatingsByKey,
    imdbRatingRequestedRef,
    imdbRetryCountRef,
    setImdbRetryTick,
    imdbInFlightRef,
    setImdbRatingsByKey,
    imdbRetryTick,
    visibleMovieCatalogueItems,
  });
  const clearTmdbCacheAndReload = async () => {
    const currentCatalogue = movieCatalogue;
    const key = currentCatalogue?.catalogue || tmdbFranchiseKey;
    const searchText = currentCatalogue ? movieCatalogueSearchText : tmdbFranchiseLabels[tmdbFranchiseKey];
    const page = currentCatalogue?.page || 1;
    const onlyReleased = currentCatalogue?.releasedOnly ?? releasedOnly;

    setIsClearingTmdbCache(true);
    setTmdbCacheMessage('');
    try {
      await api.clearTmdbMovieCaches();
      ottLookupGenerationRef.current += 1;
      ottQueueRef.current = [];
      ottQueuedIdsRef.current.clear();
      ottLiveCheckedRef.current.clear();
      ottRetryAttemptsRef.current.clear();
      ottAvailabilityRef.current = {};
      setOttAvailability({});
      setTmdbCacheMessage('TMDB catalogue and OTT caches cleared. Reloading the selected catalogue…');
      await openMovieCatalogue(key, searchText, page, onlyReleased);
      setTmdbCacheMessage('TMDB caches cleared and a fresh catalogue request was sent.');
    } catch (error: any) {
      setTmdbCacheMessage(String(error?.message || 'Could not clear TMDB caches.'));
    } finally {
      setIsClearingTmdbCache(false);
    }
  };
  const selectCachedFranchise = (franchise: CachedFranchiseKey) => {
    setOpenCachedLanguageMenu(null);
    setResolutionFilter(null);
    setSizeSort(null);
    setTimeSort(null);
    setTmdbFranchiseKey(franchise);
    const mode = franchise === 'marvel' ? 'marvel' : 'dc-live-action';
    const category = franchise === 'marvel' ? 'Marvel' : 'DC';
    void runSearch(undefined, category, mode);
  };
  // A prepared movie is an inline view, not persistent catalogue selection.
  // Clear it before changing sections, subsections, filters or numbered pages;
  // cancel any stale lookup so its late result cannot reopen the old card.
  useLayoutEffect(() => {
    prepareClickIntentRef.current = false;
    prepareTraceIdRef.current = null;
    prepareBuildPendingRef.current = false;
    setExpandedSearchGroupKey(null);
    movieTorrentSearchControllerRef.current?.abort();
    movieTorrentSearchControllerRef.current = null;
    movieTorrentSearchGenerationRef.current += 1;
    setMovieTorrentSearchLoading(false);
    setMovieTorrentPickerGroups(null);
    setMovieTorrentPreviewGroup(null);
    setMovieTorrentPreviewCatalogueId(null);
    setMovieTorrentSearchError('');
  }, [
    activeTopSection,
    marvelContentTab,
    dcContentTab,
    classicsContentTab,
    regionalContentTabs,
    regionalCatalogueModes,
    franchiseGridPage,
    marvelFilmFilter,
    showMarvelWebSeries,
    showDcWebSeries,
  ]);

  return {
    onPlaySeedrFile,
    onOpenProgress,
    onCancelPrepare,
    query,
    setQuery,
    results,
    setResults,
    setResolutionFilter,
    setSizeSort,
    setTimeSort,
    showRecentSearches,
    setShowRecentSearches,
    recentSearchRef,
    nexStreamResults,
    nexStreamSearchMode,
    setNexStreamSearchMode,
    nexStreamLoading,
    nexStreamLoadingTitle,
    nexStreamEpisodePrefetchStatus,
    nexStreamError,
    setNexStreamError,
    nexStreamPlayer,
    setNexStreamPlayer,
    nexStreamResolvingId,
    nexStreamEpisodePicker,
    setNexStreamEpisodePicker,
    nexStreamSeasons,
    nexStreamEpisodes,
    nexStreamSelectedSeason,
    nexStreamEpisodesLoading,
    nexStreamEpisodesError,
    nexStreamEpisodesStatus,
    searchMetadata,
    searchMetadataStatus,
    imdbRatingsByKey,
    searchAvailabilityByGroup,
    selectedQualityByGroup,
    setSelectedQualityByGroup,
    expandedSearchGroupKey,
    setExpandedSearchGroupKey,
    movieTorrentPreviewGroup,
    setMovieTorrentPreviewGroup,
    movieTorrentPreviewCatalogueId,
    setMovieTorrentPreviewCatalogueId,
    pendingPosterAction,
    setPendingPosterAction,
    movieTorrentPreviewPosterUrl,
    cataloguePosterUrlsRef,
    searchPosterUrlsRef,
    movieTorrentPickerGroups,
    setMovieTorrentPickerGroups,
    movieTorrentSearchLoading,
    movieTorrentSearchTitle,
    movieTorrentSearchError,
    setMovieTorrentSearchError,
    selectedMovieTorrentQualityByGroup,
    setSelectedMovieTorrentQualityByGroup,
    prepareClickIntentRef,
    prepareTraceIdRef,
    isSearching,
    isPresetCatalogueAction,
    searched,
    setSearched,
    error,
    setError,
    catalogueBuildProgress,
    movieCatalogue,
    setMovieCatalogue,
    movieCatalogueSearchText,
    tmdbFranchiseKey,
    setTmdbFranchiseKey,
    activeTopSection,
    setActiveTopSection,
    dcContentTab,
    setDcContentTab,
    regionalContentTabs,
    setRegionalContentTabs,
    marvelContentTab,
    setMarvelContentTab,
    classicsContentTab,
    setClassicsContentTab,
    classicsSort,
    setClassicsSort,
    catalogueSort,
    setCatalogueSort,
    franchiseGridPage,
    setFranchiseGridPage,
    prepareBuildPendingRef,
    posterFirstPageReadyRef,
    catalogueExpectedTitles,
    franchiseGridPageSize,
    regionalCatalogueModes,
    regionalTvModes,
    isClearingTmdbCache,
    tmdbCacheMessage,
    streamingOnly,
    ottAvailabilityForMovie,
    marvelFilmFilter,
    setMarvelFilmFilter,
    showMarvelWebSeries,
    setShowMarvelWebSeries,
    renderFranchisePagination,
    regionalWebSeriesCatalogue,
    setRegionalWebSeriesCatalogue,
    regionalWebSeriesLoading,
    setRegionalWebSeriesLoading,
    regionalWebSeriesError,
    setRegionalWebSeriesError,
    showDcWebSeries,
    setShowDcWebSeries,
    dcWebSeriesCatalogue,
    setDcWebSeriesCatalogue,
    dcWebSeriesLoading,
    setDcWebSeriesLoading,
    dcWebSeriesError,
    setDcWebSeriesError,
    marvelWebSeriesCatalogue,
    setMarvelWebSeriesCatalogue,
    marvelWebSeriesLoading,
    setMarvelWebSeriesLoading,
    marvelWebSeriesError,
    setMarvelWebSeriesError,
    openRegionalTvCatalogue,
    openRegionalCatalogue,
    selectHighestRatedSection,
    tmdbFranchiseLabels,
    visibleMovieCatalogueItems,
    ottPendingCount,
    preparingTorrentKey,
    playingTorrentKey,
    setPlayingTorrentKey,
    prepareWaitTitle,
    prepareWaitOpen,
    setPrepareWaitOpen,
    prepareError,
    setPrepareError,
    posterOverrides,
    metadataPosterFailed,
    setMetadataPosterFailed,
    posterLoadedRef,
    posterBackgroundQueueRef,
    posterBackgroundQueuedRef,
    startPosterBackgroundWorkers,
    posterUrlFor,
    preparedForResult,
    prepareMovieTorrent,
    prepareStateFor,
    preparedActionsFor,
    recentSearches,
    setRecentSearches,
    cancelSearch,
    searchNexStreamTitles,
    ...yenime,
    loadNexStreamEpisodes,
    playWithNexStream,
    switchNexStreamProvider,
    playCatalogueTvWithNexStream,
    runSearch,
    searchMovieTorrents,
    selectMovieTorrentGroup,
    closeMoviePrepareCard,
    loadDcWebSeries,
    loadDcWebSeriesPage,
    loadClassicsTvCatalogue,
    loadMarvelWebSeries,
    openMovieCatalogue,
    sortedResults,
    groupedResults,
    clearTmdbCacheAndReload,
    selectCachedFranchise,
  };
}

export type PanelModel = ReturnType<typeof useTorrentSearchPanel>;
