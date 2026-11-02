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
  const source = Buffer.from(outputFiles[0].contents).toString('base64');
  return import(`data:text/javascript;base64,${source}`);
}

function findOccurrences(source, value) {
  const positions = [];
  let position = source.indexOf(value);
  while (position !== -1) {
    positions.push(position);
    position = source.indexOf(value, position + value.length);
  }
  return positions;
}

const movieCatalogueViews = [
  { label: 'Marvel Movies', mode: 'marvel', section: 'marvel', subsection: 'movies' },
  { label: 'DC Movies', mode: 'dc-live-action', section: 'dc', subsection: 'live-action' },
  { label: 'DC Animated', mode: 'dc-animated', section: 'dc', subsection: 'animated' },
  { label: 'Favourites Movies', mode: 'classics', section: 'favourites', subsection: 'movies' },
];

test('Marvel Movies, DC Movies, DC Animated and Favourites Movies share top and bottom pagination', async t => {
  const [resultsSource, panelSource, sectionCache] = await Promise.all([
    readFile(resolve(frontendRoot, 'src/components/torrent-search/sections/SearchResultsSection.tsx'), 'utf8'),
    readFile(resolve(frontendRoot, 'src/components/torrent-search/useTorrentSearchPanel.tsx'), 'utf8'),
    loadTypeScriptModule(resolve(frontendRoot, 'src/api/sectionCache.ts')),
  ]);
  const call = '{!isSearching && renderFranchisePagination(Math.max(groupedResults.length, catalogueExpectedTitles))}';
  const positions = [...resultsSource.matchAll(new RegExp(call.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'))]
    .map(match => match.index);
  const movieGridClass = resultsSource.indexOf('className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:rounded-2xl');
  const movieGrid = resultsSource.lastIndexOf('<div', movieGridClass);

  assert.equal(positions.length, 2, 'the movie cards share top and bottom pagination bars');
  assert.ok(movieGridClass >= 0 && movieGrid >= 0);
  assert.ok(positions[0] < movieGrid);
  assert.equal(resultsSource.slice(positions[0] + call.length, movieGrid).trim(), '');
  assert.ok(positions[1] > movieGrid);
  assert.match(panelSource, /total > franchiseGridPageSize/);
  assert.match(panelSource, /franchiseGridPage <= 1[\s\S]*navigateFranchisePage\(Math\.max\(1, franchiseGridPage - 1\)\)/);
  assert.match(panelSource, /franchiseGridPage >= Math\.ceil\(total \/ franchiseGridPageSize\)[\s\S]*navigateFranchisePage\(Math\.min\(Math\.ceil\(total \/ franchiseGridPageSize\), franchiseGridPage \+ 1\)\)/);

  for (const view of movieCatalogueViews) {
    await t.test(view.label, () => {
      assert.deepEqual(sectionCache.franchiseCatalogueSection(view.mode), {
        section: view.section,
        subsection: view.subsection,
      });
    });
  }
});

test('Marvel Web Series, DC Web Series and Favourites Web Series have matching top and bottom pagination', async t => {
  const source = await readFile(
    resolve(frontendRoot, 'src/components/torrent-search/sections/SearchResultsSection.tsx'),
    'utf8',
  );
  const gridClass = 'className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 lg:gap-4"';
  const views = [
    {
      label: 'Favourites Web Series',
      start: "activeTopSection === 'classics' && classicsContentTab !== 'movies' ? (",
      end: ') : regionalWebSeriesLoading ?',
      call: 'renderFranchisePagination(marvelWebSeriesCatalogue.results.length)',
    },
    {
      label: 'DC Web Series',
      start: ') : showDcWebSeries ? (',
      end: ') : showMarvelWebSeries ? (',
      call: 'renderDcWebSeriesPagination()',
    },
    {
      label: 'Marvel Web Series',
      start: ') : showMarvelWebSeries ? (',
      end: ') : (',
      call: 'renderFranchisePagination(marvelWebSeriesCatalogue.results.length)',
    },
  ];

  for (const view of views) {
    await t.test(view.label, () => {
      const start = source.indexOf(view.start);
      assert.ok(start >= 0, 'series rendering branch exists');
      const end = source.indexOf(view.end, start + view.start.length);
      assert.ok(end > start, 'series branch has a distinct end');
      const branch = source.slice(start, end);
      const calls = findOccurrences(branch, view.call);
      const cardGridClass = branch.indexOf(gridClass);
      const cardGrid = branch.lastIndexOf('<div', cardGridClass);

      assert.equal(calls.length, 2, 'both bars use the same catalogue count and helper');
      assert.ok(cardGridClass >= 0 && cardGrid >= 0, 'series card grid exists');
      assert.ok(calls[0] < cardGrid, 'top pagination precedes the cards');
      assert.ok(calls[1] > cardGrid, 'bottom pagination follows the cards');
    });
  }
});
