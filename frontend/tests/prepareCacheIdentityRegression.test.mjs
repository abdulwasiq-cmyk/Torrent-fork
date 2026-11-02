import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { transform } from 'esbuild';

const root = new URL('../', import.meta.url);
const source = await readFile(new URL('src/api/sectionCache.ts', root), 'utf8');
const transformed = await transform(source, { loader: 'ts', format: 'esm' });
const sectionCache = await import(
  `data:text/javascript;base64,${Buffer.from(transformed.code).toString('base64')}`
);
const groupingSource = await readFile(new URL('src/components/torrent-search/grouping.ts', root), 'utf8');
const groupingTransformed = await transform(groupingSource, { loader: 'ts', format: 'esm' });
const grouping = await import(
  `data:text/javascript;base64,${Buffer.from(groupingTransformed.code).toString('base64')}`
);

const sectionCatalogues = [
  ['popular-hollywood', 'hollywood'],
  ['popular-bollywood', 'bollywood'],
  ['marvel', 'marvel'],
  ['dc-live-action', 'dc'],
  ['highest-rated-hollywood', 'highest-rated'],
  ['popular-korean', 'korean'],
  ['popular-pakistani', 'pakistani'],
  ['popular-anime', 'anime'],
  ['classics', 'favourites'],
];

const makeTorrentRecord = (overrides = {}) => ({
  guid: 'cache-source-1',
  title: 'Cached Film 2020 1080p WEB-DL',
  mediaTitle: 'Cached Film',
  size: 4 * 1024 * 1024 * 1024,
  seeders: 0,
  infoHash: 'a'.repeat(40),
  magnetUrl: 'magnet:?xt=urn:btih:' + 'a'.repeat(40),
  mediaIdentities: [{
    mediaType: 'movie',
    title: 'Cached Film',
    tmdbId: '42',
    year: '2020',
  }],
  ...overrides,
});

const cacheMedia = {
  id: 42,
  tmdbId: 42,
  title: 'Cached Film',
  year: 2020,
  mediaType: 'movie',
};

const filterResults = (results, requireActiveSeeders = true) =>
  grouping.filterUsableTorrentResults(results, {
    expectedTitles: ['cached film'],
    minSizeBytes: 250 * 1024 * 1024,
    maxSizeBytes: 2 * 1024 * 1024 * 1024,
    requireActiveSeeders,
  });

test('migrated Avengers movie card resolves cached Marvel results into an enabled Prepare source', async () => {
  const metadata = JSON.parse(await readFile(
    new URL('../backend/cache-seed/marvel.json', root),
    'utf8',
  ));
  const torrentDocument = JSON.parse(await readFile(
    new URL('../backend/cache-seed/marvel-torrents.json', root),
    'utf8',
  ));
  const catalogueSection = await readFile(
    new URL('src/components/torrent-search/sections/MovieCatalogueSection.tsx', root),
    'utf8',
  );
  const searchResultsSection = await readFile(
    new URL('src/components/torrent-search/sections/SearchResultsSection.tsx', root),
    'utf8',
  );
  const movie = metadata.subsections.movies.results.find(
    row => String(row.tmdbId ?? row.id) === '299534',
  );

  assert.ok(movie);
  assert.equal(movie.title, 'Avengers: Endgame');
  assert.equal(String(movie.year), '2019');

  const matches = sectionCache.torrentCacheRecordsForMedia(torrentDocument, {
    id: movie.id,
    tmdbId: movie.tmdbId,
    imdbId: movie.imdbId,
    title: movie.title,
    year: movie.year,
    mediaType: 'movie',
  });

  assert.ok(matches.length > 0);
  assert.ok(matches.every(record =>
    record.identityKind === 'infoHash' &&
    Boolean(record.magnetUrl || record.downloadUrl || record.sourceUrl || record.infoHash || record.infoUrl)
  ));
  const selectedSource = matches[0].magnetUrl || matches[0].downloadUrl || matches[0].sourceUrl;
  assert.ok(selectedSource);
  assert.equal(matches[0].sectionCacheRecord, true);
  assert.equal(filterResults(matches).length, matches.length);
  assert.match(catalogueSection, /disabled:\s*!prepareState\.source\s*\|\|\s*prepareState\.isPreparing/);
  assert.match(searchResultsSection, /const prepareState = prepareStateFor\(result\);/);
  assert.match(searchResultsSection, /const source = prepareState\.source;/);
  const isPreparing = false;
  assert.equal(!selectedSource || isPreparing, false);
});

