/**
 * Engine Lab: side-by-side test page for three ways of fetching a torrent in
 * the browser. Open the app with ?lab=engines.
 *
 *  - WebTorrent : runs entirely in this browser tab (WebRTC peers only).
 *  - Webtor     : hosted embed player; the Webtor service does the downloading.
 *  - TorrServer : your own VPS runs the download and streams it over HTTP.
 *
 * Nothing here touches the main app state; it is for comparing the engines.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

const WEBTORRENT_URL: string = 'https://cdn.jsdelivr.net/npm/webtorrent@2/dist/webtorrent.min.js';
const WEBTOR_SDK_URL = 'https://cdn.jsdelivr.net/npm/@webtor/embed-sdk-js/dist/index.min.js';
const WSS_TRACKERS = [
  'wss://tracker.openwebtorrent.com',
  'wss://tracker.webtorrent.dev',
  'wss://tracker.btorrent.xyz',
  'wss://tracker.files.fm:7073/announce',
];
const STORE_KEY = 'engineLab.torrserver';

const card = 'rounded-2xl border border-slate-700/80 bg-slate-900 p-4 space-y-3';
const input = 'w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100';
const button = 'rounded-lg bg-sky-500 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50';

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

/* ----------------------------- WebTorrent ----------------------------- */

interface WtFile {
  name: string;
  length: number;
  streamTo: (element: HTMLVideoElement) => void;
  blob: () => Promise<Blob>;
}
interface WtTorrent {
  files: WtFile[];
  numPeers: number;
  downloadSpeed: number;
  progress: number;
  downloaded: number;
  length: number;
  destroy: () => void;
}
interface WtClient {
  add: (magnet: string, options: { announce: string[] }, onReady: (torrent: WtTorrent) => void) => WtTorrent;
  on: (event: string, handler: (error: Error) => void) => void;
  destroy: () => void;
}

