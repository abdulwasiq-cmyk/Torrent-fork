// The size window (TORRENT_MIN_SIZE_MB / TORRENT_MAX_SIZE_GB) is for movies only; series are never size-filtered.
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const result = await build({
  entryPoints: [fileURLToPath(new URL('../src/components/torrent-search/grouping.ts', import.meta.url))],
  bundle: true, format: 'esm', platform: 'node', write: false, define: { 'import.meta.env': '{}' },
});
const { filterTorrentSearchResults, isSeriesRelease } = await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
const GB = 1024 ** 3, MB = 1024 ** 2;
const window = { minSizeBytes: 250 * MB, maxSizeBytes: 2 * GB, resolutionFilter: null };
const row = (title, size, seeders = 10) => ({ title, size, seeders });
const kept = rows => filterTorrentSearchResults(rows, window).map(r => r.title);

test('movies are held to the window, series are not', () => {
  assert.deepEqual(kept([
    row('Heat 1995 1080p', 1.5 * GB), row('Heat 1995 2160p', 30 * GB), row('Heat 1995 CAMRip tiny', 100 * MB),
    row('Reacher S02 2160p', 40 * GB), row('Reacher S01 720p', 3 * GB), row('Reacher Season 1 1080p', 12 * GB),
    row('Loki Complete Series 1080p', 90 * GB), row('Loki S01E03 1080p', 4 * GB), row('Reacher S01 tiny', 50 * MB),
  ]), ['Heat 1995 1080p', 'Reacher S02 2160p', 'Reacher S01 720p', 'Reacher Season 1 1080p', 'Loki Complete Series 1080p', 'Loki S01E03 1080p', 'Reacher S01 tiny']);
});

test('series still need a known size and seeders', () => {
  assert.deepEqual(kept([row('Reacher S02 1080p', 0), row('Reacher S02 720p', 5 * GB, 0)]), []);
});

test('what counts as a series release', () => {
  for (const title of ['Show.S01.1080p', 'Show S01E05', 'Show Season 2', 'Show.Season.12', 'Show Complete Series', 'show s1e1']) assert.ok(isSeriesRelease({ title }), title);
  for (const title of ['Heat 1995 1080p', 'Season of the Witch 2011', 'Passengers 2016', 'S1m0ne 2002', 'Mission 2018 BluRay']) assert.ok(!isSeriesRelease({ title }), title);
});
