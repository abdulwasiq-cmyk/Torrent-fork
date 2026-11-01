export const WEBTOR_SDK_URL = 'https://cdn.jsdelivr.net/npm/@webtor/embed-sdk-js/dist/index.min.js';

export function makeWebtorEmbedConfig(
  id: string,
  magnet: string,
  on: (event: unknown) => void,
): Record<string, unknown> {
  return {
    id,
    magnet,
    width: '100%',
    height: '100%',
    controls: true,
    on,
  };
}

export function webtorEventError(event: unknown): string | null {
  if (!event || typeof event !== 'object') return null;
  const value = event as { name?: unknown; data?: unknown };
  if (value.name !== 'torrent error') return null;
  if (typeof value.data === 'string' && value.data.trim()) return value.data;
  if (value.data && typeof value.data === 'object') {
    const detail = (value.data as { message?: unknown; error?: unknown }).message ||
      (value.data as { error?: unknown }).error;
    if (typeof detail === 'string' && detail.trim()) return detail;
  }
  return 'Webtor could not load this torrent.';
}
