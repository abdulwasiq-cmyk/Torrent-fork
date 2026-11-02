import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

async function loadTypeScriptModule(filePath) {
  const { outputFiles } = await build({
    entryPoints: [filePath],
    bundle: true,
    format: 'esm',
    platform: 'node',
    target: 'node20',
    write: false,
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputFiles[0].contents).toString('base64')}`);
}

const [movieCardsSource, searchResultsSource, posterUpgrade] = await Promise.all([
  readFile(resolve(frontendRoot, 'src/components/MovieCards.tsx'), 'utf8'),
  readFile(resolve(frontendRoot, 'src/components/torrent-search/sections/SearchResultsSection.tsx'), 'utf8'),
  loadTypeScriptModule(resolve(frontendRoot, 'src/components/movie-cards/posterUpgrade.ts')),
]);

const compactCardStart = movieCardsSource.indexOf('export const MovieCompactCard');
const prepareCardStart = movieCardsSource.indexOf('export interface MoviePrepareCardVariant');
const compactCardSource = movieCardsSource.slice(compactCardStart, prepareCardStart);
const prepareCardSource = movieCardsSource.slice(prepareCardStart);

test('switching movie card views keeps one poster element mounted with an unchanged source', () => {
  assert.equal((compactCardSource.match(/data-movie-poster-stage="true"/g) || []).length, 1);
  assert.match(compactCardSource, /src=\{normalizeLowQualityPosterUrl\(posterSrc\)\}/);
  assert.match(compactCardSource, /expandedContent \? expandedContent/);
  assert.match(searchResultsSource, /<MovieCompactCard[\s\S]*expanded=\{isExpanded\}[\s\S]*expandedContent=\{\([\s\S]*<MoviePrepareCard\s+contentOnly/);
  assert.doesNotMatch(searchResultsSource, /if \(expandedSearchGroupKey !== group\.key\)/);
  assert.match(prepareCardSource, /\{!contentOnly && \([\s\S]*data-movie-poster-stage="true"/);
});

test('the loaded poster stays present through Prepare and back transitions', () => {
  assert.match(compactCardSource, /<MovieCatalogueCard[\s\S]*<img[\s\S]*expanded && expandedContent \? expandedContent/);
  assert.match(searchResultsSource, /posterSrc=\{lowQualityPosterUrl\(sharedPosterUrl\)\}/);
  assert.match(searchResultsSource, /if \(isExpanded\) \{\s*setExpandedSearchGroupKey\(null\)/);
});

test('a loaded high-quality poster is reused and does not downgrade to low quality', () => {
  const originalWindow = globalThis.window;
  globalThis.window = { location: { origin: 'https://torrent-studio.test' } };
  posterUpgrade.loadedHighQualityUrls.clear();
  try {
    const lowUrl = 'https://torrent-studio.test/api/poster?path=%2Fmovie%2Fposter.jpg&size=w185';
    const highUrl = 'https://torrent-studio.test/api/poster?path=%2Fmovie%2Fposter.jpg&size=w780';
    posterUpgrade.loadedHighQualityUrls.add(highUrl);

    const image = {
      src: lowUrl,
      currentSrc: lowUrl,
      dataset: {},
      isConnected: true,
      complete: true,
      naturalWidth: 185,
      fetchPriority: 'high',
      loading: 'eager',
    };
    posterUpgrade.requestHighQualityPoster(image);
    assert.equal(image.src, highUrl);
    assert.equal(image.dataset.highQualityTried, 'true');

    image.currentSrc = highUrl;
    image.complete = true;
    image.naturalWidth = 780;
    posterUpgrade.restoreLowQualityPoster(image);
    assert.equal(image.src, highUrl);
  } finally {
    posterUpgrade.loadedHighQualityUrls.clear();
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
  }
});

test('Prepare actions and torrent variants remain wired in the embedded Prepare view', () => {
  assert.match(searchResultsSource, /contentOnly[\s\S]*variants=\{group\.variants\.map/);
  assert.match(searchResultsSource, /onSelectVariant=\{key => setSelectedQualityByGroup/);
  assert.match(searchResultsSource, /onClick: \(\) => void prepareMovieTorrent\(result\)/);
  assert.match(searchResultsSource, /prepared=\{prepareState\.primaryFile \? preparedActionsFor/);
});
