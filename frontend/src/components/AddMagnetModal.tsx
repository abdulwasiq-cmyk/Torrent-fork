import React from 'react';
import { X, FileCheck, AlertCircle, Loader2 } from 'lucide-react';

import type { AddMagnetModalProps } from './add-magnet/types.ts';
import { useAddMagnetModel } from './add-magnet/useAddMagnetModel.tsx';
import { AddMagnetFooter } from './add-magnet/AddMagnetFooter.tsx';
import { AddMagnetHeader } from './add-magnet/AddMagnetHeader.tsx';
import { AddMagnetError } from './add-magnet/AddMagnetError.tsx';
import { InspectedFilesSection } from './add-magnet/InspectedFilesSection.tsx';
export const AddMagnetModal: React.FC<AddMagnetModalProps> = (props) => {
  const vm = useAddMagnetModel({
    ...props,
    defaultFolder: props.defaultFolder ?? 'Downloads',
    initialMagnet: props.initialMagnet ?? '',
    initialSourceUrl: props.initialSourceUrl ?? '',
    initialDescriptorUrl: props.initialDescriptorUrl ?? '',
  });
  const { isOpen, onClose, onOpen, defaultFolder, inspectedFiles, isInspecting, error, backgroundMode, setBackgroundMode, handleSubmit } = vm;






















  if (!isOpen && !backgroundMode) return null;

  if (backgroundMode) {
    const ready = !isInspecting && inspectedFiles.length > 0;
    const failed = !isInspecting && Boolean(error);

    return (
      <div className="fixed right-3 bottom-[5.75rem] md:bottom-6 z-50 w-[min(92vw,24rem)]">
        <div className="rounded-2xl bg-slate-900/95 backdrop-blur-xl border border-slate-700 shadow-2xl p-3.5">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-xl bg-cyan-500/10 border border-cyan-500/20 shrink-0">
              {isInspecting ? (
                <Loader2 className="w-5 h-5 text-cyan-400 animate-spin" />
              ) : ready ? (
                <FileCheck className="w-5 h-5 text-emerald-400" />
              ) : (
                <AlertCircle className="w-5 h-5 text-rose-400" />
              )}
            </div>

            <div className="min-w-0 flex-1">
              <p className="text-xs font-bold text-slate-100 truncate">
                {isInspecting ? 'Resolving torrent in background' : ready ? 'Torrent metadata ready' : 'Torrent loading failed'}
              </p>
              <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">
                {isInspecting
                  ? 'You can keep using Torrent Studio. The torrent remains safely paused while qBittorrent resolves its metadata.'
                  : ready
                  ? `${inspectedFiles.length} file${inspectedFiles.length === 1 ? '' : 's'} found. Open the selector when you're ready.`
                  : error}
              </p>
            </div>

            <button
              type="button"
              onClick={() => {
                setBackgroundMode(false);
                onOpen();
              }}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition shrink-0"
              title="Open torrent selector"
              aria-label="Open torrent selector"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {isInspecting ? (
            <div className="mt-3 h-1.5 rounded-full bg-slate-800 overflow-hidden">
              <div className="h-full w-1/3 bg-cyan-500 rounded-full animate-pulse" />
            </div>
          ) : (
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  setBackgroundMode(false);
                  onOpen();
                }}
                className="flex-1 px-3 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-bold transition"
              >
                {ready ? 'Open File Selection' : 'Open & Retry'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setBackgroundMode(false);
                  onClose();
                }}
                className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition"
              >
                Dismiss
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 md:p-6 bg-black/80 backdrop-blur-sm animate-fadeIn">
      <div 
        className="relative w-full max-w-3xl bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[96vh] sm:max-h-[94vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <AddMagnetHeader vm={vm} />

        {/* Modal Body */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-3 sm:p-5 space-y-3 sm:space-y-4">
          <AddMagnetError vm={vm} />
          <InspectedFilesSection vm={vm} />

        </form>

        {/* Modal Footer */}
        <AddMagnetFooter vm={vm} />
      </div>
    </div>
  );
};

