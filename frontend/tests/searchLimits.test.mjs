// The browser's size window is the backend's (injected into index.html), with search_limits.json as fallback.
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import test from 'node:test';
import { build } from 'esbuild';

const result = await build({
  entryPoints: [fileURLToPath(new URL('../src/config/searchLimits.ts', import.meta.url))],
  bundle: true, format: 'esm', platform: 'node', write: false,
});
const { readSearchLimits, searchLimitsSignature } = await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
const MB = 1024 * 1024, GB = 1024 ** 3;
const fallback = JSON.parse(await readFile(new URL('../search_limits.json', import.meta.url), 'utf8'));

test('injected backend values win and decimals work', () => {
  const l = readSearchLimits({ minSizeMb: 500, maxSizeGb: 5 });
  assert.equal(l.minSizeBytes, 500 * MB); assert.equal(l.maxSizeBytes, 5 * GB);
  assert.equal(readSearchLimits({ minSizeMb: 250, maxSizeGb: 3.5 }).maxSizeBytes, Math.round(3.5 * GB));
});

test('missing or junk injection falls back to search_limits.json', () => {
  for (const bad of [undefined, null, 'x', {}, { minSizeMb: 'a', maxSizeGb: -1 }, { minSizeMb: NaN, maxSizeGb: Infinity }]) {
    const l = readSearchLimits(bad);
    assert.equal(l.minSizeBytes, fallback.minSizeMb * MB);
    assert.equal(l.maxSizeBytes, fallback.maxSizeGb * GB);
  }
});

test('max is never below min, and the cache key carries the window', () => {
  const l = readSearchLimits({ minSizeMb: 3000, maxSizeGb: 1 });
  assert.ok(l.maxSizeBytes >= l.minSizeBytes);
  assert.match(searchLimitsSignature, /^\d+-\d+$/);
});

test('only config/searchLimits.ts reads search_limits.json, and the Prepare cache key uses the window', async () => {
  const SRC = fileURLToPath(new URL('../src/', import.meta.url));
  const walk = async dir => (await Promise.all((await readdir(dir, { withFileTypes: true })).map(e =>
    e.isDirectory() ? walk(path.join(dir, e.name)) : /\.(ts|tsx)$/.test(e.name) ? [path.join(dir, e.name)] : []))).flat();
  const readers = [];
  for (const file of await walk(SRC)) if (/search_limits\.json/.test(await readFile(file, 'utf8'))) readers.push(path.relative(SRC, file));
  assert.deepEqual(readers, ['config/searchLimits.ts']);
  const text = await readFile(path.join(SRC, 'components/torrent-search/state/useMovieTorrentSearch.ts'), 'utf8');
  assert.match(text, /const cacheKey = [^;]*searchLimitsSignature;/);
});
