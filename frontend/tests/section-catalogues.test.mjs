import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = resolve(frontendRoot, '..');

async function loadTypeScriptModule(filePath, define = {}) {
  const { outputFiles } = await build({
    entryPoints: [filePath],
    bundle: true,
    format: 'esm',
    platform: 'node',
    target: 'node20',
    write: false,
    define,
  });
  const source = Buffer.from(outputFiles[0].contents).toString('base64');
  return import(`data:text/javascript;base64,${source}`);
}

const [sectionCache, grouping, classicsSort] = await Promise.all([
  loadTypeScriptModule(resolve(frontendRoot, 'src/api/sectionCache.ts')),
  loadTypeScriptModule(resolve(frontendRoot, 'src/components/torrent-search/grouping.ts')),
  loadTypeScriptModule(resolve(frontendRoot, 'src/components/torrent-search/classicsSort.ts')),
]);
const franchisePanelSource = await readFile(
  resolve(frontendRoot, 'src/components/torrent-search/useTorrentSearchPanel.tsx'),
  'utf8',
);
const resultsSectionSource = await readFile(
  resolve(frontendRoot, 'src/components/torrent-search/sections/SearchResultsSection.tsx'),
  'utf8',
);
const searchRunnerSource = await readFile(
  resolve(frontendRoot, 'src/components/torrent-search/state/useSearchRunner.ts'),
  'utf8',
);
const searchApiBundle = await build({
  entryPoints: [resolve(frontendRoot, 'src/api/search.ts')],
  bundle: true,
  format: 'esm',
  platform: 'node',
  target: 'node20',
  write: false,
  define: { 'import.meta.env': '{}' },
});
const searchApi = await import(
  `data:text/javascript;base64,${Buffer.from(searchApiBundle.outputFiles[0].text).toString('base64')}`
);

const catalogues = [
  { mode: 'marvel', section: 'marvel', subsection: 'movies', records: 96 },
  { mode: 'dc-live-action', section: 'dc', subsection: 'live-action', records: 44 },
  { mode: 'dc-animated', section: 'dc', subsection: 'animated', records: 59 },
  { mode: 'classics', section: 'favourites', subsection: 'movies', records: 75 },
];

