import { AlertTriangle } from 'lucide-react';
import { formatBytes } from '../../utils/formatters.ts';
import { TorrentSearchPanel } from '../../components/TorrentSearchPanel.tsx';
import type { StorageFile } from '../../types/index.ts';
import type { TorrentPlaybackResult } from '../../components/media-player/types.ts';
import type { PanelModel } from '../useAppModel.tsx';

export function TorrentSearchTab({ vm }: { vm: PanelModel }) {
  const { activeTab, activeUser, handleAddMagnet, handleCancelSeedrDownload, handleSearchPrepare, handleStreamSeedrFile, seedrAllPrefetchedFiles, seedrDeletedFolderIds, seedrInsufficientSpacePrompt, setActiveMediaFile, setActiveMediaSource, setActiveTab, setIsPlayerMinimized, setSeedrInsufficientSpacePrompt } = vm;
  const openTorrentPlayback = ({ provider, fileName, fileSize, source }: TorrentPlaybackResult) => {
    const streamUrl = source.streamUrl || '';
    const syntheticFile: StorageFile = {
      id: `${provider.toLowerCase()}-${Date.now()}`,
      name: fileName,
      path: fileName,
      folder: `/${provider}`,
      size: fileSize || 0,
      type: 'video',
      mimeType: 'video/mp4',
      createdAt: Date.now(),
      ownerId: activeUser?.id || 'user_admin',
      ownerName: activeUser?.name || 'Admin',
      isStreamable: true,
      downloadUrl: source.downloadUrl || streamUrl,
      streamUrl,
    };
    setActiveMediaFile(syntheticFile);
    setActiveMediaSource(source);
    setIsPlayerMinimized(false);
  };
  return (
    <>
        <div className={activeTab === 'search' ? 'block' : 'hidden'}>
          <TorrentSearchPanel
            onPrepare={handleSearchPrepare}
            onCancelPrepare={handleCancelSeedrDownload}
            onOpenProgress={() => {
              setActiveTab('files');
            }}
            seedrFiles={seedrAllPrefetchedFiles}
            seedrDeletedFolderIds={seedrDeletedFolderIds}
            onPlaySeedrFile={handleStreamSeedrFile}
            onOpenTorrentPlayback={openTorrentPlayback}
          />

          {seedrInsufficientSpacePrompt && (
            <div className="fixed inset-x-3 top-20 z-[100] flex justify-center pointer-events-none">
              <div className="w-full max-w-md rounded-2xl border border-rose-400/40 bg-slate-950/95 backdrop-blur-xl shadow-[0_0_30px_rgba(244,63,94,0.22)] p-4 pointer-events-auto">
                <div className="flex items-start gap-3">
                  <div className="shrink-0 rounded-xl bg-rose-500/10 border border-rose-500/20 p-2">
                    <AlertTriangle className="w-5 h-5 text-rose-400" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="font-bold text-rose-300 text-sm">Seedr storage is full</div>
                    <div className="mt-1 text-xs leading-5 text-slate-300">
                      This torrent needs <span className="font-semibold text-slate-100">{formatBytes(seedrInsufficientSpacePrompt.requiredBytes)}</span>,
                      but only <span className="font-semibold text-rose-300">{formatBytes(seedrInsufficientSpacePrompt.remainingBytes)}</span> is available.
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          const prompt = seedrInsufficientSpacePrompt;
                          setSeedrInsufficientSpacePrompt(null);
                          void handleAddMagnet(
                            prompt.magnet,
                            prompt.category,
                            prompt.selectedFiles,
                            prompt.manifest,
                            prompt.existingHash,
                            'qbittorrent'
                          );
                        }}
                        className="flex-1 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 px-3 py-2 text-xs font-bold transition"
                      >
                        Use qBittorrent
                      </button>
                      <button
                        type="button"
                        onClick={() => setSeedrInsufficientSpacePrompt(null)}
                        className="rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 px-3 py-2 text-xs font-semibold transition"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
    </>
  );
}
