import { SearchMediaMetadata, TorrentSearchResult } from '../../api/client.ts';

export interface TorrentQualityGroup {
  key: string;
  title: string;
  year: string;
  variants: TorrentSearchResult[];
  posterResult: TorrentSearchResult;
}

export function torrentGroupReleaseYear(group: TorrentQualityGroup): number {
  // The year shown on the card is the most trustworthy user-facing sort key.
  const displayedYear = group.title.match(/\(((?:19|20)\d{2})\)\s*$/)?.[1];
  if (displayedYear) return Number(displayedYear);

  const groupYear = Number.parseInt(String(group.year || ''), 10);
  if (groupYear > 0) return groupYear;

  for (const variant of group.variants) {
    const year = Number.parseInt(String(variant.year || ''), 10);
    if (year > 0) return year;
  }
  return 0;
}

export function releaseDateSortValue(item: { releaseDate?: string | null; year?: number | string | null }): number {
  const rawDate = String(item.releaseDate || '').trim();
  // TMDB release dates are ISO YYYY-MM-DD. Use the full date so later months
  // sort ahead of earlier months within the same year.
  if (/^\d{4}-\d{2}-\d{2}$/.test(rawDate)) {
    const timestamp = Date.parse(rawDate + 'T00:00:00Z');
    if (Number.isFinite(timestamp)) return timestamp;
  }
  const year = Number(item.year) || Number(rawDate.slice(0, 4)) || 0;
  return year ? Date.UTC(year, 0, 1) : 0;
}

export function compareReleaseDateDescending(
  a: { title?: string; releaseDate?: string | null; year?: number | string | null },
  b: { title?: string; releaseDate?: string | null; year?: number | string | null },
): number {
  const dateA = releaseDateSortValue(a);
  const dateB = releaseDateSortValue(b);
  if (!dateA && !dateB) return String(a.title || '').localeCompare(String(b.title || ''), undefined, { numeric: true });
  if (!dateA) return 1;
  if (!dateB) return -1;
  if (dateA !== dateB) return dateB - dateA;
  return String(a.title || '').localeCompare(String(b.title || ''), undefined, { numeric: true });
}

export function torrentResultKey(result: TorrentSearchResult): string {
  return String(result.guid || result.infoHash || result.magnetUrl || result.downloadUrl || result.title);
}

export function normalizeGroupTitle(value: string): string {
  return String(value || '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[’']/g, '')
    .replace(/[._]+/g, ' ')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^(?:the|a|an)\s+/, '');
}

export function normalizeSavedOttTitle(value: string): string {
  // Saved franchise catalogues often store the canonical title without the
  // release year, while torrent cards include it (for example "(2019)").
  const withoutTrailingYear = String(value || '')
    .replace(/\s*\(?((?:19|20)\d{2})\)?\s*$/, '')
    .trim();
  return normalizeGroupTitle(withoutTrailingYear);
}

export function episodeSeriesTitle(value: string): string | null {
  // Episode torrents usually contain the show name followed by SxxExx or 1x01.
  const raw = String(value || '').trim();
  const match = raw.match(/^(.*?)\s+(?:S\d{1,2}E\d{1,3}|\d{1,2}x\d{1,3})(?=$|[\s._-])/i);
  const title = String(match?.[1] || '').replace(/[._]+/g, ' ').trim();
  return title.length >= 2 ? title : null;
}

export function imdbRatingKey(
  title: string,
  year?: number | string | null,
  mediaType: 'movie' | 'tv' = 'movie',
): string {
  const raw = String(title || '').trim();
  const embeddedYear = raw.match(/\s*\(?((?:19|20)\d{2})\)?\s*$/)?.[1] || '';
  const resolvedYear = String(year || embeddedYear || '');
  const normalizedTitle = normalizeSavedOttTitle(raw).replace(/\bfour\b/g, '4');
  return (mediaType === 'tv' ? 'tv|' : 'movie|') + normalizedTitle + '|' + resolvedYear;
}

export function imdbRatingQueryTitle(title: string, year?: number | string | null): string {
  const raw = String(title || '').trim();
  const embeddedYear = raw.match(/\s*\(?((?:19|20)\d{2})\)?\s*$/)?.[1] || '';
  const resolvedYear = String(year || embeddedYear || '');
  const cleanTitle = embeddedYear ? raw.replace(/\s*\(?((?:19|20)\d{2})\)?\s*$/, '').trim() : raw;
  return cleanTitle + (resolvedYear ? ' (' + resolvedYear + ')' : '');
}

