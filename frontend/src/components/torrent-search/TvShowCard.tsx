import React from 'react';
import type { TvCatalogueItem } from '../../api/client.ts';
import { MovieCompactCard, imdbTitleLink, type MovieCardImdb } from '../MovieCards.tsx';
import { toCardProviders, uniqueOttProviders } from './ottProviders.ts';
import { lowQualityPosterUrl } from './posterUrls.ts';

type TvShowCardShow = Pick<TvCatalogueItem, 'id' | 'title' | 'year' | 'releaseDate' | 'posterUrl' | 'overview' | 'rating' | 'streamingProviders' | 'imdbRating' | 'imdbVotes' | 'imdbId' | 'imdbUrl'>;

/**
 * The initial card for every TV / web-series section. It is the same MovieCompactCard the
 * movie sections use, so a change to that card applies to movies and series alike; this
 * wrapper only maps a series to the card's props. Clicking the card runs `onOpen`.
 */
/** Rating, year and providers shown on a series card; shared by the compact and the opened card. */
export function tvCardModel(show: TvShowCardShow, imdb?: MovieCardImdb) {
  const catalogueRating = Number(show.imdbRating) > 0 ? {
    imdbRating: Number(show.imdbRating),
    imdbVotes: show.imdbVotes == null ? undefined : String(show.imdbVotes),
    imdbId: show.imdbId ?? undefined,
    imdbUrl: show.imdbUrl ?? undefined,
  } : undefined;
  // Don't let a cached negative lookup override a real rating on the TV catalogue row.
  const rating = Number(imdb?.imdbRating) > 0 ? imdb : catalogueRating || imdb;
  const releaseDateYear = String(show.releaseDate || '').match(/^(\d{4})/);
  const displayYear = show.year || (releaseDateYear ? Number(releaseDateYear[1]) : undefined);
  const providers = uniqueOttProviders(
    (show.streamingProviders || []).filter(provider => ['subscription', 'free', 'ads'].includes(provider.type)),
  );
  return { rating, displayYear, providers };
}

/** Poster error chain shared by the compact and the opened card. */
export function tvPosterErrorHandler(title: string, displayYear?: number | string | null) {
  return (event: React.SyntheticEvent<HTMLImageElement>) => {
    const image = event.currentTarget;
    if (image.src.includes('/t/p/w780/')) {
      image.src = image.src.replace('/t/p/w780/', '/t/p/w185/');
      return;
    }
    // TMDB can return a stale/missing poster path. Retry through the same-origin
    // title/year poster resolver before showing a blank card.
    if (image.dataset.posterFallbackTried !== 'true') {
      image.dataset.posterFallbackTried = 'true';
      const params = new URLSearchParams({ title, size: 'w185' });
      if (displayYear) params.set('year', String(displayYear));
      image.src = '/api/poster?' + params.toString();
      return;
    }
    image.style.display = 'none';
  };
}

export const TvShowCard: React.FC<{
  show: TvShowCardShow;
  imdb?: MovieCardImdb;
  preferImdb?: boolean;
  onOpen: () => void;
  /** Optional action area at the bottom of the card. */
  footer?: React.ReactNode;
}> = ({ show, imdb, preferImdb = false, onOpen, footer }) => {
  const { rating, displayYear, providers } = tvCardModel(show, imdb);
  return (
    <MovieCompactCard
      title={show.title}
      titleHref={imdbTitleLink(rating, show.title, displayYear)}
      year={displayYear}
      imdb={rating}
      tmdbRating={show.rating}
      preferImdb={preferImdb}
      overview={show.overview || ''}
      posterSrc={show.posterUrl ? lowQualityPosterUrl(show.posterUrl) : ''}
      posterAlt={show.title}
      onPosterClick={onOpen}
      onPosterLoad={() => {}}
      onPosterError={tvPosterErrorHandler(show.title, displayYear)}
      providers={toCardProviders(providers)}
      providersAriaLabel={'Streaming services for ' + show.title}
      providersFallbackText="Streaming providers not listed"
      footer={footer}
    />
  );
};
