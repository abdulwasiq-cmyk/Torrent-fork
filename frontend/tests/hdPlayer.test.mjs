// Play HD: platform detection and the VLC / MX Player links.
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { build } from 'esbuild';

const bundle = async entry => {
  const result = await build({ entryPoints: [fileURLToPath(new URL(entry, import.meta.url))], bundle: true, format: 'esm', platform: 'node', write: false });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
};
const { platformFromUserAgent, vlcLink, mxPlayerLink, androidIntent, playsSilently } = await bundle('../src/components/torrent-search/hdPlayer.ts');
const url = 'https://a.workers.dev/tok::1/The%20Film%20%5BHindi%5D.mkv';

test('platform detection: Android, iPhone, iPadOS (Mac UA with touch), desktop', () => {
  assert.equal(platformFromUserAgent('Mozilla/5.0 (Linux; Android 14; Pixel 8) Chrome/120'), 'android');
  assert.equal(platformFromUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)'), 'ios');
  assert.equal(platformFromUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 5), 'ios');
  assert.equal(platformFromUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 0), 'desktop');
  assert.equal(platformFromUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120'), 'desktop');
});

test('Android links are intents for the app package; the https scheme is moved into the intent', () => {
  assert.equal(androidIntent(url, 'org.videolan.vlc'), 'intent://a.workers.dev/tok::1/The%20Film%20%5BHindi%5D.mkv#Intent;scheme=https;package=org.videolan.vlc;type=video/*;end');
  assert.match(mxPlayerLink(url, 'android'), /package=com\.mxtech\.videoplayer\.ad;/);
  assert.match(vlcLink(url, 'android'), /package=org\.videolan\.vlc;/);
});

test('iOS and desktop VLC links; MX Player only on Android', () => {
  assert.equal(vlcLink(url, 'ios'), 'vlc-x-callback://x-callback-url/stream?url=' + encodeURIComponent(url));
  assert.equal(vlcLink(url, 'desktop'), 'vlc://' + url);
  assert.equal(mxPlayerLink(url, 'ios'), '');
  assert.equal(mxPlayerLink(url, 'desktop'), '');
});

test('only https links are handed to other apps', () => {
  assert.equal(vlcLink('http://plain.example/x.mkv', 'android'), '');
  assert.equal(mxPlayerLink('file:///x', 'android'), '');
});

test('silent playback is detected only when the browser reports zero decoded audio after the start', () => {
  assert.equal(playsSilently({ currentTime: 5, muted: false, webkitAudioDecodedByteCount: 0 }), true);
  assert.equal(playsSilently({ currentTime: 5, muted: false, webkitAudioDecodedByteCount: 4096 }), false);
  assert.equal(playsSilently({ currentTime: 1, muted: false, webkitAudioDecodedByteCount: 0 }), false, 'too early to tell');
  assert.equal(playsSilently({ currentTime: 5, muted: true, webkitAudioDecodedByteCount: 0 }), false, 'muted by the user');
  assert.equal(playsSilently({ currentTime: 5, muted: false }), false, 'unknown browsers count as having sound');
  assert.equal(playsSilently({ currentTime: 5, muted: false, mozHasAudio: false }), true);
});
