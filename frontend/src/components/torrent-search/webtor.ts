export const WEBTOR_URL = 'https://webtor.io/';

/** Copy text without awaiting, so the caller stays inside the user's click (popup blockers). */
export function copyTextNow(text: string): boolean {
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.cssText = 'position:fixed;top:-1000px;opacity:0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    if (ok) return true;
  } catch { /* fall through to the async API */ }
  try { void navigator.clipboard?.writeText(text); return Boolean(navigator.clipboard); } catch { return false; }
}

/** Copy the magnet, then open Webtor in a new tab where the user pastes it to stream or download. */
export function copyMagnetAndOpenWebtor(magnetUrl: string): boolean {
  const copied = copyTextNow(magnetUrl);
  window.open(WEBTOR_URL, '_blank', 'noopener,noreferrer');
  return copied;
}
