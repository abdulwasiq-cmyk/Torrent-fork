import { Search, X } from 'lucide-react';
import { MarvelFilmFilter, RegionalCatalogueMode, RegionalTvGroup } from '../types.ts';
import { nextClassicsSort, DEFAULT_CLASSICS_SORT } from '../classicsSort.ts';
import type { PanelModel } from '../useTorrentSearchPanel.tsx';

export function SearchBarSection({ vm }: { vm: PanelModel }) {
  const { activeTopSection, cancelSearch, classicsContentTab, classicsSort, setClassicsSort, dcContentTab, error, isSearching, loadClassicsTvCatalogue, loadDcWebSeries, loadMarvelWebSeries, marvelContentTab, marvelFilmFilter, marvelWebSeriesCatalogue, movieCatalogue, nexStreamLoading, openMovieCatalogue, openRegionalCatalogue, openRegionalTvCatalogue, query, recentSearchRef, recentSearches, regionalCatalogueModes, regionalContentTabs, regionalTvModes, regionalWebSeriesCatalogue, runSearch, searchNexStreamTitles, selectCachedFranchise, selectHighestRatedSection, setActiveTopSection, setCatalogueSort, setClassicsContentTab, setDcContentTab, setError, setFranchiseGridPage, setMarvelContentTab, setMarvelFilmFilter, setMovieCatalogue, setNexStreamError, setNexStreamSearchMode, setQuery, setRecentSearches, setRegionalContentTabs, setResolutionFilter, setResults, setSearched, setShowDcWebSeries, setShowMarvelWebSeries, setShowRecentSearches, setSizeSort, setTimeSort, showDcWebSeries, showMarvelWebSeries, showRecentSearches, } = vm;
  const topSectionClass = (section: 'marvel' | 'dc' | 'hollywood' | 'bollywood' | 'korean' | 'pakistani' | 'anime' | 'classics' | 'highest-rated') => activeTopSection === section
    ? 'rounded-lg border border-cyan-400 bg-cyan-500 px-3 py-1.5 text-xs font-bold text-slate-950 shadow-[0_0_12px_rgba(34,211,238,0.35)]'
    : 'rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:border-cyan-500 hover:text-cyan-300';
  return (
    <>
      <div className="p-2.5 sm:p-5 rounded-xl sm:rounded-2xl bg-slate-900 border border-slate-800">
        <div className="flex flex-col gap-1">
          <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <Search className="w-5 h-5 text-cyan-400" />
            Search Torrents
          </h2>
        </div>

        <form data-torrent-search="true" onSubmit={runSearch} className="mt-2.5 sm:mt-4 flex flex-row gap-1.5 sm:gap-2">
          <div ref={recentSearchRef} className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              value={query}
              onFocus={() => {
                if (recentSearches.length > 0) setShowRecentSearches(true);
              }}
              onChange={(e) => {
                setQuery(e.target.value);
                if (error) setError('');
                if (recentSearches.length > 0) setShowRecentSearches(true);
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  setShowRecentSearches(false);
                }
              }}
              placeholder="Search movies, TV, music, software..."
              className="w-full pl-9 pr-10 py-2 sm:py-2.5 rounded-lg sm:rounded-xl bg-slate-950 border border-slate-800 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/20"
            />
            {query && (
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  setQuery('');
                  setError('');
                  setMovieCatalogue(null);
                  setSearched(false);
                  setResults([]);
                  setShowRecentSearches(recentSearches.length > 0);
                }}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition"
                title="Clear search"
                aria-label="Clear search"
              >
                <X className="w-4 h-4" />
              </button>
            )}

            {showRecentSearches && recentSearches.length > 0 && (
              <div className="absolute left-0 right-0 top-full mt-2 z-30 rounded-xl border border-slate-700 bg-slate-900 shadow-2xl overflow-hidden">
                <div className="px-3 py-2 border-b border-slate-800">
                  <span className="text-[11px] font-semibold text-slate-400">Recent Searches</span>
                </div>
                <div className="max-h-72 overflow-y-auto">
                  {recentSearches.slice(0, 7).map((search, index) => (
                    <div
                      key={search}
                      className="flex items-center gap-1 border-b border-slate-800/70 last:border-b-0 hover:bg-slate-800 transition"
                    >
                      <button
                        type="button"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => {
                          setQuery(search);
                          setError('');
                          setShowRecentSearches(false);
                        }}
                        className="min-w-0 flex-1 px-3 py-2.5 text-left flex items-center gap-2.5 active:bg-slate-700 transition"
                      >
                        <span className="w-5 h-5 shrink-0 rounded-md bg-slate-800 text-slate-500 text-[10px] font-bold flex items-center justify-center">
                          {index + 1}
                        </span>
                        <span className="truncate text-xs text-slate-200">{search}</span>
                      </button>

                      <button
                        type="button"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => {
                          setRecentSearches(prev => {
                            const next = prev.filter(item => item !== search);
                            try {
                              localStorage.setItem('seedflow_recent_searches', JSON.stringify(next));
                            } catch {}
                            return next;
                          });
                        }}
                        className="mr-2 p-1.5 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-slate-700 transition shrink-0"
                        title="Delete recent search"
                        aria-label={`Delete recent search: ${search}`}
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <button
            type={isSearching || nexStreamLoading ? 'button' : 'submit'}
            onClick={isSearching || nexStreamLoading ? cancelSearch : undefined}
            aria-label={isSearching || nexStreamLoading ? 'Cancel search' : 'Movie Search'}
            title={isSearching || nexStreamLoading ? 'Cancel search' : 'Movie Search'}
            className={[
              'group relative isolate overflow-hidden w-auto min-h-10 px-3 sm:px-5 py-2 rounded-xl text-xs font-bold inline-flex items-center justify-center gap-2 transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950 active:scale-[0.97]',
              isSearching || nexStreamLoading
                ? 'border border-rose-300/70 bg-rose-500 text-white shadow-[0_0_0_1px_rgba(244,63,94,0.18),0_0_18px_rgba(244,63,94,0.20)] hover:bg-rose-400 hover:shadow-[0_0_24px_rgba(244,63,94,0.34)] focus-visible:ring-rose-300'
                : 'border border-cyan-300/60 bg-cyan-400 text-slate-950 shadow-[0_0_0_1px_rgba(34,211,238,0.12)] hover:-translate-y-0.5 hover:border-cyan-200 hover:bg-cyan-300 hover:shadow-[0_0_22px_rgba(34,211,238,0.36)] focus-visible:ring-cyan-300'
            ].join(' ')}
          >
            <span className="pointer-events-none absolute inset-0 -z-10 rounded-xl opacity-0 transition-opacity duration-200 group-hover:opacity-100"
              style={{ background: (isSearching || nexStreamLoading) ? 'linear-gradient(110deg, rgba(255,255,255,0.10), transparent 55%)' : 'linear-gradient(110deg, rgba(255,255,255,0.24), transparent 55%)' }}
            />
            {isSearching || nexStreamLoading ? (
              <>
                <X className="h-4 w-4 shrink-0 transition-transform duration-200 group-hover:rotate-90" />
                <span className="hidden sm:inline">Cancel</span>
              </>
            ) : (
              <>
                <Search className="h-4 w-4 shrink-0 transition-transform duration-200 group-hover:scale-110" />
                <span>Movie Search</span>
              </>
            )}
          </button>
          <button type="button" onClick={() => { const trimmed = query.trim(); if (trimmed.length < 2) { setNexStreamError('Enter at least 2 characters to search.'); return; } void searchNexStreamTitles(trimmed, 'tv', true); }} className="shrink-0 rounded-xl border border-violet-400/60 bg-violet-500/15 px-3 py-2 text-xs font-bold text-violet-200 hover:bg-violet-500/25">Series Search</button>
        </form>

        <div className="mt-2 flex flex-wrap gap-2" aria-label="Movie catalogues">
          <button type="button" onClick={() => { setFranchiseGridPage(1); setClassicsSort(DEFAULT_CLASSICS_SORT); setActiveTopSection('marvel'); setMarvelContentTab('movies'); setShowMarvelWebSeries(false); setShowDcWebSeries(false); setMarvelFilmFilter('all'); selectCachedFranchise('marvel'); }} className={topSectionClass('marvel')} aria-pressed={activeTopSection === 'marvel'}>🦸 Marvel</button>
          <button type="button" onClick={() => { setFranchiseGridPage(1); setClassicsSort(DEFAULT_CLASSICS_SORT); setActiveTopSection('dc'); setDcContentTab('movies'); setShowDcWebSeries(false); selectCachedFranchise('dc-live-action'); }} className={topSectionClass('dc')} aria-pressed={activeTopSection === 'dc'}>🦇 DC</button>
          <button type="button" onClick={() => { setFranchiseGridPage(1); setClassicsSort(DEFAULT_CLASSICS_SORT); setActiveTopSection('hollywood'); setRegionalContentTabs(previous => ({ ...previous, hollywood: 'movies' })); openRegionalCatalogue('hollywood', 'popular'); }} className={topSectionClass('hollywood')} aria-pressed={activeTopSection === 'hollywood'}>🎥 Hollywood</button>
          <button type="button" onClick={() => { setFranchiseGridPage(1); setClassicsSort(DEFAULT_CLASSICS_SORT); setActiveTopSection('bollywood'); setRegionalContentTabs(previous => ({ ...previous, bollywood: 'movies' })); openRegionalCatalogue('bollywood', 'popular'); }} className={topSectionClass('bollywood')} aria-pressed={activeTopSection === 'bollywood'}>🎬 Bollywood</button>
          <button type="button" onClick={() => { setFranchiseGridPage(1); setActiveTopSection('anime'); setRegionalContentTabs(previous => ({ ...previous, anime: 'movies' })); openRegionalCatalogue('anime', 'popular'); }} className={topSectionClass('anime')} aria-pressed={activeTopSection === 'anime'}>⛩️ Anime</button>
          <button type="button" onClick={selectHighestRatedSection} className={topSectionClass('highest-rated')} aria-pressed={activeTopSection === 'highest-rated'}>🏆 Highest Rated</button>
          <button type="button" onClick={() => { setFranchiseGridPage(1); setActiveTopSection('pakistani'); setRegionalContentTabs(previous => ({ ...previous, pakistani: 'web-series' })); void openRegionalTvCatalogue('pakistani', regionalTvModes.pakistani); }} className={topSectionClass('pakistani')} aria-pressed={activeTopSection === 'pakistani'}>🇵🇰 Pakistani</button>
          <button type="button" onClick={() => { setFranchiseGridPage(1); setActiveTopSection('korean'); setRegionalContentTabs(previous => ({ ...previous, korean: 'movies' })); openRegionalCatalogue('korean', 'popular'); }} className={topSectionClass('korean')} aria-pressed={activeTopSection === 'korean'}>🇰🇷 Korean</button>
          <button type="button" onClick={() => { setFranchiseGridPage(1); setActiveTopSection('classics'); setClassicsContentTab('movies'); setClassicsSort(DEFAULT_CLASSICS_SORT); setResolutionFilter(null); setSizeSort(null); setTimeSort(null); void runSearch(undefined, 'Classics', 'classics'); }} className={topSectionClass('classics')} aria-pressed={activeTopSection === 'classics'}>⭐ Favourites</button>
        </div>
        {activeTopSection !== null && <>
          <div className="mt-2 flex flex-wrap gap-2 rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-2.5" aria-label={activeTopSection + ' subsections'}>
            {activeTopSection === 'marvel' && <>
              <button type="button" onClick={() => { setFranchiseGridPage(1); setMarvelContentTab('movies'); setShowMarvelWebSeries(false); setMarvelFilmFilter('all'); selectCachedFranchise('marvel'); }} className={marvelContentTab === 'movies' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'}>🎬 Marvel Movies</button>
              <button type="button" onClick={() => { setFranchiseGridPage(1); setMarvelContentTab('web-series'); if (!showMarvelWebSeries || marvelWebSeriesCatalogue?.catalogue !== 'marvel-web-series') void loadMarvelWebSeries(); }} className={marvelContentTab === 'web-series' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'}>📺 Marvel Web Series</button>
            </>}
            {activeTopSection === 'dc' && <>
              <button type="button" onClick={() => { setFranchiseGridPage(1); setDcContentTab('movies'); setShowDcWebSeries(false); selectCachedFranchise('dc-live-action'); }} className={dcContentTab === 'movies' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'} aria-pressed={dcContentTab === 'movies'}>DC Movies</button>
              <button type="button" onClick={() => { setFranchiseGridPage(1); setDcContentTab('animated'); setResolutionFilter(null); setSizeSort(null); setTimeSort(null); setShowDcWebSeries(false); void runSearch(undefined, 'DC Animated Movies', 'dc-animated'); }} className={dcContentTab === 'animated' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'} aria-pressed={dcContentTab === 'animated'}>DC Animated</button>
              <button type="button" onClick={() => { setFranchiseGridPage(1); setDcContentTab('web-series'); if (showDcWebSeries) setShowDcWebSeries(false); else void loadDcWebSeries(); }} className={dcContentTab === 'web-series' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'} aria-pressed={dcContentTab === 'web-series'}>📺 DC Web Series</button>
            </>}
            {(activeTopSection === 'hollywood' || activeTopSection === 'bollywood' || activeTopSection === 'korean' || activeTopSection === 'pakistani' || activeTopSection === 'anime') && <>
              {activeTopSection !== 'pakistani' && <button type="button" onClick={() => { setRegionalContentTabs(previous => ({ ...previous, [activeTopSection]: 'movies' })); openRegionalCatalogue(activeTopSection, (activeTopSection === 'korean' || activeTopSection === 'anime') ? 'popular' : regionalCatalogueModes[activeTopSection]); }} className={regionalContentTabs[activeTopSection] === 'movies' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800'}>{({ hollywood: '🎬 Hollywood Movies', bollywood: '🎬 Bollywood Movies', korean: '🎬 Korean Movies', anime: '🎬 Anime Movies' } as Record<string, string>)[activeTopSection] || '🎬 Movies'}</button>}
              <button type="button" onClick={() => { const group = (activeTopSection === 'bollywood' ? 'indian' : activeTopSection) as RegionalTvGroup; setRegionalContentTabs(previous => ({ ...previous, [activeTopSection]: 'web-series' })); void openRegionalTvCatalogue(group, (activeTopSection === 'korean' || activeTopSection === 'anime') ? 'popular' : regionalTvModes[group]); }} className={regionalContentTabs[activeTopSection] === 'web-series' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800'}>{({ hollywood: '📺 English Web Series', bollywood: '📺 Indian Web Series', korean: '📺 Korean Dramas', pakistani: '📺 Pakistani Dramas', anime: '📺 Anime Series' } as Record<string, string>)[activeTopSection] || '📺 Web Series'}</button>
            </>}
            {activeTopSection === 'highest-rated' && <>
              <button type="button" aria-pressed={movieCatalogue?.catalogue === 'highest-rated-hollywood'} onClick={() => { setCatalogueSort('popularity'); setResolutionFilter(null); setSizeSort(null); setTimeSort(null); void openMovieCatalogue('highest-rated-hollywood', 'Highest Rated Hollywood', 1); }} className={movieCatalogue?.catalogue === 'highest-rated-hollywood' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-300 border border-slate-800 hover:border-cyan-500'}>🎥 Hollywood</button>
              <button type="button" aria-pressed={movieCatalogue?.catalogue === 'highest-rated-bollywood'} onClick={() => { setCatalogueSort('popularity'); setResolutionFilter(null); setSizeSort(null); setTimeSort(null); void openMovieCatalogue('highest-rated-bollywood', 'Highest Rated Bollywood', 1); }} className={movieCatalogue?.catalogue === 'highest-rated-bollywood' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-300 border border-slate-800 hover:border-cyan-500'}>🎬 Bollywood</button>
              <button type="button" aria-pressed={regionalWebSeriesCatalogue?.catalogue.startsWith('highest-rated-') === true} onClick={() => { setCatalogueSort('popularity'); setFranchiseGridPage(1); setRegionalContentTabs(previous => ({ ...previous, bollywood: null })); void openRegionalTvCatalogue('highest-rated', 'popular', 1); }} className={regionalWebSeriesCatalogue?.catalogue.startsWith('highest-rated-') ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-300 border border-slate-800 hover:border-cyan-500'}>📺 TV Shows</button>
            </>}
            {activeTopSection === 'classics' && <>
              <button type="button" onClick={() => { setFranchiseGridPage(1); setClassicsSort(DEFAULT_CLASSICS_SORT); setClassicsContentTab('movies'); setShowMarvelWebSeries(false); setShowDcWebSeries(false); setResolutionFilter(null); setSizeSort(null); setTimeSort(null); void runSearch(undefined, 'Classics', 'classics'); }} className={classicsContentTab === 'movies' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'}>🎬 Movies</button>
              <button type="button" onClick={() => { setFranchiseGridPage(1); setClassicsSort(DEFAULT_CLASSICS_SORT); setNexStreamError(''); setNexStreamSearchMode(null); void loadClassicsTvCatalogue('classics-web-series', 'web-series'); }} className={classicsContentTab === 'web-series' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'}>📺 Web Series</button>
              <button type="button" onClick={() => { setFranchiseGridPage(1); setClassicsSort(DEFAULT_CLASSICS_SORT); setNexStreamError(''); setNexStreamSearchMode(null); void loadClassicsTvCatalogue('classics-anime', 'anime'); }} className={classicsContentTab === 'anime' ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'}>⛩️ Anime</button>
            </>}
          </div>
          {(activeTopSection === 'marvel' || activeTopSection === 'dc' || activeTopSection === 'classics') && <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/70 px-2.5 py-2.5" aria-label="Sort">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Sort by</span>
            {(['year', 'rating'] as const).map(sortKey => {
              const active = classicsSort.key === sortKey;
              const arrow = active ? (classicsSort.direction === 'desc' ? ' ↓' : ' ↑') : ' ↓';
              return <button key={sortKey} type="button" aria-pressed={active} title={active ? 'Click to reverse the order' : 'Sort by ' + sortKey + ', ' + (sortKey === 'year' ? 'newest' : 'highest') + ' first'} onClick={() => { setFranchiseGridPage(1); setClassicsSort(nextClassicsSort(classicsSort, sortKey)); }} className={active ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'}>{sortKey === 'year' ? 'Year' : 'Rating'}{arrow}</button>;
            })}
          </div>}
          {activeTopSection === 'marvel' && marvelContentTab === 'movies' && <div className="mt-2 flex flex-wrap gap-2 rounded-lg border border-slate-800 bg-slate-950/70 px-2.5 py-2.5" aria-label="Marvel movie filters">
            {([['all','All'],['mcu','MCU'],['sony','Spiderman'],['x-men','X-Men']] as [MarvelFilmFilter,string][]).map(([filter,label]) => <button key={filter} type="button" onClick={() => { setFranchiseGridPage(1); setMarvelFilmFilter(filter); }} className={marvelFilmFilter === filter ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800 hover:text-slate-200'} aria-pressed={marvelFilmFilter === filter}>{label}</button>)}
          </div>}
          {(activeTopSection === 'hollywood' || activeTopSection === 'bollywood' || activeTopSection === 'korean' || activeTopSection === 'pakistani' || activeTopSection === 'anime') && activeTopSection !== 'pakistani' && !(['korean', 'anime'] as string[]).includes(activeTopSection) && regionalContentTabs[activeTopSection] !== null && <div className="mt-2 flex flex-wrap gap-2 rounded-lg border border-slate-800 bg-slate-950/70 px-2.5 py-2.5" aria-label={activeTopSection + ' ' + regionalContentTabs[activeTopSection] + ' filters'}>
            {(['popular','trending','latest'] as RegionalCatalogueMode[]).map(mode => regionalContentTabs[activeTopSection] === 'movies'
              ? <button key={mode} type="button" onClick={() => openRegionalCatalogue(activeTopSection, mode)} className={regionalCatalogueModes[activeTopSection] === mode ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800'} aria-pressed={regionalCatalogueModes[activeTopSection] === mode}>{mode.charAt(0).toUpperCase()+mode.slice(1)}</button>
              : <button key={mode} type="button" onClick={() => { const group = activeTopSection === 'bollywood' ? 'indian' : activeTopSection; void openRegionalTvCatalogue(group, mode); }} className={regionalTvModes[(activeTopSection === 'bollywood' ? 'indian' : activeTopSection) as RegionalTvGroup] === mode ? 'rounded-lg px-3 py-2 text-xs font-bold bg-cyan-500 text-slate-950' : 'rounded-lg px-3 py-2 text-xs font-bold bg-slate-950 text-slate-400 border border-slate-800'} aria-pressed={regionalTvModes[activeTopSection === 'bollywood' ? 'indian' : 'hollywood'] === mode}>{mode.charAt(0).toUpperCase()+mode.slice(1)}</button>)}
          </div>}
        </>}
      </div>
    </>
  );
}
