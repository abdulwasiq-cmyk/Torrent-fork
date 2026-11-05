import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const searchPath = fileURLToPath(new URL('../src/api/search.ts', import.meta.url));
const bundled = await build({
  entryPoints: [searchPath],
  bundle: true,
  format: 'esm',
  platform: 'node',
  write: false,
  define: { 'import.meta.env': '{}' },
});
const { searchApi } = await import(
  `data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].text).toString('base64')}`
);

const calls = [];
function mockFetch(status, body) {
  globalThis.fetch = async url => {
    calls.push(String(url));
    return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
  };
}
const rows = [{ title: 'Dune 2021 1080p', infoHash: 'a'.repeat(40), magnetUrl: 'magnet:?xt=urn:btih:x', size: 1, seeders: 3, leechers: 0 }];

test('getTorrentOptions asks for one movie by TMDB id, title and year', async () => {
  calls.length = 0;
  mockFetch(200, { status: 'ready', torrentDetails: { results: rows } });
  const result = await searchApi.getTorrentOptions({ tmdbId: 438631, title: 'Dune', year: 2021 });
  assert.equal(result.length, 1);
  const url = new URL(calls[0]);
  assert.equal(url.pathname, '/api/sections/all/torrent-options');
  assert.equal(url.searchParams.get('tmdb_id'), '438631');
  assert.equal(url.searchParams.get('title'), 'Dune');
  assert.equal(url.searchParams.get('year'), '2021');
});

test('getTorrentOptions sends only valid ids, trims the year and skips empty requests', async () => {
  calls.length = 0;
  mockFetch(200, { status: 'not_cached', torrentDetails: null });
  await searchApi.getTorrentOptions({ tmdbId: 'tt123', title: 'Heat', year: '1995-12-15' });
  const url = new URL(calls[0]);
  assert.equal(url.searchParams.has('tmdb_id'), false);
  assert.equal(url.searchParams.get('year'), '1995');
  calls.length = 0;
  assert.deepEqual(await searchApi.getTorrentOptions({ title: 'No Year' }), []);
  assert.equal(calls.length, 0);
});

test('getTorrentOptions degrades to an empty list so Prepare can use its fallback', async () => {
  mockFetch(200, { status: 'not_cached', torrentDetails: null });
  assert.deepEqual(await searchApi.getTorrentOptions({ tmdbId: 1, title: 'X', year: 2020 }), []);
  mockFetch(503, { detail: 'unavailable' });
  assert.deepEqual(await searchApi.getTorrentOptions({ tmdbId: 1, title: 'X', year: 2020 }), []);
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => { throw new Error('bad json'); } });
  assert.deepEqual(await searchApi.getTorrentOptions({ tmdbId: 1, title: 'X', year: 2020 }), []);
});

test('loading a section never requests torrent data', async () => {
  calls.length = 0;
  mockFetch(200, { section: 'marvel', metadataSelfContained: true, subsections: {} });
  await searchApi.getSectionCache('marvel');
  assert.equal(calls.length, 1);
  assert.ok(!calls[0].includes('torrent'), calls[0]);
});
