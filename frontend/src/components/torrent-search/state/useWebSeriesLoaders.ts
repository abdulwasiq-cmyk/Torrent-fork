import { api } from '../../../api/client.ts';
import { tvCataloguePageFromSection, tvCatalogueSection } from '../../../api/sectionCache.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useWebSeriesState } from './useWebSeriesState.ts';
import { useSearchInputState } from './useSearchInputState.ts';

async function loadTvCataloguePage(catalogue: string, page = 1) {
  const section = tvCatalogueSection(catalogue);
  if (!section) return api.getTvCatalogue(catalogue, page);
  const document = await api.getSectionCache(section.section);
  const result = tvCataloguePageFromSection(document, catalogue, section.subsection, page);
  if (!result) throw new Error('The requested TV subsection is missing from its section cache.');
  return result;
}

export function useWebSeriesLoaders({
  searchGenerationRef,
  dcWebSeriesRequestGenerationRef,
  setShowDcWebSeries,
  setDcWebSeriesLoading,
  setDcWebSeriesError,
  setDcWebSeriesCatalogue,
  setShowMarvelWebSeries,
  setClassicsContentTab,
  marvelWebSeriesCatalogue,
  marvelWebSeriesLoading,
  setMarvelWebSeriesCatalogue,
  setMarvelWebSeriesLoading,
  setMarvelWebSeriesError,
  setIsSearching,
  setSearched,
  setError,
  setMovieCatalogue,
  setActiveFranchiseSearchMode,
  setFranchiseGridPage,
  setCatalogueExpectedTitles,
  setResults,
  searchRequestRef,
  franchisePageRequestRef,
}: {
  searchGenerationRef: { current: number };
  dcWebSeriesRequestGenerationRef: { current: number };
  searchRequestRef: { current: AbortController | null };
  franchisePageRequestRef: { current: AbortController | null };
} & Pick<ReturnType<typeof useWebSeriesState>,
  | 'setShowDcWebSeries'
  | 'setDcWebSeriesLoading'
  | 'setDcWebSeriesError'
  | 'setDcWebSeriesCatalogue'
  | 'marvelWebSeriesCatalogue'
  | 'marvelWebSeriesLoading'
  | 'setMarvelWebSeriesCatalogue'
  | 'setMarvelWebSeriesLoading'
  | 'setMarvelWebSeriesError'
> & Pick<ReturnType<typeof useCatalogueNavigationState>,
  | 'setShowMarvelWebSeries'
  | 'setClassicsContentTab'
  | 'setIsSearching'
  | 'setSearched'
  | 'setError'
  | 'setMovieCatalogue'
  | 'setActiveFranchiseSearchMode'
  | 'setFranchiseGridPage'
  | 'setCatalogueExpectedTitles'
> & {
  setResults: ReturnType<typeof useSearchInputState>['setResults'];
}) {
  const loadDcWebSeriesPage = async (page: number) => {
    const generation = ++searchGenerationRef.current;
    const requestGeneration = ++dcWebSeriesRequestGenerationRef.current;
    setDcWebSeriesLoading(true);
    setDcWebSeriesError('');
    try {
      const cataloguePage = await loadTvCataloguePage('dc-live-action', page);
      if (
        generation === searchGenerationRef.current
        && requestGeneration === dcWebSeriesRequestGenerationRef.current
      ) {
        setDcWebSeriesCatalogue(cataloguePage);
      }
    } catch (error: any) {
      if (
        generation === searchGenerationRef.current
        && requestGeneration === dcWebSeriesRequestGenerationRef.current
      ) {
        setDcWebSeriesError(String(error?.message || 'Could not load DC web series.'));
      }
    } finally {
      if (requestGeneration === dcWebSeriesRequestGenerationRef.current) {
        setDcWebSeriesLoading(false);
      }
    }
  };

  const loadDcWebSeries = async () => {
    setShowDcWebSeries(true);
    setShowMarvelWebSeries(false);
    searchRequestRef.current?.abort();
    searchRequestRef.current = null;
    franchisePageRequestRef.current?.abort();
    franchisePageRequestRef.current = null;
    searchGenerationRef.current += 1;
    setIsSearching(false);
    setSearched(false);
    setError('');
    setResults([]);
    setMovieCatalogue(null);
    setActiveFranchiseSearchMode(null);
    setFranchiseGridPage(1);
    setCatalogueExpectedTitles(0);
    setDcWebSeriesCatalogue(null);
    setDcWebSeriesError('');
    // Fetch every page up front, like Marvel and Classics, so the Sort buttons order the
    // whole section and the page buttons slice the sorted list.
    const generation = searchGenerationRef.current;
    const requestGeneration = ++dcWebSeriesRequestGenerationRef.current;
    setDcWebSeriesLoading(true);
    try {
      const firstPage = await loadTvCataloguePage('dc-live-action', 1);
      const allResults = [...firstPage.results];
      for (let page = 2; page <= Math.min(firstPage.totalPages, 500); page += 1) {
        if (generation !== searchGenerationRef.current || requestGeneration !== dcWebSeriesRequestGenerationRef.current) return;
        const nextPage = await loadTvCataloguePage('dc-live-action', page);
        for (const show of nextPage.results) {
          if (!allResults.some(existing => String(existing.id) === String(show.id))) allResults.push(show);
        }
      }
      if (generation === searchGenerationRef.current && requestGeneration === dcWebSeriesRequestGenerationRef.current) {
        setDcWebSeriesCatalogue({ ...firstPage, page: firstPage.totalPages, results: allResults });
      }
    } catch (error: any) {
      if (generation === searchGenerationRef.current && requestGeneration === dcWebSeriesRequestGenerationRef.current) {
        setDcWebSeriesError(String(error?.message || 'Could not load DC web series.'));
      }
    } finally {
      if (requestGeneration === dcWebSeriesRequestGenerationRef.current) setDcWebSeriesLoading(false);
    }
  };
  const loadClassicsTvCatalogue = async (catalogueKey: 'classics-web-series' | 'classics-anime', tab: 'web-series' | 'anime') => {
    setClassicsContentTab(tab);
    setShowDcWebSeries(false);
    setShowMarvelWebSeries(true);
    if (marvelWebSeriesCatalogue?.catalogue === catalogueKey) return;
    setMarvelWebSeriesCatalogue(null);
    setMarvelWebSeriesLoading(true);
    setMarvelWebSeriesError('');
    const generation = ++searchGenerationRef.current;
    try {
      const page = await loadTvCataloguePage(catalogueKey);
      if (generation === searchGenerationRef.current) setMarvelWebSeriesCatalogue(page);
    } catch (error: any) {
      if (generation === searchGenerationRef.current) setMarvelWebSeriesError(String(error?.message || 'Could not load Classics catalogue.'));
    } finally {
      setMarvelWebSeriesLoading(false);
    }
  };
  const loadMarvelWebSeries = async () => {
    setShowMarvelWebSeries(true);
    if (marvelWebSeriesCatalogue?.catalogue === 'marvel-web-series' || marvelWebSeriesLoading) return;
    setMarvelWebSeriesLoading(true);
    setMarvelWebSeriesError('');
    const generation = ++searchGenerationRef.current;
    try {
      // Fetch every page up front so the Marvel section is complete rather than
      // silently showing only the first page until the user finds Load more.
      const firstPage = await loadTvCataloguePage('marvel', 1);
      const allResults = [...firstPage.results];
      for (let page = 2; page <= Math.min(firstPage.totalPages, 500); page += 1) {
        if (generation !== searchGenerationRef.current) return;
        const nextPage = await loadTvCataloguePage('marvel', page);
        for (const show of nextPage.results) {
          if (!allResults.some(existing => String(existing.id) === String(show.id))) allResults.push(show);
        }
      }
      if (generation === searchGenerationRef.current) setMarvelWebSeriesCatalogue({ ...firstPage, page: firstPage.totalPages, results: allResults });
    } catch (error: any) {
      if (generation === searchGenerationRef.current) setMarvelWebSeriesError(String(error?.message || 'Could not load Marvel web series.'));
    } finally {
      setMarvelWebSeriesLoading(false);
    }
  };

  return {
    loadDcWebSeries,
    loadDcWebSeriesPage,
    loadClassicsTvCatalogue,
    loadMarvelWebSeries,
  };
}
