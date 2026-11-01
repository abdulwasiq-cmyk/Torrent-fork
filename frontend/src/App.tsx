/**
 * SeedFlow - Cloud Torrent & Media Streaming Application
 * Seedr-style webapp with qBittorrent WebAPI v2 orchestration,
 * unlimited server storage, HTTP range streaming, and selective downloads.
 */

// Deployment marker: frontend is deployed from main via Vercel.



import { TorrentCard } from './components/TorrentCard.tsx';
import { lazy, Suspense } from 'react';

// The player (and the large hls.js library it uses) loads only when a file is first played.
const MediaPlayerModal = lazy(() => import('./components/MediaPlayerModal.tsx').then(module => ({ default: module.MediaPlayerModal })));
import { ActivityLogView } from './components/ActivityLogView.tsx';
import { useAppModel } from './app/useAppModel.tsx';
import { SeedrOnboardingModal } from './app/views/SeedrOnboardingModal.tsx';
import { AppModals } from './app/views/AppModals.tsx';
import { MobileNav } from './app/views/MobileNav.tsx';
import { MainContent } from './app/views/MainContent.tsx';
import { AppHeader } from './app/views/AppHeader.tsx';
import { ProductWelcomeScreen } from './app/views/ProductWelcomeScreen.tsx';

export default function App() {
  const vm = useAppModel();
  const { productWelcomeOpen, theme, setSeedrStreamLoadingId, activeMediaFile, setActiveMediaFile, activeMediaSource, setActiveMediaSource, isPlayerMinimized, setIsPlayerMinimized } = vm;












































































  if (productWelcomeOpen) {
    return (
      <ProductWelcomeScreen vm={vm} />
    );
  }

  return (
    <div className={`min-h-screen flex flex-col ${theme === 'dark' ? 'bg-slate-950' : 'bg-slate-900'} text-slate-100 transition-colors duration-200`}>
      {/* Top Main Navigation Header */}
      <AppHeader vm={vm} />

      {/* Main Content Area */}
      <MainContent vm={vm} />

      {/* Floating Bottom Media Player (when minimized or active) */}
      {activeMediaFile && (
        <Suspense fallback={null}>
        <MediaPlayerModal
          file={activeMediaFile}
          source={activeMediaSource}
          onClose={() => {
            setActiveMediaFile(null);
            setActiveMediaSource(null);
            setSeedrStreamLoadingId(null);
          }}
          onPlaybackStarted={() => {
            // Stage 1 and stage 2 both end only when the browser actually
            // starts playback. A fast stream therefore removes the spinner
            // immediately, while a slow stream keeps it visible.
            setSeedrStreamLoadingId(null);
          }}
          isMinimized={isPlayerMinimized}
          onToggleMinimize={() => setIsPlayerMinimized(!isPlayerMinimized)}
        />
        </Suspense>
      )}

      {/* Mobile Bottom Navigation */}
      <MobileNav vm={vm} />

      {/* Modals */}
      <AppModals vm={vm} />
      <SeedrOnboardingModal vm={vm} />
    </div>
  );
}