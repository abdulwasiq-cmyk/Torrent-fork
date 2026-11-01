import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Loader2 } from 'lucide-react';

export type TorrentEngine = 'webtor' | 'webtorrent' | 'torrserver';

export const TORRENT_ENGINE_OPTIONS: Array<{ key: TorrentEngine; label: string }> = [
  { key: 'webtor', label: 'Webtor' },
  { key: 'webtorrent', label: 'WebTorrent' },
  { key: 'torrserver', label: 'TorrServer' },
];

export function selectTorrentEngine(
  engine: TorrentEngine,
  close: () => void,
  onSelect: (engine: TorrentEngine) => void,
) {
  close();
  onSelect(engine);
}

export function invokeTorrentEngine<T>(
  engine: TorrentEngine,
  handlers: Record<TorrentEngine, () => T | Promise<T>>,
): T | Promise<T> {
  return handlers[engine]();
}

export function defaultMovieCardPlayHandler(
  prepared: { onPlay: () => void } | null,
  directStream: { onClick: () => void } | undefined,
) {
  return prepared ? prepared.onPlay : directStream?.onClick;
}

export interface TorrentEngineMenuProps {
  disabled?: boolean;
  activeEngine?: TorrentEngine | null;
  status?: string;
  error?: string;
  onSelect: (engine: TorrentEngine) => void;
}

export function TorrentEngineMenu({ disabled, activeEngine, status, error, onSelect }: TorrentEngineMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  const activeLabel = TORRENT_ENGINE_OPTIONS.find(option => option.key === activeEngine)?.label;
  return (
    <div ref={rootRef} className="relative min-w-0 flex-1">
      <button
        type="button"
        disabled={disabled || Boolean(activeEngine)}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(value => !value)}
        className="flex w-full min-w-0 items-center justify-center gap-1 rounded-lg border border-sky-400/40 bg-sky-500/15 px-2 py-2 text-xs font-bold text-sky-100 hover:bg-sky-500/25 disabled:cursor-wait disabled:opacity-70"
      >
        {activeEngine ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" /> : <ChevronDown className="h-3.5 w-3.5 shrink-0" />}
        <span className="truncate">{activeLabel ? `${activeLabel}…` : 'Torrent'}</span>
      </button>
      {open && (
        <div role="menu" aria-label="Torrent engine" className="absolute right-0 top-full z-30 mt-1 min-w-36 overflow-hidden rounded-lg border border-slate-700 bg-slate-950 p-1 shadow-xl">
          {TORRENT_ENGINE_OPTIONS.map(option => (
            <button
              key={option.key}
              type="button"
              role="menuitem"
              onClick={() => selectTorrentEngine(option.key, () => setOpen(false), onSelect)}
              className="block w-full rounded-md px-3 py-2 text-left text-xs font-semibold text-slate-200 hover:bg-slate-800"
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
      {status && <p role="status" className="mt-1 truncate text-[10px] text-slate-400">{status}</p>}
      {error && <p role="alert" className="mt-1 text-[10px] text-rose-300">{error}</p>}
    </div>
  );
}
