import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build, transform } from 'esbuild';

const sourcePath = fileURLToPath(new URL('../src/api/sectionCache.ts', import.meta.url));
const source = await readFile(sourcePath, 'utf8');
const { code } = await transform(source, { loader: 'ts', format: 'esm' });
const sectionCache = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
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
