import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const originalWindow = globalThis.window;
globalThis.window = {
  location: { origin: 'https://torrent-studio.test' },
  setTimeout: () => 1,
  clearTimeout: () => {},
};

async function loadModule(path) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(path, import.meta.url))],
    bundle: true,
    format: 'esm',
    platform: 'node',
    write: false,
    define: { 'import.meta.env': '{}' },
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`
  );
}

const { api } = await loadModule('../src/api/client.ts');
const modalSource = await readFile(
  new URL('../src/app/views/SeedrOnboardingModal.tsx', import.meta.url),
  'utf8',
);
const seedrStateSource = await readFile(
  new URL('../src/app/state/useSeedrState.ts', import.meta.url),
  'utf8',
);
const addFlowSource = await readFile(
  new URL('../src/app/state/useAddFlow.ts', import.meta.url),
  'utf8',
);
const appModelSource = await readFile(
  new URL('../src/app/useAppModel.tsx', import.meta.url),
  'utf8',
);
const generationSource = seedrStateSource.slice(
  seedrStateSource.indexOf('export function advanceSeedrPrepareGeneration'),
  seedrStateSource.indexOf('export function useSeedrState'),
);
const generationTransformed = await build({
  stdin: { contents: generationSource, loader: 'ts' },
  format: 'esm',
  write: false,
});
const generation = await import(
  `data:text/javascript;base64,${Buffer.from(generationTransformed.outputFiles[0].text).toString('base64')}`
);

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

test.after(() => {
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
});

test('Seedr token input is controlled, masked, and permits native paste', () => {
  assert.match(modalSource, /type="password"/);
  assert.match(modalSource, /value=\{seedrPat\}/);
  assert.match(modalSource, /onChange=\{\(e\) => setSeedrPat\(e\.target\.value\)\}/);
  assert.doesNotMatch(modalSource, /onPaste=\{[^}]*preventDefault/);
});

test('pasted PAT is trimmed, saved with CSRF, and never returned to the UI', async t => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    if (String(url).endsWith('/api/seedr/session')) {
      return new Response(JSON.stringify({ connected: false, csrfToken: 'csrf-test' }), { status: 200 });
    }
    return new Response(JSON.stringify({ connected: true, status: 'connected' }), { status: 200 });
  };
  t.after(() => { globalThis.fetch = originalFetch; });

  const session = await api.getSeedrSession();
  const result = await api.connectSeedrPat('  pasted-test-token\n');

  assert.equal(session.connected, false);
  assert.equal(result.connected, true);
  assert.equal(requests.length, 2);
  assert.equal(requests[1].init.headers.get('X-Torrent-Studio-CSRF'), 'csrf-test');
  assert.deepEqual(JSON.parse(requests[1].init.body), { pat: 'pasted-test-token' });
  assert.equal(requests[1].init.credentials, 'include');
  assert.equal('access_token' in session, false);
});

test('missing PAT is rejected before a request is sent', async t => {
  const originalFetch = globalThis.fetch;
  let requestCount = 0;
  globalThis.fetch = async () => {
    requestCount += 1;
    return new Response('{}', { status: 200 });
  };
  t.after(() => { globalThis.fetch = originalFetch; });

  await assert.rejects(
    api.connectSeedrPat(' \n '),
    /Enter your Seedr Personal Access Token/,
  );
  assert.equal(requestCount, 0);
});

test('invalid-token and insufficient-scope statuses remain distinguishable', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });

  for (const [status, code] of [
    [401, 'SEEDR_TOKEN_REJECTED'],
    [403, 'SEEDR_INSUFFICIENT_SCOPE'],
  ]) {
    globalThis.fetch = async () => new Response(
      JSON.stringify({ code, detail: `Seedr error ${code}` }),
      { status },
    );
    await assert.rejects(
      api.connectSeedrPat('test-token'),
      error => error.status === status && error.code === code,
    );
  }
});

test('changing Seedr account and preparing a result send CSRF-protected mutations', async t => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    if (String(url).endsWith('/api/seedr/session')) {
      return new Response(JSON.stringify({ connected: false, csrfToken: 'csrf-test' }), { status: 200 });
    }
    return new Response(JSON.stringify({ task_id: 17, torrent_name: 'Example' }), { status: 200 });
  };
  t.after(() => { globalThis.fetch = originalFetch; });

  await api.getSeedrSession();
  await api.disconnectSeedr();
  const magnet = 'magnet:?xt=urn:btih:' + 'd'.repeat(40) + '&dn=Example';
  const prepared = await api.prepareSeedrMagnet(
    magnet,
    1200,
    'Example',
    16,
  );

  assert.equal(prepared.seedrTaskId, 17);
  assert.equal(requests[1].url.endsWith('/api/seedr/connect/disconnect'), true);
  assert.equal(requests[1].init.headers.get('X-Torrent-Studio-CSRF'), 'csrf-test');
  assert.equal(requests[2].url.endsWith('/api/seedr/add'), true);
  const body = JSON.parse(requests[2].init.body);
  assert.equal(body.magnet, magnet);
  assert.equal(body.torrent_name, 'Example');
  assert.equal(body.required_bytes, 1200);
  assert.equal(body.replace_task_id, '16');
  assert.equal(requests[2].init.headers.get('X-Torrent-Studio-CSRF'), 'csrf-test');
});

test('Seedr Prepare preserves provider authentication and endpoint error statuses', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });

  for (const [status, code] of [
    [401, 'SEEDR_TOKEN_REJECTED'],
    [403, 'SEEDR_INSUFFICIENT_SCOPE'],
    [404, 'SEEDR_ENDPOINT_NOT_FOUND'],
    [429, 'SEEDR_RATE_LIMITED'],
  ]) {
    globalThis.fetch = async () => new Response(
      JSON.stringify({ code, detail: `Seedr error ${code}` }),
      { status },
    );
    await assert.rejects(
      api.prepareSeedrMagnet('magnet:?xt=urn:btih:' + 'e'.repeat(40)),
      error => error.status === status && error.code === code,
    );
  }
});

test('switching Seedr accounts before submission invalidates a pending Prepare', async () => {
  const prepareGenerationRef = { current: 0 };
  const accountGenerationRef = { current: 0 };
  const preflight = deferred();
  let submissions = 0;
  let stateUpdates = 0;

  const prepare = async () => {
    const operationGeneration = generation.advanceSeedrPrepareGeneration(prepareGenerationRef);
    const accountGeneration = accountGenerationRef.current;
    await preflight.promise;
    if (
      !generation.seedrPrepareGenerationIsCurrent(prepareGenerationRef, operationGeneration) ||
      accountGenerationRef.current !== accountGeneration
    ) return;
    submissions += 1;
    stateUpdates += 1;
  };

  const pendingPrepare = prepare();
  generation.advanceSeedrPrepareGeneration(prepareGenerationRef);
  accountGenerationRef.current += 1;
  preflight.resolve();
  await pendingPrepare;

  assert.equal(submissions, 0);
  assert.equal(stateUpdates, 0);
});

test('switching Seedr accounts during submission prevents stale task updates', async () => {
  const prepareGenerationRef = { current: 0 };
  const accountGenerationRef = { current: 0 };
  const addResponse = deferred();
  let submissions = 0;
  let taskIdsApplied = 0;

  const prepare = async () => {
    const operationGeneration = generation.advanceSeedrPrepareGeneration(prepareGenerationRef);
    const accountGeneration = accountGenerationRef.current;
    if (
      !generation.seedrPrepareGenerationIsCurrent(prepareGenerationRef, operationGeneration) ||
      accountGenerationRef.current !== accountGeneration
    ) return;
    submissions += 1;
    await addResponse.promise;
    if (
      !generation.seedrPrepareGenerationIsCurrent(prepareGenerationRef, operationGeneration) ||
      accountGenerationRef.current !== accountGeneration
    ) return;
    taskIdsApplied += 1;
  };

  const pendingPrepare = prepare();
  generation.advanceSeedrPrepareGeneration(prepareGenerationRef);
  accountGenerationRef.current += 1;
  addResponse.resolve({ taskId: 'stale-task' });
  await pendingPrepare;

  assert.equal(submissions, 1);
  assert.equal(taskIdsApplied, 0);
});

test('a pending Prepare remains valid while the Seedr account is unchanged', async () => {
  const prepareGenerationRef = { current: 0 };
  const accountGenerationRef = { current: 0 };
  const response = deferred();
  let taskIdApplied = '';

  const prepare = async () => {
    const operationGeneration = generation.advanceSeedrPrepareGeneration(prepareGenerationRef);
    const accountGeneration = accountGenerationRef.current;
    const result = await response.promise;
    if (
      !generation.seedrPrepareGenerationIsCurrent(prepareGenerationRef, operationGeneration) ||
      accountGenerationRef.current !== accountGeneration
    ) return;
    taskIdApplied = result.taskId;
  };

  const pendingPrepare = prepare();
  response.resolve({ taskId: 'current-task' });
  await pendingPrepare;

  assert.equal(taskIdApplied, 'current-task');
});

test('Prepare checks account and operation generations around async work', () => {
  assert.match(addFlowSource, /advanceSeedrPrepareGeneration\(seedrPrepareGenerationRef\)/);
  assert.match(addFlowSource, /await api\.resolveSearchMagnet[\s\S]*?ensurePrepareIsCurrent\(\)/);
  assert.match(addFlowSource, /await api\.inspectMagnet\([\s\S]*?ensurePrepareIsCurrent\(\)/);
  assert.match(addFlowSource, /ensurePrepareIsCurrent\(\);\s*const prepared = await api\.prepareSeedrMagnet/);
  assert.match(addFlowSource, /const prepared = await api\.prepareSeedrMagnet[\s\S]*?\);\s*ensurePrepareIsCurrent\(\)/);
  assert.match(addFlowSource, /seedrAccountGenerationRef\.current !== accountGeneration/);
  assert.match(appModelSource, /seedrAccountGenerationRef\.current \+= 1/);
});
