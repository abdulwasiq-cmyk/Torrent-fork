import React from 'react';
import { Loader2, Maximize2, X } from 'lucide-react';

export type TorrentPlayerShellProvider = {
  label: 'Yenime' | 'VidRift' | 'NexStream';
  active: boolean;
  onSelect: () => void;
};

export type TorrentPlayerShellProps = {
  id: string;
  title: string;
  loading: boolean;
  loadingLabel: string;
  closeLabel: string;
  onClose: () => void;
  children: React.ReactNode;
  providers?: TorrentPlayerShellProvider[];
};

export function TorrentPlayerShell({ id, title, loading, loadingLabel, closeLabel, onClose, children, providers }: TorrentPlayerShellProps) {
  const [controlsVisible, setControlsVisible] = React.useState(true);
  const hideTimerRef = React.useRef<number | null>(null);

  const showControlsTemporarily = React.useCallback(() => {
    setControlsVisible(true);
    if (hideTimerRef.current !== null) window.clearTimeout(hideTimerRef.current);
    // On touch screens a tap inside the player iframe never reaches this page, so a hidden bar
    // could not be brought back (and taps on it fell through to the video). Only auto-hide
    // where a mouse can reveal it again.
    if (typeof window.matchMedia === 'function' && !window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;
    hideTimerRef.current = window.setTimeout(() => setControlsVisible(false), 3500);
  }, []);

  React.useEffect(() => {
    showControlsTemporarily();
    const handleKeyOrMouse = () => showControlsTemporarily();
    document.addEventListener('mousemove', handleKeyOrMouse);
    document.addEventListener('keydown', handleKeyOrMouse);
    return () => {
      document.removeEventListener('mousemove', handleKeyOrMouse);
      document.removeEventListener('keydown', handleKeyOrMouse);
      if (hideTimerRef.current !== null) window.clearTimeout(hideTimerRef.current);
    };
  }, [showControlsTemporarily]);

  const toggleFullscreen = () => {
    const box = document.getElementById(id);
    if (document.fullscreenElement) {
      void document.exitFullscreen();
      return;
    }
    if (box?.requestFullscreen) {
      void box.requestFullscreen().catch(() => {
        const frame = box.querySelector<HTMLIFrameElement>('iframe[src]');
        if (frame?.src) window.open(frame.src, '_blank', 'noopener,noreferrer');
      });
      return;
    }
    const frame = box?.querySelector<HTMLIFrameElement>('iframe[src]');
    if (frame?.src) window.open(frame.src, '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="fixed inset-0 z-[10002] flex items-center justify-center bg-black/90 p-2 sm:p-5" onMouseMove={showControlsTemporarily}>
      <div id={id} className="relative flex max-h-[96vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-violet-400/40 bg-slate-950 shadow-2xl">
        <div className={`flex h-14 shrink-0 items-center border-b border-slate-700 bg-slate-950 px-3 transition-opacity duration-300 sm:px-4 ${controlsVisible ? 'opacity-100' : 'pointer-events-none opacity-0'}`}>
          <div className="min-w-0 flex-1 pr-3 text-xs font-bold text-white sm:text-sm">
            <span className="block truncate">{title}</span>
          </div>
          {providers && providers.length > 1 && (
            <div className="mr-2 flex shrink-0 rounded-lg border border-slate-700 bg-slate-900 p-1" role="group" aria-label="Streaming provider">
              {providers.map(provider => (
                <button key={provider.label} type="button" onClick={provider.onSelect} aria-current={provider.active ? 'true' : undefined} className={provider.active ? 'rounded-md bg-violet-500 px-2.5 py-1 text-xs font-bold text-white sm:px-3 sm:py-1.5' : 'rounded-md px-2.5 py-1 text-xs font-bold text-slate-300 hover:bg-slate-800 sm:px-3 sm:py-1.5'}>{provider.label}</button>
              ))}
            </div>
          )}
          <div className="flex shrink-0 items-center gap-1.5">
            <button type="button" onClick={toggleFullscreen} className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-600 bg-slate-900 text-slate-200 shadow-lg hover:bg-slate-700" aria-label={`Fullscreen ${title}`}><Maximize2 className="h-4 w-4" /></button>
            <button id={id + '-close'} type="button" onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-600 bg-slate-900 text-slate-200 shadow-lg hover:bg-slate-700" aria-label={closeLabel}><X className="h-4 w-4" /></button>
          </div>
        </div>
        <div className="relative min-h-0 w-full flex-1 overflow-hidden bg-black aspect-video max-sm:max-h-[calc(96vh-56px)]">
          {loading && <div role="status" className="absolute inset-0 z-[10] flex items-center justify-center bg-black/70 text-sm text-slate-200"><Loader2 className="mr-2 h-5 w-5 animate-spin" />{loadingLabel}</div>}
          {children}
        </div>
      </div>
    </div>
  );
}
