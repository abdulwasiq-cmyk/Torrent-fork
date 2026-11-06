/** Helpers for "Play HD": which device we are on and how to hand a stream link to VLC / MX Player. */

export type PlayerPlatform = 'android' | 'ios' | 'desktop';

export function platformFromUserAgent(userAgent: string, maxTouchPoints = 0): PlayerPlatform {
  if (/android/i.test(userAgent)) return 'android';
  // iPadOS reports a Mac user agent but has touch points.
  if (/iphone|ipad|ipod/i.test(userAgent) || (/macintosh/i.test(userAgent) && maxTouchPoints > 1)) return 'ios';
  return 'desktop';
}

export const currentPlatform = (): PlayerPlatform =>
  typeof navigator === 'undefined' ? 'desktop' : platformFromUserAgent(navigator.userAgent || '', navigator.maxTouchPoints || 0);

/** Android "intent:" link that opens the stream in a specific app (https URL only). */
export function androidIntent(url: string, androidPackage: string): string {
  const withoutScheme = url.replace(/^https:/i, '');
  return `intent:${withoutScheme}#Intent;scheme=https;package=${androidPackage};type=video/*;end`;
}

export const MX_PLAYER_PACKAGE = 'com.mxtech.videoplayer.ad';
export const VLC_PACKAGE = 'org.videolan.vlc';

/** Link that opens the stream in VLC, or '' when this platform has no reliable VLC link. */
export function vlcLink(url: string, platform: PlayerPlatform): string {
  if (!/^https:\/\//i.test(url)) return '';
  if (platform === 'android') return androidIntent(url, VLC_PACKAGE);
  if (platform === 'ios') return `vlc-x-callback://x-callback-url/stream?url=${encodeURIComponent(url)}`;
  return `vlc://${url}`;   // desktop: works when VLC registered its protocol handler; "Copy link" is the fallback
}

/** MX Player exists only on Android. */
export function mxPlayerLink(url: string, platform: PlayerPlatform): string {
  return platform === 'android' && /^https:\/\//i.test(url) ? androidIntent(url, MX_PLAYER_PACKAGE) : '';
}

/**
 * Chrome/Edge expose how many audio bytes the browser decoded; 0 after playback started means the video plays silently
 * (DTS / Dolby audio). Other browsers do not expose it, so unknown is treated as "has sound".
 */
export function playsSilently(video: Pick<HTMLVideoElement, 'currentTime' | 'muted'> & { webkitAudioDecodedByteCount?: number; mozHasAudio?: boolean }): boolean {
  if (video.muted || video.currentTime < 2) return false;
  if (typeof video.webkitAudioDecodedByteCount === 'number') return video.webkitAudioDecodedByteCount === 0;
  if (typeof video.mozHasAudio === 'boolean') return !video.mozHasAudio;
  return false;
}
