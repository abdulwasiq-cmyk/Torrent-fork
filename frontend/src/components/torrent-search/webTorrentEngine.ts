import type { TorrentPlaybackResult } from '../media-player/types.ts';

export const WEBTORRENT_SCRIPT_URL = 'https://cdn.jsdelivr.net/npm/webtorrent@1.9.7/webtorrent.min.js';
export const WEBTORRENT_TRACKERS = [
  'wss://tracker.openwebtorrent.com',
  'wss://tracker.webtorrent.dev',
  'wss://tracker.btorrent.xyz',
  'wss://tracker.files.fm:7073/announce',
];

const VIDEO_FILE_PATTERN = /\.(mkv|mp4|m4v|webm|mov|avi|ts)$/i;
const SAMPLE_FILE_PATTERN = /(^|[\\/._ -])(sample|trailer|preview|proof|featurette|extras?)([\\/._ -]|$)/i;
const METADATA_TIMEOUT_MESSAGE =
  'Timed out waiting for torrent metadata. Browser WebTorrent needs WebRTC-compatible peers; ordinary BitTorrent TCP/UDP peers cannot connect.';

export interface BrowserTorrentFile {
  name: string;
  path?: string;
  length: number;
  renderTo: (element: HTMLVideoElement, options?: Record<string, unknown>, callback?: (error?: Error) => void) => void;
  getBlob: (callback: (error: Error | null, blob?: Blob) => void) => void;
}

interface BrowserTorrent {
  name?: string;
  files: BrowserTorrentFile[];
  numPeers: number;
  downloadSpeed: number;
  downloaded: number;
  length: number;
  progress: number;
  on: (event: string, handler: (error?: Error) => void) => void;
}

export interface BrowserTorrentClient {
  add: (magnet: string, options: { announce: string[] }, onReady: (torrent: BrowserTorrent) => void) => BrowserTorrent;
  on: (event: string, handler: (error: Error) => void) => void;
  destroy: () => void;
}

export type BrowserTorrentConstructor = new () => BrowserTorrentClient;

export interface BrowserTorrentSession {
  torrent: BrowserTorrent;
  files: BrowserTorrentFile[];
  subscribeStatus: (listener: (status: string) => void) => () => void;
  reportStatus: (status: string) => void;
  dispose: () => void;
}

export function shouldShowTorrentFileSelection<T>(
  files: T[],
  playableFiles: T[],
): boolean {
  return files.length > 1 || playableFiles.length !== 1;
}

export function createWebTorrentPlayback(
  file: BrowserTorrentFile,
  session: BrowserTorrentSession,
  onError?: (message: string) => void,
): TorrentPlaybackResult {
  return {
    provider: 'WebTorrent',
    fileName: file.name,
    fileSize: file.length,
    source: {
      provider: 'WebTorrent',
      kind: 'webtorrent',
      attachVideo(video) {
        file.renderTo(video, {}, renderError => {
          if (!renderError) return;
          const message = `WebTorrent playback failed: ${renderError.message}`;
          onError?.(message);
          session.reportStatus(message);
        });
        return () => {
          video.pause();
          video.removeAttribute('src');
          video.load();
        };
      },
      download: () => downloadBrowserTorrentFile(file),
      dispose: session.dispose,
      subscribeStatus: session.subscribeStatus,
    },
  };
}

export function supportsBrowserWebTorrent(environment: {
  RTCPeerConnection?: unknown;
  WebSocket?: unknown;
} = globalThis as typeof globalThis & { RTCPeerConnection?: unknown; WebSocket?: unknown }): boolean {
  return typeof environment.RTCPeerConnection === 'function' &&
    typeof environment.WebSocket === 'function';
}

export function playableVideoFiles<T extends { name?: string; path?: string }>(files: T[]): T[] {
  return files.filter(file => {
    const path = file.path || file.name || '';
    return VIDEO_FILE_PATTERN.test(path) && !SAMPLE_FILE_PATTERN.test(path);
  });
}

