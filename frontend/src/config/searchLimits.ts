import fallbackLimits from '../../search_limits.json';

/**
 * The size window for torrents on the Prepare card. The backend injects its own values
 * (TORRENT_MIN_SIZE_MB / TORRENT_MAX_SIZE_GB) into index.html as window.__SEARCH_LIMITS__, so the
 * browser filter always matches the server filter and changing the env vars needs only a
 * restart. search_limits.json is the fallback (vite dev server, or an old server).
 */
const positive = (value: unknown): number | null => {
  const number = typeof value === 'number' ? value : Number.NaN;
  return Number.isFinite(number) && number > 0 ? number : null;
};

export function readSearchLimits(injected: unknown = (globalThis as { __SEARCH_LIMITS__?: unknown }).__SEARCH_LIMITS__) {
  const source = (injected && typeof injected === 'object' ? injected : {}) as { minSizeMb?: unknown; maxSizeGb?: unknown };
  const minSizeMb = positive(source.minSizeMb) ?? Number(fallbackLimits.minSizeMb);
  const maxSizeGb = positive(source.maxSizeGb) ?? Number(fallbackLimits.maxSizeGb);
  return {
    minSizeMb,
    maxSizeGb: Math.max(maxSizeGb, minSizeMb / 1024),
    minSizeBytes: Math.round(minSizeMb * 1024 * 1024),
    maxSizeBytes: Math.max(Math.round(maxSizeGb * 1024 ** 3), Math.round(minSizeMb * 1024 * 1024)),
  };
}

export const searchLimits = readSearchLimits();
/** Part of the Prepare-card cache keys: a different size window must never serve results cached under another. */
export const searchLimitsSignature = `${searchLimits.minSizeBytes}-${searchLimits.maxSizeBytes}`;
