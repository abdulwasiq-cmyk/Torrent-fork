import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build, transform } from 'esbuild';

const sourcePath = fileURLToPath(new URL('../src/api/sectionCache.ts', import.meta.url));
const source = await readFile(sourcePath, 'utf8');
const { code } = await transform(source, { loader: 'ts', format: 'esm' });
const sectionCache = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const groupingBundle = await build({
  entryPoints: [fileURLToPath(new URL('../src/components/torrent-search/grouping.ts', import.meta.url))],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
});
const grouping = await import(
  `data:text/javascript;base64,${Buffer.from(groupingBundle.outputFiles[0].text).toString('base64')}`
);
const searchPath = fileURLToPath(new URL('../src/api/search.ts', import.meta.url));
const bundledSearch = await build({
  entryPoints: [searchPath],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
  define: { 'import.meta.env': '{}' },
});
const searchApiModule = await import(
  `data:text/javascript;base64,${Buffer.from(bundledSearch.outputFiles[0].text).toString('base64')}`
);

function rows(count, prefix) {
  return Array.from({ length: count }, (_, index) => ({
    id: index + 1,
    title: `${prefix} ${String(index + 1).padStart(2, '0')}`,
    year: 2020,
    mediaType: 'tv',
  }));
}

function tvDocument(section, subsectionName, results, pageOffsets, totalResults = results.length) {
  return {
    section,
    metadataSelfContained: true,
    subsections: {
      [subsectionName]: {
        mediaType: 'tv',
        pageSize: 18,
        pageCount: pageOffsets.length - 1,
        pageOffsets,
        totalResults,
        results,
      },
    },
  };
}

test('initial TV loading fetches its section endpoint, not the legacy catalogue API', async t => {
  const document = tvDocument('hollywood', 'tv-popular', rows(54, 'Show'), [0, 18, 36, 54], 60);
  const originalFetch = globalThis.fetch;
  const requests = [];
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async input => {
    requests.push(String(input));
    return new Response(JSON.stringify(document), { status: 200 });
  };
  const page = await sectionCache.tvCataloguePageFromSectionCache(
    section => searchApiModule.searchApi.getSectionCache(section),
    'hollywood-popular',
    1,
  );

  assert.equal(page.provider, 'self-contained-section-cache');
  assert.equal(page.page, 1);
  assert.equal(requests.length, 1);
  assert.match(requests[0], /\/api\/sections\/hollywood$/);
  assert.equal(requests.some(url => url.includes('/api/tv/catalogue/')), false);
});

test('TV previous/next reuse the section response and never call the legacy TV API', async t => {
  const document = tvDocument('bollywood', 'tv-popular', rows(51, 'Bollywood'), [0, 16, 34, 51], 56);
  const originalFetch = globalThis.fetch;
  const requests = [];
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async input => {
    requests.push(String(input));
    return new Response(JSON.stringify(document), { status: 200 });
  };
  const loadPage = page => sectionCache.tvCataloguePageFromSectionCache(
    section => searchApiModule.searchApi.getSectionCache(section),
    'indian-popular',
    page,
  );

  const initial = await loadPage(1);
  const next = await loadPage(initial.page + 1);
  const previous = await loadPage(next.page - 1);

  assert.equal(initial.results[0].sectionCacheRecord, true);
  assert.deepEqual(next.results.map(show => show.title), rows(51, 'Bollywood').slice(18, 36).map(show => show.title));
  assert.deepEqual(previous.results.map(show => show.title), rows(51, 'Bollywood').slice(0, 18).map(show => show.title));
  assert.equal(requests.length, 1);
  assert.match(requests[0], /\/api\/sections\/bollywood$/);
  assert.equal(requests.some(url => url.includes('/api/tv/catalogue/')), false);
});

