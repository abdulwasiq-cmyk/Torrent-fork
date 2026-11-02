import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build, transform } from 'esbuild';

const root = new URL('../', import.meta.url);
const sectionCachePath = fileURLToPath(new URL('src/api/sectionCache.ts', root));
const source = await readFile(sectionCachePath, 'utf8');
const transformed = await transform(source, { loader: 'ts', format: 'esm' });
const sectionCache = await import(
  `data:text/javascript;base64,${Buffer.from(transformed.code).toString('base64')}`
);
const searchBundle = await build({
  entryPoints: [fileURLToPath(new URL('src/api/search.ts', root))],
  bundle: true,
  format: 'esm',
  platform: 'node',
  target: 'node20',
  write: false,
  define: { 'import.meta.env': '{}' },
});
const searchApi = await import(
  `data:text/javascript;base64,${Buffer.from(searchBundle.outputFiles[0].text).toString('base64')}`
);
const repositoryRoot = new URL('../../', import.meta.url);

function sectionDocument(section, subsection, mediaType, results) {
  return {
    section,
    metadataSelfContained: true,
    subsections: {
      [subsection]: {
        mediaType,
        pageSize: 18,
        totalResults: results.length,
        results,
      },
    },
  };
}

test('movie sections with torrent support map to their canonical cache section', () => {
  const expected = {
    marvel: 'marvel',
    'marvel-hindi': 'marvel',
    'dc-live-action': 'dc',
    'dc-live-action-hindi': 'dc',
    'dc-animated': 'dc',
    classics: 'favourites',
    'highest-rated-hollywood': 'highest-rated',
    'highest-rated-bollywood': 'highest-rated',
    'latest-hollywood': 'hollywood',
    'popular-hollywood': 'hollywood',
    'trending-hollywood': 'hollywood',
    'latest-bollywood': 'bollywood',
    'popular-bollywood': 'bollywood',
    'trending-bollywood': 'bollywood',
    'bollywood-library': 'bollywood',
  };
  for (const [catalogue, section] of Object.entries(expected)) {
    assert.equal(sectionCache.torrentCacheSectionForMovieCatalogue(catalogue), section);
    assert.equal(sectionCache.movieCatalogueTorrentLookupEnabled(catalogue), true);
  }
});

test('Korean, Pakistani and Anime movie catalogues remain metadata-only', () => {
  for (const region of ['korean', 'pakistani', 'anime']) {
    for (const mode of ['popular', 'trending', 'latest']) {
      const catalogue = `${mode}-${region}`;
      assert.equal(sectionCache.torrentCacheSectionForMovieCatalogue(catalogue), null);
      assert.equal(sectionCache.movieCatalogueTorrentLookupEnabled(catalogue), false);
    }
  }
  assert.deepEqual(sectionCache.movieCatalogueSection('popular-korean'), {
    section: 'korean',
    subsection: 'movies',
  });
  assert.deepEqual(sectionCache.movieCatalogueSection('popular-anime'), {
    section: 'anime',
    subsection: 'movies',
  });
  assert.equal(sectionCache.torrentCacheSectionForMovieCatalogue('unknown'), null);
});

test('TV section mappings remain independent of movie torrent lookup configuration', () => {
  assert.equal(sectionCache.torrentCacheSectionForTvCatalogue('marvel'), 'marvel');
  assert.equal(sectionCache.torrentCacheSectionForTvCatalogue('pakistani-popular'), 'pakistani');
  assert.deepEqual(sectionCache.franchiseCatalogueSection('marvel'), {
    section: 'marvel',
    subsection: 'movies',
  });
  assert.deepEqual(sectionCache.franchiseCatalogueSection('dc-live-action-hindi'), {
    section: 'dc',
    subsection: 'live-action',
  });
});

test('movie and TV pages paginate metadata rows without torrent variants', () => {
  const movieRows = Array.from({ length: 37 }, (_, index) => ({
    id: index + 1,
    tmdbId: index + 1,
    title: `Movie ${index + 1}`,
    year: 2020,
  }));
  const movieDocument = sectionDocument('marvel', 'movies', 'movie', movieRows);
  const moviePage1 = sectionCache.franchiseMoviePageFromSection(movieDocument, 'movies', 1, 18);
  const moviePage2 = sectionCache.franchiseMoviePageFromSection(movieDocument, 'movies', 2, 18);
  const moviePage3 = sectionCache.franchiseMoviePageFromSection(movieDocument, 'movies', 3, 18);

  assert.equal(moviePage1.totalResults, 37);
  assert.deepEqual(
    [moviePage1.cards.length, moviePage2.cards.length, moviePage3.cards.length],
    [18, 18, 1],
  );
  assert.deepEqual(
    moviePage1.cards.map(movie => movie.title),
    movieRows.slice(0, 18).map(movie => movie.title),
  );
  assert.deepEqual(
    moviePage2.cards.map(movie => movie.title),
    movieRows.slice(18, 36).map(movie => movie.title),
  );
  assert.equal(
    new Set([...moviePage1.cards, ...moviePage2.cards].map(movie => movie.key)).size,
    36,
  );
  assert.ok([...moviePage1.cards, ...moviePage2.cards].every(movie =>
    !Object.hasOwn(movie, 'variants') &&
    !Object.hasOwn(movie, 'magnetUrl') &&
    !Object.hasOwn(movie, 'infoHash')
  ));

  const tvRows = Array.from({ length: 40 }, (_, index) => ({
    id: index + 1,
    title: `Series ${index + 1}`,
  }));
  const tvDocument = sectionDocument('marvel', 'series', 'tv', tvRows);
  const tvPage1 = sectionCache.tvCataloguePageFromSection(tvDocument, 'marvel', 'series', 1);
  const tvPage2 = sectionCache.tvCataloguePageFromSection(tvDocument, 'marvel', 'series', 2);
  assert.deepEqual([tvPage1.results.length, tvPage2.results.length], [18, 18]);
  assert.equal(
    sectionCache.franchiseMoviePageFromSection(tvDocument, 'series', 1, 18),
    null,
  );
});

