import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../', import.meta.url);

test('opening a movie card sets explicit intent before requesting its cache options', async () => {
  const renderer = await readFile(new URL(
    'src/components/torrent-search/sections/SearchResultsSection.tsx',
    root,
  ), 'utf8');
  const movieHook = await readFile(new URL(
    'src/components/torrent-search/state/useMovieTorrentSearch.ts',
    root,
  ), 'utf8');

  const intent = renderer.indexOf('prepareClickIntentRef.current = true');
  const trace = renderer.indexOf('prepareTraceIdRef.current = traceId', intent);
  const request = renderer.indexOf('void searchMovieTorrents(movie)', trace);
  const guard = movieHook.indexOf('if (!prepareClickIntentRef.current');
  const targetedLookup = movieHook.indexOf('api.getTorrentMovieCache(');

  assert.ok(intent >= 0);
  assert.ok(trace > intent);
  assert.ok(request > trace);
  assert.ok(guard >= 0 && targetedLookup > guard);
  assert.match(movieHook, /tmdbId: \/\^\\d\+\$\/\.test\(tmdbIdCandidate\) \? tmdbIdCandidate : undefined/);
  assert.match(movieHook, /imdbId: movie\.imdbId/);
});

test('a no-match movie still has a Prepare state and does not lose its catalogue card', async () => {
  const renderer = await readFile(new URL(
    'src/components/torrent-search/sections/SearchResultsSection.tsx',
    root,
  ), 'utf8');
  const sectionCache = await readFile(new URL('src/api/sectionCache.ts', root), 'utf8');

  assert.match(renderer, /visibleSectionMovieCards !== null \? visibleSectionMovieCards\.map/);
  assert.match(renderer, /group\.variants\.length === 0/);
  assert.match(renderer, /No cached torrent options are available for this title/);
  assert.match(sectionCache, /return \{\s*cards,\s*totalResults,/);
});

test('Prepare actions still expose all variants and the existing Seedr flow', async () => {
  const renderer = await readFile(new URL(
    'src/components/torrent-search/sections/SearchResultsSection.tsx',
    root,
  ), 'utf8');
  const prepareActions = await readFile(new URL(
    'src/components/torrent-search/state/usePrepareActions.ts',
    root,
  ), 'utf8');

  assert.match(renderer, /group\.variants\.map\(variant => <option/);
  assert.match(renderer, /prepareMovieTorrent\(result\)/);
  assert.match(prepareActions, /onPrepare\(result, metadata\)/);
  assert.match(prepareActions, /seedr/i);
});
