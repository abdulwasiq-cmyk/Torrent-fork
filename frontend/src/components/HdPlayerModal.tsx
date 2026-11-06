import React, { useEffect, useRef, useState } from 'react';
import { Check, Copy, ExternalLink, Loader2, X } from 'lucide-react';
import type { NuvioStreamOption } from '../api/types.ts';
import { copyTextNow } from './torrent-search/webtor.ts';
import { currentPlatform, mxPlayerLink, playsSilently, vlcLink } from './torrent-search/hdPlayer.ts';

/**
 * Play HD: tries the file in the browser. If the browser cannot decode it (HEVC / DTS are common in these files) or it
 * plays without sound, the message and the "Open in" links offer VLC and MX Player, which play everything.
 */
export const HdPlayerModal: React.FC<{ title: string; option: NuvioStreamOption; onClose: () => void }> = ({ title, option, onClose }) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<'loading' | 'playing' | 'failed' | 'silent'>('loading');
  const [copied, setCopied] = useState(false);
  const platform = currentPlatform();
  const vlc = vlcLink(option.url, platform);
  const mx = mxPlayerLink(option.url, platform);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    if (state !== 'playing') return undefined;
    const timer = window.setInterval(() => {
      const video = videoRef.current;
      if (video && !video.paused && playsSilently(video)) setState('silent');
    }, 1500);
    return () => window.clearInterval(timer);
  }, [state]);

  const linkClass = 'inline-flex items-center gap-1 rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-100 hover:bg-slate-700';
  const problem = state === 'failed'
    ? 'This browser cannot play this file (the video or audio format is not supported).'
    : state === 'silent' ? 'The video plays but has no sound in this browser (the audio format is not supported).' : '';

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/80 p-3" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-label={`Play ${title}`} className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-2.5">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-bold text-slate-100">{title}</h2>
            <p className="truncate text-[11px] text-slate-400" title={option.filename}>{option.label}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close player" className="shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"><X className="h-4 w-4" /></button>
        </header>
        <div className="relative bg-black">
          <video
            ref={videoRef}
            src={option.url}
            controls
            autoPlay
            playsInline
            preload="metadata"
            className="max-h-[60vh] w-full"
            onPlaying={() => setState(previous => (previous === 'silent' ? previous : 'playing'))}
            onError={() => setState('failed')}
          />
          {state === 'loading' && <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-slate-300"><Loader2 className="h-6 w-6 animate-spin" /></div>}
        </div>
        <div className="space-y-2 px-4 py-3">
          {problem && <div role="alert" className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">{problem} Open it in a player app instead:</div>}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-slate-500">Open in</span>
            {vlc && <a href={vlc} className={linkClass}><ExternalLink className="h-3.5 w-3.5" />VLC</a>}
            {mx && <a href={mx} className={linkClass}><ExternalLink className="h-3.5 w-3.5" />MX Player</a>}
            <button type="button" className={linkClass} onClick={() => { if (copyTextNow(option.url)) { setCopied(true); window.setTimeout(() => setCopied(false), 2000); } }}>
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}Copy link
            </button>
          </div>
          {platform === 'desktop' && <p className="text-[10px] text-slate-500">On a computer, paste the copied link in VLC: Media → Open Network Stream.</p>}
        </div>
      </section>
    </div>
  );
};