export function searchMetadataForGroup(
  group: TorrentQualityGroup,
  items: SearchMediaMetadata[],
): SearchMediaMetadata | undefined {
  const key = normalizeSavedOttTitle(group.title);
  let candidates = items.filter(item => normalizeSavedOttTitle(item.title) === key);
  if (!candidates.length) {
    // TV torrent card names include episode titles (e.g. "The Rookie S06E10 Escape Plan").
    // Match the series title separately so show synopsis and TMDB rating appear on the card.
    const seriesTitle = episodeSeriesTitle(group.title);
    if (seriesTitle) {
      const seriesKey = normalizeSavedOttTitle(seriesTitle);
      candidates = items.filter(item =>
        item.mediaType === 'tv' && normalizeSavedOttTitle(item.title) === seriesKey
      );
    }
  }
  if (!candidates.length) return undefined;

  const year = String(group.year || '');
  if (year) {
    const sameYear = candidates.find(item => String(item.year || '') === year);
    if (sameYear) return sameYear;
    const noYear = candidates.filter(item => !item.year);
    // Unknown-year records can be used when uniquely identifiable, but never
    // substitute a different known release year (remakes often share titles).
    return noYear.length === 1 ? noYear[0] : undefined;
  }
  const noYear = candidates.filter(item => !item.year);
  if (noYear.length === 1) return noYear[0];
  return candidates.length === 1 ? candidates[0] : undefined;
}

export function mergeSearchMetadataItems(
  current: SearchMediaMetadata[],
  incoming: SearchMediaMetadata[],
): SearchMediaMetadata[] {
  const merged = [...current];
  for (const candidate of incoming) {
    const candidateTitle = normalizeSavedOttTitle(candidate.title);
    const candidateYear = String(candidate.year || '');
    const candidateType = candidate.mediaType || 'movie';
    const index = merged.findIndex(item =>
      normalizeSavedOttTitle(item.title) === candidateTitle &&
      String(item.year || '') === candidateYear &&
      (item.mediaType || 'movie') === candidateType
    );
    if (index < 0) {
      merged.push(candidate);
      continue;
    }

    const previous = merged[index];
    merged[index] = {
      ...previous,
      ...candidate,
      overview: String(candidate.overview || '').trim() || previous.overview,
      posterUrl: candidate.posterUrl || previous.posterUrl,
      backdropUrl: candidate.backdropUrl || previous.backdropUrl,
      tmdbUrl: candidate.tmdbUrl || previous.tmdbUrl,
      rating: candidate.rating || previous.rating,
      tmdbId: candidate.tmdbId || previous.tmdbId || previous.id,
    };
  }
  return merged;
}

