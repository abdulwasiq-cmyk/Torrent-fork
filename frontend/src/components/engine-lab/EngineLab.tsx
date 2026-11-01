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
import { API_BASE, api, type TorrServerFile, type TorrServerTorrentInfo } from '../../api/client.ts';
import { downloadBrowserTorrentFile, playableVideoFiles, startBrowserWebTorrent, type BrowserTorrentFile, type BrowserTorrentSession } from '../torrent-search/webTorrentEngine.ts';

const WEBTOR_SDK_URL = 'https://cdn.jsdelivr.net/npm/@webtor/embed-sdk-js/dist/index.min.js';
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

function WebTorrentPanel({ magnet }: { magnet: string }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const sessionRef = useRef<BrowserTorrentSession | null>(null);
  const [status, setStatus] = useState('Idle');
  const [files, setFiles] = useState<BrowserTorrentFile[]>([]);

  const stop = useCallback(() => {
    sessionRef.current?.dispose();
    sessionRef.current = null;
    videoRef.current?.pause();
    videoRef.current?.removeAttribute('src');
    videoRef.current?.load();
    setFiles([]);
  }, []);

  useEffect(() => stop, [stop]);

  const play = (file: BrowserTorrentFile) => {
    if (videoRef.current) {
      file.renderTo(videoRef.current);
      setStatus(`Streaming ${file.name}`);
    }
  };

  const start = async () => {
    stop();
    setStatus('Loading WebTorrent...');
    try {
      const session = await startBrowserWebTorrent(magnet, { onStatus: setStatus });
      sessionRef.current = session;
      setFiles(session.files);
      const video = playableVideoFiles(session.files).sort((a, b) => b.length - a.length)[0];
      if (video) play(video);
      else setStatus('Metadata loaded; no playable video file was found.');
    } catch (error) {
      setStatus(`Failed to start: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const save = async (file: BrowserTorrentFile) => {
    try {
      await downloadBrowserTorrentFile(file);
    } catch (error) {
      setStatus(`Download failed: ${error instanceof Error ? error.message : String(error)}`);
    }
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

function TorrServerPanel({ magnet }: { magnet: string }) {
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState('Checking backend configuration…');
  const [torrent, setTorrent] = useState<TorrServerTorrentInfo | null>(null);
  const [streamUrl, setStreamUrl] = useState('');
  const streamUrlFor = (file: TorrServerFile) => new URL(file.streamUrl, API_BASE).toString();

  useEffect(() => {
    try {
      window.localStorage.removeItem('engineLab.torrserver');
    } catch {
      // The obsolete browser-stored access key is removed when storage is available.
    }
    void api.getTorrServerStatus()
      .then(result => {
        setEnabled(result.enabled);
        setStatus(result.error || (result.enabled ? 'Idle' : 'TorrServer playback is disabled.'));
      })
      .catch(error => setStatus(`Backend configuration failed: ${error instanceof Error ? error.message : String(error)}`));
  }, []);

  const start = async () => {
    setStatus('Adding torrent (waiting for metadata)...');
    setStreamUrl('');
    try {
      let added = await api.addTorrServerTorrent(magnet);
      for (let attempt = 0; added.files.length === 0 && attempt < 20; attempt++) {
        await new Promise(resolve => window.setTimeout(resolve, 1000));
        added = await api.getTorrServerTorrent(added.hash);
      }
      setTorrent(added);
      const videos = added.files.filter(file => /\.(mkv|mp4|m4v|webm|mov|avi|ts)$/i.test(file.path));
      const video = [...videos].sort((a, b) => b.length - a.length)[0];
      if (video) setStreamUrl(streamUrlFor(video));
      setStatus('Added. Streaming starts when the browser requests the file.');
    } catch (error) {
      setStatus(`Failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const remove = async () => {
    if (!torrent?.hash) return;
    try {
      await api.removeTorrServerTorrent(torrent.hash);
      setStatus('Removed from TorrServer');
      setStreamUrl('');
      setTorrent(null);
    } catch (error) {
      setStatus(`Remove failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  };

  useEffect(() => {
    if (!torrent?.hash) return;
    const timer = window.setInterval(() => {
      void api.getTorrServerTorrent(torrent.hash)
        .then(setTorrent)
        .catch(error => setStatus(`Could not refresh torrent info: ${error instanceof Error ? error.message : String(error)}`));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [torrent?.hash]);

  const files = torrent?.files || [];

  return (
    <section className={card}>
      <h2 className="text-base font-bold text-sky-300">TorrServer (your VPS)</h2>
      <p className="text-xs text-slate-400">The backend connects to your configured TorrServer. Its URL and access key stay server-side.</p>
      <div className="flex gap-2">
        <button className={button} disabled={!magnet || !enabled} onClick={start}>Start</button>
        <button className="rounded-lg border border-slate-600 px-3 py-2 text-sm" disabled={!torrent} onClick={remove}>Remove</button>
      </div>
      <div className="text-xs text-slate-300">{status}</div>
      {streamUrl && <video src={streamUrl} controls className="w-full rounded-lg bg-black" />}
      {files.length > 0 && (
        <ul className="space-y-1 text-xs">
          {files.map((file) => (
            <li key={file.id} className="flex items-center justify-between gap-2">
              <span className="truncate">{file.path} ({formatBytes(file.length)})</span>
              <span className="flex gap-2">
                <button className="underline" onClick={() => setStreamUrl(streamUrlFor(file))}>play</button>
                <a className="underline" href={streamUrlFor(file)} download>download</a>
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
