import type {
  MovieCatalogueItem,
  MovieCatalogueKey,
  MovieCataloguePage,
  SectionCacheDocument,
  SectionCacheRow,
  TvCatalogueItem,
  TvCataloguePage,
} from './types.ts';

export interface SectionCacheLocation {
  section: string;
  subsection: string;
}

const SECTION_PAGE_SIZE = 18;

const MOVIE_CATALOGUE_SECTIONS: Partial<Record<MovieCatalogueKey, SectionCacheLocation>> = {
  marvel: { section: 'marvel', subsection: 'movies' },
  'dc-live-action': { section: 'dc', subsection: 'live-action' },
  'dc-animated': { section: 'dc', subsection: 'animated' },
  classics: { section: 'favourites', subsection: 'movies' },
  'highest-rated-hollywood': { section: 'highest-rated', subsection: 'hollywood' },
  'highest-rated-bollywood': { section: 'highest-rated', subsection: 'bollywood' },
  'latest-hollywood': { section: 'hollywood', subsection: 'latest' },
  'latest-bollywood': { section: 'bollywood', subsection: 'latest' },
  'popular-hollywood': { section: 'hollywood', subsection: 'popular' },
  'popular-bollywood': { section: 'bollywood', subsection: 'popular' },
  'trending-hollywood': { section: 'hollywood', subsection: 'trending' },
  'trending-bollywood': { section: 'bollywood', subsection: 'trending' },
  'popular-korean': { section: 'korean', subsection: 'movies' },
  'trending-korean': { section: 'korean', subsection: 'movies' },
  'latest-korean': { section: 'korean', subsection: 'movies' },
  'popular-anime': { section: 'anime', subsection: 'movies' },
  'trending-anime': { section: 'anime', subsection: 'movies' },
  'latest-anime': { section: 'anime', subsection: 'movies' },
};

const TV_CATALOGUE_SECTIONS: Record<string, SectionCacheLocation> = {
  'hollywood-popular': { section: 'hollywood', subsection: 'tv-popular' },
  'hollywood-trending': { section: 'hollywood', subsection: 'tv-trending' },
  'hollywood-latest': { section: 'hollywood', subsection: 'tv-latest' },
  'indian-popular': { section: 'bollywood', subsection: 'tv-popular' },
  'indian-trending': { section: 'bollywood', subsection: 'tv-trending' },
  'indian-latest': { section: 'bollywood', subsection: 'tv-latest' },
  'bollywood-popular': { section: 'bollywood', subsection: 'tv-popular' },
  'bollywood-trending': { section: 'bollywood', subsection: 'tv-trending' },
  'bollywood-latest': { section: 'bollywood', subsection: 'tv-latest' },
  marvel: { section: 'marvel', subsection: 'series' },
  'dc-live-action': { section: 'dc', subsection: 'series' },
  'classics-web-series': { section: 'favourites', subsection: 'series' },
  'classics-anime': { section: 'favourites', subsection: 'anime' },
  'highest-rated-popular': { section: 'highest-rated', subsection: 'tv' },
  'korean-popular': { section: 'korean', subsection: 'series' },
  'pakistani-popular': { section: 'pakistani', subsection: 'series' },
  'anime-popular': { section: 'anime', subsection: 'series' },
};

const FRANCHISE_SECTION_MODES: Record<string, SectionCacheLocation> = {
  marvel: { section: 'marvel', subsection: 'movies' },
  'marvel-hindi': { section: 'marvel', subsection: 'movies' },
  'dc-live-action': { section: 'dc', subsection: 'live-action' },
  'dc-live-action-hindi': { section: 'dc', subsection: 'live-action' },
  'dc-animated': { section: 'dc', subsection: 'animated' },
  classics: { section: 'favourites', subsection: 'movies' },
};

const FRANCHISE_TORRENT_SECTION_ALIASES: Record<string, string> = {
  'marvel-hindi': 'marvel',
  'dc-live-action-hindi': 'dc',
};

