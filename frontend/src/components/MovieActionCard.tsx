import React, { useEffect, useState } from 'react';
import { Check, Copy, Download, Loader2, Play, X } from 'lucide-react';
import { api } from '../api/client.ts';
import type { NuvioStreamOption, TorrentSearchResult } from '../api/types.ts';
import { formatBytes } from '../utils/formatters.ts';
import { torrentQualityDetails, torrentResultKey } from './torrent-search/grouping.ts';
import { copyMagnetAndOpenWebtor } from './torrent-search/webtor.ts';

export interface MovieActionChip {
  key: string;
  label: string;
  title?: string;
}

export interface MovieActionCardProps {
  title: string;
  titleHref: string;
  year?: number | string | null;
  /** TMDB id: the Webtor (over-the-limit torrents) and Download HD lookups use it. */
  tmdbId?: number | string | null;
  onClose: () => void;
  /** The existing Vidrift / NexStream playback. Omitted when this title cannot be played. */
  play?: { disabled: boolean; resolving: boolean; onClick: () => void };
  /** Seedr: torrents up to the size limit (TORRENT_MAX_SIZE_GB). Omitted when the title has none. */
  prepare?: { chips: MovieActionChip[]; selectedKey: string; onSelect: (key: string) => void; isPreparing: boolean; disabled: boolean; onClick: () => void };
  /** Set once the selected torrent has been prepared in Seedr (replaces the Prepare button). */
  prepared?: null | { isPlaying: boolean; isCopied: boolean; onPlay: () => void; onDownload: () => void; onCopy: () => void };
}

const chipClass = (active: boolean) =>
  'min-w-0 rounded-md border px-1.5 py-1 text-[10px] font-semibold leading-tight transition-colors ' +
  (active ? 'border-cyan-400 bg-cyan-500/20 text-cyan-100' : 'border-slate-700 bg-slate-950 text-slate-300 hover:border-cyan-500/60');

const Chips: React.FC<{ chips: MovieActionChip[]; selectedKey: string; onSelect: (key: string) => void; label: string }> = ({ chips, selectedKey, onSelect, label }) => (
  <div className="mt-1.5 flex flex-wrap gap-1" role="group" aria-label={label}>
    {chips.map(chip => (
      <button key={chip.key} type="button" aria-pressed={chip.key === selectedKey} title={chip.title} onClick={() => onSelect(chip.key)} className={chipClass(chip.key === selectedKey)}>
        {chip.label}
      </button>
    ))}
  </div>
);

/** Quality chip text for a torrent: "1080p · 3.4 GB". */
export const torrentChip = (row: TorrentSearchResult): MovieActionChip => ({
  key: torrentResultKey(row),
  label: `${torrentQualityDetails(row).label || 'Unknown'} · ${formatBytes(Number(row.size) || 0)}`,
  title: `${row.title} · ▲${Number(row.seeders) || 0}${row.indexer ? ` · ${row.indexer}` : ''}`,
});

/**
 * The second card of a movie: only action buttons, no poster.
 *   Play      the existing Vidrift / NexStream playback
 *   Prepare   Seedr, torrents up to the size limit (quality chips)
 *   Webtor    torrents above the size limit: copies the magnet and opens Webtor (quality chips)
 *   Download HD  direct file links from the Nuvio Streams add-on (quality chips)
 * A button is rendered only when its source has something; the Webtor and Download HD lookups start when this
 * card opens (never on page load) and their buttons appear when they return.
 * "Play HD" is intentionally absent: the add-on's files are HEVC MKV, which browsers cannot play.
 */