test('TV pages use fixed 18-record boundaries even when stored offsets are legacy splits', () => {
  const document = tvDocument('bollywood', 'tv-popular', rows(54, 'Drama'), [0, 16, 34, 51], 56);

  const page1 = sectionCache.tvCataloguePageFromSection(document, 'indian-popular', 'tv-popular', 1);
  const page2 = sectionCache.tvCataloguePageFromSection(document, 'indian-popular', 'tv-popular', 2);
  const page3 = sectionCache.tvCataloguePageFromSection(document, 'indian-popular', 'tv-popular', 3);

  assert.deepEqual([page1.results.length, page2.results.length, page3.results.length], [18, 18, 18]);
  assert.deepEqual(
    [...page1.results, ...page2.results, ...page3.results].map(show => show.title),
    rows(54, 'Drama').map(show => show.title),
  );
  for (const page of [page1, page2, page3]) {
    assert.equal(page.totalPages, 3);
    assert.equal(page.totalResults, 54);
    assert.equal(page.curatedOrder, true);
  }
});

test('the final TV page contains at most 18 remaining records', () => {
  const document = tvDocument('bollywood', 'tv-popular', rows(51, 'Drama'), [0, 16, 34, 51], 56);
  const pages = [1, 2, 3].map(page => (
    sectionCache.tvCataloguePageFromSection(document, 'indian-popular', 'tv-popular', page)
  ));

  assert.deepEqual(pages.map(page => page.results.length), [18, 18, 15]);
  assert.equal(pages[2].totalResults, 51);
  assert.equal(pages[2].totalPages, 3);
});

test('movie pagination still slices section rows in order', () => {
  const movieRows = Array.from({ length: 36 }, (_, index) => ({
    id: index + 1,
    title: `Movie ${String(index + 1).padStart(2, '0')}`,
    mediaType: 'movie',
  }));
  const document = {
    section: 'hollywood',
    metadataSelfContained: true,
    subsections: {
      popular: {
        mediaType: 'movie',
        pageSize: 18,
        totalResults: 36,
        results: movieRows,
      },
    },
  };

  const page = sectionCache.movieCataloguePageFromSection(document, 'popular-hollywood', 'popular', 2);
  assert.equal(page.page, 2);
  assert.equal(page.totalPages, 2);
  assert.deepEqual(page.results.map(movie => movie.title), movieRows.slice(18).map(movie => movie.title));
  assert.equal(page.results[0].sectionCacheRecord, true);
});

test('franchise movie rows use matching cached torrent results when available', async () => {
  const metadata = JSON.parse(await readFile(
    new URL('../../backend/cache-seed/marvel.json', import.meta.url),
    'utf8',
  ));
  const torrentCache = JSON.parse(await readFile(
    new URL('../../backend/cache-seed/marvel-torrents.json', import.meta.url),
    'utf8',
  ));
  const rows = sectionCache.franchiseRowsFromSection(metadata, 'movies', torrentCache);
  const spiderMan = rows.filter(row => String(row.tmdbId) === '969681');

  assert.ok(spiderMan.length > 0);
  assert.ok(spiderMan.every(row =>
    row.sectionCacheRecord === true &&
    Boolean(row.magnetUrl || row.downloadUrl || row.sourceUrl || row.infoHash || row.infoUrl)
  ));
  assert.ok(spiderMan.every(row => row.mediaTitle === 'Spider-Man: Brand New Day'));
});

test('franchise metadata rows without a cached torrent remain source-less', () => {
  const metadata = {
    subsections: {
      movies: {
        mediaType: 'movie',
        results: [{ id: 7, title: 'No Torrent Movie', year: 2020 }],
      },
    },
  };
  const torrentCache = { schemaVersion: 1, section: 'marvel', records: [] };
  const rows = sectionCache.franchiseRowsFromSection(metadata, 'movies', torrentCache);

  assert.equal(rows.length, 1);
  assert.equal(rows[0].title, 'No Torrent Movie');
  assert.equal(rows[0].magnetUrl, undefined);
  assert.equal(rows[0].infoHash, undefined);
});

