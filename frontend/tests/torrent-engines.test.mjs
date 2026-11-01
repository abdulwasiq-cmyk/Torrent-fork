import assert from 'node:assert/strict';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

async function loadModule(relativePath) {
  const { outputFiles } = await build({
    entryPoints: [resolve(frontendRoot, relativePath)],
    bundle: true,
    format: 'esm',
    platform: 'node',
    target: 'node20',
    write: false,
  });
  const source = Buffer.from(outputFiles[0].contents).toString('base64');
  return import(`data:text/javascript;base64,${source}`);
}

const [webTorrent, webtor, menu] = await Promise.all([
  loadModule('src/components/torrent-search/webTorrentEngine.ts'),
  loadModule('src/components/torrent-search/webtorEmbed.ts'),
  loadModule('src/components/torrent-search/TorrentEngineMenu.tsx'),
]);

function installWindow() {
  const previous = globalThis.window;
  const previousDocument = globalThis.document;
  globalThis.window = {
    setTimeout(callback, delay, ...args) {
      if (delay === 60_000) {
        setImmediate(callback, ...args);
        return 0;
      }
      return setTimeout(callback, delay, ...args);
    },
    clearTimeout,
    setInterval,
    clearInterval,
  };
  globalThis.document = {
    createElement() {
      return { click() {} };
    },
  };
  return () => {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  };
}

function makeClient({ ready = true } = {}) {
  const clientEvents = new Map();
  const torrentEvents = new Map();
  const file = {
    name: 'movie.mp4',
    path: 'Movie/movie.mp4',
    length: 1024,
    renderTo(video, _options, callback) {
      video.src = 'blob:browser-torrent';
      callback?.();
    },
    getBlob(callback) {
      callback(null, new Blob(['video']));
    },
  };
  const torrent = {
    name: 'Movie',
    files: [file],
    numPeers: 2,
    downloadSpeed: 512,
    downloaded: 1024,
    length: 1024,
    progress: 1,
    on(event, handler) {
      torrentEvents.set(event, handler);
    },
  };
  let destroyed = 0;
  return {
    client: {
      add(_magnet, _options, onReady) {
        if (ready) queueMicrotask(() => onReady(torrent));
        return torrent;
      },
      on(event, handler) {
        clientEvents.set(event, handler);
      },
      destroy() {
        destroyed += 1;
      },
    },
    clientEvents,
    torrentEvents,
    file,
    torrent,
    destroyed: () => destroyed,
  };
}

test('Torrent menu has exactly the three named engines and dispatches only the selected one', () => {
  assert.deepEqual(menu.TORRENT_ENGINE_OPTIONS, [
    { key: 'webtor', label: 'Webtor' },
    { key: 'webtorrent', label: 'WebTorrent' },
    { key: 'torrserver', label: 'TorrServer' },
  ]);
  const calls = [];
  let closed = false;
  menu.selectTorrentEngine('webtorrent', () => { closed = true; }, engine => {
    return menu.invokeTorrentEngine(engine, {
      webtor: () => calls.push('webtor'),
      webtorrent: () => calls.push('webtorrent'),
      torrserver: () => calls.push('torrserver'),
    });
  });
  assert.equal(closed, true);
  assert.deepEqual(calls, ['webtorrent']);
});

test('Play continues to use the established NexStream or prepared Seedr handler', () => {
  const directPlay = () => 'direct';
  const seedrPlay = () => 'seedr';
  assert.equal(menu.defaultMovieCardPlayHandler(null, { onClick: directPlay }), directPlay);
  assert.equal(menu.defaultMovieCardPlayHandler({ onPlay: seedrPlay }, { onClick: directPlay }), seedrPlay);
});

test('Webtor submission uses the official embed SDK config and reports provider errors', () => {
  const on = () => {};
  const config = webtor.makeWebtorEmbedConfig('player', 'magnet:?xt=urn:btih:abc', on);
  assert.equal(config.id, 'player');
  assert.equal(config.magnet, 'magnet:?xt=urn:btih:abc');
  assert.equal(config.controls, true);
  assert.equal(config.on, on);
  assert.equal(webtor.webtorEventError({ name: 'torrent error', data: { message: 'Unavailable' } }), 'Unavailable');
  assert.equal(webtor.webtorEventError({ name: 'player status', data: 'playing' }), null);
});

