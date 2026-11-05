// TV / web series: tap -> cached season packs -> second card (Play + Webtor). Lookup is click-only.
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import test from 'node:test';
import { build } from 'esbuild';

const bundle = async entry => {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(entry, import.meta.url))],
    bundle: true, format: 'esm', platform: 'node', write: false, define: { 'import.meta.env': '{}' },
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
};
const { createTvTorrentStore, packScopeLabel, tvShowKey } = await bundle('../src/components/torrent-search/tvTorrentStore.ts');
const tick = ms => new Promise(resolve => setTimeout(resolve, ms));
const show = { id: 108978, title: 'Reacher', year: 2022 };
const packs = [{ infoHash: 'a'.repeat(40), title: 'Reacher S01', scope: 'season', season: 1, magnetUrl: 'magnet:?xt=urn:btih:' + 'a'.repeat(40) }];

test('packs found: the card opens (after the lookup) and Play is not triggered', async () => {
  let calls = 0, played = 0;
  const store = createTvTorrentStore(async () => { calls += 1; return packs; });
  store.open(show, () => { played += 1; });
  assert.equal(store.getOpenKey(), null, 'not open before the lookup returns');
  await tick(10);
  assert.equal(store.getOpenKey(), tvShowKey(show));
  assert.equal(played, 0);
  assert.deepEqual(store.releasesFor(show), packs);
  store.close(); store.open(show, () => { played += 1; });
  assert.equal(store.getOpenKey(), tvShowKey(show), 'second tap opens synchronously from the cache');
  assert.equal(calls, 1, 'the lookup is cached for the session');
});

test('no packs cached: tapping plays straight away (existing behaviour), the card never opens', async () => {
  let played = 0;
  const store = createTvTorrentStore(async () => []);
  store.open(show, () => { played += 1; });
  await tick(10);
  assert.equal(played, 1); assert.equal(store.getOpenKey(), null);
  store.open(show, () => { played += 1; });            // cached miss: instant
  assert.equal(played, 2);
});

test('a failed or slow lookup falls back to Play once and does not cache the failure', async () => {
  let played = 0, calls = 0;
  const store = createTvTorrentStore(async () => { calls += 1; throw new Error('offline'); }, 30);
  store.open(show, () => { played += 1; });
  await tick(20);
  assert.equal(played, 1);
  store.open(show, () => { played += 1; });
  await tick(20);
  assert.equal(calls, 2, 'a failure is retried on the next tap');
  const slow = createTvTorrentStore(() => new Promise(() => {}), 20);
  let slowPlayed = 0;
  slow.open(show, () => { slowPlayed += 1; });
  await tick(60);
  assert.equal(slowPlayed, 1);
});

test('one card is open at a time and listeners are notified', async () => {
  const store = createTvTorrentStore(async () => packs);
  let notified = 0;
  const off = store.subscribe(() => { notified += 1; });
  store.open(show, () => {}); await tick(10);
  store.open({ id: 2, title: 'Other' }, () => {}); await tick(10);
  assert.equal(store.getOpenKey(), 'tv:2');
  store.close();
  assert.equal(store.getOpenKey(), null);
  assert.equal(notified, 3);
  off();
});

test('pack labels', () => {
  assert.equal(packScopeLabel({ scope: 'complete' }), 'Complete series');
  assert.equal(packScopeLabel({ scope: 'season', season: 3 }), 'Season 3');
});

// ---- source guards ---------------------------------------------------------------------------
const SRC = fileURLToPath(new URL('../src/', import.meta.url));
const read = file => readFile(path.join(SRC, file), 'utf8');

test('the TV lookup is only reachable from a card tap', async () => {
  const tile = await read('components/torrent-search/TvShowTile.tsx');
  assert.equal(tile.match(/getTorrentOptions\(/g).length, 1);
  assert.match(tile, /const open = \(\) => tvTorrents\.open\(show, onPlay\)/);
  const store = await read('components/torrent-search/tvTorrentStore.ts');
  assert.equal(store.match(/lookup\(show\)/g).length, 1, 'only open() starts a lookup');
  for (const file of ['api/sectionCache.ts']) assert.ok(!/tv:|media=tv|TvShowTile/.test(await read(file)), `${file} must stay torrent-free`);
});

test('every series grid uses the tile, so each gets the second card', async () => {
  for (const file of ['components/torrent-search/sections/SearchResultsSection.tsx', 'components/torrent-search/sections/RegionalTvCatalogueSection.tsx']) {
    const text = await read(file);
    assert.ok(!/<TvShowCard\b/.test(text), `${file} must render TvShowTile`);
    assert.match(text, /<TvShowTile\b/);
  }
});

test('Webtor: copies the magnet and opens webtor.io in a new tab', async () => {
  const text = await read('components/torrent-search/webtor.ts');
  assert.match(text, /WEBTOR_URL = 'https:\/\/webtor\.io\/'/);
  assert.match(text, /window\.open\(WEBTOR_URL, '_blank', 'noopener,noreferrer'\)/);
});
