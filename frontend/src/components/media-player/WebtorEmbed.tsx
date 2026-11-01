import { useEffect, useRef, useState } from 'react';
import { makeWebtorEmbedConfig, webtorEventError, WEBTOR_SDK_URL } from '../torrent-search/webtorEmbed.ts';

declare global {
  interface Window {
    webtor?: Array<Record<string, unknown>>;
  }
}

let webtorSdkLoad: Promise<void> | null = null;

function loadWebtorSdk(): Promise<void> {
  if (webtorSdkLoad) return webtorSdkLoad;
  webtorSdkLoad = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${WEBTOR_SDK_URL}"]`);
    const script = existing || document.createElement('script');
    const timeout = window.setTimeout(() => reject(new Error('Timed out loading the Webtor player SDK.')), 15_000);
    const loaded = () => {
      window.clearTimeout(timeout);
      script.dataset.loaded = 'true';
      resolve();
    };
    const failed = () => {
      window.clearTimeout(timeout);
      webtorSdkLoad = null;
      reject(new Error('Could not load the Webtor player SDK.'));
    };

    if (script.dataset.loaded === 'true' || (window.webtor && !Array.isArray(window.webtor))) {
      window.clearTimeout(timeout);
      resolve();
      return;
    }
    script.addEventListener('load', loaded, { once: true });
    script.addEventListener('error', failed, { once: true });
    if (!existing) {
      script.src = WEBTOR_SDK_URL;
      script.async = true;
      document.head.appendChild(script);
    }
  });
  return webtorSdkLoad;
}

export function WebtorEmbed({ magnet }: { magnet: string }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState('Loading Webtor…');
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    let iframeTimer = 0;
    let observer: MutationObserver | null = null;
    const element = mountRef.current;
    if (!element) return;

    const id = `webtor-player-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    element.id = id;
    void loadWebtorSdk()
      .then(() => {
        if (!active) return;
        const events = (event: unknown) => {
          const message = webtorEventError(event);
          if (message) {
            setError(message);
            setStatus('');
          }
        };
        window.webtor = window.webtor || [];
        window.webtor.push(makeWebtorEmbedConfig(id, magnet, events));
        observer = new MutationObserver(() => {
          if (element.querySelector('iframe')) {
            setStatus('Webtor player ready. Choose a video file in the player.');
            window.clearTimeout(iframeTimer);
          }
        });
        observer.observe(element, { childList: true, subtree: true });
        iframeTimer = window.setTimeout(() => {
          if (active && !element.querySelector('iframe')) {
            setError('Webtor did not create its player. The hosted provider may be unavailable.');
            setStatus('');
          }
        }, 15_000);
      })
      .catch(loadError => {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : String(loadError));
          setStatus('');
        }
      });

    return () => {
      active = false;
      window.clearTimeout(iframeTimer);
      observer?.disconnect();
      element.replaceChildren();
    };
  }, [magnet]);

  return (
    <div className="flex min-h-[300px] flex-1 flex-col bg-black">
      {status && <p className="px-3 py-2 text-xs text-slate-300">{status}</p>}
      {error && <p role="alert" className="px-3 py-2 text-xs text-rose-300">{error}</p>}
      <div ref={mountRef} className="min-h-[280px] flex-1" />
    </div>
  );
}