test('TV pages keep fixed 18-record boundaries and do not duplicate records', () => {
  const rows = Array.from({ length: 51 }, (_, index) => ({
    id: index + 1,
    title: `Series ${index + 1}`,
  }));
  const document = sectionDocument('bollywood', 'tv-popular', 'tv', rows);
  document.subsections['tv-popular'].pageOffsets = [0, 16, 34, 51];
  const pages = [1, 2, 3].map(page => (
    sectionCache.tvCataloguePageFromSection(
      document,
      'indian-popular',
      'tv-popular',
      page,
    )
  ));

  assert.deepEqual(pages.map(page => page.results.length), [18, 18, 15]);
  assert.deepEqual(
    pages.flatMap(page => page.results).map(show => show.title),
    rows.map(show => show.title),
  );
  assert.equal(
    new Set(pages.flatMap(page => page.results).map(show => show.id)).size,
    rows.length,
  );
});

test('Marvel, DC, Favourites and Anime TV catalogues retain their section pagination', async t => {
  const views = [
    { label: 'Marvel Web Series', section: 'marvel', catalogue: 'marvel', subsection: 'series', count: 57 },
    { label: 'DC Web Series', section: 'dc', catalogue: 'dc-live-action', subsection: 'series', count: 40 },
    { label: 'Favourites Series', section: 'favourites', catalogue: 'classics-web-series', subsection: 'series', count: 32 },
    { label: 'Anime TV', section: 'anime', catalogue: 'anime-popular', subsection: 'series', count: 54 },
    { label: 'Favourites Anime TV', section: 'favourites', catalogue: 'classics-anime', subsection: 'anime', count: 29 },
  ];

  for (const view of views) {
    await t.test(view.label, async () => {
      const document = JSON.parse(await readFile(
        new URL(`backend/cache-seed/${view.section}.json`, repositoryRoot),
        'utf8',
      ));
      const pages = Array.from(
        { length: Math.ceil(view.count / 18) },
        (_, index) => sectionCache.tvCataloguePageFromSection(
          document,
          view.catalogue,
          view.subsection,
          index + 1,
        ),
      );
      const rows = pages.flatMap(page => page.results);

      assert.equal(rows.length, view.count);
      assert.deepEqual(
        rows.map(row => `${row.id}|${row.title}`),
        document.subsections[view.subsection].results.map(row => `${row.id}|${row.title}`),
      );
      assert.deepEqual(
        pages.map(page => page.results.length),
        [...Array.from({ length: pages.length - 1 }, () => 18), view.count % 18 || 18],
      );
      assert.ok(pages.every(page => page.totalResults === view.count));
    });
  }
});

test('TV section selection and pagination make no torrent API request', async t => {
  const document = sectionDocument(
    'marvel',
    'series',
    'tv',
    Array.from({ length: 40 }, (_, index) => ({ id: index + 1, title: `Series ${index + 1}` })),
  );
  const originalFetch = globalThis.fetch;
  const requests = [];
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async input => {
    requests.push(String(input));
    return new Response(JSON.stringify(document), { status: 200 });
  };

  const page1 = await sectionCache.tvCataloguePageFromSectionCache(
    section => searchApi.searchApi.getSectionCache(section),
    'marvel',
    1,
  );
  const page2 = await sectionCache.tvCataloguePageFromSectionCache(
    section => searchApi.searchApi.getSectionCache(section),
    'marvel',
    2,
  );

  assert.equal(page1.results.length, 18);
  assert.equal(page2.results.length, 18);
  assert.equal(requests.length, 1);
  assert.match(requests[0], /\/api\/sections\/marvel(?:\?|$)/);
  assert.doesNotMatch(requests[0], /torrent|torrents|torrent-options/);
});

test('all nine metadata section documents retain valid structure without torrent rows', async () => {
  const sections = [
    'hollywood', 'bollywood', 'marvel', 'dc', 'highest-rated',
    'korean', 'pakistani', 'anime', 'favourites',
  ];

  for (const section of sections) {
    const document = JSON.parse(await readFile(
      new URL(`backend/cache-seed/${section}.json`, repositoryRoot),
      'utf8',
    ));
    assert.equal(document.section, section);
    assert.equal(document.metadataSelfContained, true);
    assert.ok(document.subsections && typeof document.subsections === 'object');
    assert.equal(Object.hasOwn(document, 'records'), false);
    for (const subsection of Object.values(document.subsections)) {
      assert.ok(Array.isArray(subsection.results));
      assert.equal(subsection.pageSize, 18);
      assert.equal(subsection.totalResults, subsection.results.length);
      assert.ok(subsection.results.every(row =>
        !Object.hasOwn(row, 'variants') &&
        !Object.hasOwn(row, 'magnetUrl') &&
        !Object.hasOwn(row, 'infoHash')
      ));
    }
  }
});