test('franchise browsing loads only metadata and renders catalogue rows directly', () => {
  assert.match(searchRunnerSource, /franchiseMoviePageFromSection\(\s*document,\s*sectionLocation\.subsection,\s*1,\s*Math\.max\(1,\s*subsection\.results\.length\),\s*\)/);
  assert.match(searchRunnerSource, /setFranchiseMovieCardsByMode\(previous => \(\{\s*\.\.\.previous,\s*\[searchMode\]: cataloguePage\.cards/);
  assert.match(searchRunnerSource, /data = \[\]/);
  assert.match(searchRunnerSource, /searchMode\s*\?\s*Promise\.resolve\(\[\]\)\s*:\s*Promise\.allSettled/);
  assert.match(searchRunnerSource, /if \(!searchMode\)\s*\{\s*void cachedSearchPromise/);
  assert.doesNotMatch(searchRunnerSource, /getTorrent(?:Section|Movie)Cache/);
  assert.doesNotMatch(franchisePanelSource, /getTorrent(?:Section|Movie)Cache/);
  assert.doesNotMatch(searchRunnerSource + franchisePanelSource, /readFranchisePageCache/);
  assert.match(searchRunnerSource, /new Set\(Array\.from\(\{ length: totalPages \}, \(_, index\) => index \+ 1\)\)/);
  assert.match(franchisePanelSource, /setFranchiseMovieCardsByMode\(previous =>/);
  assert.match(franchisePanelSource, /cataloguePage\.cards\.forEach\(card => byKey\.set\(card\.key, card\)\)/);
  assert.match(resultsSectionSource, /visibleSectionMovieCards\.map\(\(movie, index\)/);
  assert.match(resultsSectionSource, /searchMovieTorrents\(movie\)/);
  assert.match(resultsSectionSource, /franchiseMovieCardsForPage\(sortedSectionMovieCards, franchiseGridPage, franchiseGridPageSize\)/);
  assert.match(resultsSectionSource, /const isSectionBackedMovieView = activeFranchiseSearchMode &&[\s\S]*!showMarvelWebSeries &&[\s\S]*!showDcWebSeries/);
  assert.match(resultsSectionSource, /const sectionMovieCards = isSectionBackedMovieView/);
});

test('franchise summary distinguishes catalogue titles and deferred torrent options', () => {
  assert.match(resultsSectionSource, /catalogue titles.*match current filters.*on this page.*cached torrent options load when a title is prepared/);
});

test('startup and catalogue navigation do not read torrent caches or issue torrent requests', async () => {
  const sectionCacheSource = await readFile(
    resolve(frontendRoot, 'src/api/sectionCache.ts'),
    'utf8',
  );
  const cacheHookSource = await readFile(
    resolve(frontendRoot, 'src/components/torrent-search/state/useMovieTorrentCache.ts'),
    'utf8',
  );
  const pageLoaderStart = franchisePanelSource.indexOf('async function loadCachedFranchisePage');
  const pageLoaderEnd = franchisePanelSource.indexOf('function navigateFranchisePage', pageLoaderStart);
  const pageLoader = franchisePanelSource.slice(pageLoaderStart, pageLoaderEnd);
  const sectionBranchStart = franchisePanelSource.indexOf('const section = movieCatalogueSection(key);');
  const sectionBranchEnd = franchisePanelSource.indexOf('// Regional catalogues', sectionBranchStart);
  const sectionBranch = franchisePanelSource.slice(sectionBranchStart, sectionBranchEnd);

  assert.ok(pageLoaderStart >= 0 && pageLoaderEnd > pageLoaderStart);
  assert.match(pageLoader, /api\.getSectionCache/);
  assert.doesNotMatch(pageLoader, /getTorrent|searchTorrents|torrent-options/);
  assert.ok(sectionBranchStart >= 0 && sectionBranchEnd > sectionBranchStart);
  assert.match(sectionBranch, /api\.getSectionCache\(section\.section\)/);
  assert.doesNotMatch(sectionBranch, /getMovieCatalogue|torrent-options|torrents/);
  assert.doesNotMatch(sectionCacheSource, /mediaIdentities|infoHash|magnetUrl|torrentCacheRecordsForMedia/);
  assert.doesNotMatch(cacheHookSource, /useEffect|localStorage\.getItem/);
  assert.match(searchRunnerSource, /searchMode\s*\?\s*Promise\.resolve\(\[\]\)\s*:\s*Promise\.allSettled/);
  assert.doesNotMatch(franchisePanelSource, /getTorrent(?:Section|Movie)Cache/);
});

test('franchise movie pages retain metadata rows across all affected sections', async t => {
  const documents = new Map();
  for (const section of new Set(catalogues.map(catalogue => catalogue.section))) {
    const path = resolve(repositoryRoot, 'backend/cache-seed', `${section}.json`);
    documents.set(section, JSON.parse(await readFile(path, 'utf8')));
  }

  for (const catalogue of catalogues) {
    await t.test(`${catalogue.mode} loads ${catalogue.section}.${catalogue.subsection}`, async () => {
      const location = sectionCache.franchiseCatalogueSection(catalogue.mode);
      assert.deepEqual(location, {
        section: catalogue.section,
        subsection: catalogue.subsection,
      });

      const sectionRequests = [];
      const loaded = await sectionCache.franchiseSectionDocumentFromCache(async section => {
        sectionRequests.push(section);
        return documents.get(section);
      }, catalogue.mode);
      assert.ok(loaded, 'mapped franchise mode must use a section document, not a legacy loader');
      assert.deepEqual(sectionRequests, [catalogue.section]);
      assert.equal(loaded.document.metadataSelfContained, true);

      const subsection = loaded.document.subsections[loaded.location.subsection];
      assert.equal(subsection.mediaType, 'movie');
      assert.equal(subsection.results.length, catalogue.records);

      const moviePage = sectionCache.franchiseMoviePageFromSection(
        loaded.document,
        catalogue.subsection,
        1,
        18,
      );
      assert.ok(moviePage);
      assert.equal(moviePage.totalResults, catalogue.records);
      assert.equal(moviePage.cards.length, 18);
      const page2 = sectionCache.franchiseMoviePageFromSection(
        loaded.document,
        catalogue.subsection,
        2,
        18,
      );
      assert.ok(page2);
      assert.equal(page2.cards.length, 18);
      assert.deepEqual(
        moviePage.cards.map(card => card.title),
        subsection.results.slice(0, 18).map(row => row.title),
      );
      assert.deepEqual(
        page2.cards.map(card => card.title),
        subsection.results.slice(18, 36).map(row => row.title),
      );
      assert.equal(
        new Set([...moviePage.cards, ...page2.cards].map(card => card.key)).size,
        moviePage.cards.length + page2.cards.length,
      );
      assert.ok(moviePage.cards.every(card =>
        card.tmdbId || card.id || card.imdbId || card.title
      ));
      assert.ok(moviePage.cards.every(card => !Object.hasOwn(card, 'variants')));
      const sortedCards = subsection.results.map((row, index) => ({
        ...row,
        key: String(row.tmdbId ?? row.id ?? row.title) + '|' + String(row.year || 'unknown'),
        sourceIndex: index,
      })).sort(classicsSort.classicsComparator(
        classicsSort.DEFAULT_CLASSICS_SORT,
        card => grouping.releaseDateSortValue(card),
        card => classicsSort.ratingValue(card),
        card => card.title,
      ));
      const sortedPageOne = sectionCache.franchiseMovieCardsForPage(sortedCards, 1, 18);
      const sortedPageTwo = sectionCache.franchiseMovieCardsForPage(sortedCards, 2, 18);
      assert.equal(sortedPageOne.length, 18);
      assert.equal(sortedPageTwo.length, 18);
      assert.equal(
        sortedPageOne.some(first => sortedPageTwo.some(second => first.key === second.key)),
        false,
        'catalogue pages must remain distinct after sorting the complete row set',
      );
      assert.equal(
        sortedPageOne.some(first => sortedPageTwo.some(second => (
          first.title === second.title && first.year === second.year
        ))),
        false,
        'catalogue pages must not repeat a title/year pair',
      );
    });
  }
});

test('96 Marvel movies stay metadata-only beside the 3,544-record torrent cache', async () => {
  const metadata = JSON.parse(await readFile(
    resolve(repositoryRoot, 'backend/cache-seed/marvel.json'),
    'utf8',
  ));
  const torrentCache = JSON.parse(await readFile(
    resolve(repositoryRoot, 'backend/cache-seed/marvel-torrents.json'),
    'utf8',
  ));
  const movies = metadata.subsections.movies;
  const page1 = sectionCache.franchiseMoviePageFromSection(metadata, 'movies', 1, 18);
  const page2 = sectionCache.franchiseMoviePageFromSection(metadata, 'movies', 2, 18);

  assert.equal(movies.results.length, 96);
  assert.equal(torrentCache.records.length, 3544);
  assert.deepEqual([page1.cards.length, page2.cards.length], [18, 18]);
  assert.deepEqual(
    [...page1.cards, ...page2.cards].map(card => card.title),
    movies.results.slice(0, 36).map(row => row.title),
  );
  assert.ok([...page1.cards, ...page2.cards].every(card =>
    !Object.hasOwn(card, 'variants') &&
    !Object.hasOwn(card, 'magnetUrl') &&
    !Object.hasOwn(card, 'infoHash')
  ));
  assert.match(searchRunnerSource, /searchMode\s*\?\s*Promise\.resolve\(\[\]\)\s*:\s*Promise\.allSettled/);
});

test('Yenime MAL lookup sends TMDB ID for offline mapping lookup', async t => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async input => {
    requests.push(String(input));
    return new Response(JSON.stringify({
      status: 'resolved',
      malId: 16498,
      source: 'AniList',
      title: 'Attack on Titan',
    }), { status: 200 });
  };

  const result = await searchApi.searchApi.resolveYenimeMalId(
    'Attack on Titan',
    2013,
    null,
    1429,
  );

  assert.equal(result.status, 'resolved');
  assert.match(requests[0], /\/api\/yenime\/resolve-mal\?/);
  assert.match(requests[0], /tmdbId=1429/);
  assert.match(requests[0], /year=2013/);
});

test('browser Back records and restores catalogue and playback navigation', async () => {
  const panel = await readFile(
    resolve(frontendRoot, 'src/components/torrent-search/useTorrentSearchPanel.tsx'),
    'utf8',
  );
  const shell = await readFile(
    resolve(frontendRoot, 'src/app/state/useAppShellState.ts'),
    'utf8',
  );
  const yenime = await readFile(
    resolve(frontendRoot, 'src/components/torrent-search/state/useYenimePlayer.ts'),
    'utf8',
  );

  assert.match(panel, /window\.history\.pushState\(/);
  assert.match(panel, /window\.addEventListener\('popstate', restore\)/);
  assert.match(panel, /setActiveTopSection\(view\.activeTopSection/);
  assert.match(panel, /setNexStreamEpisodePicker\(view\.nexStreamEpisodePicker/);
  assert.match(panel, /yenime\.setYenimeEpisodePicker\(view\.yenimeEpisodePicker/);
  assert.match(panel, /if \(hadPlayer && !hasPlayer/);
  assert.match(panel, /window\.history\.back\(\)/);
  assert.match(shell, /setActiveTab\(stateTab\)/);
  assert.match(yenime, /setYenimeSeasons, setYenimeEpisodes/);
});

test('anime playback hides MAL IDs, defaults to Dub, and preserves episode pickers', async () => {
  const hookSource = await readFile(
    resolve(frontendRoot, 'src/components/torrent-search/state/useYenimePlayer.ts'),
    'utf8',
  );
  const yenimeUi = await readFile(
    resolve(frontendRoot, 'src/components/torrent-search/sections/YenimeSection.tsx'),
    'utf8',
  );
  const vidriftUi = await readFile(
    resolve(frontendRoot, 'src/components/torrent-search/sections/NexStreamSection.tsx'),
    'utf8',
  );
  const yenimeHelpers = await readFile(
    resolve(frontendRoot, 'src/components/torrent-search/yenime.ts'),
    'utf8',
  );

  assert.match(hookSource, /type: 'dub'/);
  assert.match(hookSource, /type: 'sub' \| 'dub'/);
  assert.match(yenimeHelpers, /type: 'sub' \| 'dub' = 'dub'/);
  assert.doesNotMatch(yenimeUi, /<label[^>]*>MAL ID/);
  assert.match(yenimeUi, /role="alert"/);
  assert.match(yenimeUi, /onClose=\{\(\) => vm\.setYenimePlayer\(null\)\}/);
  assert.match(vidriftUi, /onClose=\{\(\) => setNexStreamPlayer\(null\)\}/);
  assert.doesNotMatch(vidriftUi, /setNexStreamEpisodePicker\(null\); if \(selected\) void playWithNexStream/);
});