const ADDITIONAL_TORRENT_MOVIE_SECTIONS: Partial<Record<MovieCatalogueKey, string>> = {
  'bollywood-library': 'bollywood',
};

const TORRENT_DISABLED_MOVIE_CATALOGUES = new Set<MovieCatalogueKey>([
  'popular-pakistani',
  'trending-pakistani',
  'latest-pakistani',
  'popular-korean',
  'trending-korean',
  'latest-korean',
  'popular-anime',
  'trending-anime',
  'latest-anime',
]);

const MCU_TITLES = new Set([
  'ant man', 'ant man and the wasp', 'ant man and the wasp quantumania',
  'avengers', 'the avengers', 'avengers age of ultron', 'avengers endgame', 'avengers infinity war',
  'black panther', 'black panther wakanda forever', 'black widow', 'captain america brave new world',
  'captain america civil war', 'captain america the first avenger', 'captain america the winter soldier',
  'captain marvel', 'doctor strange', 'doctor strange in the multiverse of madness',
  'deadpool and wolverine', 'eternals', 'guardians of the galaxy', 'guardians of the galaxy vol 2',
  'guardians of the galaxy vol 3', 'iron man', 'iron man 2', 'iron man 3',
  'shang chi and the legend of the ten rings', 'spider man brand new day', 'spider man far from home',
  'spider man homecoming', 'spider man no way home', 'the fantastic four first steps',
  'the incredible hulk', 'the marvels', 'the punisher one last kill', 'the punisher: one last kill',
  'thor', 'thor love and thunder', 'thor ragnarok', 'thor the dark world', 'thunderbolts',
]);

function pageResults<T>(rows: T[], page: number, pageSize: number): T[] {
  const start = (Math.max(1, page) - 1) * pageSize;
  return rows.slice(start, start + pageSize);
}

function numericYear(value: number | string | null | undefined): number | null {
  const year = Number(value);
  return Number.isFinite(year) && year > 0 ? year : null;
}

export function sectionRowTmdbId(row: SectionCacheRow): number | string | undefined {
  if (row.tmdbId != null && row.tmdbId !== '') return row.tmdbId;
  if (typeof row.id === 'number' || /^\d+$/.test(String(row.id || ''))) return row.id || undefined;
  return undefined;
}

function movieItem(row: SectionCacheRow): MovieCatalogueItem {
  const tmdbId = sectionRowTmdbId(row);
  return {
    id: tmdbId ?? row.id ?? row.title,
    title: row.title,
    sectionCacheRecord: true,
    year: numericYear(row.year),
    releaseDate: row.releaseDate || undefined,
    overview: row.overview || undefined,
    posterUrl: row.posterUrl || undefined,
    backdropUrl: row.backdropUrl || undefined,
    rating: row.rating ?? undefined,
    genres: Array.isArray(row.genres)
      ? row.genres.filter((genre): genre is number => typeof genre === 'number')
      : undefined,
    source: row.source || 'self-contained-section-cache',
    tmdbId,
    trendingWeek: row.trendingWeek,
    trendingRank: row.trendingRank,
    trendingWeeks: row.trendingWeeks,
    directStreamBroken: row.directStreamBroken,
    imdbRatingStatus: row.imdbRatingStatus || undefined,
    imdbRating: row.imdbRating,
    imdbVotes: row.imdbVotes == null ? null : String(row.imdbVotes),
    imdbId: row.imdbId,
    imdbCheckedAt: row.imdbCheckedAt,
    tmdbUrl: row.tmdbUrl || undefined,
    imdbUrl: row.imdbUrl || undefined,
    ottAvailability: row.ottAvailability || undefined,
  };
}