test('franchise movie pages paginate distinct catalogue rows before expanding torrent variants', async t => {
  const views = [
    { mode: 'marvel', section: 'marvel', subsection: 'movies' },
    { mode: 'dc-live-action', section: 'dc', subsection: 'live-action' },
    { mode: 'dc-animated', section: 'dc', subsection: 'animated' },
    { mode: 'classics', section: 'favourites', subsection: 'movies' },
  ];
  const movieRows = Array.from({ length: 37 }, (_, index) => ({
    id: index + 1,
    tmdbId: index + 1,
    title: `Movie ${String(index + 1).padStart(2, '0')}`,
    year: 2020,
  }));
  const torrentRecords = movieRows.flatMap((movie, movieIndex) => (
    Array.from({ length: movieIndex === 0 ? 3 : 1 }, (_, variantIndex) => {
      const infoHash = String(movieIndex * 3 + variantIndex + 1).padStart(40, '0');
      return {
        identity: infoHash,
        identityKind: 'infoHash',
        infoHash,
        title: `${movie.title} ${variantIndex ? '720p WEBRip' : '1080p WEB-DL'}`,
        size: 1024,
        seeders: 10,
        leechers: 1,
        mediaIdentities: [{
          mediaType: 'movie',
          title: movie.title,
          year: movie.year,
          tmdbId: movie.tmdbId,
        }],
      };
    })
  ));
  const torrentDocument = { schemaVersion: 1, section: 'fixture', records: torrentRecords };

  for (const view of views) {
    await t.test(view.mode, () => {
      const document = {
        section: view.section,
        metadataSelfContained: true,
        subsections: {
          [view.subsection]: {
            mediaType: 'movie',
            pageSize: 18,
            totalResults: movieRows.length,
            results: movieRows,
          },
        },
      };
      const page1 = sectionCache.franchiseMoviePageFromSection(
        document,
        view.subsection,
        1,
        18,
        torrentDocument,
      );
      const page2 = sectionCache.franchiseMoviePageFromSection(
        document,
        view.subsection,
        2,
        18,
        torrentDocument,
      );
      const page3 = sectionCache.franchiseMoviePageFromSection(
        document,
        view.subsection,
        3,
        18,
        torrentDocument,
      );
      const groups1 = grouping.groupTorrentResults(page1.results);
      const groups2 = grouping.groupTorrentResults(page2.results);
      const titles1 = groups1.map(group => group.variants[0].mediaTitle);
      const titles2 = groups2.map(group => group.variants[0].mediaTitle);

      assert.equal(page1.totalResults, 37, 'the page carries the full catalogue count');
      assert.equal(page2.totalResults, 37);
      assert.equal(page3.totalResults, 37);
      assert.equal(groups1.length, 18, 'page 1 contains 18 distinct catalogue movies');
      assert.equal(groups2.length, 18, 'page 2 contains the next 18 distinct catalogue movies');
      assert.equal(page3.results.length, 1, 'the final page contains the one remaining movie');
      assert.deepEqual(titles1, movieRows.slice(0, 18).map(movie => movie.title));
      assert.deepEqual(titles2, movieRows.slice(18, 36).map(movie => movie.title));
      assert.equal(new Set([...titles1, ...titles2]).size, 36, 'no catalogue title repeats across pages');
      assert.equal(groups1[0].variants.length, 3, 'all cached variants remain grouped with their movie');
      assert.equal(
        groups1.flatMap(group => group.variants).length,
        20,
        'the page keeps every cached torrent option for its 18 movies',
      );
    });
  }
});

