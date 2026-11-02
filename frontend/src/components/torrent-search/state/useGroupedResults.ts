import { useMemo } from 'react';
import searchLimits from '../../../../search_limits.json';
import { filterTorrentSearchResults, groupTorrentResults, normalizeGroupTitle, releaseDateSortValue, torrentGroupReleaseYear } from '../grouping.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useSearchInputState } from './useSearchInputState.ts';
import { ClassicsSort, classicsComparator, ratingValue } from '../classicsSort.ts';
import { imdbRatingKey } from '../grouping.ts';
import { matchesMarvelFilmFilter } from '../../../api/sectionCache.ts';

export function useGroupedResults({ results, resolutionFilter, sizeSort, timeSort, isMarvelEnglishResults, showMarvelWebSeries, marvelFilmFilter, activeFranchiseSearchMode, classicsSort, imdbRatingsByKey }: { classicsSort: ClassicsSort; imdbRatingsByKey: Record<string, { imdbRating?: number | string | null } | undefined> } & Pick<ReturnType<typeof useSearchInputState>, 'results' | 'resolutionFilter' | 'sizeSort' | 'timeSort'> & Pick<ReturnType<typeof useCatalogueNavigationState>, 'isMarvelEnglishResults' | 'showMarvelWebSeries' | 'marvelFilmFilter' | 'activeFranchiseSearchMode'>) {
  const sortedResults = useMemo(() => {
    // Use the shared root search_limits.json settings. Keep both bounds local
    // to this memo: the manual-search handler has its own separate scope.
    const minSeedrFriendlySize = searchLimits.minSizeMb * 1024 * 1024;
    const maxSeedrFriendlySize = searchLimits.maxSizeGb * 1024 * 1024 * 1024;
    const sorted = filterTorrentSearchResults(results, {
      minSizeBytes: minSeedrFriendlySize,
      maxSizeBytes: maxSeedrFriendlySize,
      resolutionFilter,
    });
    sorted.sort((a, b) => {
      const aSize = Number(a.size) || 0;
      const bSize = Number(b.size) || 0;
      const aTime = a.publishDate ? new Date(a.publishDate).getTime() : 0;
      const bTime = b.publishDate ? new Date(b.publishDate).getTime() : 0;
      if (sizeSort) {
        const comparison = sizeSort === 'asc' ? aSize - bSize : bSize - aSize;
        if (comparison !== 0) return comparison;
      }
      if (timeSort) {
        const comparison = timeSort === 'asc' ? aTime - bTime : bTime - aTime;
        if (comparison !== 0) return comparison;
      }
      // Keep the backend's relevance-first ranking by default. Re-sorting here
      // by quality/seeders would undo its title-match scoring and let popular
      // but less relevant releases appear above better matches.
      return 0;
    });
    return sorted;
  }, [results, resolutionFilter, sizeSort, timeSort]);
  const groupedResults = useMemo(() => {
    let groups = groupTorrentResults(sortedResults);

    // The Marvel buttons are shown on torrent-search results as well as
    // catalogue cards, so apply the selected franchise to the actual groups.
    if (isMarvelEnglishResults && !showMarvelWebSeries) {
      groups = groups.filter(group =>
        matchesMarvelFilmFilter(group.title, group.year, marvelFilmFilter)
      );
    }

    // Every franchise section: the user picks Year or Rating (IMDb), each newest/highest first by default.
    if (activeFranchiseSearchMode) {
      const ratingOf = (group: (typeof groups)[number]) => {
        const bare = String(group.title || '').replace(/\s*\(?(?:19|20)\d{2}\)?\s*$/, '').trim();
        return ratingValue(imdbRatingsByKey[imdbRatingKey(bare, group.year, 'movie')] || imdbRatingsByKey[imdbRatingKey(group.title, group.year, 'movie')]);
      };
      return [...groups].sort(classicsComparator(
        classicsSort,
        group => releaseDateSortValue(group.posterResult),
        ratingOf,
        group => normalizeGroupTitle(group.title),
      ));
    }

    // Sort whole movie groups, never individual torrent variants.
    return [...groups].sort((a, b) => {
      if (activeFranchiseSearchMode) {
        const dateOrder = releaseDateSortValue(b.posterResult) - releaseDateSortValue(a.posterResult);
        if (dateOrder !== 0) return dateOrder;
      }
      const yearA = torrentGroupReleaseYear(a);
      const yearB = torrentGroupReleaseYear(b);
      if (!yearA && !yearB) return normalizeGroupTitle(a.title).localeCompare(normalizeGroupTitle(b.title), undefined, { numeric: true });
      if (!yearA) return 1;
      if (!yearB) return -1;
      if (yearA !== yearB) return yearB - yearA;
      return normalizeGroupTitle(a.title).localeCompare(normalizeGroupTitle(b.title), undefined, { numeric: true });
    });
  }, [sortedResults, activeFranchiseSearchMode, isMarvelEnglishResults, showMarvelWebSeries, marvelFilmFilter, classicsSort, imdbRatingsByKey]);

  return {
    sortedResults,
    groupedResults,
  };
}