test('The Punisher: One Last Kill resolves to usable cached Marvel torrent sources', async () => {
  const document = JSON.parse(await readFile(
    new URL('../backend/cache-seed/marvel-torrents.json', root),
    'utf8',
  ));
  const matches = sectionCache.torrentCacheRecordsForMedia(document, {
    id: 1439930,
    tmdbId: 1439930,
    title: 'The Punisher: One Last Kill',
    year: 2026,
    mediaType: 'movie',
  });

  assert.ok(matches.length > 0);
  assert.ok(matches.every(record =>
    record.sectionCacheRecord === true &&
    Boolean(record.magnetUrl || record.downloadUrl || record.infoHash || record.infoUrl)
  ));
});

for (const [catalogue, section] of sectionCatalogues) {
  test(`${section} section preserves a valid cached Prepare source`, () => {
    assert.equal(sectionCache.torrentCacheSectionForMovieCatalogue(catalogue), section);
    const document = {
      schemaVersion: 1,
      section,
      records: [makeTorrentRecord()],
    };
    const matches = sectionCache.torrentCacheRecordsForMedia(document, cacheMedia);
    assert.equal(matches.length, 1);
    assert.equal(matches[0].sectionCacheRecord, true);

    const usable = filterResults(matches);
    assert.equal(usable.length, 1);
    assert.equal(grouping.groupTorrentResults(usable)[0].variants.length, 1);
  });
}

test('cached matching preserves multiple sources and bypasses live size and seeder filters', () => {
  const document = {
    schemaVersion: 1,
    section: 'marvel',
    records: [
      makeTorrentRecord(),
      makeTorrentRecord({
        guid: 'cache-source-2',
        infoHash: 'b'.repeat(40),
        magnetUrl: 'magnet:?xt=urn:btih:' + 'b'.repeat(40),
        size: 0,
        seeders: null,
      }),
    ],
  };
  const matches = sectionCache.torrentCacheRecordsForMedia(document, cacheMedia);
  const groups = grouping.groupTorrentResults(filterResults(matches));

  assert.equal(matches.length, 2);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].variants.length, 2);
  assert.ok(groups[0].variants.every(result => Boolean(result.magnetUrl)));
});

test('cached infoHash-only records remain usable Prepare sources', () => {
  const document = {
    schemaVersion: 1,
    section: 'marvel',
    records: [makeTorrentRecord({ magnetUrl: '', downloadUrl: '', sourceUrl: '' })],
  };
  const matches = sectionCache.torrentCacheRecordsForMedia(document, cacheMedia);
  const usable = filterResults(matches);

  assert.equal(usable.length, 1);
  assert.equal(usable[0].infoHash, 'a'.repeat(40));
});

test('cached infoUrl-only records remain usable Prepare sources', () => {
  const document = {
    schemaVersion: 1,
    section: 'marvel',
    records: [makeTorrentRecord({
      infoHash: '',
      magnetUrl: '',
      downloadUrl: '',
      sourceUrl: '',
      infoUrl: 'https://indexer.example/torrent/123',
    })],
  };
  const matches = sectionCache.torrentCacheRecordsForMedia(document, cacheMedia);

  assert.equal(filterResults(matches).length, 1);
});

test('cached records without a usable source do not enable Prepare', () => {
  const document = {
    schemaVersion: 1,
    section: 'marvel',
    records: [makeTorrentRecord({
      infoHash: '',
      magnetUrl: '',
      downloadUrl: '',
      sourceUrl: '',
      infoUrl: '',
    })],
  };
  const matches = sectionCache.torrentCacheRecordsForMedia(document, cacheMedia);

  assert.equal(matches.length, 1);
  assert.equal(filterResults(matches).length, 0);
});

test('cache matching rejects unrelated identities and keeps live-search filters unchanged', () => {
  const unrelatedDocument = {
    schemaVersion: 1,
    section: 'marvel',
    records: [makeTorrentRecord({
      mediaIdentities: [{
        mediaType: 'movie',
        title: 'Another Film',
        tmdbId: '99',
        year: '2020',
      }],
    })],
  };
  assert.equal(sectionCache.torrentCacheRecordsForMedia(unrelatedDocument, cacheMedia).length, 0);

  const liveResults = [
    { title: 'Cached Film 2020 1080p WEB-DL', mediaTitle: 'Cached Film', size: 300 * 1024 * 1024, seeders: 2, magnetUrl: 'magnet:?xt=urn:btih:live' },
    { title: 'Cached Film 2020 1080p WEB-DL', mediaTitle: 'Cached Film', size: 4 * 1024 * 1024 * 1024, seeders: 0, magnetUrl: 'magnet:?xt=urn:btih:oversized' },
    { title: 'Unrelated Film 2020 1080p WEB-DL', mediaTitle: 'Unrelated Film', size: 300 * 1024 * 1024, seeders: 2, magnetUrl: 'magnet:?xt=urn:btih:unrelated' },
  ];

  assert.equal(filterResults(liveResults).length, 1);
});
