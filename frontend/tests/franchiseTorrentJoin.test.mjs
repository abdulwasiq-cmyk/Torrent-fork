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

// ---- opening the card without a flash of the disabled Prepare button -------------------------
const { openWhenReady } = await bundle('../src/components/torrent-search/franchiseJoin.ts');
const tick = ms => new Promise(resolve => setTimeout(resolve, ms));

test('no lookup needed: the card opens synchronously (no added delay)', () => {
  let opened = 0;
  openWhenReady(false, () => { throw new Error('must not look up'); }, () => { opened += 1; }, 800);
  assert.equal(opened, 1);
});

test('lookup needed: the card opens only after the releases are in', async () => {
  const events = [];
  let release;
  const join = () => new Promise(resolve => { release = () => { events.push('joined'); resolve(); }; });
  openWhenReady(true, join, () => events.push('opened'), 800);
  await tick(20);
  assert.deepEqual(events, [], 'still waiting: the card has not opened with a disabled Prepare');
  release();
  await tick(5);
  assert.deepEqual(events, ['joined', 'opened']);
});

test('a slow lookup never blocks the tap longer than the cap', async () => {
  let opened = 0;
  openWhenReady(true, () => new Promise(() => {}), () => { opened += 1; }, 30);
  await tick(10); assert.equal(opened, 0);
  await tick(60); assert.equal(opened, 1);
});

test('a failed lookup still opens the card, and open runs exactly once', async () => {
  let opened = 0;
  openWhenReady(true, () => Promise.reject(new Error('offline')), () => { opened += 1; }, 30);
  await tick(80);
  assert.equal(opened, 1, 'opened once even though both the failure and the timer fired');
});