function WebTorrentPanel({ magnet }: { magnet: string }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const clientRef = useRef<WtClient | null>(null);
  const torrentRef = useRef<WtTorrent | null>(null);
  const [status, setStatus] = useState('Idle');
  const [stats, setStats] = useState('');
  const [files, setFiles] = useState<WtFile[]>([]);

  const stop = useCallback(() => {
    clientRef.current?.destroy();
    clientRef.current = null;
    torrentRef.current = null;
    setFiles([]);
    setStats('');
  }, []);

  useEffect(() => stop, [stop]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const torrent = torrentRef.current;
      if (!torrent) return;
      setStats(
        `${torrent.numPeers} peers | ${formatBytes(torrent.downloadSpeed)}/s | ` +
          `${(torrent.progress * 100).toFixed(1)}% of ${formatBytes(torrent.length)}`,
      );
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const play = (file: WtFile) => {
    if (videoRef.current) {
      file.streamTo(videoRef.current);
      setStatus(`Streaming ${file.name}`);
    }
  };

  const start = async () => {
    stop();
    setStatus('Loading WebTorrent...');
    try {
      const module = (await import(/* @vite-ignore */ WEBTORRENT_URL)) as { default: new () => WtClient };
      const client = new module.default();
      clientRef.current = client;
      client.on('error', (error: Error) => setStatus(`Error: ${error.message}`));
      setStatus('Looking for WebRTC peers (many swarms have none)...');
      client.add(magnet, { announce: WSS_TRACKERS }, (torrent) => {
        torrentRef.current = torrent;
        setFiles(torrent.files);
        const video = torrent.files
          .filter((file) => /\.(mp4|webm|m4v)$/i.test(file.name))
          .sort((a, b) => b.length - a.length)[0];
        if (video) play(video);
        else setStatus('Metadata loaded; no browser-playable file (mp4/webm). Download one below.');
      });
    } catch (error) {
      setStatus(`Failed to start: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const save = async (file: WtFile) => {
    const blob = await file.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = file.name;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className={card}>
      <h2 className="text-base font-bold text-sky-300">WebTorrent (in this browser)</h2>
      <p className="text-xs text-slate-400">Your device downloads it; no server bandwidth. Only reaches peers that speak WebRTC.</p>
      <div className="flex gap-2">
        <button className={button} disabled={!magnet} onClick={start}>Start</button>
        <button className="rounded-lg border border-slate-600 px-3 py-2 text-sm" onClick={stop}>Stop</button>
      </div>
      <div className="text-xs text-slate-300">{status}</div>
      {stats && <div className="text-xs font-mono text-emerald-300">{stats}</div>}
      <video ref={videoRef} controls className="w-full rounded-lg bg-black" />
      {files.length > 0 && (
        <ul className="space-y-1 text-xs">
          {files.map((file) => (
            <li key={file.name} className="flex items-center justify-between gap-2">
              <span className="truncate">{file.name} ({formatBytes(file.length)})</span>
              <span className="flex gap-2">
                <button className="underline" onClick={() => play(file)}>play</button>
                <button className="underline" onClick={() => void save(file)}>save</button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/* ------------------------------- Webtor ------------------------------- */

declare global {
  interface Window {
    webtor?: Array<Record<string, unknown>>;
  }
}

function WebtorPanel({ magnet }: { magnet: string }) {
  const [mountId, setMountId] = useState('');

  useEffect(() => {
    if (!document.querySelector(`script[src="${WEBTOR_SDK_URL}"]`)) {
      const script = document.createElement('script');
      script.src = WEBTOR_SDK_URL;
      script.async = true;
      document.head.appendChild(script);
    }
  }, []);

  useEffect(() => {
    if (!mountId) return;
    window.webtor = window.webtor || [];
    window.webtor.push({ id: mountId, magnet, width: '100%', height: '360px', features: { continue: false } });
  }, [mountId, magnet]);

  return (
    <section className={card}>
      <h2 className="text-base font-bold text-sky-300">Webtor (hosted embed)</h2>
      <p className="text-xs text-slate-400">Webtor's servers fetch and stream it; the free tier may show ads and has limits.</p>
      <button className={button} disabled={!magnet} onClick={() => setMountId(`webtor-${Date.now()}`)}>Start</button>
      {mountId && <div id={mountId} className="min-h-[200px]" />}
    </section>
  );
}

/* ----------------------------- TorrServer ----------------------------- */

interface TsFile {
  id: number;
  path: string;
  length: number;
}
interface TsTorrent {
  hash?: string;
  title?: string;
  stat_string?: string;
  active_peers?: number;
  total_peers?: number;
  download_speed?: number;
  preloaded_bytes?: number;
  torrent_size?: number;
  file_stats?: TsFile[];
}

function loadSaved(): { base: string; key: string } {
  try {
    const raw = window.localStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw) as { base: string; key: string };
  } catch {
    /* ignore */
  }
  return { base: '', key: '' };
}

function TorrServerPanel({ magnet }: { magnet: string }) {
  const saved = loadSaved();
  const [base, setBase] = useState(saved.base);
  const [key, setKey] = useState(saved.key);
  const [status, setStatus] = useState('Idle');
  const [torrent, setTorrent] = useState<TsTorrent | null>(null);
  const [streamUrl, setStreamUrl] = useState('');
  const hashRef = useRef('');

  const call = useCallback(
    async (body: Record<string, unknown>): Promise<TsTorrent> => {
      const root = base.replace(/\/+$/, '');
      const response = await fetch(`${root}/torrents?key=${encodeURIComponent(key)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`TorrServer answered HTTP ${response.status}`);
      return (await response.json()) as TsTorrent;
    },
    [base, key],
  );

  const urlFor = useCallback(
    (file: TsFile, hash: string) => {
      const root = base.replace(/\/+$/, '');
      const name = encodeURIComponent(file.path.split('/').pop() || 'video');
      return `${root}/stream/${name}?link=${hash}&index=${file.id}&play&key=${encodeURIComponent(key)}`;
    },
    [base, key],
  );

  const start = async () => {
    try {
      window.localStorage.setItem(STORE_KEY, JSON.stringify({ base, key }));
    } catch {
      /* ignore */
    }
    setStatus('Adding torrent (waiting for metadata)...');
    setStreamUrl('');
    try {
      const added = await call({ action: 'add', link: magnet, save_to_db: false });
      if (!added.hash) throw new Error('No hash returned');
      hashRef.current = added.hash;
      setTorrent(added);
      const files = added.file_stats || [];
      const video = [...files].sort((a, b) => b.length - a.length)[0];
      if (video) setStreamUrl(urlFor(video, added.hash));
      setStatus('Added. Streaming starts when the browser requests the file.');
    } catch (error) {
      setStatus(`Failed: ${error instanceof Error ? error.message : String(error)} (check URL, key, CORS)`);
    }
  };

  const remove = async () => {
    if (!hashRef.current) return;
    try {
      await call({ action: 'rem', hash: hashRef.current });
      setStatus('Removed from TorrServer');
      setStreamUrl('');
      setTorrent(null);
      hashRef.current = '';
    } catch (error) {
      setStatus(`Remove failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  useEffect(() => {
    if (!torrent?.hash) return;
    const timer = window.setInterval(() => {
      call({ action: 'get', hash: torrent.hash }).then(setTorrent).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [torrent?.hash, call]);

  const files = torrent?.file_stats || [];

  return (
    <section className={card}>
      <h2 className="text-base font-bold text-sky-300">TorrServer (your VPS)</h2>
      <p className="text-xs text-slate-400">The VPS downloads and streams over HTTP, so VPS bandwidth is used. Handles normal TCP peers.</p>
      <input className={input} placeholder="https://ts.your-domain.com" value={base} onChange={(event) => setBase(event.target.value)} />
      <input className={input} placeholder="access key" value={key} onChange={(event) => setKey(event.target.value)} />
      <div className="flex gap-2">
        <button className={button} disabled={!magnet || !base} onClick={start}>Start</button>
        <button className="rounded-lg border border-slate-600 px-3 py-2 text-sm" disabled={!torrent} onClick={remove}>Remove</button>
      </div>
      <div className="text-xs text-slate-300">{status}</div>
      {torrent && (
        <div className="text-xs font-mono text-emerald-300">
          {torrent.active_peers ?? 0}/{torrent.total_peers ?? 0} peers | {formatBytes(torrent.download_speed ?? 0)}/s |
          cached {formatBytes(torrent.preloaded_bytes ?? 0)} of {formatBytes(torrent.torrent_size ?? 0)}
        </div>
      )}
      {streamUrl && <video src={streamUrl} controls className="w-full rounded-lg bg-black" />}
      {files.length > 0 && (
        <ul className="space-y-1 text-xs">
          {files.map((file) => (
            <li key={file.id} className="flex items-center justify-between gap-2">
              <span className="truncate">{file.path} ({formatBytes(file.length)})</span>
              <span className="flex gap-2">
                <button className="underline" onClick={() => setStreamUrl(urlFor(file, torrent?.hash || ''))}>play</button>
                <a className="underline" href={urlFor(file, torrent?.hash || '')} download>download</a>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/* -------------------------------- Page -------------------------------- */

export default function EngineLab() {
  const [draft, setDraft] = useState('');
  const [magnet, setMagnet] = useState('');

  return (
    <div className="min-h-screen bg-slate-950 p-4 text-slate-100">
      <div className="mx-auto max-w-6xl space-y-4">
        <header className="space-y-2">
          <h1 className="text-xl font-bold">Engine Lab</h1>
          <p className="text-xs text-slate-400">Paste a magnet link (a well-seeded, legal one such as a Linux ISO or Big Buck Bunny), then start each engine and compare.</p>
          <div className="flex gap-2">
            <input className={input} placeholder="magnet:?xt=urn:btih:..." value={draft} onChange={(event) => setDraft(event.target.value)} />
            <button className={button} disabled={!draft.startsWith('magnet:')} onClick={() => setMagnet(draft.trim())}>Use</button>
          </div>
          <a className="text-xs underline text-sky-300" href="/">Back to app</a>
        </header>
        <div className="grid gap-4 lg:grid-cols-3">
          <WebTorrentPanel key={`wt-${magnet}`} magnet={magnet} />
          <WebtorPanel key={`wb-${magnet}`} magnet={magnet} />
          <TorrServerPanel magnet={magnet} />
        </div>
      </div>
    </div>
  );
}
