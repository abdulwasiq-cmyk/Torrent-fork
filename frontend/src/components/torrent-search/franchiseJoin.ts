import type { TorrentSearchResult } from '../../api/types.ts';

/**
 * Put one title's releases (from the per-section torrent files) into the catalogue row's group.
 * Each joined row keeps the catalogue row's mediaTitle / year / TMDB id / metadata, so
 * groupTorrentResults gives the same group key as before (normalized title | year) and the open
 * card does not collapse or move.
 */
export function joinReleasesIntoRow(base: TorrentSearchResult, releases: TorrentSearchResult[]): TorrentSearchResult[] {
  return releases.map(release => ({
    ...release,
    sectionCacheRecord: undefined,
    mediaTitle: base.mediaTitle || base.title,
    year: base.year ?? release.year,
    releaseDate: base.releaseDate,
    posterUrl: base.posterUrl || release.posterUrl,
    overview: base.overview || release.overview,
    rating: base.rating ?? release.rating,
    tmdbId: base.tmdbId ?? release.tmdbId,
    id: base.id ?? release.id,
    imdbId: base.imdbId || release.imdbId,
    imdbRating: base.imdbRating ?? release.imdbRating,
    imdbRatingStatus: base.imdbRatingStatus || release.imdbRatingStatus,
    imdbVotes: base.imdbVotes ?? release.imdbVotes,
    imdbUrl: base.imdbUrl || release.imdbUrl,
    imdbCheckedAt: base.imdbCheckedAt ?? release.imdbCheckedAt,
    ottAvailability: base.ottAvailability || release.ottAvailability,
    streamingProviders: base.streamingProviders || release.streamingProviders,
    providerLink: base.providerLink || release.providerLink,
  }));
}
