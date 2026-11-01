import React, { useState, useRef, useEffect } from 'react';
import Hls from 'hls.js';
import { api, API_BASE } from '../../api/client.ts';
import type { MediaPlayerModalProps } from './types.ts';

export function useMediaPlayerModel(props: MediaPlayerModalProps) {
  const { file, source, onClose, onPlaybackStarted, isMinimized, onToggleMinimize } = props;
  const [isPlaying, setIsPlaying] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [fullscreenControlsVisible, setFullscreenControlsVisible] = useState(false);
  const [copied, setCopied] = useState(false);
  const [mediaError, setMediaError] = useState('');
  const [providerStatus, setProviderStatus] = useState('');
  const [isSeeking, setIsSeeking] = useState(false);
  const [audioTracks, setAudioTracks] = useState<Array<{
    index: number; language: string; title: string; codec: string; channels: number; default: boolean;
  }>>([]);
  const [subtitleTracks, setSubtitleTracks] = useState<Array<{
    index: number; language: string; title: string; codec: string; url: string;
  }>>([]);
  const [hlsSubtitleTracks, setHlsSubtitleTracks] = useState<Array<{
    index: number; language: string; title: string; codec: string;
  }>>([]);
  const [selectedAudioIndex, setSelectedAudioIndex] = useState<number | undefined>(undefined);
  const [selectedSubtitleIndex, setSelectedSubtitleIndex] = useState<number | undefined>(undefined);
  const [selectedHlsSubtitleIndex, setSelectedHlsSubtitleIndex] = useState<number | undefined>(undefined);
  const [trackNotice, setTrackNotice] = useState('');
  const [subtitleSearchError, setSubtitleSearchError] = useState('');
  const [tracksLoading, setTracksLoading] = useState(false);
  const [subtitleSyncOpen, setSubtitleSyncOpen] = useState(false);
  const [subtitleOffset, setSubtitleOffset] = useState(0);
  const subtitleCueOriginalsRef = useRef<Map<string, Array<{ cue: any; start: number; end: number }>>>(new Map());
  const resumeTimeRef = useRef(0);
  const resumePlayingRef = useRef(false);
  const subtitleTrackRef = useRef<HTMLTrackElement>(null);
  const [usingDirectFallback, setUsingDirectFallback] = useState(false);
  const hlsActiveRef = useRef(false);
  const hlsRef = useRef<Hls | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const alternateAudioRef = useRef<HTMLAudioElement>(null);
  const alternateAudioIndexRef = useRef<number | undefined>(undefined);
  const primaryAudioIndexRef = useRef<number | undefined>(undefined);
  const alternateAudioRequestRef = useRef(0);
  const automaticAudioFallbackRef = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const isVideo = file?.type === 'video';
  const mediaRef = isVideo ? videoRef : audioRef;
  useEffect(() => {
    if (!source?.dispose) return;
    return () => source.dispose?.();
  }, [source]);
  useEffect(() => {
    if (!source?.subscribeStatus) {
      setProviderStatus('');
      return;
    }
    return source.subscribeStatus(setProviderStatus);
  }, [source]);
  useEffect(() => {
    setCurrentTime(0);
    setDuration(0);
    setIsPlaying(true);
    setMediaError('');
    setIsSeeking(false);
    setUsingDirectFallback(false);
    hlsActiveRef.current = false;
    const initialSubtitles = file?.subtitleTracks || [];
    setSubtitleTracks(initialSubtitles);
    setHlsSubtitleTracks([]);
    setSelectedSubtitleIndex(undefined);
    setSelectedHlsSubtitleIndex(undefined);
    setSubtitleSyncOpen(false);
    setSubtitleOffset(0);
    subtitleCueOriginalsRef.current.clear();
    alternateAudioIndexRef.current = undefined;
    primaryAudioIndexRef.current = undefined;
    alternateAudioRequestRef.current += 1;
    automaticAudioFallbackRef.current = false;
    const alternateAudio = alternateAudioRef.current;
    if (alternateAudio) {
      alternateAudio.pause();
      alternateAudio.removeAttribute('src');
      alternateAudio.load();
    }
    const initialAudioTracks = file?.audioTracks || [];
    const initialAudio = initialAudioTracks.find((track: any) => track.default) || initialAudioTracks[0];
    primaryAudioIndexRef.current = initialAudio?.index;
    setAudioTracks(initialAudioTracks);
    setSelectedAudioIndex(initialAudio?.index);
  }, [file?.id]);
  useEffect(() => {
    const media = mediaRef.current;
    if (!media || !file) return;

    setMediaError('');
    setTrackNotice(source?.kind === 'webtorrent' ? 'Connecting to WebTorrent peers…' : 'Preparing browser stream…');

    // Always have a concrete browser source. Prefer the resolved backend
    // stream, then the direct Seedr presentation URL, then the download
    // endpoint as the final browser-playback fallback.
    const rawStreamUrl = String(source?.streamUrl || file.streamUrl || '').trim();
    const directBaseUrl = rawStreamUrl.includes('/api/torrents/stream/')
      ? rawStreamUrl.replace('/api/torrents/stream/', '/api/torrents/direct-stream/')
      : rawStreamUrl;
    const streamUrl = rawStreamUrl || String(file.externalStreamUrl || '').trim() || String(file.downloadUrl || '').trim();

    // HLS audio tracks are switched through HLS.js. Do not append an audio query parameter.
    const fallbackStreamUrl = String(file.externalStreamUrl || '').trim() &&
      String(file.externalStreamUrl || '').trim() !== streamUrl
      ? String(file.externalStreamUrl || '').trim()
      : String(file.downloadUrl || '').trim() !== streamUrl
        ? String(file.downloadUrl || '').trim()
        : '';

    const restoreTime = resumeTimeRef.current;
    const restorePlaying = resumePlayingRef.current || (!media.paused && duration > 0);

    const handleLoaded = () => {
      if (Number.isFinite(restoreTime) && restoreTime > 0 && Number.isFinite(media.duration)) {
        const safeTime = Math.min(restoreTime, Math.max(0, media.duration - 0.25));
        try {
          media.currentTime = safeTime;
          setCurrentTime(safeTime);
        } catch {}
      }

      // A transient native MEDIA_ERR_SRC_NOT_SUPPORTED can be emitted while
      // Hls.js is attaching MediaSource. Clear any stale overlay once metadata
      // has successfully arrived.
      setMediaError('');

      // Stream buttons are an explicit user action, so always attempt to
      // start playback as soon as the browser has media metadata. The
      // <video>/<audio> elements also have autoPlay enabled below. If the
      // browser's autoplay policy blocks playback, the controls remain
      // available for a manual click.
      media.play()
        .then(() => setIsPlaying(true))
        .catch(() => setIsPlaying(false));
    };

    media.addEventListener('loadedmetadata', handleLoaded, { once: true });

    const handlePlaying = () => {
      // Stage 2 ends only when the browser is actually rendering playback.
      // This prevents the spinner from disappearing merely because metadata
      // or the first buffer arrived.
      setTrackNotice('');
      setMediaError('');
      setIsSeeking(false);
      setIsPlaying(true);
      onPlaybackStarted?.();
    };

    media.addEventListener('playing', handlePlaying);

    if (source?.kind === 'webtorrent') {
      return () => {
        media.removeEventListener('loadedmetadata', handleLoaded);
        media.removeEventListener('playing', handlePlaying);
      };
    }

    if (source?.kind === 'webtor') {
      return () => {
        media.removeEventListener('loadedmetadata', handleLoaded);
        media.removeEventListener('playing', handlePlaying);
      };
    }

    let hls: Hls | null = null;
    // Seedr's browser endpoint intentionally uses a clean same-origin
    // path instead of exposing the upstream .m3u8 filename. Treat that
    // endpoint as HLS explicitly.
    const isHlsStream =
      /\.m3u8(?:$|\?)/i.test(streamUrl) ||
      streamUrl.includes('/api/seedr/hls/') ||
      streamUrl.includes('/api/media/hls/');

    if (isHlsStream && isVideo && Hls.isSupported()) {
      hlsActiveRef.current = true;
      let triedFallback = false;

      const startHls = (sourceUrl: string) => {
        hls?.destroy();
        hls = new Hls({
          enableWorker: true,
          lowLatencyMode: false,
          backBufferLength: 90,
        });
        hlsRef.current = hls;
        setMediaError('');
        hls.loadSource(sourceUrl);
        hls.attachMedia(media as HTMLMediaElement);
        const syncHlsTracks = () => {
          const audio = (hls?.audioTracks || []).map((track: any, index: number) => ({
            index,
            language: String(track?.lang || track?.language || '').trim(),
            title: String(track?.name || track?.title || track?.lang || '').trim(),
            codec: String(track?.audioCodec || track?.codec || '').trim(),
            channels: Number(track?.channels || 0),
            default: Boolean(track?.default),
          }));
          const subtitles = (hls?.subtitleTracks || []).map((track: any, index: number) => ({
            index,
            language: String(track?.lang || track?.language || '').trim(),
            title: String(track?.name || track?.title || track?.lang || '').trim(),
            codec: String(track?.textCodec || track?.codec || '').trim(),
          }));
          setAudioTracks(audio);
          setHlsSubtitleTracks(subtitles);
          const defaultAudio = audio.find(track => track.default);
          if (selectedAudioIndex === undefined && defaultAudio) setSelectedAudioIndex(defaultAudio.index);
          if (selectedHlsSubtitleIndex !== undefined && !subtitles.some(track => track.index === selectedHlsSubtitleIndex)) {
            setSelectedHlsSubtitleIndex(undefined);
          }
        };
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          syncHlsTracks();
          setMediaError('');
        });
        hls.on(Hls.Events.AUDIO_TRACKS_UPDATED, syncHlsTracks);
        hls.on(Hls.Events.SUBTITLE_TRACKS_UPDATED, syncHlsTracks);
        hls.on(Hls.Events.ERROR, (_event, data) => {
          if (!data?.fatal) return;

          console.warn('[MEDIA][HLS] fatal error', {
            details: data?.details,
            type: data?.type,
            response: data?.response?.code,
            url: sourceUrl,
          });

          if (!triedFallback && fallbackStreamUrl && sourceUrl !== fallbackStreamUrl) {
            triedFallback = true;
            setTrackNotice('Trying browser-compatible stream…');
            startHls(fallbackStreamUrl);
            return;
          }

          setMediaError(data?.details || 'Unable to play the HLS stream.');
          setTrackNotice('');
          hls?.destroy();
          hls = null;
          hlsRef.current = null;
        });
      };

      startHls(streamUrl);
    } else if (isHlsStream && isVideo && media.canPlayType('application/vnd.apple.mpegurl')) {
      media.src = streamUrl;
      media.load();
    } else {
      media.src = streamUrl;
      media.load();
    }

    if (!isVideo) {
      media.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
    }

    return () => {
      media.removeEventListener('loadedmetadata', handleLoaded);
      media.removeEventListener('playing', handlePlaying);
      if (hlsRef.current === hls) hlsRef.current = null;
      hls?.destroy();
      media.pause();
      media.removeAttribute('src');
      media.load();
      hlsActiveRef.current = false;
    };
  }, [file?.id, file?.streamUrl, file?.externalStreamUrl, isVideo, source]);
  useEffect(() => {
    if (source?.kind !== 'webtorrent' || !source.attachVideo || !isVideo) return;
    const video = videoRef.current;
    if (!video) return;
    let detach: void | (() => void);
    try {
      detach = source.attachVideo(video);
    } catch (error) {
      setMediaError(error instanceof Error ? error.message : String(error));
      setTrackNotice('');
    }
    return () => {
      detach?.();
      video.pause();
      video.removeAttribute('src');
      video.load();
    };
  }, [source, isVideo, isMinimized]);
  useEffect(() => {
    if (!file || !isVideo) return;
    if (source) return;
    if (file.streamUrl.includes('/api/torrserver/stream/')) return;

    const fileId = file.streamId || file.id.replace(/^seedr-/, '');
    if (!fileId) return;

    const controller = new AbortController();
    let cancelled = false;
    setTracksLoading(true);

    // Keep any already-discovered sidecar subtitles, but still inspect the
    // media container so embedded subtitles and embedded audio tracks are not
    // hidden just because a folder also contains an .srt/.vtt file.
    const sidecarSubtitles = Array.isArray(file.subtitleTracks) ? file.subtitleTracks : [];

    api.getSeedrMediaInfo(fileId)
      .then(data => {
        if (cancelled || !data) return;

        const realAudio = Array.isArray(data.audioTracks) ? data.audioTracks : [];
        const embeddedSubtitles = Array.isArray(data.subtitleTracks) ? data.subtitleTracks : [];
        const sidecarSubtitles = Array.isArray(file.subtitleTracks) ? file.subtitleTracks : [];

        setAudioTracks(realAudio);
        const defaultAudio = realAudio.find((track: any) => track.default) || realAudio[0];
        primaryAudioIndexRef.current = defaultAudio?.index;
        setSelectedAudioIndex(prev =>
          prev !== undefined && realAudio.some((track: any) => track.index === prev)
            ? prev
            : defaultAudio?.index
        );

        // Keep both embedded WebVTT tracks and Seedr sidecar tracks. The API
        // client converts embedded relative URLs to the Render API origin so
        // a Vercel-hosted frontend can actually load the subtitle file.
        const seen = new Set<string>();
        const mergedSubtitles = [...embeddedSubtitles, ...sidecarSubtitles].filter((track: any) => {
          const key = String(track.url || '') + '|' + String(track.title || '');
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        }).map((track: any, index: number) => ({ ...track, index }));

        setSubtitleTracks(mergedSubtitles);
        setSelectedSubtitleIndex(undefined);
        setSelectedHlsSubtitleIndex(undefined);
      })
      .catch(error => {
        // Embedded-track inspection is optional. If FFprobe is unavailable or
        // the remote Seedr source cannot be inspected, keep the sidecar tracks
        // that were already discovered instead of leaving the subtitle menu
        // empty.
        if (!cancelled) {
          if (sidecarSubtitles.length > 0) {
            setSubtitleTracks(sidecarSubtitles.map((track: any, index: number) => ({ ...track, index })));
          } else {
            console.warn('[MEDIA] Seedr track inspection failed:', error);
          }
        }
      })
      .finally(() => {
        if (!cancelled) setTracksLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [file?.id, file?.streamId, isVideo, source]);
  useEffect(() => {
    const track = subtitleTrackRef.current?.track;
    if (track) track.mode = selectedSubtitleIndex === undefined ? 'disabled' : 'showing';
  }, [selectedSubtitleIndex, subtitleTracks]);
  // Subtitle sync is entirely client-side. We adjust the loaded WebVTT cue
  // timestamps in memory, so changing the offset never sends another request
  // to Render or reprocesses the subtitle on the backend.
  useEffect(() => {
    const track = subtitleTrackRef.current?.track;
    if (!track || selectedSubtitleIndex === undefined) return;

    const url = subtitleTracks.find(item => item.index === selectedSubtitleIndex)?.url;
    if (!url) return;

    const applyOffset = () => {
      const cues = Array.from(track.cues || []) as any[];
      if (!cues.length) return;

      let originals = subtitleCueOriginalsRef.current.get(url);
      if (!originals) {
        originals = cues.map(cue => ({
          cue,
          start: Number(cue.startTime),
          end: Number(cue.endTime),
        }));
        subtitleCueOriginalsRef.current.set(url, originals);
      }

      const originalByCue = new Map(originals.map(item => [item.cue, item]));
      cues.forEach(cue => {
        const original = originalByCue.get(cue);
        if (!original) return;
        cue.startTime = Math.max(0, original.start + subtitleOffset);
        cue.endTime = Math.max(cue.startTime, original.end + subtitleOffset);
      });
    };

    // The cue list may not exist until the browser finishes parsing WebVTT.
    applyOffset();
    const timer = window.setTimeout(applyOffset, 50);
    const laterTimer = window.setTimeout(applyOffset, 250);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(laterTimer);
    };
  }, [selectedSubtitleIndex, subtitleOffset, subtitleTracks]);
  useEffect(() => {
    const hls = hlsRef.current;
    if (!hls) return;
    if (selectedAudioIndex !== undefined && hls.audioTracks?.[selectedAudioIndex]) {
      hls.audioTrack = selectedAudioIndex;
    }
  }, [selectedAudioIndex, audioTracks]);
  useEffect(() => {
    const hls = hlsRef.current;
    if (!hls) return;
    if (selectedHlsSubtitleIndex === undefined) {
      hls.subtitleDisplay = false;
      hls.subtitleTrack = -1;
    } else if (hls.subtitleTracks?.[selectedHlsSubtitleIndex]) {
      hls.subtitleDisplay = true;
      hls.subtitleTrack = selectedHlsSubtitleIndex;
    }
  }, [selectedHlsSubtitleIndex, hlsSubtitleTracks]);
  // Keep React state synchronized with the browser's actual fullscreen state.
  useEffect(() => {
    const handleFullscreenChange = () => {
      const active = document.fullscreenElement === containerRef.current;
      setIsFullscreen(active);
      setFullscreenControlsVisible(false);
      if (active) {
        void lockLandscape();
      } else {
        unlockOrientation();
      }
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, [isVideo]);
  // Native <track> elements can be inserted after the video has already
  // loaded. Explicitly switch the selected track to "showing" so mobile
  // Chrome/Android does not leave the newly-created TextTrack in "disabled".
  useEffect(() => {
    if (!isVideo || selectedSubtitleIndex === undefined) return;

    const timer = window.setTimeout(() => {
      const media = videoRef.current;
      if (!media) return;

      const selected = subtitleTracks.find(track => track.index === selectedSubtitleIndex);
      const selectedTextTrack = subtitleTrackRef.current?.track;
      const textTracks = Array.from(media.textTracks || []);

      textTracks.forEach(track => {
        track.mode = selectedTextTrack && track === selectedTextTrack ? 'showing' : 'disabled';
      });

      if (selected) {
        setTrackNotice('');
      }
    }, 50);

    return () => window.clearTimeout(timer);
  }, [isVideo, selectedSubtitleIndex, subtitleTracks]);
  // Some MKV files contain audio codecs that Chromium can demux poorly or not
  // decode at all (E-AC-3, AC-3, DTS, TrueHD, PCM, etc.). In that case the
  // video element can play normally while producing no audible sound. Reuse
  // the existing FFmpeg audio-track endpoint automatically for the selected
  // track instead of making the user manually switch tracks.
  const browserNeedsAudioFallback = (codec: string) => {
    const normalized = String(codec || '').trim().toLowerCase();
    if (!normalized) return false;
    const browserFriendly = new Set([
      'aac', 'mp3', 'mpeg', 'opus', 'vorbis', 'flac', 'mp4a', 'alac'
    ]);
    if (browserFriendly.has(normalized)) return false;
    return normalized.startsWith('ac3') ||
      normalized.startsWith('eac3') ||
      normalized.startsWith('dts') ||
      normalized.startsWith('dca') ||
      normalized.startsWith('truehd') ||
      normalized.startsWith('mlp') ||
      normalized.startsWith('pcm') ||
      normalized.startsWith('wma') ||
      normalized.startsWith('wmav') ||
      normalized.startsWith('cook') ||
      normalized.startsWith('atrac');
  };
  useEffect(() => {
    if (!isVideo || !file || hlsActiveRef.current || selectedAudioIndex === undefined) return;
    if (automaticAudioFallbackRef.current || alternateAudioIndexRef.current !== undefined) return;

    const selectedTrack = audioTracks.find(track => track.index === selectedAudioIndex);
    if (!selectedTrack || !browserNeedsAudioFallback(selectedTrack.codec)) return;

    const media = videoRef.current;
    if (!media) return;

    automaticAudioFallbackRef.current = true;
    const position = Number.isFinite(media.currentTime) ? media.currentTime : currentTime;
    const wasPlaying = !media.paused;

    console.info('[MEDIA] Native audio codec is not browser-safe; using FFmpeg fallback', {
      codec: selectedTrack.codec,
      track: selectedTrack.index,
      position,
    });

    loadAlternateAudio(selectedTrack.index, position, wasPlaying);
  }, [audioTracks, currentTime, file, isVideo, selectedAudioIndex]);
  if (!file) return null;
  const handleMediaError = () => {
    // When Hls.js owns the video element, Chrome can briefly report
    // MEDIA_ERR_SRC_NOT_SUPPORTED while MediaSource is being attached.
    // Hls.js is the authoritative error source in that mode.
    if (hlsActiveRef.current) return;

    const media = mediaRef.current;
    if (
      media &&
      file?.externalStreamUrl &&
      file.externalStreamUrl !== file.streamUrl &&
      !usingDirectFallback
    ) {
      // The backend proxy is the preferred browser path, but Seedr's
      // presentation URL is known to be directly playable by Chrome for
      // some files. If the proxy response is rejected by the browser,
      // immediately retry the exact Seedr presentation URL rather than
      // showing a fatal error.
      setUsingDirectFallback(true);
      setMediaError('');
      setTrackNotice('Trying direct Seedr stream…');
      media.src = file.externalStreamUrl;
      media.load();
      return;
    }

    const code = media && 'error' in media ? media.error?.code : undefined;
    setMediaError(
      code ? `Browser could not play this stream (media error ${code}).` : 'Unable to play this video stream.'
    );
    setTrackNotice('');
    setIsSeeking(false);
    setIsPlaying(false);
    onPlaybackStarted?.();
  };
  // Toggle play/pause
  const togglePlay = () => {
    const media = mediaRef.current;
    const alternateAudio = alternateAudioRef.current;
    if (!media) return;

    if (isPlaying) {
      media.pause();
      alternateAudio?.pause();
      setIsPlaying(false);
      return;
    }

    const playRequests: Promise<any>[] = [media.play()];
    if (alternateAudioIndexRef.current !== undefined && alternateAudio?.src) {
      playRequests.push(alternateAudio.play());
    }
    Promise.allSettled(playRequests).then(() => {
      setIsPlaying(!media.paused);
    });
  };
  // Seek
  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value);
    const media = mediaRef.current;
    if (!media || !Number.isFinite(time)) return;

    const wasPlaying = !media.paused;
    setCurrentTime(time);
    setIsSeeking(true);
    setTrackNotice('Seeking…');

    media.currentTime = Math.max(0, Math.min(duration || file.duration || time, time));

    // When an alternate Seedr audio track is active, reload that audio from
    // the requested absolute video position. The video itself remains on its
    // original full-duration timeline.
    if (alternateAudioIndexRef.current !== undefined) {
      loadAlternateAudio(alternateAudioIndexRef.current, time, wasPlaying);
      return;
    }

    if (media.paused) {
      const clearPausedSeek = () => {
        setIsSeeking(false);
        setTrackNotice('');
        media.removeEventListener('seeked', clearPausedSeek);
      };
      media.addEventListener('seeked', clearPausedSeek, { once: true });
    }
  };
  // Skip
  const skip = (seconds: number) => {
    const media = mediaRef.current;
    if (!media) return;
    const nextTime = Math.max(0, Math.min(duration || file.duration || media.duration || 0, currentTime + seconds));
    handleSeek({ target: { value: String(nextTime) } } as React.ChangeEvent<HTMLInputElement>);
  };
  // Volume
  const handleVolume = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value);
    setVolume(val);
    setIsMuted(val === 0);
    if (mediaRef.current) {
      mediaRef.current.volume = val;
    }
    if (alternateAudioRef.current) {
      alternateAudioRef.current.volume = val;
      alternateAudioRef.current.muted = val === 0;
    }
  };
  const toggleMute = () => {
    const media = mediaRef.current;
    const alternateAudio = alternateAudioRef.current;
    if (!media) return;

    if (isMuted) {
      const nextVolume = volume || 0.8;
      media.volume = nextVolume;
      media.muted = false;
      if (alternateAudio) {
        alternateAudio.volume = nextVolume;
        alternateAudio.muted = false;
      }
      setIsMuted(false);
    } else {
      media.volume = 0;
      media.muted = true;
      if (alternateAudio) {
        alternateAudio.volume = 0;
        alternateAudio.muted = true;
      }
      setIsMuted(true);
    }
  };
  const loadAlternateAudio = (trackIndex: number, position: number, resumePlaying: boolean) => {
    const media = mediaRef.current;
    const audio = alternateAudioRef.current;
    const fileId = file?.streamId || file?.id?.replace(/^seedr-/, '');

    if (!media || !audio || !fileId) {
      setTrackNotice('Selected audio track is not available in this stream.');
      return;
    }

    const requestId = ++alternateAudioRequestRef.current;
    const safePosition = Math.max(0, Number.isFinite(position) ? position : 0);

    // Keep the original video resource and timeline intact. Only its audio
    // output is muted while the selected track is prepared in a second audio
    // element. This avoids resetting the video's duration/seekable range.
    media.pause();
    media.muted = true;
    audio.pause();
    audio.volume = media.volume;
    audio.muted = isMuted;
    audio.playbackRate = playbackSpeed;

    const url =
      API_BASE +
      '/api/seedr/media/audio/' + encodeURIComponent(fileId) +
      '?track=' + encodeURIComponent(String(trackIndex)) +
      '&start=' + encodeURIComponent(String(safePosition));

    setTrackNotice('Switching audio…');
    setMediaError('');
    setIsSeeking(true);
    alternateAudioIndexRef.current = trackIndex;
    audio.src = url;
    audio.load();

    const handleAudioError = () => {
      if (requestId !== alternateAudioRequestRef.current) return;
      alternateAudioIndexRef.current = undefined;
      media.muted = isMuted;
      setIsSeeking(false);
      setIsPlaying(false);
      setTrackNotice('Unable to load the selected audio track.');
      audio.removeEventListener('loadeddata', startTogether);
      audio.removeEventListener('canplay', startTogether);
      audio.removeEventListener('error', handleAudioError);
    };

    const startTogether = () => {
      if (requestId !== alternateAudioRequestRef.current) return;
      audio.removeEventListener('loadeddata', startTogether);
      audio.removeEventListener('canplay', startTogether);
      audio.removeEventListener('error', handleAudioError);
      audio.currentTime = 0;

      if (!resumePlaying) {
        setIsSeeking(false);
        setIsPlaying(false);
        setTrackNotice('');
        return;
      }

      // Start both elements from the same user-visible position only after
      // the alternate audio is playable. This prevents the audio track from
      // getting ahead of the first video frame during a track switch.
      const startVideo = media.play();
      const startAudio = audio.play();
      Promise.allSettled([startVideo, startAudio]).then((results) => {
        if (requestId !== alternateAudioRequestRef.current) return;
        const videoStarted = results[0]?.status === 'fulfilled';
        const audioStarted = results[1]?.status === 'fulfilled';
        if (!videoStarted || !audioStarted) {
          media.pause();
          audio.pause();
          setIsSeeking(false);
          setIsPlaying(false);
          setTrackNotice('Playback could not resume with the selected audio track.');
          return;
        }
        setIsSeeking(false);
        setIsPlaying(true);
        setTrackNotice('');
      });
    };

    // WebM/Opus can become playable before the browser reaches the native
    // canplay threshold. loadeddata is enough to start the synchronized pair.
    audio.addEventListener('loadeddata', startTogether, { once: true });
    audio.addEventListener('canplay', startTogether, { once: true });
    audio.addEventListener('error', handleAudioError, { once: true });
  };
  const clearAlternateAudio = (restoreVideoAudio = true) => {
    const media = mediaRef.current;
    const audio = alternateAudioRef.current;
    alternateAudioRequestRef.current += 1;

    if (audio) {
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
    }
    alternateAudioIndexRef.current = undefined;

    if (restoreVideoAudio && media) {
      media.muted = isMuted;
    }
  };
  const handleAudioTrackChange = (value: string) => {
    const next = Number(value);
    if (!Number.isInteger(next)) return;

    const media = mediaRef.current;
    const hls = hlsRef.current;

    if (hls?.audioTracks?.[next]) {
      hls.audioTrack = next;
      setSelectedAudioIndex(next);
      setTrackNotice('');
      return;
    }

    if (media && file?.streamUrl.includes('/api/seedr/media/video/')) {
      const position = Number.isFinite(media.currentTime) ? media.currentTime : currentTime;
      const wasPlaying = !media.paused;
      const primaryIndex = primaryAudioIndexRef.current;

      setSelectedAudioIndex(next);

      if (primaryIndex !== undefined && next === primaryIndex) {
        clearAlternateAudio(true);
        media.currentTime = position;
        if (wasPlaying) {
          media.play()
            .then(() => {
              setIsPlaying(true);
              setTrackNotice('');
            })
            .catch(() => setIsPlaying(false));
        } else {
          setIsPlaying(false);
          setTrackNotice('');
        }
        return;
      }

      loadAlternateAudio(next, position, wasPlaying);
      return;
    }

    setTrackNotice('Selected audio track is not available in this stream.');
  };
  const handleSubtitleTrackChange = (value: string) => {
    if (value === 'off') {
      setSelectedSubtitleIndex(undefined);
      setSelectedHlsSubtitleIndex(undefined);
      return;
    }
    if (value.startsWith('hls:')) {
      const next = Number(value.slice(4));
      if (Number.isInteger(next)) {
        setSelectedSubtitleIndex(undefined);
        setSelectedHlsSubtitleIndex(next);
      }
      return;
    }
    if (value.startsWith('external:')) {
      const next = Number(value.slice(9));
      if (Number.isInteger(next)) {
        setSelectedHlsSubtitleIndex(undefined);
        setSelectedSubtitleIndex(next);
      }
    }
  };
  // Speed
  const handleSpeedChange = (speed: number) => {
    setPlaybackSpeed(speed);
    if (mediaRef.current) {
      mediaRef.current.playbackRate = speed;
    }
    if (alternateAudioRef.current) {
      alternateAudioRef.current.playbackRate = speed;
    }
  };
  const languageNames: Record<string, string> = {
    en: 'English', eng: 'English',
    hi: 'Hindi', hin: 'Hindi',
    fr: 'French', fra: 'French',
    de: 'German', deu: 'German',
    es: 'Spanish', spa: 'Spanish',
    it: 'Italian', ita: 'Italian',
    pt: 'Portuguese', por: 'Portuguese',
    ru: 'Russian', rus: 'Russian',
    ja: 'Japanese', jpn: 'Japanese',
    ko: 'Korean', kor: 'Korean',
    zh: 'Chinese', zho: 'Chinese',
    ar: 'Arabic', ara: 'Arabic',
    bn: 'Bengali', ben: 'Bengali',
  };
  const formatTrackLabel = (
    track: { language?: string; title?: string },
    index: number,
    fallbackPrefix: string
  ) => {
    const languageCode = String(track.language || '').trim().toLowerCase();
    const language = languageNames[languageCode] || languageCode.toUpperCase();
    const title = String(track.title || '').trim();
    if (language && title && title.toLowerCase() !== language.toLowerCase()) {
      return language + ' (' + title + ')';
    }
    return language || title || fallbackPrefix + ' ' + (index + 1);
  };
  // Fullscreen
  const lockLandscape = async () => {
    if (!isVideo) return;
    try {
      if (typeof screen !== 'undefined' && screen.orientation?.lock) {
        await screen.orientation.lock('landscape');
      }
    } catch {
      // Some Android browsers expose fullscreen but do not allow orientation
      // locking. The fullscreen layout below still uses the real viewport.
    }
  };
  const unlockOrientation = () => {
    try {
      if (typeof screen !== 'undefined' && screen.orientation?.unlock) {
        screen.orientation.unlock();
      }
    } catch {
      // Orientation unlock is not supported by every browser.
    }
  };
  const toggleFullscreen = async () => {
    if (!containerRef.current) return;

    if (!document.fullscreenElement) {
      try {
        await containerRef.current.requestFullscreen?.();
        setIsFullscreen(true);
        await lockLandscape();
      } catch {
        setIsFullscreen(Boolean(document.fullscreenElement));
      }
    } else {
      try {
        await document.exitFullscreen?.();
      } finally {
        setIsFullscreen(false);
        unlockOrientation();
      }
    }
  };
  // Copy Direct Stream URL
  const copyStreamUrl = () => {
    // For Seedr files, prefer the exact external-player HLS URL generated by
    // the backend. Otherwise copy the app's same-origin stream URL.
    const url = source?.streamUrl || file.externalStreamUrl || file.streamUrl;
    const fullUrl = (
      url.startsWith('http://') || url.startsWith('https://')
        ? url
        : window.location.origin + url
    );
    navigator.clipboard.writeText(fullUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  const downloadProviderFile = async () => {
    if (!source?.download) return;
    setMediaError('');
    try {
      await source.download();
    } catch (error) {
      setMediaError(error instanceof Error ? error.message : String(error));
    }
  };
  // Picture in Picture
  const togglePip = async () => {
    if (videoRef.current && document.pictureInPictureEnabled) {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture();
      } else {
        await videoRef.current.requestPictureInPicture();
      }
    }
  };
  // Timeline seeking/buffering
  const onSeeking = () => {
    setIsSeeking(true);
    setTrackNotice('Seeking…');
  };
  const onSeeked = () => {
    const media = mediaRef.current;
    // If playback was paused, "playing" will never arrive to clear the
    // loader. For active playback, keep it visible until "playing" resumes.
    if (media?.paused) {
      setIsSeeking(false);
      setTrackNotice('');
    }
  };
  // Time update
  const onTimeUpdate = () => {
    if (mediaRef.current) {
      setCurrentTime(mediaRef.current.currentTime);
    }
  };
  const onLoadedMetadata = () => {
    if (mediaRef.current) {
      setDuration(mediaRef.current.duration || file.duration || 600);

      if (resumePlayingRef.current) {
        mediaRef.current.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
      } else {
        setIsPlaying(false);
      }
    }
  };

  return {
    file,
    source,
    providerStatus,
    canMinimize: source?.kind !== 'webtor',
    hasCopyableUrl: Boolean(source?.streamUrl || file?.streamUrl || file?.externalStreamUrl),
    hasDownload: Boolean(source?.download || source?.downloadUrl || (!source && file?.downloadUrl)),
    downloadProviderFile,
    onClose,
    onPlaybackStarted,
    isMinimized,
    onToggleMinimize,
    isPlaying,
    setIsPlaying,
    currentTime,
    duration,
    volume,
    isMuted,
    playbackSpeed,
    isFullscreen,
    fullscreenControlsVisible,
    setFullscreenControlsVisible,
    copied,
    mediaError,
    setIsSeeking,
    audioTracks,
    subtitleTracks,
    hlsSubtitleTracks,
    selectedAudioIndex,
    selectedSubtitleIndex,
    selectedHlsSubtitleIndex,
    trackNotice,
    setTrackNotice,
    tracksLoading,
    subtitleSyncOpen,
    setSubtitleSyncOpen,
    subtitleOffset,
    setSubtitleOffset,
    subtitleCueOriginalsRef,
    subtitleTrackRef,
    videoRef,
    audioRef,
    alternateAudioRef,
    containerRef,
    isVideo,
    handleMediaError,
    togglePlay,
    handleSeek,
    skip,
    handleVolume,
    toggleMute,
    handleAudioTrackChange,
    handleSubtitleTrackChange,
    handleSpeedChange,
    formatTrackLabel,
    toggleFullscreen,
    copyStreamUrl,
    togglePip,
    onSeeking,
    onSeeked,
    onTimeUpdate,
    onLoadedMetadata,
  };
}

// The hook returns null while there is no file to play (same as the old early return).
export type PanelModel = NonNullable<ReturnType<typeof useMediaPlayerModel>>;
