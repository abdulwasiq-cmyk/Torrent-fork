import { useMemo } from 'react';
import searchLimits from '../../../../search_limits.json';
import { filterTorrentSearchResults, groupTorrentResults, normalizeGroupTitle, releaseDateSortValue, torrentGroupReleaseYear } from '../grouping.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useSearchInputState } from './useSearchInputState.ts';
import { ClassicsSort, classicsComparator, ratingValue } from '../classicsSort.ts';
import { imdbRatingKey } from '../grouping.ts';

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
    if (isMarvelEnglishResults) {
      groups = groups.filter(group => {
        const rawTitle = String(group.title || '');
        const title = normalizeGroupTitle(rawTitle.replace(/\s*\(?((?:19|20)\d{2})\)?\s*$/, ''));
        const year = Number(group.year || rawTitle.match(/\b(?:19|20)\d{2}\b/)?.[0] || 0);
        return !(year === 1977 && /^(?:the )?amazing spider man$/i.test(title));
      });
    }
    if (isMarvelEnglishResults && !showMarvelWebSeries && marvelFilmFilter !== 'all') {
      const normalize = (value: string) => normalizeGroupTitle(String(value || '').replace(/\s*\(?((?:19|20)\d{2})\)?\s*$/, ''));
      const mcuTitles = new Set([
        'ant man', 'ant man and the wasp', 'ant man and the wasp quantumania',
        'avengers', 'the avengers', 'avengers age of ultron', 'avengers endgame', 'avengers infinity war',
        'black panther', 'black panther wakanda forever', 'black widow', 'captain america brave new world',
        'captain america civil war', 'captain america the first avenger', 'captain america the winter soldier',
        'captain marvel', 'doctor strange', 'doctor strange in the multiverse of madness',
        'deadpool and wolverine', 'eternals', 'guardians of the galaxy', 'guardians of the galaxy vol 2',
        'guardians of the galaxy vol 3', 'iron man', 'iron man 2', 'iron man 3',
        'shang chi and the legend of the ten rings', 'spider man brand new day', 'spider man far from home',
        'spider man homecoming', 'spider man no way home', 'the fantastic four first steps',
        'the incredible hulk', 'the marvels', 'the punisher one last kill', 'the punisher: one last kill', 'thor', 'thor love and thunder', 'thor ragnarok',
        'thor the dark world', 'thunderbolts'
      ]);
      const isSpiderMan = (title: string) => /spider\s*man|spider\s*verse|into the spider|across the spider/i.test(title);
      const isXMen = (title: string) => /x\s*men|wolverine|deadpool|new mutants|dark phoenix/i.test(title);
      const isSony = (title: string) => isSpiderMan(title) || /venom|morbius|kraven|madame web/i.test(title);
      groups = groups.filter(group => {
        const title = normalize(group.title);
        switch (marvelFilmFilter) {
          case 'mcu': return mcuTitles.has(title) || [...mcuTitles].some(item => title.startsWith(item + ' ')) ||
            /^(?:marvel television special presentation )?(?:the )?punisher one last kill$/.test(title);
          case 'x-men': return isXMen(title);
          case 'sony': return isSony(title);
          default: return true;
        }
      });
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
