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
    Boolean(record.magnetUrl || record.downloadUrl || record.sourceUrl)
  ));
  const selectedSource = matches[0].magnetUrl || matches[0].downloadUrl || matches[0].sourceUrl;
  assert.ok(selectedSource);
  assert.match(catalogueSection, /disabled:\s*!prepareState\.source\s*\|\|\s*prepareState\.isPreparing/);
  const isPreparing = false;
  assert.equal(!selectedSource || isPreparing, false);
});