function tvItem(row: SectionCacheRow): TvCatalogueItem {
  const tmdbId = sectionRowTmdbId(row);
  return {
    id: tmdbId ?? row.id ?? row.title,
    title: row.title,
    sectionCacheRecord: true,
    year: numericYear(row.year),
    releaseDate: row.releaseDate || undefined,
    overview: row.overview || undefined,
    posterUrl: row.posterUrl || undefined,
    backdropUrl: row.backdropUrl || undefined,
    rating: row.rating ?? undefined,
    imdbRating: row.imdbRating,
    imdbVotes: row.imdbVotes,
    imdbId: row.imdbId,
    imdbListRank: row.imdbListRank,
    imdbUrl: row.imdbUrl || undefined,
    imdbRatingStatus: row.imdbRatingStatus || undefined,
    originCountry: row.originCountry,
    originalLanguage: row.originalLanguage,
    tmdbUrl: row.tmdbUrl || undefined,
    streamingProviders: row.streamingProviders,
    providerLink: row.providerLink || undefined,
    tmdbId,
    imdbCheckedAt: row.imdbCheckedAt,
    ottAvailability: row.ottAvailability || undefined,
    genres: Array.isArray(row.genres) ? row.genres : undefined,
    seriesType: row.seriesType,
    networks: row.networks,
    source: row.source || 'self-contained-section-cache',
    malId: row.malId,
  };
}

export function movieCatalogueSection(key: MovieCatalogueKey): SectionCacheLocation | null {
  return MOVIE_CATALOGUE_SECTIONS[key] || null;
}

export function torrentCacheSectionForMovieCatalogue(key: string | undefined): string | null {
  if (!key) return null;
  if (TORRENT_DISABLED_MOVIE_CATALOGUES.has(key as MovieCatalogueKey)) return null;
  return FRANCHISE_TORRENT_SECTION_ALIASES[key]
    || MOVIE_CATALOGUE_SECTIONS[key as MovieCatalogueKey]?.section
    || ADDITIONAL_TORRENT_MOVIE_SECTIONS[key as MovieCatalogueKey]
    || null;
}

export function movieCatalogueTorrentLookupEnabled(key: string | undefined): boolean {
  return !key || !TORRENT_DISABLED_MOVIE_CATALOGUES.has(key as MovieCatalogueKey);
}

export function torrentCacheSectionForTvCatalogue(key: string): string | null {
  return TV_CATALOGUE_SECTIONS[key]?.section || null;
}