export function torrentMediaIdentity(result: TorrentSearchResult): { title: string; normalized: string; year: string } {
  const source = String(result.mediaTitle || result.title || '').trim();
  const embeddedYears: Array<{ year: string; index: number }> = [];
  const yearPattern = /\b((?:19|20)\d{2})\b/g;
  let yearMatch: RegExpExecArray | null;
  while ((yearMatch = yearPattern.exec(source)) !== null) {
    embeddedYears.push({ year: yearMatch[1], index: yearMatch.index });
  }
  const metadataYear = String(result.year || '').trim();
  // Titles such as "Wonder Woman 1984" can contain a year-like token that is
  // not the film's release year. Only remove a token matching release metadata.
  const embeddedYear = metadataYear
    ? [...embeddedYears].reverse().find(match => match.year === metadataYear) || null
    : embeddedYears[embeddedYears.length - 1] || null;
  let year = metadataYear || embeddedYear?.year || '';
  let title = source.replace(/[._]+/g, ' ');

  if (embeddedYear) {
    title = title.slice(0, embeddedYear.index);
  } else {
    // Release tags in brackets are often incomplete on public indexers.
    title = title
      .replace(/\[[^\]]*(?:\]|$)/g, ' ')
      .replace(/\([^)]*(?:\)|$)/g, ' ');
    title = title.split(
      /\b(?:2160p|1440p|1080p|720p|576p|480p|4k|8k|web[- ]?dl|web[- ]?rip|webrip|bluray|blu[- ]?ray|brrip|hdrip|dvdrip|dvdscr|telesync|telecine|r5|r6|cam|hdcam|x264|x265|h264|h265|hevc|xvid|divx|dts|aac|ac3|ddp|eng|english|nlsub|dual[ .-]?audio|hindi|tamil|telugu|malayalam|kannada|proper|repack|remux|hdr|bluelady|jaybob|haggis|voltage|dtrg|document|vision|sonido|saimorny|ltt)\b/i
    )[0];
  }

  title = title.replace(/\s+/g, ' ').trim().replace(/[\s._:[\](){}-]+$/g, '').trim();
  let normalized = normalizeGroupTitle(title);

  // Common LimeTorrents release shorthand: keep the sequel distinct from
  // The Avengers (2012), while presenting it with its catalogue title.
  if ((normalized === 'avengers 2' || normalized === 'the avengers 2') && (!year || year === '2015')) {
    title = 'Avengers: Age of Ultron';
    normalized = normalizeGroupTitle(title);
    year = year || '2015';
  } else if (
    (normalized === 'marvel s the avengers' || normalized === 'marvels the avengers') &&
    (!year || year === '2012')
  ) {
    title = 'The Avengers';
    normalized = normalizeGroupTitle(title);
    year = year || '2012';
  } else if (normalized === 'avengers age of ultron' && (!year || year === '2015')) {
    title = 'Avengers: Age of Ultron';
    year = year || '2015';
  } else if (normalized === 'the avengers' && year === '2012') {
    title = 'The Avengers';
  }

  if (!title) title = String(result.title || result.mediaTitle || 'Unknown title').trim();
  return { title, normalized: normalizeGroupTitle(title), year };
}

export function torrentQualityDetails(result: TorrentSearchResult): { key: string; label: string; rank: number } {
  const raw = `${String(result.quality || '')} ${String(result.title || '')}`;
  const resolution = raw.match(/\b(2160p|1440p|1080p|720p|576p|480p|4k|8k)\b/i)?.[1]?.toLowerCase() || '';
  const resolutionLabel = resolution === '4k' ? '2160p (4K)' : resolution.toUpperCase();
  const formats: Array<[RegExp, string, number]> = [
    [/\b3d\b.*\b(?:bluray|blu[ .-]?ray)\b|\b(?:bluray|blu[ .-]?ray)\b.*\b3d\b/i, '3D BluRay', 950],
    [/\b(?:blu[ .-]?ray|bluray)\b/i, 'BluRay', 900],
    [/\b(?:web[- .]?dl)\b/i, 'WEB-DL', 850],
    [/\b(?:web[- .]?rip|webrip)\b/i, 'WEBRip', 800],
    [/\b(?:brrip)\b/i, 'BRRip', 700],
    [/\b(?:hdtv)\b/i, 'HDTV', 650],
    [/\b(?:hdrip)\b/i, 'HDRip', 600],
    [/\b(?:dvdscr|dvd[ .-]?scr)\b/i, 'DVDScr', 500],
    [/\b(?:dvdrip|dvd)\b/i, 'DVDRip', 450],
    [/\b(?:telesync|ts)\b/i, 'Telesync', 400],
    [/\b(?:telecine|tc)\b/i, 'Telecine', 350],
    [/\b(?:r5|r6)\b/i, 'R5/R6', 300],
    [/\b(?:hdcam|cam)\b/i, 'CAM', 200],
  ];
  const format = formats.find(([pattern]) => pattern.test(raw));
  const label = [resolutionLabel, format?.[1]].filter(Boolean).join(' ') || (resolutionLabel || 'Other release');
  const resolutionRank = resolution === '2160p' || resolution === '4k' ? 2160
    : resolution === '1440p' ? 1440
    : resolution === '1080p' ? 1080
    : resolution === '720p' ? 720
    : resolution === '576p' ? 576
    : resolution === '480p' ? 480
    : resolution === '8k' ? 4320
    : 0;
  // Resolution dominates source format so 1080p is never ranked below 720p
  // just because the latter carries a BluRay tag.
  const rank = resolutionRank * 1000 + (format?.[2] || 0);
  return { key: label.toLowerCase().replace(/[^a-z0-9]+/g, '-'), label, rank };
}

