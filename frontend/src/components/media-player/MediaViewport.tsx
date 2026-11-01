import { Music } from 'lucide-react';
import { API_BASE } from '../../api/client.ts';
import type { PanelModel } from './useMediaPlayerModel.tsx';
import { WebtorEmbed } from './WebtorEmbed.tsx';

export function MediaViewport({ vm }: { vm: PanelModel }) {
  const { alternateAudioRef, audioRef, file, handleMediaError, isFullscreen, isPlaying, isVideo, mediaError, onLoadedMetadata, onSeeked, onSeeking, onTimeUpdate, providerStatus, selectedSubtitleIndex, setFullscreenControlsVisible, setIsPlaying, setIsSeeking, setTrackNotice, source, subtitleCueOriginalsRef, subtitleOffset, subtitleTrackRef, subtitleTracks, trackNotice, videoRef } = vm;
  return (
    <>
        <div
          className={`relative flex-1 min-h-0 bg-black flex items-center justify-center overflow-hidden ${
            isFullscreen ? 'h-full min-h-0' : 'min-h-[260px] md:min-h-[420px]'
          }`}
          onClick={() => {
            if (isFullscreen) {
              setFullscreenControlsVisible(prev => !prev);
            }
          }}
        >
          {mediaError && (
            <div className="absolute inset-0 z-10 flex items-center justify-center p-6 text-center">
              <div className="max-w-md rounded-xl bg-slate-900/95 border border-rose-500/30 p-5">
                <p className="text-sm font-semibold text-rose-300">{mediaError}</p>
                <p className="text-xs text-slate-400 mt-2">
                  {source?.provider ? `${source.provider} could not open this media source.` : 'The Seedr stream could not be played. We tried the direct Seedr presentation URL and the server proxy.'}
                </p>
              </div>
            </div>
          )}

          {/* Stage 2: the stream URL is ready and the player is now opening it.
              Keep this lightweight overlay visible until browser media
              metadata arrives so the player never looks frozen/empty. */}
          {!mediaError && trackNotice && (
            <div className="absolute inset-0 z-10 flex items-center justify-center p-6 text-center pointer-events-none">
              <div className="rounded-xl bg-slate-900/90 border border-cyan-500/20 px-5 py-4 shadow-xl">
                <div className="flex items-center justify-center gap-2 text-cyan-300">
                  <span className="inline-flex w-5 h-5 rounded-full border-2 border-cyan-300/30 border-t-cyan-300 animate-spin" />
                  <span className="text-sm font-semibold">{trackNotice}</span>
                </div>
                <p className="text-[11px] text-slate-400 mt-1.5">
                  Connecting to the browser stream…
                </p>
              </div>
            </div>
          )}

          {source?.provider === 'WebTorrent' && providerStatus && (
            <div role="status" className="absolute bottom-3 left-3 right-3 z-20 rounded-lg bg-slate-950/85 px-3 py-2 text-center text-[11px] text-slate-300">
              {providerStatus}
            </div>
          )}

          {source?.kind === 'webtor' ? (
            <WebtorEmbed magnet={source.magnet || ''} />
          ) : isVideo ? (
            <video
              ref={videoRef}
              crossOrigin={file.streamUrl?.startsWith(API_BASE) ? 'anonymous' : undefined}
              autoPlay
              className={`object-contain cursor-pointer ${
                isFullscreen
                  ? 'w-full h-full max-w-full max-h-full'
                  : 'w-auto h-auto max-w-full max-h-[60vh]'
              }`}
              onClick={(event) => {
                event.stopPropagation();
                if (isFullscreen) {
                  setFullscreenControlsVisible(prev => !prev);
                }
              }}
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
              onError={handleMediaError}>
              {selectedSubtitleIndex !== undefined && (
                <track
                  ref={subtitleTrackRef}
                  key={selectedSubtitleIndex}
                  kind="subtitles"
                  src={subtitleTracks.find(track => track.index === selectedSubtitleIndex)?.url}
                  srcLang={subtitleTracks.find(track => track.index === selectedSubtitleIndex)?.language || 'en'}
                  label={subtitleTracks.find(track => track.index === selectedSubtitleIndex)?.title || subtitleTracks.find(track => track.index === selectedSubtitleIndex)?.language?.toUpperCase() || 'Subtitles'}
                  default
                  onLoad={() => {
                    // Force activation again after the browser finishes
                    // loading the WebVTT resource.
                    const media = videoRef.current;
                    const selectedTextTrack = subtitleTrackRef.current?.track;
                    if (!media || !selectedTextTrack) return;
                    Array.from(media.textTracks || []).forEach(track => {
                      track.mode = track === selectedTextTrack ? 'showing' : 'disabled';
                    });
                    const cues = Array.from(selectedTextTrack.cues || []) as any[];
                    const url = subtitleTracks.find(track => track.index === selectedSubtitleIndex)?.url;
                    if (url && cues.length) {
                      subtitleCueOriginalsRef.current.set(url, cues.map(cue => ({
                        cue,
                        start: Number(cue.startTime),
                        end: Number(cue.endTime),
                      })));
                    }
                    window.setTimeout(() => {
                      const currentUrl = subtitleTracks.find(track => track.index === selectedSubtitleIndex)?.url;
                      const originals = currentUrl ? subtitleCueOriginalsRef.current.get(currentUrl) : undefined;
                      if (!originals) return;
                      originals.forEach(({ cue, start, end }) => {
                        cue.startTime = Math.max(0, start + subtitleOffset);
                        cue.endTime = Math.max(cue.startTime, end + subtitleOffset);
                      });
                    }, 0);
                  }}
                  onError={() => {
                    console.error('[MEDIA] Subtitle track failed to load:', {
                      url: subtitleTracks.find(track => track.index === selectedSubtitleIndex)?.url,
                      track: selectedSubtitleIndex,
                    });
                    setTrackNotice('Subtitle could not be loaded');
                  }}
                />
              )}
            </video>
          ) : (
            <div className="flex flex-col items-center justify-center p-8 text-center gap-4">
              <div className="w-24 h-24 rounded-full bg-gradient-to-tr from-cyan-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-500/20 animate-pulse-subtle">
                <Music className="w-12 h-12 text-white" />
              </div>
              <div>
                <h4 className="text-lg font-bold text-slate-100">{file.name}</h4>
                <p className="text-sm text-slate-400 mt-1">Lossless Cloud Audio Playback</p>
              </div>

              {/* Dynamic waveform simulation */}
              <div className="flex items-center gap-1 h-12 mt-2">
                {[40, 65, 30, 85, 95, 45, 75, 55, 90, 60, 35, 70, 80, 50, 65, 85, 40, 70].map((h, i) => (
                  <div
                    key={i}
                    className="w-1.5 bg-gradient-to-t from-cyan-500 to-indigo-400 rounded-full transition-all duration-300"
                    style={{
                      height: isPlaying ? `${Math.max(12, (h * (0.4 + (i % 3) * 0.3)))}px` : '8px',
                      opacity: isPlaying ? 1 : 0.4
                    }}
                  />
                ))}
              </div>

              <audio
                ref={audioRef}
                src={file.streamUrl}
                onTimeUpdate={onTimeUpdate}
                onLoadedMetadata={onLoadedMetadata}
                onEnded={() => setIsPlaying(false)}
              />
            </div>
          )}
          <audio ref={alternateAudioRef} preload="auto" className="hidden" aria-hidden="true" />
        </div>
    </>
  );
}