export async function loadBrowserWebTorrent(): Promise<BrowserTorrentConstructor> {
  const existing = (window as Window & { WebTorrent?: BrowserTorrentConstructor }).WebTorrent;
  if (existing) return existing;

  await new Promise<void>((resolve, reject) => {
    const priorScript = document.querySelector<HTMLScriptElement>(`script[src="${WEBTORRENT_SCRIPT_URL}"]`);
    const script = priorScript || document.createElement('script');
    const onLoad = () => {
      script.dataset.loaded = 'true';
      resolve();
    };
    const onError = () => reject(new Error('Could not load the WebTorrent browser library.'));

    if (script.dataset.loaded === 'true') {
      resolve();
      return;
    }

    script.addEventListener('load', onLoad, { once: true });
    script.addEventListener('error', onError, { once: true });
    if (!priorScript) {
      script.src = WEBTORRENT_SCRIPT_URL;
      script.async = true;
      document.head.appendChild(script);
    }
  });

  const constructor = (window as Window & { WebTorrent?: BrowserTorrentConstructor }).WebTorrent;
  if (!constructor) throw new Error('The WebTorrent browser library loaded without exposing its client.');
  return constructor;
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

export async function startBrowserWebTorrent(
  magnet: string,
  options: {
    clientFactory?: () => BrowserTorrentClient | Promise<BrowserTorrentClient>;
    onStatus?: (status: string) => void;
    metadataTimeoutMs?: number;
    environment?: { RTCPeerConnection?: unknown; WebSocket?: unknown };
  } = {},
): Promise<BrowserTorrentSession> {
  if (!supportsBrowserWebTorrent(options.environment)) {
    throw new Error('This browser does not support WebRTC required by browser WebTorrent.');
  }
  const factory = options.clientFactory || (async () => {
    const Constructor = await loadBrowserWebTorrent();
    return new Constructor();
  });
  const client = await factory();
  const statusListeners = new Set<(status: string) => void>();
  const emitStatus = (status: string) => {
    options.onStatus?.(status);
    statusListeners.forEach(listener => listener(status));
  };

  return new Promise((resolve, reject) => {
    let settled = false;
    let disposed = false;
    let progressTimer: number | undefined;
    const timeout = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      client.destroy();
      reject(new Error(METADATA_TIMEOUT_MESSAGE));
    }, options.metadataTimeoutMs ?? 45_000);

    const fail = (error?: Error) => {
      const message = error?.message || 'The browser WebTorrent client failed.';
      if (!settled) {
        settled = true;
        window.clearTimeout(timeout);
        client.destroy();
        reject(new Error(message));
      } else {
        emitStatus(`WebTorrent error: ${message}`);
      }
    };

    client.on('error', error => fail(error));
    emitStatus('Loading torrent metadata from WebRTC-compatible peers…');
    try {
      const torrent = client.add(magnet, { announce: WEBTORRENT_TRACKERS }, readyTorrent => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        readyTorrent.on('error', error => fail(error));
        const connectedAt = Date.now();
        let reportedNoPeers = false;
        const updateProgress = () => {
          if (readyTorrent.numPeers === 0 && !reportedNoPeers && Date.now() - connectedAt >= 20_000) {
            reportedNoPeers = true;
            emitStatus('No WebRTC-compatible peers are connected. Ordinary TCP/UDP BitTorrent peers cannot serve this browser client.');
            return;
          }
          if (readyTorrent.numPeers > 0) reportedNoPeers = false;
          emitStatus(
            `${readyTorrent.numPeers} WebRTC peers · ${formatBytes(readyTorrent.downloadSpeed)}/s · ` +
            `${(readyTorrent.progress * 100).toFixed(1)}% of ${formatBytes(readyTorrent.length)}`,
          );
        };
        updateProgress();
        progressTimer = window.setInterval(updateProgress, 1000);
        resolve({
          torrent: readyTorrent,
          files: readyTorrent.files,
          subscribeStatus(listener) {
            statusListeners.add(listener);
            return () => statusListeners.delete(listener);
          },
          reportStatus: emitStatus,
          dispose() {
            if (disposed) return;
            disposed = true;
            if (progressTimer !== undefined) window.clearInterval(progressTimer);
            statusListeners.clear();
            client.destroy();
          },
        });
      });
      torrent.on('error', error => fail(error));
    } catch (error) {
      fail(error instanceof Error ? error : new Error(String(error)));
    }
  });
}

export function downloadBrowserTorrentFile(file: BrowserTorrentFile): Promise<void> {
  return new Promise((resolve, reject) => {
    file.getBlob((error, blob) => {
      if (error || !blob) {
        reject(error || new Error('WebTorrent could not prepare this file for download.'));
        return;
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = file.name;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      resolve();
    });
  });
}
