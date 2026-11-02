import { useRef, useState } from 'react';
import { MovieCataloguePage } from '../../../api/client.ts';
import { CachedFranchiseSearchMode } from '../persistentCaches.ts';
import { ActiveTopSection, CachedFranchiseKey, ClassicsContentTab, FranchiseTmdbKey, MainCatalogueMenu, MarvelFilmFilter, RegionalCatalogueGroup, RegionalCatalogueMode, RegionalContentTab, RegionalTvGroup, RegionalTvMode } from '../types.ts';
import { useOttAvailability } from '../useOttAvailability.ts';
import { ClassicsSort, DEFAULT_CLASSICS_SORT } from '../classicsSort.ts';

export function useCatalogueNavigationState() {
  const [isSearching, setIsSearching] = useState(false);
  const [isPresetCatalogueAction, setIsPresetCatalogueAction] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState('');
  const [catalogueBuildProgress, setCatalogueBuildProgress] = useState('');
  const [movieCatalogue, setMovieCatalogue] = useState<MovieCataloguePage | null>(null);
  const [movieCatalogueSearchText, setMovieCatalogueSearchText] = useState('');
  const [releasedOnly, setReleasedOnly] = useState(true);
  const [tmdbFranchiseKey, setTmdbFranchiseKey] = useState<FranchiseTmdbKey>('marvel');
  const [openCachedLanguageMenu, setOpenCachedLanguageMenu] = useState<CachedFranchiseKey | null>(null);
  const [openMainCatalogueMenu, setOpenMainCatalogueMenu] = useState<MainCatalogueMenu | null>(null);
  const [activeTopSection, setActiveTopSection] = useState<ActiveTopSection>(null);
  const [dcContentTab, setDcContentTab] = useState<'movies' | 'animated' | 'web-series'>('movies');
  const [regionalContentTabs, setRegionalContentTabs] = useState<Record<RegionalCatalogueGroup, RegionalContentTab>>({ bollywood: null, hollywood: null, korean: null, pakistani: null, anime: null });
  const [marvelContentTab, setMarvelContentTab] = useState<RegionalContentTab>(null);
  const [classicsContentTab, setClassicsContentTab] = useState<ClassicsContentTab>('movies');
  const [classicsSort, setClassicsSort] = useState<ClassicsSort>(DEFAULT_CLASSICS_SORT);
  const [catalogueSort, setCatalogueSort] = useState<'popularity' | 'year' | 'rating'>('popularity');
  const [activeFranchiseSearchMode, setActiveFranchiseSearchMode] = useState<CachedFranchiseSearchMode | null>(null);
  const franchisePageRequestRef = useRef<AbortController | null>(null);
  const franchisePageGenerationRef = useRef(0);
  const franchiseLoadedPagesRef = useRef(new Map<CachedFranchiseSearchMode, Set<number>>());
  const [franchiseGridPage, setFranchiseGridPage] = useState(1);
  // Hold explicit Prepare clicks until the visible catalogue posters settle.
  const prepareBuildPendingRef = useRef(false);
  const previousPosterPageRef = useRef(1);
  const [posterFirstPageReady, setPosterFirstPageReady] = useState(false);
  const posterFirstPageReadyRef = useRef(false);
  const [catalogueExpectedTitles, setCatalogueExpectedTitles] = useState(0);
  const franchiseGridPageSize = 18;
  const [openRegionalCatalogueMenu, setOpenRegionalCatalogueMenu] = useState<RegionalCatalogueGroup | null>(null);
  const [regionalCatalogueModes, setRegionalCatalogueModes] = useState<Record<RegionalCatalogueGroup, RegionalCatalogueMode>>({
    bollywood: 'popular',
    hollywood: 'popular',
    korean: 'popular',
    pakistani: 'popular',
    anime: 'popular',
  });
  const [openRegionalTvMenu, setOpenRegionalTvMenu] = useState<RegionalTvGroup | null>(null);
  const [regionalTvModes, setRegionalTvModes] = useState<Record<RegionalTvGroup, RegionalTvMode>>({
    indian: 'popular',
    hollywood: 'popular',
    korean: 'popular',
    pakistani: 'popular',
    anime: 'popular',
    'highest-rated': 'popular',
  });
  const [isClearingTmdbCache, setIsClearingTmdbCache] = useState(false);
  const [tmdbCacheMessage, setTmdbCacheMessage] = useState('');
  const [streamingOnly, setStreamingOnly] = useState(false);
  const { ottAvailability, setOttAvailability, ottAvailabilityRef, ottQueueRef, ottQueuedIdsRef, ottLookupGenerationRef, ottLiveCheckedRef, ottRetryAttemptsRef, queueOttLookups, ottAvailabilityForMovie } = useOttAvailability();
  // Initialize state used by visibleMovieCatalogueItems before evaluating its memo dependencies.
  const [marvelFilmFilter, setMarvelFilmFilter] = useState<MarvelFilmFilter>('all');
  const [isMarvelEnglishResults, setIsMarvelEnglishResults] = useState(false);
  const [showMarvelWebSeries, setShowMarvelWebSeries] = useState(false);
  const [isDcLiveActionEnglishResults, setIsDcLiveActionEnglishResults] = useState(false);

  return {
    isSearching,
    setIsSearching,
    isPresetCatalogueAction,
    setIsPresetCatalogueAction,
    searched,
    setSearched,
    error,
    setError,
    catalogueBuildProgress,
    setCatalogueBuildProgress,
    movieCatalogue,
    setMovieCatalogue,
    movieCatalogueSearchText,
    setMovieCatalogueSearchText,
    releasedOnly,
    tmdbFranchiseKey,
    setTmdbFranchiseKey,
    openCachedLanguageMenu,
    setOpenCachedLanguageMenu,
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
    activeFranchiseSearchMode,
    setActiveFranchiseSearchMode,
    franchisePageRequestRef,
    franchisePageGenerationRef,
    franchiseLoadedPagesRef,
    franchiseGridPage,
    setFranchiseGridPage,
    prepareBuildPendingRef,
    previousPosterPageRef,
    posterFirstPageReady,
    setPosterFirstPageReady,
    posterFirstPageReadyRef,
    catalogueExpectedTitles,
    setCatalogueExpectedTitles,
    franchiseGridPageSize,
    openRegionalCatalogueMenu,
    setOpenRegionalCatalogueMenu,
    regionalCatalogueModes,
    setRegionalCatalogueModes,
    openRegionalTvMenu,
    setOpenRegionalTvMenu,
    regionalTvModes,
    setRegionalTvModes,
    isClearingTmdbCache,
    setIsClearingTmdbCache,
    tmdbCacheMessage,
    setTmdbCacheMessage,
    streamingOnly,
    ottAvailability,
    setOttAvailability,
    ottAvailabilityRef,
    ottQueueRef,
    ottQueuedIdsRef,
    ottLookupGenerationRef,
    ottLiveCheckedRef,
    ottRetryAttemptsRef,
    queueOttLookups,
    ottAvailabilityForMovie,
    marvelFilmFilter,
    setMarvelFilmFilter,
    isMarvelEnglishResults,
    setIsMarvelEnglishResults,
    showMarvelWebSeries,
    setShowMarvelWebSeries,
    isDcLiveActionEnglishResults,
    setIsDcLiveActionEnglishResults,
  };
}
