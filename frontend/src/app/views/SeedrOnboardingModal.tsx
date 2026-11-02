import { Cloud, ShieldCheck, Loader2 } from 'lucide-react';
import type { PanelModel } from '../useAppModel.tsx';

export function SeedrOnboardingModal({ vm }: { vm: PanelModel }) {
  const { connectSeedrWithPat, seedrConnectError, seedrConnected, seedrOnboardingOpen, seedrPat, seedrPatSubmitting, seedrSessionReady, setSeedrOnboardingOpen, setSeedrPat } = vm;
  return (
    <>
      {seedrOnboardingOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center overflow-y-auto bg-slate-950/50 px-4 py-6 backdrop-blur-[3px]"
          role="dialog"
          aria-modal="true"
          aria-labelledby="seedr-onboarding-title"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setSeedrOnboardingOpen(false);
            }
          }}
        >
          <div
            className="relative my-auto w-full max-w-lg rounded-2xl border border-emerald-500/25 bg-slate-900/95 p-5 shadow-2xl shadow-emerald-500/10 sm:p-6"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              aria-label="Close Seedr connection dialog"
              onClick={() => setSeedrOnboardingOpen(false)}
              className="absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-full text-slate-400 transition hover:bg-slate-800 hover:text-white"
            >
              <span className="text-2xl leading-none">×</span>
            </button>

            <div className="flex items-start gap-3 pr-8">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400">
                <Cloud className="h-6 w-6" />
              </div>
              <div className="min-w-0">
                <h2 id="seedr-onboarding-title" className="text-lg font-bold text-slate-100">
                  {seedrConnected ? 'Seedr account connected' : 'Connect to Seedr'}
                </h2>
                <p className="mt-1 text-sm leading-5 text-slate-400">
                  {seedrConnected
                    ? 'Torrent Studio is connected to your Seedr account.'
                    : 'Connect your own Seedr account to send torrents directly to your Seedr storage.'}
                </p>
              </div>
            </div>

            {seedrConnected ? (
              <>
                <div className="mt-5 rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-4">
                  <p className="text-sm font-semibold text-emerald-200">Connected successfully</p>
                  <p className="mt-1 text-xs leading-5 text-slate-300">
                    This browser session is using your Seedr account. No shared Seedr storage is used.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSeedrOnboardingOpen(false)}
                  className="mt-5 w-full rounded-xl bg-emerald-500 px-4 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-emerald-400"
                >
                  Done
                </button>
              </>
            ) : (
              <div className="mt-5 space-y-4">
                <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-4">
                  <div className="flex items-start gap-3">
                    <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-400" />
                    <div className="min-w-0">
                      <p className="text-sm font-bold text-emerald-200">Have a Seedr account?</p>
                      <p className="mt-1 text-xs leading-5 text-slate-300">
                        Paste your Seedr token below. Your Seedr password is never requested.
                      </p>
                    </div>
                  </div>

                  <input
                    type="password"
                    value={seedrPat}
                    onChange={(e) => setSeedrPat(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !seedrPatSubmitting && seedrSessionReady) {
                        void connectSeedrWithPat();
                      }
                    }}
                    placeholder="Paste your Seedr token"
                    autoComplete="off"
                    spellCheck={false}
                    className="mt-4 w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-3 font-mono text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-emerald-500/50 focus:ring-2 focus:ring-emerald-500/10"
                  />

                  {seedrConnectError && (
                    <div className="mt-3 rounded-xl border border-amber-500/25 bg-amber-500/10 p-3">
                      <p className="text-xs leading-5 text-amber-100">{seedrConnectError}</p>
                    </div>
                  )}

                  <button
                    type="button"
                    disabled={seedrPatSubmitting || !seedrPat.trim() || !seedrSessionReady}
                    onClick={() => { void connectSeedrWithPat(); }}
                    className="mt-3 w-full rounded-xl bg-emerald-500 px-4 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {seedrPatSubmitting ? (
                      <span className="inline-flex items-center justify-center gap-2">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Connecting…
                      </span>
                    ) : (
                      'Connect'
                    )}
                  </button>
                </div>

                <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
                  <div className="flex items-center gap-2">
                    <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-cyan-500/10 text-xs font-black text-cyan-300">?</div>
                    <p className="text-sm font-bold text-slate-100">Create your Seedr token</p>
                  </div>

                  <ol className="mt-3 space-y-2.5 pl-5 text-xs leading-5 text-slate-300 list-decimal">
                    <li>
                      Open the{' '}
                      <a
                        href="https://www.seedr.cc/api/v0.1/console/tokens"
                        target="_blank"
                        rel="noreferrer"
                        className="font-semibold text-emerald-300 underline decoration-emerald-500/40 underline-offset-2 hover:text-emerald-200"
                      >
                        Seedr tokens
                      </a>{' '}
                      page.
                    </li>
                    <li>Click <span className="font-semibold text-slate-100">“Google Login”</span>.</li>
                    <li>The token page opens.</li>
                    <li>Token Name = <span className="font-semibold text-slate-100">Any name</span>.</li>
                    <li><span className="font-semibold text-slate-100">Expiration</span> = <span className="font-semibold text-slate-100">Never</span>.</li>
                    <li>Scopes = click <span className="font-semibold text-slate-100">Full Account Access</span>.</li>
                    <li>Go below and click <span className="font-semibold text-slate-100">Generate Token</span>.</li>
                    <li>Copy the token code and save it somewhere safe.</li>
                    <li>Paste the token code above and click <span className="font-semibold text-slate-100">Connect</span>.</li>
                  </ol>
                </div>

                <p className="text-center text-[11px] leading-4 text-slate-500">
                  Your token is sent only to Torrent Studio over HTTPS and is kept in your secure browser session.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