export function filterTorrentSearchResults(
  results: TorrentSearchResult[],
  options: { minSizeBytes: number; maxSizeBytes: number; resolutionFilter: string | null },
): TorrentSearchResult[] {
  const lowQualityRelease = /(?:^|[\s._()[\]-])(?:cam(?:rip)?|hdcam|hd[ ._-]?cam|telesync|tele[ ._-]?sync|ts[ ._-]?(?:md|ac3|hd)?|telecine|dvdscr|dvd[ ._-]?scr|screener|workprint)(?:$|[\s._()[\]-])/i;
  return results.filter(result => {
    if (result.sectionCacheRecord) return true;
    const size = Number(result.size) || 0;
    const seeders = Number(result.seeders);
    if (!Number.isFinite(seeders) || seeders <= 0) return false;
    if (size < options.minSizeBytes || size > options.maxSizeBytes) return false;
    const releaseText = `${String(result.title || '')} ${String(result.quality || '')}`;
    const qualityText = `${String(result.quality || '')} ${String(result.title || '')}`;
    if (/(?:^|[^a-z0-9])3[ ._-]*d(?:$|[^a-z0-9])/i.test(qualityText)) return false;
    if (lowQualityRelease.test(releaseText)) return false;
    if (options.resolutionFilter) {
      const quality = torrentQualityDetails(result).label;
      const pattern = options.resolutionFilter === '720p' ? /(?:^|[^0-9])720p(?:[^0-9]|$)/i : /(?:^|[^0-9])1080p(?:[^0-9]|$)/i;
      if (!pattern.test(quality)) return false;
    }
    return true;
  });
}

export function groupTorrentResults(results: TorrentSearchResult[]): TorrentQualityGroup[] {
  const titleBuckets = new Map<string, Array<{ result: TorrentSearchResult; identity: ReturnType<typeof torrentMediaIdentity> }>>();
  for (const result of results) {
    const identity = torrentMediaIdentity(result);
    if (!identity.normalized) continue;
    const bucket = titleBuckets.get(identity.normalized) || [];
    bucket.push({ result, identity });
    titleBuckets.set(identity.normalized, bucket);
  }

  const groups: TorrentQualityGroup[] = [];
  for (const [normalized, entries] of titleBuckets) {
    const knownYears = Array.from(new Set(entries.map(entry => entry.identity.year).filter(Boolean)));
    const yearBuckets = new Map<string, typeof entries>();
    for (const entry of entries) {
      // Unknown-year releases can join a title only if this result set has one
      // unambiguous year for that title; don't merge remakes with one another.
      const year = entry.identity.year || (knownYears.length === 1 ? knownYears[0] : '');
      const bucket = yearBuckets.get(year) || [];
      bucket.push(entry);
      yearBuckets.set(year, bucket);
    }

    for (const [year, yearEntries] of yearBuckets) {
      // Keep distinct torrent releases even when they share the same resolution
      // and source label. This lets users choose another encode, size, or swarm,
      // rather than hiding those options and making the quality selector disappear.
      const uniqueVariants = new Map<string, { result: TorrentSearchResult; quality: ReturnType<typeof torrentQualityDetails> }>();
      for (const entry of yearEntries) {
        const key = torrentResultKey(entry.result);
        if (!uniqueVariants.has(key)) {
          uniqueVariants.set(key, { result: entry.result, quality: torrentQualityDetails(entry.result) });
        }
      }

      const variants = Array.from(uniqueVariants.values())
        .sort((a, b) => {
          const qualityDifference = b.quality.rank - a.quality.rank;
          if (qualityDifference !== 0) return qualityDifference;
          const seederDifference = (Number(b.result.seeders) || 0) - (Number(a.result.seeders) || 0);
          if (seederDifference !== 0) return seederDifference;
          return (Number(b.result.size) || 0) - (Number(a.result.size) || 0);
        })
        .map(value => value.result);
      if (!variants.length) continue;
      const title = yearEntries[0].identity.title;
      groups.push({
        key: `${normalized}|${year || 'unknown'}`,
        title: year ? `${title} (${year})` : title,
        year,
        variants,
        posterResult: variants.find(item => item.posterUrl || item.mediaTitle) || variants[0],
      });
    }
  }

  return groups;
}