export const MovieActionCard: React.FC<MovieActionCardProps> = ({ title, titleHref, year, tmdbId, onClose, play, prepare, prepared }) => {
  const [large, setLarge] = useState<TorrentSearchResult[]>([]);
  const [largeKey, setLargeKey] = useState('');
  const [hint, setHint] = useState('');
  const [hd, setHd] = useState<NuvioStreamOption[]>([]);
  const [hdKey, setHdKey] = useState('');
  const [hdLoading, setHdLoading] = useState(false);
  const [largeLoading, setLargeLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLarge([]); setLargeKey(''); setHd([]); setHdKey(''); setHint('');
    setLargeLoading(true);
    void api.getTorrentOptions({ tmdbId, title, year }, controller.signal, 'all', 'movie', true)
      .then(rows => { if (!controller.signal.aborted) { setLarge(rows); setLargeKey(rows[0] ? torrentResultKey(rows[0]) : ''); } })
      .catch(() => {})
      .finally(() => { if (!controller.signal.aborted) setLargeLoading(false); });
    const id = Number(tmdbId);
    if (Number.isInteger(id) && id > 0) {
      setHdLoading(true);
      void api.getNuvioStreams(id, controller.signal)
        .then(options => { if (!controller.signal.aborted) { setHd(options); setHdKey(options[0]?.key || ''); } })
        .catch(() => {})
        .finally(() => { if (!controller.signal.aborted) setHdLoading(false); });
    }
    return () => controller.abort();
  }, [tmdbId, title, year]);

  const selectedLarge = large.find(row => torrentResultKey(row) === largeKey) || large[0];
  const selectedHd = hd.find(option => option.key === hdKey) || hd[0];
  const nothing = !play && !prepare && !prepared && large.length === 0 && hd.length === 0;
  const checking = hdLoading || largeLoading;

  return (
    <div className="relative min-w-0 self-start rounded-xl border border-slate-800 bg-slate-900 p-2.5 sm:p-3 lg:rounded-[14px]">
      <div className="flex items-start gap-1.5">
        <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-1.5">
          <a href={titleHref} target="_blank" rel="noreferrer" title="Open on IMDb"
            className="min-w-0 text-left text-xs font-semibold leading-4 text-slate-100 hover:text-cyan-300 sm:text-sm">
            {title}
          </a>
          {year ? <span className="shrink-0 text-[10px] text-slate-500 sm:text-xs">{year}</span> : null}
        </div>
        <button type="button" onClick={onClose} title="Back to the movie cards" aria-label="Back to the movie cards"
          className="shrink-0 rounded-md p-1 text-slate-500 hover:bg-slate-800 hover:text-slate-100">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="mt-2.5 space-y-2.5">
        {play && (
          <button type="button" disabled={play.disabled} onClick={play.onClick}
            className="flex w-full items-center justify-center gap-1 whitespace-nowrap rounded-lg border border-violet-400/40 bg-violet-500/15 px-2 py-2 text-xs font-bold text-violet-200 hover:bg-violet-500/25 disabled:opacity-60">
            {play.resolving ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Resolving…</> : <><Play className="h-3.5 w-3.5 fill-current" />Play</>}
          </button>
        )}

        {prepared ? (
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Prepared in Seedr</div>
            <div className="flex flex-wrap items-center gap-1.5">
              <button type="button" disabled={prepared.isPlaying} onClick={prepared.onPlay} title={prepared.isPlaying ? 'Opening stream…' : 'Play from Seedr'}
                className="flex items-center gap-1 whitespace-nowrap rounded-lg bg-emerald-400 px-2.5 py-1.5 text-xs font-bold text-slate-950 hover:bg-emerald-300 disabled:cursor-wait disabled:opacity-70">
                {prepared.isPlaying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}Play
              </button>
              <button type="button" onClick={prepared.onDownload} title="Download file" aria-label="Download file"
                className="rounded-lg bg-slate-800 p-2 text-slate-300 hover:bg-slate-700 hover:text-white"><Download className="h-3.5 w-3.5" /></button>
              <button type="button" disabled={prepared.isCopied} onClick={prepared.onCopy} title="Copy download link" aria-label="Copy download link"
                className="rounded-lg bg-slate-800 p-2 text-slate-300 hover:bg-slate-700 hover:text-cyan-400 disabled:opacity-60">
                {prepared.isCopied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>
        ) : prepare && (
          <div>
            <button type="button" disabled={prepare.disabled} onClick={prepare.onClick}
              className="w-full whitespace-nowrap rounded-lg bg-cyan-500 px-2 py-2 text-xs font-bold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60">
              {prepare.isPreparing ? 'Preparing…' : 'Prepare'}
            </button>
            {prepare.chips.length > 0 && <Chips chips={prepare.chips} selectedKey={prepare.selectedKey} onSelect={prepare.onSelect} label={`Quality for ${title}`} />}
          </div>
        )}

        {selectedLarge && (
          <div>
            <button type="button" title="Copy the magnet link and open Webtor"
              onClick={() => {
                const copied = copyMagnetAndOpenWebtor(String(selectedLarge.magnetUrl || ''));
                setHint(copied ? 'Magnet copied. Paste it on Webtor to stream or download.' : 'Webtor opened, but the magnet could not be copied. Pick another quality and try again.');
              }}
              className="flex w-full items-center justify-center gap-1 whitespace-nowrap rounded-lg border border-cyan-400/40 bg-cyan-500/15 px-2 py-2 text-xs font-bold text-cyan-200 hover:bg-cyan-500/25">
              <Download className="h-3.5 w-3.5" />Webtor
            </button>
            <Chips chips={large.map(torrentChip)} selectedKey={largeKey} onSelect={key => { setLargeKey(key); setHint(''); }} label={`Webtor quality for ${title}`} />
            {hint ? <div className="mt-1.5 text-[10px] leading-snug text-slate-400" role="status">{hint}</div> : null}
          </div>
        )}

        {selectedHd && (
          <div>
            <a href={selectedHd.url} target="_blank" rel="noreferrer noopener" download={selectedHd.filename || undefined} title={selectedHd.filename}
              className="flex w-full items-center justify-center gap-1 whitespace-nowrap rounded-lg border border-emerald-400/40 bg-emerald-500/15 px-2 py-2 text-xs font-bold text-emerald-200 hover:bg-emerald-500/25">
              <Download className="h-3.5 w-3.5" />Download HD
            </a>
            <Chips chips={hd.map(option => ({ key: option.key, label: option.label, title: option.filename }))} selectedKey={hdKey} onSelect={setHdKey} label={`Download HD quality for ${title}`} />
          </div>
        )}

        {checking && !nothing && <div className="text-[10px] text-slate-500" role="status">Checking more downloads…</div>}
        {nothing && (
          <div className="text-xs text-slate-400" role="status">{checking ? 'Checking available downloads…' : 'Nothing available yet'}</div>
        )}
      </div>
    </div>
  );
};
