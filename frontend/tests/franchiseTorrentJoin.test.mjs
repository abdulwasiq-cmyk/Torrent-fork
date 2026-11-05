// Marvel / DC / Favourites: opening a card joins that one title's releases into its group.
// Uses real data (Spider-Man: Brand New Day) and the real grouping code.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const bundle = async entry => {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(entry, import.meta.url))],
    bundle: true, format: 'esm', platform: 'node', write: false,
    define: { 'import.meta.env': '{}' },
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
};

const { joinReleasesIntoRow } = await bundle('../src/components/torrent-search/franchiseJoin.ts');
const { groupTorrentResults } = await bundle('../src/components/torrent-search/grouping.ts');
const { row, releases } = JSON.parse(await readFile(new URL('./fixtures/franchise-spiderman.json', import.meta.url), 'utf8'));

// What franchiseRowsFromSection() produces for this title: metadata only, no source.
const base = {
  sectionCacheRecord: true, title: row.title, mediaTitle: row.title, size: 0, seeders: 0, leechers: 0,
  year: row.year, releaseDate: row.releaseDate, rating: row.rating, posterUrl: row.posterUrl, overview: row.overview,
  tmdbId: row.tmdbId, id: row.tmdbId, imdbId: row.imdbId, imdbRating: row.imdbRating, imdbUrl: row.imdbUrl,
  ottAvailability: row.ottAvailability, streamingProviders: row.streamingProviders, providerLink: row.providerLink,
};
const hasSource = r => Boolean(r.magnetUrl || r.downloadUrl || r.sourceUrl);

test('before the join the card has no source (Prepare disabled); after it every variant has one', () => {
  const [before] = groupTorrentResults([base]);
  assert.equal(before.variants.some(hasSource), false);
  const joined = joinReleasesIntoRow(base, releases);
  const [after] = groupTorrentResults(joined);
  assert.ok(after.variants.length >= 5, 'quality options appear');
  assert.ok(after.variants.every(hasSource));
  assert.ok(after.variants.every(v => v.magnetUrl.startsWith('magnet:?xt=urn:btih:')));
});

test('the group key does not change, so the open card does not collapse or move', () => {
  const [before] = groupTorrentResults([base]);
  const [after] = groupTorrentResults(joinReleasesIntoRow(base, releases));
  assert.equal(after.key, before.key);
  assert.equal(groupTorrentResults(joinReleasesIntoRow(base, releases)).length, 1, 'all releases land in ONE group');
});

test('joined rows keep the catalogue metadata and the real release title and size', () => {
  const joined = joinReleasesIntoRow(base, releases);
  for (const r of joined) {
    assert.equal(r.mediaTitle, row.title);
    assert.equal(r.tmdbId, row.tmdbId);
    assert.equal(r.posterUrl, row.posterUrl);
    assert.equal(r.sectionCacheRecord, undefined);
  }
  assert.deepEqual(joined.map(r => r.title), releases.map(r => r.title));
  assert.deepEqual(joined.map(r => r.size), releases.map(r => r.size));
  assert.equal(new Set(joined.map(r => r.guid)).size, joined.length, 'each release has its own key');
});

test('other titles in the grid are untouched by one title\'s join', () => {
  const other = { ...base, title: 'Iron Man', mediaTitle: 'Iron Man', year: 2008, tmdbId: 1726, id: 1726, posterUrl: 'x' };
  const groups = groupTorrentResults([other, ...joinReleasesIntoRow(base, releases)]);
  assert.equal(groups.length, 2);
  assert.equal(groups.find(g => g.title.startsWith('Iron Man')).variants.length, 1);
});
