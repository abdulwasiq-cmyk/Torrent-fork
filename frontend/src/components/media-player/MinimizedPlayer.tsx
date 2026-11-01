import { Play, Pause, Volume2, VolumeX, RotateCcw, RotateCw, Music, Video, X, Maximize2 } from 'lucide-react';
import { API_BASE } from '../../api/client.ts';
import { formatDuration } from '../../utils/formatters.ts';
import type { PanelModel } from './useMediaPlayerModel.tsx';

export function MinimizedPlayer({ vm }: { vm: PanelModel }) {
  const { alternateAudioRef, audioRef, currentTime, duration, file, handleSeek, isMuted, isPlaying, isVideo, onClose, onLoadedMetadata, onSeeked, onSeeking, onTimeUpdate, onToggleMinimize, setIsPlaying, setIsSeeking, setTrackNotice, skip, source, toggleMute, togglePlay, videoRef } = vm;
  return (
    <>
      <div className="fixed bottom-16 md:bottom-6 right-4 z-50 w-80 md:w-96 bg-slate-900/95 backdrop-blur-xl border border-slate-700 shadow-2xl rounded-2xl p-3.5 flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 overflow-hidden">
            <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400">
              {isVideo ? <Video className="w-4 h-4" /> : <Music className="w-4 h-4" />}
            </div>
            <div className="truncate">
              <p className="text-xs font-semibold text-slate-200 truncate">{file.name}</p>
              <p className="text-[10px] text-slate-400">{formatDuration(currentTime)} / {formatDuration(duration || file.duration || 0)}</p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={onToggleMinimize}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200"
              title="Expand"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200"
              title="Close Player"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Hidden or small video preview */}
        {isVideo ? (
          <video
            ref={videoRef}
            crossOrigin={file.streamUrl?.startsWith(API_BASE) ? 'anonymous' : undefined}
            src={source?.kind === 'webtorrent' ? undefined : file.streamUrl || file.externalStreamUrl || file.downloadUrl}
            className="w-full h-32 object-contain bg-black rounded-lg"
            onTimeUpdate={onTimeUpdate}
            onSeeking={onSeeking}
            onSeeked={onSeeked}
            onPlaying={() => {
              setIsSeeking(false);
              setTrackNotice('');
              setIsPlaying(true);
            }}
            onLoadedMetadata={onLoadedMetadata}
            onEnded={() => setIsPlaying(false)}
          />
        ) : (
          <audio
            ref={audioRef}
            autoPlay
            src={file.streamUrl || file.externalStreamUrl || file.downloadUrl}
            onTimeUpdate={onTimeUpdate}
            onLoadedMetadata={onLoadedMetadata}
            onEnded={() => setIsPlaying(false)}
          />
        )}

        <audio ref={alternateAudioRef} preload="auto" className="hidden" aria-hidden="true" />

        {/* Mini Controls */}
        <div className="flex items-center justify-between pt-1">
          <button
            onClick={() => skip(-10)}
            className="p-1.5 rounded text-slate-400 hover:text-slate-200"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={togglePlay}
            className="p-2 rounded-full bg-cyan-500 text-slate-950 font-bold hover:bg-cyan-400 transition"
          >
            {isPlaying ? <Pause className="w-4 h-4 fill-current" /> : <Play className="w-4 h-4 fill-current" />}
          </button>
          <button
            onClick={() => skip(10)}
            className="p-1.5 rounded text-slate-400 hover:text-slate-200"
          >
            <RotateCw className="w-3.5 h-3.5" />
          </button>
          <div className="flex items-center gap-1.5 ml-2">
            <button onClick={toggleMute} className="text-slate-400 hover:text-slate-200">
              {isMuted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>

        {/* Scrubber */}
        <input
          type="range"
          min={0}
          max={duration || file.duration || 100}
          value={currentTime}
          onChange={handleSeek}
          className="w-full h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-cyan-400"
        />
      </div>
    </>
  );
}
