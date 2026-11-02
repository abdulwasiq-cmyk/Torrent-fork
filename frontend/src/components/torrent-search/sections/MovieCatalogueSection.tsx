import { Loader2 } from 'lucide-react';
import { API_BASE } from '../../../api/client.ts';
import { formatBytes } from '../../../utils/formatters.ts';
import { MovieCompactCard, MoviePrepareCard, imdbTitleLink } from '../../MovieCards.tsx';
import { imdbRatingKey, torrentQualityDetails, torrentResultKey } from '../grouping.ts';
import { toCardProviders, uniqueOttProviders } from '../ottProviders.ts';
import { cataloguePosterOverride, cataloguePosterSource, imdbFallbackForCatalogueMovie, imdbRatingForCatalogueMovie, isTheCrow2024 } from '../cataloguePosters.ts';
import { lowQualityPosterUrl, posterKeyFor } from '../posterUrls.ts';
import { catalogueMovieIdentity, extractedQuality } from '../helpers.ts';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function MovieCatalogueSection({ vm }: { vm: PanelModel }) {
  const { cataloguePosterUrlsRef, catalogueSort, closeMoviePrepareCard, imdbRatingsByKey, isSearching, movieCatalogue, movieCatalogueSearchText, movieTorrentPreviewCatalogueId, movieTorrentPreviewGroup, movieTorrentPreviewPosterUrl, movieTorrentSearchError, movieTorrentSearchLoading, movieTorrentSearchTitle, nexStreamResolvingId, openMovieCatalogue, setCatalogueSort, ottAvailabilityForMovie, ottPendingCount, pendingPosterAction, playWithNexStream, posterBackgroundQueueRef, posterBackgroundQueuedRef, posterFirstPageReadyRef, posterLoadedRef, posterOverrides, posterUrlFor, prepareBuildPendingRef, prepareClickIntentRef, prepareMovieTorrent, prepareStateFor, prepareTraceIdRef, preparedActionsFor, searchMovieTorrents, selectedMovieTorrentQualityByGroup, setMovieTorrentSearchError, setNexStreamError, setPendingPosterAction, setSelectedMovieTorrentQualityByGroup, startPosterBackgroundWorkers, streamingOnly, visibleMovieCatalogueItems } = vm;
  const sortedVisibleMovieCatalogueItems = catalogueSort === 'popularity'
    ? visibleMovieCatalogueItems
    : visibleMovieCatalogueItems
      .map((movie, index) => ({ movie, index }))
      .sort((a, b) => {
        if (catalogueSort === 'year') {
          const yearOf = (movie: typeof a.movie) =>
            Number(movie.year) || Number(String(movie.releaseDate || '').match(/^(\d{4})/)?.[1]) || 0;
          return yearOf(b.movie) - yearOf(a.movie) || a.index - b.index;
        }
        const ratingOf = (movie: typeof a.movie) =>
          Number(movie.imdbRating) ||
          Number(imdbRatingsByKey[imdbRatingKey(movie.title, movie.year)]?.imdbRating) ||
          Number(imdbFallbackForCatalogueMovie(movie)?.imdbRating) ||
          0;
        return ratingOf(b.movie) - ratingOf(a.movie) || a.index - b.index;
      })
      .map(({ movie }) => movie);
  return (
    <>
      {movieCatalogue && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2 px-1">
            <div className="text-xs text-slate-400">
              {movieCatalogue.catalogue.startsWith('trending-')
                ? movieCatalogue.results.length + ' trending titles on this page · Page ' + movieCatalogue.page + ' of ' + movieCatalogue.totalPages
                : movieCatalogue.totalResults.toLocaleString() + ' movies · Page ' + movieCatalogue.page + ' of ' + movieCatalogue.totalPages.toLocaleString()
              } · Metadata by {movieCatalogue.provider}
            </div>
            <div className="text-[11px] text-slate-500">Select a movie to search torrent providers</div>
          </div>



          {movieCatalogue && visibleMovieCatalogueItems.length > 0 && !isSearching && (
            <div className="flex flex-wrap items-center gap-2 px-1" aria-label="Sort movies">
              <span className="mr-1 text-xs text-slate-400">Sort by</span>
              {([
                ['popularity', 'Popularity'],
                ['rating', 'Rating'],
                ['year', 'Year'],
              ] as const).map(([sort, label]) => (
                <button
                  key={sort}
                  type="button"
                  aria-pressed={catalogueSort === sort}
                  onClick={() => setCatalogueSort(sort)}
                  className={'rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ' + (
                    catalogueSort === sort
                      ? 'border-cyan-400 bg-cyan-500 text-slate-950'
                      : 'border-slate-700 bg-slate-950 text-slate-300 hover:border-cyan-500/60'
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900 px-3 py-2">
            <button
              type="button"
              disabled={isSearching || movieCatalogue.page <= 1}
              onClick={() => void openMovieCatalogue(movieCatalogue.catalogue, movieCatalogueSearchText, movieCatalogue.page - 1)}
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-300 hover:border-cyan-500 disabled:opacity-40"
            >
              Previous
            </button>
            <span className="text-xs text-slate-500">Page {movieCatalogue.page} of {movieCatalogue.totalPages.toLocaleString()}</span>
            <button
              type="button"
              disabled={isSearching || movieCatalogue.page >= movieCatalogue.totalPages}
              onClick={() => void openMovieCatalogue(movieCatalogue.catalogue, movieCatalogueSearchText, movieCatalogue.page + 1)}
              className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 hover:bg-cyan-400 disabled:opacity-40"
            >
              Next
            </button>
          </div>

          {movieTorrentSearchLoading && (
            <div className="flex items-center gap-3 rounded-xl border border-cyan-500/30 bg-slate-950 px-3 py-3 text-sm text-slate-200">
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-cyan-400" />
              <div>
                <div className="font-semibold">Finding torrent releases for {movieTorrentSearchTitle}…</div>
                <div className="mt-0.5 text-xs text-slate-500">Combining matching qualities in the background. The movie catalogue stays open.</div>
              </div>
            </div>
          )}
          {pendingPosterAction && (
            <div className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-400">
              Loading the visible posters before opening this card…
            </div>
          )}
          {movieTorrentSearchError && (
            <div className={'flex items-start justify-between gap-3 rounded-xl border px-3 py-3 text-xs ' + (movieTorrentSearchError.startsWith('Coming soon on OTT') ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100' : 'border-amber-500/30 bg-amber-500/10 text-amber-200')}>
              <span>{movieTorrentSearchError}</span>
              <button type="button" onClick={() => setMovieTorrentSearchError('')} className="shrink-0 underline">Dismiss</button>
            </div>
          )}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:gap-4">
            {sortedVisibleMovieCatalogueItems.map(movie => {
              // Keep the selected torrent preview attached only to the exact
              // catalogue item the user clicked. Never reuse it by title alone.
              // A title match alone can leak an old Prepare card into another section
              // where the same title appears under a different catalogue record.
              const releaseDateYear = String(movie.releaseDate || '').match(/^(\d{4})/);
              const displayYear = movie.year || (releaseDateYear ? Number(releaseDateYear[1]) : undefined);
              const previewMatchesMovie =
                movieTorrentPreviewCatalogueId !== null &&
                movieTorrentPreviewCatalogueId === catalogueMovieIdentity(movie, movieCatalogue.catalogue);
              const previewGroup = previewMatchesMovie ? movieTorrentPreviewGroup : null;
              const isPunisherSpecial = /punisher.*one last kill|one last kill.*punisher/i.test(String(movie.title || ''));
              const cachedMovieImdb = imdbRatingsByKey[imdbRatingKey(movie.title, movie.year)];
              const cachedTvImdb = isPunisherSpecial ? imdbRatingsByKey[imdbRatingKey(movie.title, movie.year, 'tv')] : undefined;
              const catalogueImdb = imdbRatingForCatalogueMovie(movie);
              const fallbackImdb = imdbFallbackForCatalogueMovie(movie);
              // A cached "not_found"/"unavailable" result must never shadow a real
              // score embedded in the catalogue row or a known fallback rating.
              const movieImdb = [cachedMovieImdb, cachedTvImdb, catalogueImdb, fallbackImdb]
                .find(candidate => Number(candidate?.imdbRating) > 0) ||
                cachedMovieImdb || cachedTvImdb || catalogueImdb || fallbackImdb;
              const movieTitleHref = imdbTitleLink(movieImdb, movie.title, movie.year);

              if (previewGroup) {
                const selectedKey = selectedMovieTorrentQualityByGroup[previewGroup.key] || (previewGroup.variants[0] ? torrentResultKey(previewGroup.variants[0]) : '');
                const result = previewGroup.variants.find(variant => torrentResultKey(variant) === selectedKey) || previewGroup.variants[0];
                // No torrent for this title: the card can offer manual unverified VidRift playback only.
                const prepareState = prepareStateFor(result || previewGroup.posterResult);
                // Keep the catalogue poster as the source of truth for the
                // inline Prepare card; torrent-result poster metadata is often absent
                // or delayed and must not replace the movie's known poster.
                const isRegionalMoviePreview = /^(popular|trending|latest)-(bollywood|hollywood)$/.test(String(movieCatalogue?.catalogue || ''));
                const posterOverride = cataloguePosterOverride(movie);
                const loadedCataloguePosterUrl = cataloguePosterUrlsRef.current[String(movie.id)] || '';
                const cataloguePosterUrl = loadedCataloguePosterUrl ||
                  (isTheCrow2024(movie) ? posterOverride : movieTorrentPreviewPosterUrl) ||
                  posterOverride || cataloguePosterSource(movie);
                const posterSrc = loadedCataloguePosterUrl || lowQualityPosterUrl(
                  cataloguePosterUrl ||
                  (isRegionalMoviePreview ? '' : posterUrlFor(previewGroup.posterResult) || previewGroup.posterResult?.posterUrl || '')
                );
                const nexStreamMovieId = 'movie:' + String(movie.tmdbId || movie.id);
                return (
                  <MoviePrepareCard
                    key={'movie-prepare-' + String(movie.id) + '-' + posterSrc}
                    posterSrc={posterSrc}
                    posterAlt={previewGroup.title}
                    providers={(() => {
                      const availability = ottAvailabilityForMovie(movie);
                      return availability && availability.status !== 'loading' && availability.status !== 'error'
                        ? toCardProviders(uniqueOttProviders([
                            ...(availability.streamingProviders || []),
                            ...(availability.rentProviders || []),
                            ...(availability.buyProviders || []),
                          ]))
                        : [];
                    })()}
                    onPosterClick={closeMoviePrepareCard}
                    onPosterLoad={event => {
                      posterLoadedRef.current.add(posterKeyFor(previewGroup.posterResult));
                      event.currentTarget.style.display = '';
                      event.currentTarget.parentElement?.querySelector('[data-poster-placeholder="true"]')?.classList.add('hidden');
                    }}
                    onPosterError={event => {
                      const image = event.currentTarget;
                      const originalUrl = lowQualityPosterUrl(String(
                        movieTorrentPreviewPosterUrl ||
                        cataloguePosterUrlsRef.current[String(movie.id)] ||
                        cataloguePosterSource(movie) ||
                        (isRegionalMoviePreview ? '' : previewGroup.posterResult?.posterUrl || '')
                      ).trim(), 'w185');
                      // The compact card retries the unmodified poster when the resized
                      // URL fails. Do the same here so both cards show the same artwork.
                      if (originalUrl && image.dataset.originalFallbackTried !== 'true') {
                        const fallbackUrl = originalUrl.startsWith('/') ? API_BASE + originalUrl : originalUrl;
                        image.dataset.originalFallbackTried = 'true';
                        if (image.src !== new URL(fallbackUrl, window.location.origin).toString()) {
                          image.src = fallbackUrl;
                          return;
                        }
                      }
                      const key = posterKeyFor(previewGroup.posterResult);
                      posterLoadedRef.current.delete(key);
                      image.style.display = 'none';
                      image.parentElement?.querySelector('[data-poster-placeholder="true"]')?.classList.remove('hidden');
                      if (!posterBackgroundQueuedRef.current.has(key) && !posterOverrides[key]) {
                        posterBackgroundQueuedRef.current.add(key);
                        posterBackgroundQueueRef.current.unshift({ key, result: previewGroup.posterResult });
                        startPosterBackgroundWorkers();
                      }
                    }}
                    imdb={movieImdb}
                    seeders={result?.seeders}
                    indexer={result?.indexer}
                    quality={result ? extractedQuality(result) : undefined}
                    title={movie.title}
                    titleHref={movieTitleHref}
                    year={movie.year || previewGroup.year}
                    onClose={closeMoviePrepareCard}
                    variants={previewGroup.variants.map(variant => {
                      const quality = torrentQualityDetails(variant);
                      const provider = String(variant.indexer || '').trim();
                      const size = formatBytes(Number(variant.size) || 0);
                      const seeds = Number(variant.seeders) || 0;
                      return {
                        key: torrentResultKey(variant),
                        label: `${quality.label} · ${size} · ▲${seeds}${provider ? ` · ${provider}` : ''}`,
                      };
                    })}
                    selectedVariantKey={result ? torrentResultKey(result) : ''}
                    onSelectVariant={key => setSelectedMovieTorrentQualityByGroup(previous => ({ ...previous, [previewGroup.key]: key }))}
                    variantsAriaLabel={`Choose quality for ${previewGroup.title}`}
                    prepared={result && prepareState.primaryFile ? preparedActionsFor(prepareState.torrentKey, prepareState.primaryFile) : null}
                    directStream={movie.directStreamBroken === true || !Number(movie.tmdbId || movie.id) ? undefined : {
                      disabled: !Number(movie.tmdbId || movie.id) || nexStreamResolvingId === nexStreamMovieId,
                      label: nexStreamResolvingId === nexStreamMovieId ? 'Resolving…' : 'Direct Stream',
                      onClick: () => {
                        const tmdbId = Number(movie.tmdbId || movie.id);
                        if (!Number.isInteger(tmdbId) || tmdbId <= 0) {
                          setNexStreamError('This catalogue card has no valid TMDB ID for VidRift playback.');
                          return;
                        }
                        void playWithNexStream({
                          id: tmdbId,
                          title: movie.title,
                          date: movie.releaseDate || (movie.year ? String(movie.year) : ''),
                          overview: movie.overview || '',
                          poster: movie.posterUrl || movieTorrentPreviewPosterUrl || null,
                          type: 'movie',
                        });
                      },
                    }}
                    prepare={!result ? undefined : {
                      isPreparing: prepareState.isPreparing,
                      disabled: !prepareState.source || prepareState.isPreparing,
                      onClick: () => void prepareMovieTorrent(result),
                    }}
                  />
                );
              }

              const ott = ottAvailabilityForMovie(movie);
              const ottProviders = ott && ott.status !== 'loading' && ott.status !== 'error'
                ? toCardProviders(uniqueOttProviders([
                    ...(ott.streamingProviders || []),
                    ...(ott.rentProviders || []),
                    ...(ott.buyProviders || []),
                  ]))
                : [];
              return (
                <MovieCompactCard
                  key={String(movie.id)}
                  title={movie.title}
                  titleHref={movieTitleHref}
                  year={displayYear}
                  imdb={movieImdb}
                  tmdbRating={movie.rating}
                  trendWeekLabel={movieCatalogue.catalogue.startsWith('trending-') && movie.trendingWeek
                    ? 'Week of ' + new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(movie.trendingWeek + 'T00:00:00Z')) + (movie.trendingRank ? ' · #' + movie.trendingRank : '')
                    : undefined}
                  overview={movie.overview || 'No synopsis available from TMDB for this title.'}
                  posterSrc={lowQualityPosterUrl(cataloguePosterSource(movie), 'w185')}
                  posterAlt={movie.title}
                  onPosterClick={() => {
                    if (isSearching || movieTorrentSearchLoading || pendingPosterAction || prepareBuildPendingRef.current) return;
                    const traceId = `prep-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
                    prepareClickIntentRef.current = true;
                    prepareTraceIdRef.current = traceId;
                    console.info('[PREPARE_TRACE]', JSON.stringify({
                      event: 'explicit-card-click',
                      traceId,
                      title: movie.title,
                      year: movie.year || null,
                      at: new Date().toISOString(),
                    }));
                    const isHollywoodCatalogue = /^(popular|trending|latest)-hollywood$/.test(movieCatalogue.catalogue);
                    if (!isHollywoodCatalogue && !posterFirstPageReadyRef.current) {
                      setPendingPosterAction({
                        kind: 'catalogue',
                        movie,
                        catalogue: movieCatalogue.catalogue,
                        page: movieCatalogue.page,
                      });
                      return;
                    }
                    void searchMovieTorrents(movie);
                  }}
                  onPosterLoad={event => {
                    // Preserve the exact URL that made this catalogue poster visible.
                    cataloguePosterUrlsRef.current[String(movie.id)] = event.currentTarget.currentSrc || event.currentTarget.src;
                    event.currentTarget.style.display = '';
                    event.currentTarget.parentElement?.querySelector('[data-poster-placeholder="true"]')?.classList.add('hidden');
                  }}
                  onPosterError={event => {
                    const image = event.currentTarget;
                    const originalUrl = lowQualityPosterUrl(cataloguePosterSource(movie), 'w185');
                    // If the optimized w500 URL fails, retry the catalogue's
                    // original poster URL once before showing the placeholder.
                    if (originalUrl && image.dataset.originalFallbackTried !== 'true' && image.src !== new URL(originalUrl, window.location.origin).toString()) {
                      image.dataset.originalFallbackTried = 'true';
                      image.src = originalUrl.startsWith('/') ? API_BASE + originalUrl : originalUrl;
                      return;
                    }
                    image.style.display = 'none';
                    image.parentElement?.querySelector('[data-poster-placeholder="true"]')?.classList.remove('hidden');
                  }}
                  providers={ottProviders}
                  providersAriaLabel={'Streaming services for ' + movie.title}
                  providersFallbackText={
                    !ott || ott.status === 'loading'
                      ? 'Checking streaming services…'
                      : ott.status === 'error'
                        ? 'Streaming availability temporarily unavailable'
                        : ott.status === 'not_confirmed'
                          ? 'Streaming providers not confirmed'
                          : 'No streaming providers reported'
                  }
                />
              );
            })}
          </div>



          {streamingOnly && ottPendingCount > 0 && (
            <div className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-400">
              Checking OTT availability in India for {ottPendingCount} more title{ottPendingCount === 1 ? '' : 's'}…
            </div>
          )}
          {streamingOnly && visibleMovieCatalogueItems.length === 0 && ottPendingCount === 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-5 text-sm text-slate-400">
              No titles on this page have confirmed streaming availability in India. Provider data can be incomplete; try another page or turn off this filter.
            </div>
          )}

          <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900 px-3 py-2">
            <button
              type="button"
              disabled={isSearching || movieCatalogue.page <= 1}
              onClick={() => void openMovieCatalogue(movieCatalogue.catalogue, movieCatalogueSearchText, movieCatalogue.page - 1)}
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-300 hover:border-cyan-500 disabled:opacity-40"
            >
              Previous
            </button>
            <span className="text-xs text-slate-500">Browse all pages to explore older releases too</span>
            <button
              type="button"
              disabled={isSearching || movieCatalogue.page >= movieCatalogue.totalPages}
              onClick={() => void openMovieCatalogue(movieCatalogue.catalogue, movieCatalogueSearchText, movieCatalogue.page + 1)}
              className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 hover:bg-cyan-400 disabled:opacity-40"
            >
              Next
            </button>
          </div>

          <div className="flex flex-col items-start gap-2 rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3 sm:flex-row sm:items-center">
            <a href="https://www.themoviedb.org/" target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-2">
              <img
                src="https://www.themoviedb.org/assets/2/v4/logos/v2/blue_square_1-5bdc75aaebeb75dc7ae79426ddd9be3b2be1e342510f8202baf6bffa71d7f5c4.svg"
                alt="The Movie Database (TMDB)"
                className="h-7 w-7 object-contain"
              />
              <span className="text-xs font-bold text-slate-300">The Movie Database (TMDB)</span>
            </a>
            <p className="text-[10px] leading-relaxed text-slate-500">
              This product uses the TMDB API but is not endorsed or certified by TMDB.
            </p>
          </div>
        </div>
      )}

    </>
  );
}
