import { useEffect, useRef } from 'react';
import { api, TorrentSearchResult } from '../../../api/client.ts';
import { franchiseCatalogueSection } from '../../../api/sectionCache.ts';
import { TorrentQualityGroup, torrentResultKey } from '../grouping.ts';
import { joinReleasesIntoRow, openWhenReady } from '../franchiseJoin.ts';

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
const MAX_WAIT_MS = 800;
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
  const inflightRef = useRef<Map<string, Promise<void>>>(new Map());

  const metadataRowsOf = (group: TorrentQualityGroup) =>
    group.variants.some(hasSource) ? [] : group.variants.filter(row => row.sectionCacheRecord && !hasSource(row));
  const needsJoin = (group: TorrentQualityGroup) =>
    Boolean(activeFranchiseSearchMode && franchiseCatalogueSection(activeFranchiseSearchMode)) &&
    metadataRowsOf(group).length > 0 &&
    !attemptedRef.current.has(activeFranchiseSearchMode + '|' + group.key);

  const joinGroup = (group: TorrentQualityGroup): Promise<void> => {
    const metadataRows = metadataRowsOf(group);
    if (!activeFranchiseSearchMode || !franchiseCatalogueSection(activeFranchiseSearchMode) || metadataRows.length === 0) {
      return Promise.resolve();
    }
    const attemptKey = activeFranchiseSearchMode + '|' + group.key;
    const running = inflightRef.current.get(attemptKey);
    if (running) return running;
    if (attemptedRef.current.has(attemptKey)) return Promise.resolve();
    attemptedRef.current.add(attemptKey);

    const base = metadataRows[0];
    // No abort on re-render: the join is idempotent (it replaces rows by key), and letting a started
    // lookup finish means the releases are already there if the card is opened again.
    const promise = (async () => {
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
    })().finally(() => { inflightRef.current.delete(attemptKey); });
    inflightRef.current.set(attemptKey, promise);
    return promise;
  };

  /**
   * Open a card only once its releases are in, so the Prepare button never flashes disabled.
   * Titles that need no lookup (already joined, or a known miss) open immediately; a slow lookup
   * never blocks the tap for longer than MAX_WAIT_MS (the card then opens and the effect below finishes the job).
   */
  const openFranchiseCard = (group: TorrentQualityGroup, open: () => void) =>
    openWhenReady(needsJoin(group), () => joinGroup(group), open, MAX_WAIT_MS);

  // Fallback for any other way a card gets expanded (e.g. the deferred first-page click).
  useEffect(() => {
    if (!expandedSearchGroupKey) return;
    const group = groupedResults.find(item => item.key === expandedSearchGroupKey);
    if (group) void joinGroup(group);
  }, [expandedSearchGroupKey, activeFranchiseSearchMode, groupedResults]);

  return { openFranchiseCard };
}
