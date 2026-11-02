export interface TorrentSearchResult {
  sectionCacheRecord?: boolean;
  guid?: string;
  title: string;
  mediaTitle?: string;
  size: number;
  seeders: number;
  leechers: number;
  indexer?: string;
  protocol?: string;
  publishDate?: string;
  infoHash?: string;
  magnetUrl?: string;
  downloadUrl?: string;
  infoUrl?: string;
  sourceUrl?: string;
  descriptorUrl?: string;
  year?: number | string | null;
  releaseDate?: string;
  rating?: number | null;
  genres?: string[];
  posterUrl?: string;
  quality?: string;
  // Set on catalogue-derived poster results.
  overview?: string;
  tmdbId?: number | string | null;
  id?: number | string | null;
  imdbId?: string;
  imdbRating?: number | null;
  imdbRatingStatus?: ImdbRatingResult['status'];
  imdbVotes?: string;
  imdbUrl?: string;
  imdbCheckedAt?: number | string | null;
  ottAvailability?: MovieCatalogueItem['ottAvailability'];
  streamingProviders?: TvCatalogueItem['streamingProviders'];
  providerLink?: string;
}


export interface MarvelCatalogueResponse {
  status: 'idle' | 'building' | 'ready' | 'failed';
  results: TorrentSearchResult[];
  completed: number;
  total: number;
  resultCount?: number;
  builtAt?: string;
  error?: string;
  refreshing?: boolean;
  page?: number;
  pageSize?: number;
  totalPages?: number;
  totalMovies?: number;
}

export interface TvCatalogueItem {
  id: number | string;
  tmdbId?: number | string;
  title: string;
  sectionCacheRecord?: boolean;
  year?: number | null;
  releaseDate?: string;
  overview?: string;
  posterUrl?: string;
  backdropUrl?: string;
  rating?: number;
  imdbRating?: number | null;
  imdbVotes?: string | number | null;
  imdbId?: string | null;
  imdbListRank?: number;
  imdbUrl?: string | null;
  imdbCheckedAt?: number | string | null;
  imdbRatingStatus?: ImdbRatingResult['status'];
  genres?: Array<number | { id?: number; name?: string }>;
  seriesType?: string;
  networks?: Array<{
    id?: number;
    logo_path?: string | null;
    name?: string;
    origin_country?: string;
  }>;
  ottAvailability?: MovieCatalogueItem['ottAvailability'];
  originCountry?: string[];
  originalLanguage?: string;
  tmdbUrl?: string;
  streamingProviders?: Array<{
    providerId?: number | null;
    name: string;
    type: 'subscription' | 'free' | 'ads' | 'rent' | 'buy' | string;
    region?: string;
    logoUrl?: string;
    webUrl?: string;
  }>;
  providerLink?: string;
  source?: string;
  malId?: number | string | null;
}

export interface TvCataloguePage {
  catalogue: string;
  page: number;
  totalPages: number;
  totalResults: number;
  provider: string;
  results: TvCatalogueItem[];
  curatedOrder?: boolean;
}

export type MovieCatalogueKey =
  | 'marvel'
  | 'dc-live-action'
  | 'dc-animated'
  | 'classics'
  | 'highest-rated-hollywood' | 'highest-rated-bollywood'
  | 'latest-hollywood'
  | 'latest-bollywood'
  | 'popular-hollywood'
  | 'popular-bollywood'
  | 'trending-hollywood'
  | 'trending-bollywood'
  | 'bollywood-library'
  | 'popular-pakistani' | 'trending-pakistani' | 'latest-pakistani'
  | 'popular-korean' | 'trending-korean' | 'latest-korean'
  | 'popular-anime' | 'trending-anime' | 'latest-anime';

