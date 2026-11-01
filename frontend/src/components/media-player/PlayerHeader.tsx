import { Download, Copy, Check, Music, Video, X, Minimize2 } from 'lucide-react';
import { formatBytes } from '../../utils/formatters.ts';
import type { PanelModel } from './useMediaPlayerModel.tsx';

export function PlayerHeader({ vm }: { vm: PanelModel }) {
  const { canMinimize, copied, copyStreamUrl, downloadProviderFile, file, hasCopyableUrl, hasDownload, isFullscreen, isVideo, onClose, onToggleMinimize, source } = vm;
  const providerName = source?.provider || 'Direct Browser Streaming';
  return (
    <>
        <div className={`${isFullscreen ? 'hidden' : 'flex'} items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900/90 z-10`}>
          <div className="flex items-center gap-3 overflow-hidden">
            <div className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400">
              {isVideo ? <Video className="w-5 h-5" /> : <Music className="w-5 h-5" />}
            </div>
            <div className="truncate">
              <h3 className="text-sm md:text-base font-semibold text-slate-100 truncate">{file.name}</h3>
              <p className="text-xs text-slate-400 flex items-center gap-2">
                <span>{file.size > 0 ? formatBytes(file.size) : 'Size unavailable'}</span>
                <span>•</span>
                <span className="text-emerald-400 font-medium">{providerName}</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {hasCopyableUrl && (
              <button
                onClick={copyStreamUrl}
                className="flex items-center gap-1.5 rounded-lg bg-slate-800 px-2.5 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-slate-700"
                title="Copy Direct Streaming Link"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                <span className="hidden sm:inline">{copied ? 'Copied' : 'Stream URL'}</span>
              </button>
            )}

            {hasDownload && (source?.download ? (
              <button
                type="button"
                onClick={() => void downloadProviderFile()}
                className="flex items-center gap-1.5 rounded-lg bg-slate-800 px-2.5 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-slate-700"
                title={`Download with ${source.provider}`}
              >
                <Download className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Download</span>
              </button>
            ) : (
              <a
                href={source?.downloadUrl || file.downloadUrl}
                download={file.name}
                className="flex items-center gap-1.5 rounded-lg bg-slate-800 px-2.5 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-slate-700"
                title="Direct Download File"
              >
                <Download className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Download</span>
              </a>
            ))}

            {canMinimize && <button
              onClick={onToggleMinimize}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition"
              title="Minimize to Floating Player"
            >
              <Minimize2 className="w-4 h-4" />
            </button>}

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition"
              title="Close Player"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>
    </>
  );
}