test('franchise movie pagination does not alter Marvel, DC, Favourites or Anime TV section pages', async t => {
  const views = [
    { label: 'Marvel Web Series', section: 'marvel', subsection: 'series', catalogue: 'marvel', count: 57 },
    { label: 'DC Web Series', section: 'dc', subsection: 'series', catalogue: 'dc-live-action', count: 40 },
    { label: 'Favourites Series', section: 'favourites', subsection: 'series', catalogue: 'classics-web-series', count: 32 },
    { label: 'Favourites Anime TV', section: 'favourites', subsection: 'anime', catalogue: 'classics-anime', count: 29 },
  ];

  for (const view of views) {
    await t.test(view.label, async () => {
      const document = JSON.parse(await readFile(
        new URL(`../../backend/cache-seed/${view.section}.json`, import.meta.url),
        'utf8',
      ));
      const page1 = sectionCache.tvCataloguePageFromSection(
        document,
        view.catalogue,
        view.subsection,
        1,
      );
      const page2 = sectionCache.tvCataloguePageFromSection(
        document,
        view.catalogue,
        view.subsection,
        2,
      );
      const pageCount = Math.ceil(view.count / 18);
      const pages = Array.from({ length: pageCount }, (_, index) => (
        sectionCache.tvCataloguePageFromSection(
          document,
          view.catalogue,
          view.subsection,
          index + 1,
        )
      ));

      assert.equal(page1.totalResults, view.count);
      assert.equal(page1.results.length, 18);
      assert.equal(page2.totalResults, view.count);
      assert.equal(page2.results.length, Math.min(18, view.count - 18));
      assert.deepEqual(pages.map(page => page.results.length), [
        ...Array.from({ length: pageCount - 1 }, () => 18),
        view.count - (pageCount - 1) * 18,
      ]);
      assert.equal(
        sectionCache.franchiseMoviePageFromSection(document, view.subsection, 1, 18),
        null,
        'the movie page helper does not handle TV subsections',
      );
      assert.equal(
        new Set(pages.flatMap(page => page.results).map(show => show.id)).size,
        view.count,
        'TV pages still contain each catalogue record exactly once',
      );
    });
  }
});

test('Hollywood and Bollywood TV catalogue mappings retain all three subsections', () => {
  const expected = {
    'hollywood-popular': ['hollywood', 'tv-popular'],
    'hollywood-trending': ['hollywood', 'tv-trending'],
    'hollywood-latest': ['hollywood', 'tv-latest'],
    'indian-popular': ['bollywood', 'tv-popular'],
    'indian-trending': ['bollywood', 'tv-trending'],
    'indian-latest': ['bollywood', 'tv-latest'],
  };

  for (const [catalogue, location] of Object.entries(expected)) {
    assert.deepEqual(sectionCache.tvCatalogueSection(catalogue), {
      section: location[0],
      subsection: location[1],
    });
  }
});

test('all nine section documents declare consistent 18-record pagination metadata', async () => {
  const sections = [
    'hollywood', 'bollywood', 'marvel', 'dc', 'highest-rated',
    'korean', 'pakistani', 'anime', 'favourites',
  ];
  const cacheDirectory = new URL('../../backend/cache-seed/', import.meta.url);

  for (const section of sections) {
    const document = JSON.parse(await readFile(new URL(`${section}.json`, cacheDirectory), 'utf8'));
    for (const subsection of Object.values(document.subsections)) {
      const results = subsection.results;
      const pages = Array.from({ length: subsection.pageCount }, (_, index) => (
        results.slice(index * 18, (index + 1) * 18)
      ));
      assert.equal(subsection.pageSize, 18, `${section}/${subsection.catalogueKey}`);
      assert.equal(subsection.pageCount, Math.ceil(results.length / 18), `${section}/${subsection.catalogueKey}`);
      assert.equal(subsection.totalResults, results.length, `${section}/${subsection.catalogueKey}`);
      assert.ok(pages.every(page => page.length === 18 || page.length < 18));
      assert.ok(pages.every((page, index) => index === pages.length - 1 || page.length === 18));
      if (subsection.mediaType === 'tv') {
        assert.deepEqual(
          subsection.pageOffsets,
          [...Array.from({ length: pages.length }, (_, index) => index * 18), results.length],
          `${section}/${subsection.catalogueKey} offsets`,
        );
      }
    }
  }
});
