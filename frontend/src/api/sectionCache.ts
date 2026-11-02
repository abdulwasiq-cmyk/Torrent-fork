import type {
  MovieCatalogueItem,
  MovieCatalogueKey,
  MovieCataloguePage,
  SectionCacheDocument,
  SectionCacheRow,
  TorrentSearchResult,
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
  'dc-live-action': { section: 'dc', subsection: 'live-action' },
  'dc-animated': { section: 'dc', subsection: 'animated' },
  classics: { section: 'favourites', subsection: 'movies' },
};

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

export function franchiseRowsFromSection(
  document: SectionCacheDocument,
  subsectionName: string,
): TorrentSearchResult[] | null {
  const subsection = document.subsections[subsectionName];
  if (!subsection || subsection.mediaType !== 'movie') return null;
  return subsection.results.map(row => {
    const tmdbId = sectionRowTmdbId(row);
    return {
      sectionCacheRecord: true,
      title: row.title,
      mediaTitle: row.title,
      size: 0,
      seeders: 0,
      leechers: 0,
      year: row.year,
      releaseDate: row.releaseDate || undefined,
      rating: row.rating,
      posterUrl: row.posterUrl || undefined,
      overview: row.overview || undefined,
      tmdbId,
      id: tmdbId ?? row.id,
      imdbId: row.imdbId || undefined,
      imdbRating: row.imdbRating,
      imdbRatingStatus: row.imdbRatingStatus || undefined,
      imdbVotes: row.imdbVotes == null ? undefined : String(row.imdbVotes),
      imdbUrl: row.imdbUrl || undefined,
      imdbCheckedAt: row.imdbCheckedAt,
      ottAvailability: row.ottAvailability || undefined,
      streamingProviders: row.streamingProviders,
      providerLink: row.providerLink || undefined,
    };
  });
}
