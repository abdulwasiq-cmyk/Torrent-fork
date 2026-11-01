import React from 'react';
import type { MediaPlayerModalProps } from './media-player/types.ts';
import { useMediaPlayerModel } from './media-player/useMediaPlayerModel.tsx';
import { PlayerControlsBar } from './media-player/PlayerControlsBar.tsx';
import { MediaViewport } from './media-player/MediaViewport.tsx';
import { PlayerHeader } from './media-player/PlayerHeader.tsx';
import { MinimizedPlayer } from './media-player/MinimizedPlayer.tsx';

export const MediaPlayerModal: React.FC<MediaPlayerModalProps> = (props) => {
  const vm = useMediaPlayerModel(props);
  if (!vm) return null;
  const { isMinimized, isFullscreen, containerRef, source } = vm;












































  // Minimized floating player (for multitasking while downloading or browsing folders)
  if (isMinimized) {
    return (
      <MinimizedPlayer vm={vm} />
    );
  }

  // Full Player Modal
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 md:p-6 bg-black/80 backdrop-blur-md">
      <div
        ref={containerRef}
        className={`relative bg-slate-900 overflow-hidden flex flex-col ${
          isFullscreen
            ? 'w-screen h-screen max-w-none max-h-none rounded-none border-0'
            : 'w-full max-w-4xl border border-slate-700/80 rounded-2xl shadow-2xl max-h-[95vh]'
        }`}
      >
        {/* Top Header */}
        <PlayerHeader vm={vm} />

        {/* Media Viewport */}
        <MediaViewport vm={vm} />

        {/* Player Controls Bar */}
        {source?.kind !== 'webtor' && <PlayerControlsBar vm={vm} />}
      </div>

    </div>
  );
};