export interface MovieCatalogueItem {
  id: number | string;
  title: string;
  sectionCacheRecord?: boolean;
  year?: number | null;
  releaseDate?: string;
  overview?: string;
  posterUrl?: string;
  backdropUrl?: string;
  rating?: number;
  genres?: number[];
  source?: string;
  tmdbId?: number | string;
  trendingWeek?: string;
  trendingRank?: number;
  trendingWeeks?: string[];
  /** The title's direct stream is known not to play (recorded failure): hide Play, keep the torrent card. */
  directStreamBroken?: boolean;
  imdbRatingStatus?: ImdbRatingResult['status'];
  imdbRating?: number | null;
  imdbVotes?: string | null;
  imdbId?: string | null;
  imdbCheckedAt?: number | string | null;
  verified?: boolean;
  tmdbUrl?: string;
  imdbUrl?: string;
  torrentMatch?: {
    title?: string;
    indexer?: string;
    infoUrl?: string;
    magnetUrl?: string;
    infoHash?: string;
    size?: number;
    seeders?: number;
    leechers?: number;
    matchScore?: number;
  };
  torrentMatches?: Array<{
    title?: string;
    indexer?: string;
    infoUrl?: string;
    magnetUrl?: string;
    infoHash?: string;
    size?: number;
    seeders?: number;
    leechers?: number;
    matchScore?: number;
  }>;
  ottAvailability?: {
    region?: string;
    status?: string;
    streamingProviders?: MovieOttProvider[];
    rentProviders?: MovieOttProvider[];
    buyProviders?: MovieOttProvider[];
    providerLink?: string;
    checkedAt?: string;
    source?: string;
    providerAttribution?: string;
    attribution?: string;
  };
}

export interface SectionCacheRow {
  id: number | string | null;
  title: string;
  year?: number | string | null;
  releaseDate?: string | null;
  overview?: string | null;
  posterUrl?: string | null;
  backdropUrl?: string | null;
  rating?: number | null;
  genres?: Array<number | { id?: number; name?: string }> | null;
  source?: string | null;
  tmdbId?: number | string | null;
  tmdbUrl?: string | null;
  imdbRatingStatus?: ImdbRatingResult['status'] | null;
  imdbRating?: number | null;
  imdbVotes?: string | number | null;
  imdbId?: string | null;
  imdbCheckedAt?: number | string | null;
  imdbUrl?: string | null;
  ottAvailability?: MovieCatalogueItem['ottAvailability'] | null;
  streamingProviders?: TvCatalogueItem['streamingProviders'];
  providerLink?: string | null;
  originCountry?: string[];
  originalLanguage?: string;
  malId?: number | string | null;
  imdbListRank?: number;
  seriesType?: string;
  networks?: TvCatalogueItem['networks'];
  trendingWeek?: string;
  trendingRank?: number;
  trendingWeeks?: string[];
  directStreamBroken?: boolean;
}

export interface SectionCacheSubsection {
  catalogueKey?: string;
  mediaType: 'movie' | 'tv';
  pageSize: number;
  pageCount: number;
  pageOffsets?: number[];
  totalResults: number;
  results: SectionCacheRow[];
}

export interface SectionCacheDocument {
  schemaVersion: number;
  section: string;
  builtAt?: string;
  metadataSelfContained: boolean;
  metadataSources: string[];
  subsections: Record<string, SectionCacheSubsection>;
}

export interface SearchMediaMetadata {
  id: number | string;
  tmdbId?: number | string;
  title: string;
  year?: number | null;
  mediaType: 'movie' | 'tv';
  overview?: string;
  posterUrl?: string;
  backdropUrl?: string;
  rating?: number;
  tmdbUrl: string;
  source?: string;
}

export interface SearchMediaMetadataResponse {
  status: 'ready' | 'not_found' | 'unavailable';
  query: string;
  source?: string;
  results: SearchMediaMetadata[];
}

export interface ImdbRatingResult {
  query?: string;
  title: string;
  year?: number | null;
  mediaType?: 'movie' | 'tv';
  status: 'found' | 'not_found' | 'unavailable' | 'rate_limited';
  imdbRating?: number | null;
  imdbVotes?: string | null;
  imdbId?: string | null;
  imdbUrl?: string | null;
}

export interface MovieCataloguePage {
  catalogue: MovieCatalogueKey;
  provider: string;
  page: number;
  totalPages: number;
  totalResults: number;
  releasedOnly?: boolean;
  maxSizeGb?: number;
  results: MovieCatalogueItem[];
  attribution?: string;
  curatedOrder?: boolean;
}


export type MovieOttStatus =
  | 'streaming'
  | 'rent_buy'
  | 'digital_scheduled'
  | 'digital_release_known'
  | 'not_confirmed';

export interface MovieOttProvider {
  providerId?: number | string | null;
  name: string;
  logoUrl?: string;
  webUrl?: string;
}

export interface MovieOttAvailability {
  movieId: number;
  region: string;
  status: MovieOttStatus;
  streamingProviders: MovieOttProvider[];
  rentProviders: MovieOttProvider[];
  buyProviders: MovieOttProvider[];
  theatricalReleaseDate?: string | null;
  digitalReleaseDate?: string | null;
  providerLink: string;
  checkedAt: string;
  source: string;
  providerAttribution: string;
  attribution: string;
  stale?: boolean;
  cacheWarning?: string;
}