function normalizedTitle(value: string): string {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

export function matchesMarvelFilmFilter(
  title: string,
  year: number | string | null | undefined,
  filter: 'all' | 'mcu' | 'x-men' | 'sony',
): boolean {
  const rawTitle = String(title || '');
  const normalized = normalizedTitle(rawTitle.replace(/\s*\(?((?:19|20)\d{2})\)?\s*$/, ''));
  const releaseYear = Number(year || rawTitle.match(/\b(?:19|20)\d{2}\b/)?.[0] || 0);
  if (releaseYear === 1977 && /^(?:the )?amazing spider man$/.test(normalized)) return false;
  if (filter === 'all') return true;

  const isSpiderMan = (value: string) => /spider\s*man|spider\s*verse|into the spider|across the spider/i.test(value);
  const isXMen = (value: string) => /x\s*men|wolverine|deadpool|new mutants|dark phoenix/i.test(value);
  const isSony = (value: string) => isSpiderMan(value) || /venom|morbius|kraven|madame web/i.test(value);
  switch (filter) {
    case 'mcu':
      return MCU_TITLES.has(normalized) || [...MCU_TITLES].some(item => normalized.startsWith(item + ' ')) ||
        /^(?:marvel television special presentation )?(?:the )?punisher one last kill$/.test(normalized);
    case 'x-men':
      return isXMen(normalized);
    case 'sony':
      return isSony(normalized);
    default:
      return true;
  }
}

export function movieCataloguePageFromSection(
  document: SectionCacheDocument,
  catalogue: MovieCatalogueKey,
  subsectionName: string,
  page: number,
): MovieCataloguePage | null {
  const subsection = document.subsections[subsectionName];
  if (!subsection || subsection.mediaType !== 'movie') return null;
  const results = Array.isArray(subsection.results) ? subsection.results : [];
  const totalResults = results.length;
  const totalPages = Math.max(1, Math.ceil(totalResults / SECTION_PAGE_SIZE));
  const currentPage = Math.min(totalPages, Math.max(1, Math.floor(Number(page) || 1)));
  return {
    catalogue,
    provider: 'self-contained-section-cache',
    page: currentPage,
    totalPages,
    totalResults,
    results: pageResults(results, currentPage, SECTION_PAGE_SIZE).map(movieItem),
    curatedOrder: true,
  };
}

export function tvCatalogueSection(key: string): SectionCacheLocation | null {
  return TV_CATALOGUE_SECTIONS[key] || null;
}

export function tvCataloguePageFromSection(
  document: SectionCacheDocument,
  catalogue: string,
  subsectionName: string,
  page: number,
): TvCataloguePage | null {
  const subsection = document.subsections[subsectionName];
  if (!subsection || subsection.mediaType !== 'tv') return null;
  const results = Array.isArray(subsection.results) ? subsection.results : [];
  const totalResults = results.length;
  const totalPages = Math.max(1, Math.ceil(totalResults / SECTION_PAGE_SIZE));
  const currentPage = Math.min(totalPages, Math.max(1, Math.floor(Number(page) || 1)));
  return {
    catalogue,
    page: currentPage,
    totalPages,
    totalResults,
    provider: 'self-contained-section-cache',
    results: pageResults(results, currentPage, SECTION_PAGE_SIZE).map(tvItem),
    curatedOrder: true,
  };
}

export async function tvCataloguePageFromSectionCache(
  loadSectionCache: (section: string) => Promise<SectionCacheDocument>,
  catalogue: string,
  page: number,
): Promise<TvCataloguePage | null> {
  const location = tvCatalogueSection(catalogue);
  if (!location) return null;
  const document = await loadSectionCache(location.section);
  return tvCataloguePageFromSection(document, catalogue, location.subsection, page);
}

export function franchiseCatalogueSection(mode: string): SectionCacheLocation | null {
  return FRANCHISE_SECTION_MODES[mode] || null;
}

export async function franchiseSectionDocumentFromCache(
  loadSectionCache: (section: string) => Promise<SectionCacheDocument>,
  mode: string,
): Promise<{ location: SectionCacheLocation; document: SectionCacheDocument } | null> {
  const location = franchiseCatalogueSection(mode);
  if (!location) return null;
  return {
    location,
    document: await loadSectionCache(location.section),
  };
}

export interface FranchiseMovieCard extends MovieCatalogueItem {
  key: string;
}

export function franchiseMovieCardsForPage(
  cards: FranchiseMovieCard[],
  page: number,
  pageSize: number,
): FranchiseMovieCard[] {
  const safePageSize = Math.max(1, Math.floor(Number(pageSize) || SECTION_PAGE_SIZE));
  const safePage = Math.max(1, Math.floor(Number(page) || 1));
  const start = (safePage - 1) * safePageSize;
  return cards.slice(start, start + safePageSize);
}

export function franchiseMoviePageFromSection(
  document: SectionCacheDocument,
  subsectionName: string,
  page: number,
  pageSize: number,
): { cards: FranchiseMovieCard[]; totalResults: number } | null {
  const subsection = document.subsections[subsectionName];
  if (!subsection || subsection.mediaType !== 'movie') return null;
  const totalResults = Number(subsection.totalResults) || subsection.results.length;
  const safePageSize = Math.max(1, Math.floor(Number(pageSize) || SECTION_PAGE_SIZE));
  const safePage = Math.max(1, Math.floor(Number(page) || 1));
  const start = (safePage - 1) * safePageSize;
  const cards = subsection.results.slice(start, start + safePageSize).map(row => {
    const movie = movieItem(row);
    const year = String(row.year ?? '');
    const identity = movie.tmdbId ?? movie.id ?? movie.imdbId ?? normalizedTitle(row.title);
    return {
      ...movie,
      key: `${identity}|${year || 'unknown'}`,
    };
  });
  return {
    cards,
    totalResults,
  };
}
