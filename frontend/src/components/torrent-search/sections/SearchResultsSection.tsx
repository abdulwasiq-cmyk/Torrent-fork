import { api } from '../../../api/client.ts';
import { formatBytes } from '../../../utils/formatters.ts';
import { TvShowCard } from '../TvShowCard.tsx';
import { MovieCompactCard, MoviePrepareCard, imdbTitleLink } from '../../MovieCards.tsx';
import { compareReleaseDateDescending, episodeSeriesTitle, releaseDateSortValue, imdbRatingKey, normalizeGroupTitle, normalizeSavedOttTitle, searchMetadataForGroup, torrentQualityDetails, torrentResultKey } from '../grouping.ts';
import { toCardProviders, uniqueOttProviders } from '../ottProviders.ts';
import { normalizeTorrentTitleForNexStream } from '../nexstream.ts';
import { lowQualityPosterUrl, posterImageUrlForResult, posterKeyFor } from '../posterUrls.ts';
import { extractedQuality } from '../helpers.ts';
import { classicsComparator, ratingValue } from '../classicsSort.ts';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';
import { isAnimeCatalogue } from '../yenime.ts';
import { tvCataloguePageFromSectionCache } from '../../../api/sectionCache.ts';

export function SearchResultsSection({ vm }: { vm: PanelModel }) {
  const isRegionalTvView = ['hollywood', 'bollywood', 'korean', 'pakistani', 'anime'].includes(vm.activeTopSection || '')
    && vm.regionalContentTabs[vm.activeTopSection as keyof typeof vm.regionalContentTabs] === 'web-series';
  if (isRegionalTvView) return null;

  const { activeTopSection, catalogueExpectedTitles, classicsContentTab, classicsSort, dcWebSeriesCatalogue, dcWebSeriesError, dcWebSeriesLoading, error, expandedSearchGroupKey, franchiseGridPage, franchiseGridPageSize, groupedResults, imdbRatingsByKey, isSearching, loadDcWebSeriesPage, marvelWebSeriesCatalogue, marvelWebSeriesError, marvelWebSeriesLoading, metadataPosterFailed, movieCatalogue, movieTorrentPreviewGroup, nexStreamLoading, nexStreamLoadingTitle, nexStreamResolvingId, nexStreamResults, onPlaySeedrFile, openYenimeRequest, pendingPosterAction, playCatalogueTvWithNexStream, playWithNexStream, playingTorrentKey, posterBackgroundQueueRef, posterBackgroundQueuedRef, posterFirstPageReadyRef, posterLoadedRef, posterOverrides, prepareMovieTorrent, prepareStateFor, preparedActionsFor, preparedForResult, preparingTorrentKey, regionalWebSeriesCatalogue, regionalWebSeriesError, regionalWebSeriesLoading, renderFranchisePagination, results, searchAvailabilityByGroup, searchMetadata, searchMetadataStatus, searchNexStreamTitles, searchPosterUrlsRef, selectedMovieTorrentQualityByGroup, selectedQualityByGroup, setExpandedSearchGroupKey, setMarvelWebSeriesCatalogue, setMarvelWebSeriesError, setMarvelWebSeriesLoading, setMetadataPosterFailed, setMovieTorrentPreviewCatalogueId, setMovieTorrentPreviewGroup, setMovieTorrentSearchError, setNexStreamError, setPendingPosterAction, setPlayingTorrentKey, setRegionalWebSeriesCatalogue, setRegionalWebSeriesError, setRegionalWebSeriesLoading, setSelectedMovieTorrentQualityByGroup, setSelectedQualityByGroup, showDcWebSeries, showMarvelWebSeries, sortedResults, startPosterBackgroundWorkers } = vm;
  const renderDcWebSeriesPagination = () => {
    if (!dcWebSeriesCatalogue || dcWebSeriesCatalogue.totalPages <= 1) return null;
    const page = dcWebSeriesCatalogue.page;
    const totalPages = dcWebSeriesCatalogue.totalPages;
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900 px-3 py-2">
        <button type="button" disabled={dcWebSeriesLoading || page <= 1} onClick={() => void loadDcWebSeriesPage(page - 1)} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-200 disabled:opacity-40">← Previous</button>
        <span className="text-xs text-slate-400">Page {page} of {totalPages} · {dcWebSeriesCatalogue.totalResults} titles</span>
        <button type="button" disabled={dcWebSeriesLoading || page >= totalPages} onClick={() => void loadDcWebSeriesPage(page + 1)} className="rounded-lg bg-cyan-500 px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-40">Next →</button>
      </div>
    );
  };
  return (
    <>
      {(results.length > 0 || regionalWebSeriesLoading || Boolean(regionalWebSeriesError) || Boolean(regionalWebSeriesCatalogue) || showDcWebSeries || (activeTopSection === 'classics' && classicsContentTab !== null)) && (
        <div className="space-y-2">
          <div className="px-1 text-[11px] text-slate-500">Use the subsection buttons above to switch catalogue views.</div>

          <div className="flex items-center justify-between gap-2 px-1">
            <div className="text-xs text-slate-400">
              {groupedResults.length} titles · {sortedResults.length} torrent options
            </div>
          </div>
          {pendingPosterAction?.kind === 'search' && (
            <div className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-400">
              Loading the visible posters before opening this card…
            </div>
          )}

          {activeTopSection === 'classics' && classicsContentTab !== 'movies' ? (
            <section className="space-y-3">
              <div className="px-1 text-xs text-slate-400">
                {classicsContentTab === 'web-series'
                  ? 'Classic live-action series · full TMDB details and India OTT availability · playback through NexStream'
                  : 'Classic anime series · Metadata by TMDB · playback through Yenime · availability unverified'}
              </div>
              {marvelWebSeriesLoading && <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm text-slate-300">Loading {classicsContentTab === 'anime' ? 'Classics anime' : 'Classics web series'}…</div>}
              {marvelWebSeriesError && <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">{marvelWebSeriesError}</div>}
              {marvelWebSeriesCatalogue && marvelWebSeriesCatalogue.catalogue === (classicsContentTab === 'anime' ? 'classics-anime' : 'classics-web-series') && (
                <>
                  <div className="px-1 text-xs text-slate-400">{marvelWebSeriesCatalogue.totalResults.toLocaleString()} {classicsContentTab === 'anime' ? 'anime titles' : 'web series'} · Metadata by TMDB</div>
                  {renderFranchisePagination(marvelWebSeriesCatalogue.results.length)}
                  <div className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:gap-4">
                    {[...marvelWebSeriesCatalogue.results].sort(classicsComparator(classicsSort, show => releaseDateSortValue(show), show => ratingValue(imdbRatingsByKey[imdbRatingKey(show.title, show.year, 'tv')]), show => String(show.title || ''))).slice((franchiseGridPage - 1) * franchiseGridPageSize, franchiseGridPage * franchiseGridPageSize).map(show => (
                      <TvShowCard key={String(show.id)} show={show} imdb={imdbRatingsByKey[imdbRatingKey(show.title, show.year, 'tv')]} onOpen={() => {
                        if (isAnimeCatalogue(marvelWebSeriesCatalogue.catalogue)) openYenimeRequest(show.title, show.year, show.malId, 1, show.id);
                        else playCatalogueTvWithNexStream(show);
                      }} />
                    ))}
                  </div>
                  {renderFranchisePagination(marvelWebSeriesCatalogue.results.length)}
                </>
              )}
            </section>
          ) : regionalWebSeriesLoading ? (
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm text-slate-300">Loading web series catalogue…</div>
          ) : regionalWebSeriesError ? (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">{regionalWebSeriesError}</div>
          ) : regionalWebSeriesCatalogue ? (
            <div className="space-y-3">
              <div className="px-1 text-xs text-slate-400">{regionalWebSeriesCatalogue.totalResults.toLocaleString()} web series · Page {regionalWebSeriesCatalogue.page} of {regionalWebSeriesCatalogue.totalPages.toLocaleString()} · Metadata by TMDB</div>
              <div className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:gap-4">
                {regionalWebSeriesCatalogue.results.map(show => (
                  <TvShowCard key={String(show.id)} show={show} imdb={imdbRatingsByKey[imdbRatingKey(show.title, show.year, 'tv')]} onOpen={() => playCatalogueTvWithNexStream(show)} />
                ))}
              </div>
              {(() => {
                const goToRegionalPage = async (targetPage: number) => {
                  if (
                    regionalWebSeriesLoading
                    || targetPage < 1
                    || targetPage > regionalWebSeriesCatalogue.totalPages
                    || targetPage === regionalWebSeriesCatalogue.page
                  ) return;
                  setRegionalWebSeriesLoading(true);
                  setRegionalWebSeriesError('');
                  try {
                    const nextPage = await tvCataloguePageFromSectionCache(
                      section => api.getSectionCache(section),
                      regionalWebSeriesCatalogue.catalogue,
                      targetPage,
                    );
                    if (!nextPage) throw new Error('The requested TV subsection is missing from its section cache.');
                    setRegionalWebSeriesCatalogue(nextPage);
                  } catch (error: any) {
                    setRegionalWebSeriesError(String(error?.message || 'Could not load this page.'));
                  } finally {
                    setRegionalWebSeriesLoading(false);
                  }
                };
                return (
                  <div className="flex items-center justify-between gap-3">
                    <button type="button" disabled={regionalWebSeriesLoading || regionalWebSeriesCatalogue.page <= 1} onClick={() => void goToRegionalPage(regionalWebSeriesCatalogue.page - 1)} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-40">← Previous</button>
                    <span className="text-xs text-slate-500">Page {regionalWebSeriesCatalogue.page} of {regionalWebSeriesCatalogue.totalPages}</span>
                    <button type="button" disabled={regionalWebSeriesLoading || regionalWebSeriesCatalogue.page >= regionalWebSeriesCatalogue.totalPages} onClick={() => void goToRegionalPage(regionalWebSeriesCatalogue.page + 1)} className="rounded-lg border border-cyan-500/50 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-40">Next →</button>
                  </div>
                );
              })()}
            </div>
          ) : showDcWebSeries ? (
            <div className="space-y-3">
              {dcWebSeriesLoading && <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm text-slate-300">Loading DC web series…</div>}
              {dcWebSeriesError && <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">{dcWebSeriesError}</div>}
              {dcWebSeriesCatalogue && (
                <>
                  <div className="px-1 text-xs text-slate-400">{dcWebSeriesCatalogue.totalResults.toLocaleString()} DC web series · Page {dcWebSeriesCatalogue.page} of {dcWebSeriesCatalogue.totalPages.toLocaleString()} · Metadata by TMDB</div>
                  {renderDcWebSeriesPagination()}
                  <div className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:gap-4">
                    {dcWebSeriesCatalogue.results.map(show => (
                      <TvShowCard key={String(show.id)} show={show} imdb={imdbRatingsByKey[imdbRatingKey(show.title, show.year, 'tv')]} onOpen={() => playCatalogueTvWithNexStream(show)} />
                    ))}
                  </div>
                  {renderDcWebSeriesPagination()}
                </>
              )}
            </div>
          ) : showMarvelWebSeries ? (
            <div className="space-y-3">
              {marvelWebSeriesLoading && <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm text-slate-300">Loading {activeTopSection === 'classics' ? (classicsContentTab === 'anime' ? 'Classics anime' : 'Classics web series') : 'Marvel web series'}…</div>}
              {marvelWebSeriesError && <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">{marvelWebSeriesError}</div>}
              {marvelWebSeriesCatalogue && (
                <>
                  <div className="px-1 text-xs text-slate-400">{marvelWebSeriesCatalogue.totalResults.toLocaleString()} {activeTopSection === 'classics' ? (classicsContentTab === 'anime' ? 'Classics anime' : 'Classics web series') : 'Marvel web series'} · Page {marvelWebSeriesCatalogue.page} of {marvelWebSeriesCatalogue.totalPages.toLocaleString()} · Metadata by TMDB</div>
                  {renderFranchisePagination(marvelWebSeriesCatalogue.results.length)}
                  <div className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:gap-4">
                    {[...marvelWebSeriesCatalogue.results]
                      .filter(show => activeTopSection !== 'marvel' || !['iron man and his awesome friends', 'moon girl and devil dinosaur', 'moon girl and the devil dinosaur', 'spidey and his amazing friends'].includes(show.title.trim().toLowerCase()))
                      .sort(classicsComparator(classicsSort, show => releaseDateSortValue(show), show => ratingValue(imdbRatingsByKey[imdbRatingKey(show.title, show.year, 'tv')]), show => String(show.title || '')))
                      .slice((franchiseGridPage - 1) * franchiseGridPageSize, franchiseGridPage * franchiseGridPageSize)
                      .map(show => (
                      <TvShowCard key={String(show.id)} show={show} imdb={imdbRatingsByKey[imdbRatingKey(show.title, show.year, 'tv')]} onOpen={() => playCatalogueTvWithNexStream(show)} />
                    ))}
                  </div>
                  {renderFranchisePagination(marvelWebSeriesCatalogue.results.length)}
                  {marvelWebSeriesCatalogue.page < marvelWebSeriesCatalogue.totalPages && <button type="button" disabled={marvelWebSeriesLoading} onClick={async () => { setMarvelWebSeriesLoading(true); setMarvelWebSeriesError(''); try { const nextPage = await api.getTvCatalogue('marvel', marvelWebSeriesCatalogue.page + 1); setMarvelWebSeriesCatalogue(current => current ? { ...nextPage, page: nextPage.page, results: [...current.results, ...nextPage.results.filter(item => !current.results.some(existing => String(existing.id) === String(item.id)))].sort(compareReleaseDateDescending) } : nextPage); } catch (error: any) { setMarvelWebSeriesError(String(error?.message || 'Could not load more series.')); } finally { setMarvelWebSeriesLoading(false); } }} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-200 hover:border-cyan-500 disabled:opacity-50">Load more</button>}
                </>
              )}
            </div>
          ) : (
          <>
          {!movieCatalogue && movieTorrentPreviewGroup && (
            <section className="mb-3 overflow-hidden rounded-2xl border border-cyan-500/40 bg-slate-950 shadow-lg">
              <div className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
                <div className="min-w-0">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-cyan-300">Prepare card</div>
                  <h3 className="mt-1 truncate text-sm font-bold text-slate-100">{movieTorrentPreviewGroup.title}</h3>
                  <p className="mt-1 text-[11px] text-slate-400">Choose a release quality, then prepare it or try NexStream.</p>
                </div>
                <button type="button" onClick={() => { setMovieTorrentPreviewGroup(null); setMovieTorrentPreviewCatalogueId(null); setMovieTorrentSearchError(''); }} className="shrink-0 rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-slate-800 hover:text-white" aria-label="Close Prepare card">✕</button>
              </div>
              {(() => {
                const group = movieTorrentPreviewGroup;
                const selectedKey = selectedMovieTorrentQualityByGroup[group.key] || torrentResultKey(group.variants[0]);
                const result = group.variants.find(variant => torrentResultKey(variant) === selectedKey) || group.variants[0];
                const source = result.magnetUrl || result.downloadUrl || result.sourceUrl;
                const torrentKey = result.infoHash || source || result.title;
                const isPreparing = preparingTorrentKey === torrentKey;
                const preparedFiles = preparedForResult(result);
                const primaryFile = preparedFiles.find(file => /\\.(mkv|mp4|m4v|webm|mov|avi|m3u8|ts|mp3|wav|flac|aac|ogg|m4a)$/i.test(file.name)) || preparedFiles[0];
                const qualityLabel = torrentQualityDetails(result).label;
                return (
                  <div className="grid gap-3 p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                    <div className="min-w-0">
                      {group.variants.length > 1 ? (
                        <select aria-label={'Choose quality for ' + group.title} value={torrentResultKey(result)} onChange={event => setSelectedMovieTorrentQualityByGroup(previous => ({ ...previous, [group.key]: event.target.value }))} className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-200 outline-none focus:border-cyan-500">
                          {group.variants.map(variant => <option key={torrentResultKey(variant)} value={torrentResultKey(variant)}>{torrentQualityDetails(variant).label} · {formatBytes(Number(variant.size) || 0)} · ▲{Number(variant.seeders) || 0}{variant.indexer ? ' · ' + variant.indexer : ''}</option>)}
                        </select>
                      ) : <div className="text-xs font-semibold text-slate-200">{qualityLabel}</div>}
                      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-400">
                        <span>{formatBytes(Number(result.size) || 0)}</span><span className="text-emerald-400">▲ {Number(result.seeders) || 0} seeders</span><span className="text-amber-400">▼ {Number(result.leechers) || 0} peers</span>{result.indexer && <span>{result.indexer}</span>}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                      {preparedFiles.length > 0 && primaryFile ? (
                        <button type="button" onClick={async () => { setPlayingTorrentKey(torrentKey); try { await onPlaySeedrFile?.(primaryFile); } finally { setPlayingTorrentKey(current => current === torrentKey ? null : current); } }} disabled={playingTorrentKey === torrentKey} className="rounded-lg bg-emerald-400 px-4 py-2 text-xs font-bold text-slate-950 disabled:opacity-60">{playingTorrentKey === torrentKey ? 'Opening…' : 'Play'}</button>
                      ) : (
                        <button type="button" onClick={() => void prepareMovieTorrent(result)} disabled={!source || isPreparing} className="rounded-lg bg-cyan-500 px-4 py-2 text-xs font-bold text-slate-950 hover:bg-cyan-400 disabled:opacity-50">{isPreparing ? 'Preparing…' : 'Prepare'}</button>
                      )}
                      <button type="button" disabled={!Number(movieTorrentPreviewGroup.posterResult?.tmdbId || movieTorrentPreviewGroup.posterResult?.id) || nexStreamResolvingId === 'movie:' + String(movieTorrentPreviewGroup.posterResult?.tmdbId || movieTorrentPreviewGroup.posterResult?.id)} onClick={() => { const item = movieTorrentPreviewGroup.posterResult; const tmdbId = Number(item?.tmdbId || item?.id); if (!Number.isInteger(tmdbId) || tmdbId <= 0) { setNexStreamError('This catalogue card has no valid TMDB ID for NexStream.'); return; } void playWithNexStream({ id: tmdbId, title: item.title || movieTorrentPreviewGroup.title, date: item.releaseDate || (item.year ? String(item.year) : ''), overview: item.overview || '', poster: item.posterUrl || null, type: 'movie' }); }} className="rounded-lg border border-violet-400/50 bg-violet-500/15 px-4 py-2 text-xs font-bold text-violet-200 hover:bg-violet-500/25 disabled:opacity-50">{nexStreamResolvingId?.startsWith('movie:') ? 'Resolving…' : 'NexStream'}</button>
                    </div>
                  </div>
                );
              })()}
            </section>
          )}
          {!isSearching && renderFranchisePagination(Math.max(groupedResults.length, catalogueExpectedTitles))}
          <div
            className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:rounded-2xl lg:border-0 lg:bg-transparent lg:gap-4 lg:w-full lg:max-w-none lg:mx-0 lg:p-0 lg:divide-y-0 lg:overflow-visible"
          >
            {groupedResults.slice((franchiseGridPage - 1) * franchiseGridPageSize, franchiseGridPage * franchiseGridPageSize).map((group, index) => {
              const selectedKey = selectedQualityByGroup[group.key];
              const result = group.variants.find(variant => torrentResultKey(variant) === selectedKey) || group.variants[0];
              const posterResult = group.posterResult;
              const normalizedCardTitle = normalizeTorrentTitleForNexStream(group.title);
              const cardYear = Number((group.title.match(/\\b((?:19|20)\\d{2})\\b/) || [])[1] || group.year || 0);
              const titleMatches = nexStreamResults.filter(item => {
                if (item.type !== 'movie') return false;
                const candidateTitle = normalizeTorrentTitleForNexStream(item.title);
                const exactTitle = candidateTitle === normalizedCardTitle;
                const titleContains = candidateTitle.length >= 4 && normalizedCardTitle.length >= 4 &&
                  (normalizedCardTitle.startsWith(candidateTitle + ' ') || candidateTitle.startsWith(normalizedCardTitle + ' '));
                const yearMatches = !cardYear || !item.date || Number(String(item.date).slice(0, 4)) === cardYear;
                return (exactTitle || titleContains) && yearMatches;
              }).slice(0, 1);
              const seriesTitle = episodeSeriesTitle(group.title);
              const mediaMetadata = searchMetadataForGroup(group, searchMetadata);
              const mediaDisplayTitle = !seriesTitle && mediaMetadata?.title
                ? mediaMetadata.title
                : group.title.replace(/\s*\((?:19|20)\d{2}\)\s*$/, '');
              const mediaDisplayYear = !seriesTitle ? (mediaMetadata?.year || group.year) : group.year;
              const imdbDisplayTitle = seriesTitle ? (mediaMetadata?.title || seriesTitle) : mediaDisplayTitle;
              const imdbDisplayYear = seriesTitle ? mediaMetadata?.year : mediaDisplayYear;
              const imdbDisplayType = seriesTitle ? 'tv' as const : (mediaMetadata?.mediaType === 'tv' ? 'tv' as const : 'movie' as const);
              const displayImdbRating =
                imdbRatingsByKey[imdbRatingKey(imdbDisplayTitle, imdbDisplayYear, imdbDisplayType)] ||
                imdbRatingsByKey[imdbRatingKey(mediaMetadata?.title || imdbDisplayTitle, mediaMetadata?.year || imdbDisplayYear, imdbDisplayType)] ||
                imdbRatingsByKey[imdbRatingKey(group.title, group.year, imdbDisplayType)];
              const imdbTitleHref = imdbTitleLink(displayImdbRating, imdbDisplayTitle || mediaDisplayTitle, imdbDisplayYear);
              const groupPosterKey = posterKeyFor(posterResult);
              // Never trust an unrelated catalogue/indexer poster. Use the title-and-year
              // resolver result (exact title match) or the card's own metadata poster.
              // While that resolver is still working, show the poster of the same TMDB
              // title the card's synopsis comes from, so no card sits blank.
              // TMDB-id based metadata poster first (same title as the synopsis), then the
              // title+year resolver. If the metadata poster fails to load, the resolver takes over.
              const loadedSearchPosterUrl = searchPosterUrlsRef.current[groupPosterKey] || '';
              const metadataPosterUrl = mediaMetadata?.posterUrl && !metadataPosterFailed[groupPosterKey]
                ? mediaMetadata.posterUrl
                : '';
              // Give the image an immediate same-origin resolver URL instead of
              // waiting for the background JSON lookup to finish before loading
              // its first thumbnail. The backend's poster map makes common
              // title/year lookups a fast redirect to the image CDN.
              const sharedPosterUrl = loadedSearchPosterUrl ||
                metadataPosterUrl ||
                posterOverrides[groupPosterKey] ||
                posterResult?.posterUrl ||
                posterImageUrlForResult(posterResult);

              // Normal searches use a poster-first two-state card. Clicking the poster
              // opens the Prepare/details card; clicking it again returns here.
              if (expandedSearchGroupKey !== group.key) {
                const availability = searchAvailabilityByGroup[group.key];
                const providerMatchTitle = episodeSeriesTitle(group.title) || group.title;
                const groupTitleKey = normalizeSavedOttTitle(providerMatchTitle);
                const matchingSavedTitles = (availability?.matches || []).filter(match =>
                  Array.isArray(match.providers) &&
                  match.providers.length > 0 &&
                  normalizeSavedOttTitle(String(match.title || '')) === groupTitleKey
                );
                const compactProviders = uniqueOttProviders(
                  matchingSavedTitles.length > 0
                    ? matchingSavedTitles.flatMap(match => match.providers)
                    : (availability?.providers || [])
                );
                return (
                  <MovieCompactCard
                    key={group.key || (group.title + '-' + index)}
                    title={mediaDisplayTitle}
                    titleHref={imdbTitleHref}
                    year={mediaDisplayYear}
                    imdb={displayImdbRating}
                    tmdbRating={mediaMetadata?.rating}
                    overview={
                      mediaMetadata?.overview ||
                      (searchMetadataStatus === 'loading'
                        ? 'Loading synopsis from TMDB…'
                        : searchMetadataStatus === 'unavailable'
                          ? 'TMDB synopsis is temporarily unavailable.'
                          : 'No synopsis available from TMDB for this title.')
                    }
                    posterSrc={lowQualityPosterUrl(sharedPosterUrl)}
                    posterAlt={mediaDisplayTitle}
                    onPosterClick={() => {
                      if (pendingPosterAction) return;
                      if (!posterFirstPageReadyRef.current) {
                        setPendingPosterAction({
                          kind: 'search',
                          groupKey: group.key,
                          page: franchiseGridPage,
                        });
                        return;
                      }
                      setExpandedSearchGroupKey(group.key);
                    }}
                    onPosterLoad={event => {
                      const key = posterKeyFor(posterResult);
                      searchPosterUrlsRef.current[key] = event.currentTarget.currentSrc || event.currentTarget.src;
                      posterLoadedRef.current.add(key);
                      event.currentTarget.style.display = '';
                      event.currentTarget.parentElement?.querySelector('[data-poster-placeholder="true"]')?.classList.add('hidden');
                    }}
                    onPosterError={event => {
                      const image = event.currentTarget;
                      // Do not fall back to catalogue artwork here: metadata sources can
                      // attach a poster for a different title/remake. Retry the strict
                      // title-and-year resolver instead.
                      const key = posterKeyFor(posterResult);
                      delete searchPosterUrlsRef.current[key];
                      posterLoadedRef.current.delete(key);
                      setMetadataPosterFailed(previous => previous[key] ? previous : { ...previous, [key]: true });
                      image.style.display = 'none';
                      image.parentElement?.querySelector('[data-poster-placeholder="true"]')?.classList.remove('hidden');

                      // Match the expanded card's retry path; do not leave a blank black poster
                      // slot just because the first image request failed.
                      if (!posterBackgroundQueuedRef.current.has(key)) {
                        posterBackgroundQueuedRef.current.add(key);
                        posterBackgroundQueueRef.current.unshift({ key, result: posterResult });
                        startPosterBackgroundWorkers();
                      }
                    }}
                    providers={toCardProviders(compactProviders)}
                    providersAriaLabel={'Streaming services for ' + group.title}
                    providersFallbackText={
                      availability?.status === 'loading'
                        ? 'Checking streaming services…'
                        : availability?.status === 'unavailable'
                          ? 'Streaming availability temporarily unavailable'
                          : availability?.status === 'not_confirmed'
                            ? 'Streaming providers not confirmed'
                            : availability?.status === 'ready'
                              ? 'No streaming providers reported'
                              : searchMetadataStatus === 'loading'
                                ? 'Checking streaming availability…'
                                : 'Streaming providers not listed'
                    }
                  />
                );
              }

              const prepareState = prepareStateFor(result);
              return (
                <MoviePrepareCard
                  key={group.key || (group.title + '-' + index)}
                  className="z-0"
                  posterSrc={loadedSearchPosterUrl || lowQualityPosterUrl(sharedPosterUrl)}
                  posterAlt={group.title}
                  providers={toCardProviders(uniqueOttProviders(
                    (searchAvailabilityByGroup[group.key]?.matches || [])
                      .filter(match => Array.isArray(match.providers) && match.providers.length > 0 &&
                        normalizeSavedOttTitle(String(match.title || '')) === normalizeSavedOttTitle(episodeSeriesTitle(group.title) || group.title))
                      .flatMap(match => match.providers)
                  ))}
                  onPosterClick={() => setExpandedSearchGroupKey(null)}
                  onPosterLoad={event => {
                    const key = posterKeyFor(posterResult);
                    searchPosterUrlsRef.current[key] = event.currentTarget.currentSrc || event.currentTarget.src;
                    posterLoadedRef.current.add(key);
                    event.currentTarget.style.display = '';
                    event.currentTarget.parentElement?.querySelector('[data-poster-placeholder="true"]')?.classList.add('hidden');
                  }}
                  onPosterError={event => {
                    const key = posterKeyFor(posterResult);
                    delete searchPosterUrlsRef.current[key];
                    posterLoadedRef.current.delete(key);
                    setMetadataPosterFailed(previous => previous[key] ? previous : { ...previous, [key]: true });
                    event.currentTarget.style.display = 'none';
                    event.currentTarget.parentElement?.querySelector('[data-poster-placeholder="true"]')?.classList.remove('hidden');

                    if (
                      !posterBackgroundQueuedRef.current.has(key) &&
                      !posterOverrides[key]
                    ) {
                      posterBackgroundQueuedRef.current.add(key);
                      posterBackgroundQueueRef.current.unshift({ key, result: posterResult });
                      startPosterBackgroundWorkers();
                    }
                  }}
                  imdb={displayImdbRating}
                  seeders={result.seeders}
                  indexer={result.indexer}
                  quality={extractedQuality(result)}
                  title={mediaDisplayTitle}
                  titleHref={imdbTitleHref}
                  year={mediaMetadata?.year || group.year}
                  onClose={() => setExpandedSearchGroupKey(null)}
                  variants={group.variants.map(variant => {
                    const quality = torrentQualityDetails(variant);
                    const provider = String(variant.indexer || '').trim();
                    const size = formatBytes(Number(variant.size) || 0);
                    const seeds = Number(variant.seeders) || 0;
                    return {
                      key: torrentResultKey(variant),
                      label: `${quality.label} · ${size} · ▲${seeds}${provider ? ` · ${provider}` : ''}`,
                    };
                  })}
                  selectedVariantKey={torrentResultKey(result)}
                  onSelectVariant={key => setSelectedQualityByGroup(previous => ({ ...previous, [group.key]: key }))}
                  variantsAriaLabel={`Choose quality for ${group.title}`}
                  prepared={prepareState.primaryFile ? preparedActionsFor(prepareState.torrentKey, prepareState.primaryFile) : null}
                  prepare={{
                    isPreparing: prepareState.isPreparing,
                    disabled: !prepareState.source || prepareState.isPreparing,
                    onClick: () => void prepareMovieTorrent(result),
                  }}
                  directStream={{
                    disabled: nexStreamResolvingId !== null || (nexStreamLoading && normalizeGroupTitle(nexStreamLoadingTitle) === normalizeGroupTitle(mediaDisplayTitle || group.title)),
                    label: nexStreamResolvingId !== null
                      ? 'Resolving…'
                      : nexStreamLoading && normalizeGroupTitle(nexStreamLoadingTitle) === normalizeGroupTitle(mediaDisplayTitle || group.title)
                        ? 'Searching…'
                        : 'Direct Stream',
                    onClick: () => {
                      if (titleMatches.length > 0) {
                        void playWithNexStream(titleMatches[0]);
                        return;
                      }
                      const tmdbId = Number(mediaMetadata?.tmdbId || mediaMetadata?.id);
                      if (Number.isInteger(tmdbId) && tmdbId > 0) {
                        void playWithNexStream({
                          id: tmdbId,
                          title: mediaDisplayTitle || group.title,
                          date: String(mediaMetadata?.year || group.year || ''),
                          overview: mediaMetadata?.overview || '',
                          poster: mediaMetadata?.posterUrl || null,
                          type: 'movie',
                        });
                      } else {
                        void searchNexStreamTitles(mediaDisplayTitle || group.title, 'movie');
                      }
                    },
                  }}
                />
              );
            })}
          </div>
          {!isSearching && renderFranchisePagination(Math.max(groupedResults.length, catalogueExpectedTitles))}
          </>
          )}
        </div>
      )}

    </>
  );
}