test('WebTorrent detects WebRTC support and filters samples and non-video files', () => {
  assert.equal(webTorrent.supportsBrowserWebTorrent({}), false);
  assert.equal(webTorrent.supportsBrowserWebTorrent({ RTCPeerConnection() {}, WebSocket() {} }), true);
  const files = [
    { name: 'Movie.mkv' },
    { name: 'sample.mp4' },
    { name: 'trailer/movie.webm' },
    { name: 'subtitles.srt' },
  ];
  assert.deepEqual(webTorrent.playableVideoFiles(files), [files[0]]);
  assert.equal(webTorrent.shouldShowTorrentFileSelection(files, [files[0]]), true);
  assert.equal(webTorrent.shouldShowTorrentFileSelection([files[0]], [files[0]]), false);
});

test('WebTorrent metadata loading, progress, player attachment, download, and cleanup work', async () => {
  const restoreWindow = installWindow();
  try {
    const mock = makeClient();
    const statuses = [];
    const session = await webTorrent.startBrowserWebTorrent('magnet:?xt=urn:btih:test', {
      clientFactory: () => mock.client,
      environment: { RTCPeerConnection() {}, WebSocket() {} },
      onStatus: status => statuses.push(status),
    });
    assert.equal(session.files[0].name, 'movie.mp4');
    assert.ok(statuses.some(status => status.includes('2 WebRTC peers')));

    const listeners = [];
    const unsubscribe = session.subscribeStatus(status => listeners.push(status));
    session.reportStatus('playback attached');
    assert.deepEqual(listeners, ['playback attached']);
    unsubscribe();

    const playback = webTorrent.createWebTorrentPlayback(mock.file, session);
    assert.equal(playback.provider, 'WebTorrent');
    assert.equal(playback.fileName, 'movie.mp4');
    assert.equal(playback.fileSize, 1024);
    const video = {
      pause() {},
      removeAttribute() {},
      load() {},
    };
    const detach = playback.source.attachVideo(video);
    assert.equal(video.src, 'blob:browser-torrent');
    detach();
    await playback.source.download();
    playback.source.dispose();
    playback.source.dispose();
    assert.equal(mock.destroyed(), 1);
  } finally {
    restoreWindow();
  }
});

test('WebTorrent reports unsupported WebRTC and metadata timeouts, destroying the client', async () => {
  const restoreWindow = installWindow();
  try {
    await assert.rejects(
      webTorrent.startBrowserWebTorrent('magnet:?xt=urn:btih:test', {
        environment: {},
        clientFactory: () => {
          throw new Error('must not construct client');
        },
      }),
      /does not support WebRTC/,
    );

    const mock = makeClient({ ready: false });
    await assert.rejects(
      webTorrent.startBrowserWebTorrent('magnet:?xt=urn:btih:test', {
        clientFactory: () => mock.client,
        environment: { RTCPeerConnection() {}, WebSocket() {} },
        metadataTimeoutMs: 5,
      }),
      /ordinary BitTorrent TCP\/UDP peers cannot connect/,
    );
    assert.equal(mock.destroyed(), 1);
  } finally {
    restoreWindow();
  }
});

test('WebTorrent peer errors are surfaced and rejected before metadata is ready', async () => {
  const restoreWindow = installWindow();
  try {
    const mock = makeClient({ ready: false });
    const request = webTorrent.startBrowserWebTorrent('magnet:?xt=urn:btih:test', {
      clientFactory: () => mock.client,
      environment: { RTCPeerConnection() {}, WebSocket() {} },
    });
    await new Promise(resolve => setImmediate(resolve));
    mock.clientEvents.get('error')(new Error('tracker connection failed'));
    await assert.rejects(request, /tracker connection failed/);
    assert.equal(mock.destroyed(), 1);
  } finally {
    restoreWindow();
  }
});
