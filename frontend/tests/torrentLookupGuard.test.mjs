// Keeps the fast path fast: torrent data may only be requested from a Prepare click.
// Source-level guard (no bundler needed), like the "shared card" check in CI.
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import test from 'node:test';

const SRC = fileURLToPath(new URL('../src/', import.meta.url));

async function sourceFiles(dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...await sourceFiles(full));
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full);
  }
  return out;
}

const rel = file => path.relative(SRC, file).split(path.sep).join('/');

test('getTorrentOptions is only called from the two Prepare click paths', async () => {
  const callers = [];
  for (const file of await sourceFiles(SRC)) {
    const text = await readFile(file, 'utf8');
    if (/\.getTorrentOptions\s*\(/.test(text)) callers.push(rel(file));
  }
  assert.deepEqual(callers.sort(), [
    'components/torrent-search/state/useFranchiseTorrentJoin.ts',   // Marvel / DC / Favourites: card opened
    'components/torrent-search/state/useMovieTorrentSearch.ts',     // regional grids: Prepare clicked
  ]);
});

test('the franchise join only runs for a tapped or expanded card in a franchise view', async () => {
  const text = await readFile(path.join(SRC, 'components/torrent-search/state/useFranchiseTorrentJoin.ts'), 'utf8');
  const lookup = text.indexOf('api.getTorrentOptions(');
  const modeGuard = text.indexOf('!franchiseCatalogueSection(activeFranchiseSearchMode)');
  assert.ok(modeGuard > 0 && lookup > modeGuard, 'lookup must sit behind the franchise-mode guard');
  // the only two ways to reach it: the card tap, or an already-expanded card
  assert.match(text, /const openFranchiseCard = /);
  assert.match(text, /useEffect\(\(\) => \{\s*if \(!expandedSearchGroupKey\) return;/);
  assert.equal(text.match(/joinGroup\(/g).length, 2, 'joinGroup may only be called from the tap path and the expanded-card effect');
  assert.ok(!/api\.getSectionCache|loadCachedFranchisePage/.test(text), 'the join must not touch page loading');
});

test('the Prepare lookup runs after the click-intent guard in searchMovieTorrents', async () => {
  const text = await readFile(path.join(SRC, 'components/torrent-search/state/useMovieTorrentSearch.ts'), 'utf8');
  const guard = text.indexOf('missing-explicit-click-intent');
  const lookup = text.indexOf('api.getTorrentOptions(');
  assert.ok(guard > 0 && lookup > guard, 'torrent lookup must come after the explicit-click guard');
});

test('section loading and paging code never mention torrent files', async () => {
  for (const name of ['api/sectionCache.ts']) {
    const text = await readFile(path.join(SRC, name), 'utf8');
    assert.ok(!/torrent-options|-torrents\.json|getTorrentOptions/.test(text), `${name} must stay torrent-free`);
  }
  const search = await readFile(path.join(SRC, 'api/search.ts'), 'utf8');
  const sectionMethod = search.split('async getSectionCache')[1].split('async getTorrentOptions')[0];
  assert.ok(!sectionMethod.includes('torrent-options'), 'getSectionCache must not fetch torrent data');
});

test('an empty cached "no releases" result is never served or saved', async () => {
  const text = await readFile(path.join(SRC, 'components/torrent-search/state/useMovieTorrentSearch.ts'), 'utf8');
  assert.match(text, /persistedDetails\.groups\?\.length > 0 && Date\.now\(\)/, 'cached empty results must count as a miss');
  const write = text.split('movieTorrentDetailsCacheRef.current.set(cacheKey, { groups, savedAt')[0].trimEnd();
  assert.ok(write.endsWith('if (groups.length > 0) {'), 'only non-empty results may be written to the cache');
});
