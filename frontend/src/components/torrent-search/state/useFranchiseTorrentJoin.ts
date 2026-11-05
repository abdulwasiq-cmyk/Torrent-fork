import { useEffect, useRef } from 'react';
import { api, TorrentSearchResult } from '../../../api/client.ts';
import { franchiseCatalogueSection } from '../../../api/sectionCache.ts';
import { TorrentQualityGroup, torrentResultKey } from '../grouping.ts';
import { joinReleasesIntoRow } from '../franchiseJoin.ts';

/**
 * Marvel, DC and Favourites list one metadata-only row per title (no magnet, size or seeders).
 * When the user opens a title's card, fetch that ONE title's releases from the per-section torrent
 * files and put them into the same group, so the Prepare card gets quality options and an enabled
 * Prepare button.
 *
 * Page loads and pagination never run this: it fires only when a card is expanded. The joined rows
 * keep the catalogue row's mediaTitle / year / TMDB id / metadata, so the group key
 * (normalized title | year) stays the same and the open card does not collapse or move.
 */
const hasSource = (row: TorrentSearchResult) => Boolean(row.magnetUrl || row.downloadUrl || row.sourceUrl);

export function useFranchiseTorrentJoin({
  expandedSearchGroupKey,
  groupedResults,
  activeFranchiseSearchMode,
  setResults,
}: {
  expandedSearchGroupKey: string | null;
  groupedResults: TorrentQualityGroup[];
  activeFranchiseSearchMode: string | null;
  setResults: (update: (previous: TorrentSearchResult[]) => TorrentSearchResult[]) => void;
}) {
  // Titles already looked up (hit or miss) so a miss is not retried in a loop.
  const attemptedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!expandedSearchGroupKey || !activeFranchiseSearchMode || !franchiseCatalogueSection(activeFranchiseSearchMode)) return;
    const group = groupedResults.find(item => item.key === expandedSearchGroupKey);
    if (!group) return;
    const metadataRows = group.variants.filter(row => row.sectionCacheRecord && !hasSource(row));
    if (metadataRows.length === 0 || group.variants.some(hasSource)) return;
    const attemptKey = activeFranchiseSearchMode + '|' + group.key;
    if (attemptedRef.current.has(attemptKey)) return;
    attemptedRef.current.add(attemptKey);

    const base = metadataRows[0];
    // No abort on re-render: the join is idempotent (it replaces rows by key), and letting a started
    // lookup finish means the releases are already there if the card is opened again.
    void (async () => {
      try {
        const releases = await api.getTorrentOptions({
          tmdbId: base.tmdbId ?? base.id,
          title: String(base.mediaTitle || base.title),
          year: base.year,
        });
        if (releases.length === 0) return;
        const joined = joinReleasesIntoRow(base, releases);
        const replaced = new Set(metadataRows.map(torrentResultKey));
        setResults(previous => {
          const next: TorrentSearchResult[] = [];
          let inserted = false;
          for (const row of previous) {
            if (replaced.has(torrentResultKey(row))) {
              if (!inserted) { next.push(...joined); inserted = true; }   // same position in the grid
            } else {
              next.push(row);
            }
          }
          return inserted ? next : previous;
        });
      } catch {
        attemptedRef.current.delete(attemptKey);   // allow a retry after a network error
      }
    })();
  }, [expandedSearchGroupKey, activeFranchiseSearchMode, groupedResults]);
}
