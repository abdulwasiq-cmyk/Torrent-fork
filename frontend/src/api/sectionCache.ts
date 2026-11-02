import type {
  MovieCatalogueItem,
  MovieCatalogueKey,
  MovieCataloguePage,
  SectionCacheDocument,
  SectionCacheRow,
  TorrentSearchResult,
  TorrentCacheDocument,
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

const ADDITIONAL_TORRENT_MOVIE_SECTIONS: Partial<Record<MovieCatalogueKey, string>> = {
  'bollywood-library': 'bollywood',
  'popular-pakistani': 'pakistani',
  'trending-pakistani': 'pakistani',
  'latest-pakistani': 'pakistani',
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

export function torrentCacheSectionForMovieCatalogue(key: string | undefined): string | null {
  if (!key) return null;
  return MOVIE_CATALOGUE_SECTIONS[key as MovieCatalogueKey]?.section
    || ADDITIONAL_TORRENT_MOVIE_SECTIONS[key as MovieCatalogueKey]
    || null;
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

export function torrentCacheRecordsForMedia(
  document: import('./types.ts').TorrentCacheDocument,
  media: {
    id?: number | string | null;
    tmdbId?: number | string | null;
    imdbId?: string | null;
    title: string;
    year?: number | string | null;
    mediaType?: 'movie' | 'tv';
    seasonNumber?: number;
    episodeNumber?: number;
  },
): TorrentSearchResult[] {
  const mediaType = media.mediaType || 'movie';
  const stableIds = new Set(
    [media.tmdbId, media.id, media.imdbId]
      .filter((value): value is string | number => value != null && String(value).trim() !== '')
      .map(value => String(value).toLowerCase()),
  );
  const title = normalizedTitle(media.title);
  const year = media.year == null ? '' : String(media.year).slice(0, 4);
  return document.records
    .filter(record => {
      const identities = Array.isArray(record.mediaIdentities) ? record.mediaIdentities : [];
      return identities.some(identity => {
        if (identity.mediaType !== mediaType) return false;
        if (
          media.seasonNumber != null &&
          Number(identity.seasonNumber) !== media.seasonNumber
        ) return false;
        if (
          media.episodeNumber != null &&
          Number(identity.episodeNumber) !== media.episodeNumber
        ) return false;
        const identityIds = [identity.tmdbId, identity.imdbId]
          .filter((value): value is string | number => value != null && String(value).trim() !== '')
          .map(value => String(value).toLowerCase());
        if (identityIds.some(value => stableIds.has(value))) return true;
        const identityYear = identity.year == null ? '' : String(identity.year).slice(0, 4);
        return normalizedTitle(identity.title) === title && (!year || !identityYear || year === identityYear);
      });
    })
    .map(record => {
      const identity = record.mediaIdentities?.find(candidate => (
        candidate.mediaType === mediaType &&
        normalizedTitle(candidate.title) === title &&
        (!year || !candidate.year || String(candidate.year).slice(0, 4) === year) &&
        (media.seasonNumber == null || Number(candidate.seasonNumber) === media.seasonNumber) &&
        (media.episodeNumber == null || Number(candidate.episodeNumber) === media.episodeNumber)
      ));
      return {
        ...record,
        sectionCacheRecord: true,
        mediaTitle: identity?.title || media.title,
        year: identity?.year ?? media.year ?? record.year,
        mediaType,
        ...(identity?.seasonNumber == null ? {} : { seasonNumber: identity.seasonNumber }),
        ...(identity?.episodeNumber == null ? {} : { episodeNumber: identity.episodeNumber }),
      };
    });
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
  torrentDocument?: TorrentCacheDocument,
): TorrentSearchResult[] | null {
  const subsection = document.subsections[subsectionName];
  if (!subsection || subsection.mediaType !== 'movie') return null;
  return franchiseMovieCardsForMovies(subsection.results, torrentDocument)
    .flatMap(card => card.variants.length ? card.variants : [card.posterResult]);
}

export interface FranchiseMovieCard {
  key: string;
  title: string;
  year: string;
  catalogue: SectionCacheRow;
  posterResult: TorrentSearchResult;
  variants: TorrentSearchResult[];
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
  torrentDocument?: TorrentCacheDocument,
): { cards: FranchiseMovieCard[]; results: TorrentSearchResult[]; totalResults: number } | null {
  const subsection = document.subsections[subsectionName];
  if (!subsection || subsection.mediaType !== 'movie') return null;
  const totalResults = Number(subsection.totalResults) || subsection.results.length;
  const safePageSize = Math.max(1, Math.floor(Number(pageSize) || SECTION_PAGE_SIZE));
  const safePage = Math.max(1, Math.floor(Number(page) || 1));
  const start = (safePage - 1) * safePageSize;
  const movieRows = subsection.results.slice(start, start + safePageSize);
  const cards = franchiseMovieCardsForMovies(movieRows, torrentDocument);
  return {
    cards,
    results: cards.flatMap(card => card.variants.length ? card.variants : [card.posterResult]),
    totalResults,
  };
}

function franchiseMovieCardsForMovies(
  movies: SectionCacheRow[],
  torrentDocument?: TorrentCacheDocument,
): FranchiseMovieCard[] {
  return movies.map(row => {
    const tmdbId = sectionRowTmdbId(row);
    const catalogueRecord: TorrentSearchResult = {
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
    const cachedTorrents = torrentDocument
      ? torrentCacheRecordsForMedia(torrentDocument, {
        id: catalogueRecord.id,
        tmdbId: catalogueRecord.tmdbId,
        imdbId: catalogueRecord.imdbId,
        title: catalogueRecord.title,
        year: catalogueRecord.year,
        mediaType: 'movie',
      })
      : [];
    const variants = cachedTorrents.map(torrent => ({
      ...catalogueRecord,
      ...torrent,
      mediaTitle: catalogueRecord.mediaTitle,
      posterUrl: torrent.posterUrl || catalogueRecord.posterUrl,
      overview: torrent.overview || catalogueRecord.overview,
      rating: torrent.rating ?? catalogueRecord.rating,
      tmdbId: catalogueRecord.tmdbId ?? torrent.tmdbId,
      id: catalogueRecord.id ?? torrent.id,
      imdbId: catalogueRecord.imdbId || torrent.imdbId,
      imdbRating: catalogueRecord.imdbRating ?? torrent.imdbRating,
      imdbRatingStatus: catalogueRecord.imdbRatingStatus || torrent.imdbRatingStatus,
      imdbVotes: catalogueRecord.imdbVotes ?? torrent.imdbVotes,
      imdbUrl: catalogueRecord.imdbUrl || torrent.imdbUrl,
      imdbCheckedAt: catalogueRecord.imdbCheckedAt ?? torrent.imdbCheckedAt,
      ottAvailability: catalogueRecord.ottAvailability || torrent.ottAvailability,
      streamingProviders: catalogueRecord.streamingProviders || torrent.streamingProviders,
      providerLink: catalogueRecord.providerLink || torrent.providerLink,
    }));
    const year = String(row.year ?? '');
    const identity = tmdbId ?? row.id ?? row.imdbId ?? normalizedTitle(row.title);
    return {
      key: `${identity}|${year || 'unknown'}`,
      title: row.title,
      year,
      catalogue: row,
      posterResult: catalogueRecord,
      variants,
    };
  });
}
