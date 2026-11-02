import { useEffect, useCallback } from 'react';
import { api } from '../../api/client.ts';
import { useSeedrState } from './useSeedrState.ts';
import { useSeedrFolderGroups } from './useSeedrFolderGroups.ts';
import { useAppShellState } from './useAppShellState.ts';
import { useSeedrConnectionState } from './useSeedrConnectionState.ts';

export function useSeedrLibrary({ seedrConnected, setSeedrConfigured, setSeedrLoading, setSeedrError, setSeedrQuotaError, setSeedrQuota, seedrNotice, setSeedrNotice, setSeedrLibraryRoot, setSeedrLibraryFolders, setSeedrDeletedFolderIds, setSeedrFolderContentsCache, setSeedrPrefetchLoading, seedrFolderContentsRequests, selectedSeedrFolderId, seedrFolderContentsCache, setSeedrFiles, setSeedrFolderContentsLoading, setSelectedSeedrFolderId, rememberSeedrTorrentName, seedrFolderGroups, activeTab }: Pick<ReturnType<typeof useSeedrConnectionState>, 'seedrConnected' | 'setSeedrConfigured'> & Pick<ReturnType<typeof useSeedrState>, 'setSeedrLoading' | 'setSeedrError' | 'setSeedrQuotaError' | 'setSeedrQuota' | 'seedrNotice' | 'setSeedrNotice' | 'setSeedrLibraryRoot' | 'setSeedrLibraryFolders' | 'setSeedrDeletedFolderIds' | 'setSeedrFolderContentsCache' | 'setSeedrPrefetchLoading' | 'seedrFolderContentsRequests' | 'selectedSeedrFolderId' | 'seedrFolderContentsCache' | 'setSeedrFiles' | 'setSeedrFolderContentsLoading' | 'setSelectedSeedrFolderId'> & Pick<ReturnType<typeof useSeedrFolderGroups>, 'rememberSeedrTorrentName' | 'seedrFolderGroups'> & Pick<ReturnType<typeof useAppShellState>, 'activeTab'>) {
  const loadSeedrLibrary = useCallback(async (forceRefresh = false) => {
    if (!seedrConnected) return null;
    setSeedrLoading(true);
    setSeedrError(null);

    try {
      // Check authentication explicitly so the Library panel reports the
      // actual Seedr state instead of turning every failure into a generic
      // library error.
      try {
        const auth = await api.getSeedrAuthStatus();
        if (!auth.configured) {
          setSeedrError('SEEDR_TOKEN_MISSING: Seedr API token is not configured in Render.');
          setSeedrConfigured(false);
          setSeedrLoading(false);
          return null;
        }
        if (!auth.authenticated) {
          try {
            const diagnostic = await api.getSeedrTokenDiagnostic();
            const checks = diagnostic?.checks || {};
            const userCheck = checks.user || {};
            const tokenLabel = userCheck.ok
              ? 'TOKEN_PRESENT_AND_ACCEPTED_BY_SEEDR'
              : 'TOKEN_REJECTED_BY_SEEDR';
            const detail = userCheck.ok
              ? 'Seedr accepted the token through the account endpoint.'
              : 'Seedr rejected the token on the account endpoint.';
            setSeedrError(
              `${tokenLabel}: ${detail} [user=${userCheck.status ?? '?'}]`
            );
          } catch {
            setSeedrError(
              auth.code === 'SEEDR_TOKEN_REJECTED'
                ? 'SEEDR_TOKEN_REJECTED: Seedr rejected the configured API token.'
                : auth.code === 'SEEDR_LIBRARY_ACCESS_DENIED'
                  ? 'SEEDR_LIBRARY_ACCESS_DENIED: Seedr denied the library/auth operation.'
                  : `Seedr authentication check failed: ${auth.message || auth.code}`
            );
          }
          setSeedrConfigured(true);
          setSeedrLoading(false);
          return null;
        }
        setSeedrError(null);
      } catch (error: any) {
        const code = String(error?.code || '').trim();
        setSeedrError(
          code === 'SEEDR_TOKEN_REJECTED'
            ? 'SEEDR_TOKEN_REJECTED: Seedr rejected the configured API token.'
            : code === 'SEEDR_LIBRARY_ACCESS_DENIED'
              ? 'SEEDR_LIBRARY_ACCESS_DENIED: Seedr denied the library/auth operation.'
              : 'SEEDR_QUOTA_UNAVAILABLE: Seedr authentication status is temporarily unavailable.'
        );
        setSeedrLoading(false);
        return null;
      }

      // Keep the Seedr storage/quota cards populated independently of the
      // library metadata request. Quota is small and should never delay the
      // library UI or the download progress bar.
      void api.getSeedrQuota().then(quota => {
        if (!quota.configured) {
          setSeedrQuotaError('SEEDR_TOKEN_MISSING: Seedr API token is not configured in Render.');
          return;
        }        setSeedrQuotaError(null);
        setSeedrQuota({
          maxSpace: quota.maxSpace,          usedSpace: quota.usedSpace,
          remainingSpace: quota.remainingSpace,
        });
      }).catch((error: any) => {
        const code = String(error?.code || '').trim();
        const message =
          code === 'SEEDR_TOKEN_REJECTED'
            ? 'SEEDR_TOKEN_REJECTED: Seedr rejected the configured API token.'
            : code === 'SEEDR_LIBRARY_ACCESS_DENIED'
              ? 'SEEDR_LIBRARY_ACCESS_DENIED: Seedr denied access to account storage information.'
              : 'SEEDR_QUOTA_UNAVAILABLE: Seedr account storage information is unavailable right now.';
        setSeedrQuotaError(message);
      });

      // Refresh the active transfer progress independently of library
      // metadata. This request is intentionally tiny, so the progress bar can
      // move immediately instead of waiting for the library tree.
      const activeTaskId = seedrNotice?.taskId;
      if (activeTaskId && seedrNotice?.status !== 'completed') {
        void api.getSeedrTaskProgress(activeTaskId).then(progressResult => {
          if (progressResult.status === 'not_found') return;
          const progress = Math.max(0, Math.min(100, Number(progressResult.progress) || 0));
          const progressName = String(progressResult.name || '').trim();
          const progressFolderId = String(progressResult.folderId || '').trim();
          setSeedrNotice(prev => {
            if (!prev) return null;

            const canonicalName = String(prev.name || '').trim() || progressName;
            if (
              progressFolderId &&
              canonicalName &&
              canonicalName !== 'Waiting for torrent name…' &&
              canonicalName !== 'Waiting for Seedr metadata…'
            ) {
              rememberSeedrTorrentName(progressFolderId, canonicalName);
            }

            return {
              ...prev,
              name: canonicalName,
              folderId: progressFolderId || prev.folderId || '',
              status: progressResult.status,
              progress,
            };
          });
        }).catch(() => {
          // The normal task poll continues to provide progress updates.
        });
      }

      // Stage 1 — only the metadata required to paint the outer Seedr
      // Library immediately. Do not wait for quota or file rows.
      const result = await api.getSeedrLibrary(forceRefresh);

      setSeedrConfigured(result.configured);
      setSeedrLibraryRoot(result.root);
      setSeedrLibraryFolders(result.folders);
      setSeedrDeletedFolderIds(prev =>
        prev.filter(folderId =>
          result.folders.some(folder => String(folder.folderId || folder.id || '') === folderId)
        )
      );
      setSeedrLoading(false);

      // Stage 2 — immediately load the file rows for every library folder.
      // The old implementation only set seedrPrefetchLoading=true here and
      // waited for a folder click to call getSeedrFolderContents(). That left
      // the root Files view showing a permanent spinner until the user opened
      // a folder and came back. Populate the same cache used by the folder
      // view so the root page is complete on first load.
      const validFolderKeys = new Set(
        result.folders.map(folder => String(folder.folderId || folder.id))
      );
      setSeedrFolderContentsCache(prev =>
        Object.fromEntries(
          Object.entries(prev).filter(([key]) => validFolderKeys.has(key))
        )
      );

      if (result.folders.length === 0) {
        setSeedrPrefetchLoading(false);
      } else {
        setSeedrPrefetchLoading(true);

        void (async () => {
          const foldersToLoad = result.folders.filter(folder =>
            String(folder.folderId || folder.id).trim()
          );

          const loadedEntries: Record<string, Array<{
            id: string;
            streamId?: string;
            name: string;
            size: number;
            folderId: string;
            folderPath: string;
          }>> = {};

          // Keep the initial page responsive when a Seedr account contains
          // many folders, while still loading all folder contents without
          // requiring user navigation.
          const concurrency = 4;
          for (let start = 0; start < foldersToLoad.length; start += concurrency) {
            const batch = foldersToLoad.slice(start, start + concurrency);

            await Promise.all(batch.map(async folder => {
              const folderId = String(folder.folderId || folder.id).trim();
              if (!folderId) return;

              try {
                const existingRequest = seedrFolderContentsRequests.current[folderId];
                const request = existingRequest || (async () => {
                  const contents = await api.getSeedrFolderContents(folderId);
                  const folderPath = folder.path || '/Torrent Studio';
                  return contents.files.map(file => ({
                    id: file.id,
                    streamId: file.streamId,
                    name: file.name,
                    size: Number(file.size) || 0,
                    folderId: file.folderId || folderId,
                    folderPath,
                  }));
                })();

                seedrFolderContentsRequests.current[folderId] = request;
                const mapped = await request;
                loadedEntries[folderId] = mapped;
                setSeedrFolderContentsCache(prev => ({
                  ...prev,
                  [folderId]: mapped,
                }));
              } catch (error) {
                // A single inaccessible/still-indexing folder must not leave
                // the whole Files page in a permanent loading state. The
                // folder can still be retried by clicking it.
                console.warn('Failed to prefetch Seedr folder contents:', folderId, error);
              } finally {
                delete seedrFolderContentsRequests.current[folderId];
              }
            }));
          }

          setSeedrPrefetchLoading(false);
        })();
      }

      // Do not clear the existing file rows during refresh. React keeps the
      // current visible component intact while fresh internal details arrive.
      // The cache effect above swaps them in as soon as they are available.
      return result;
    } catch (error: any) {
      const code = String(error?.code || '').trim();
      const message =
        code === 'SEEDR_TOKEN_REJECTED'
          ? 'SEEDR_TOKEN_REJECTED: Seedr rejected the configured API token.'
          : code === 'SEEDR_LIBRARY_ACCESS_DENIED'
            ? 'SEEDR_LIBRARY_ACCESS_DENIED: Seedr denied access to the Seedr library.'
            : code === 'SEEDR_QUOTA_UNAVAILABLE'
              ? 'SEEDR_QUOTA_UNAVAILABLE: Seedr account storage information is unavailable right now.'
              : error?.message || 'Failed to refresh Seedr metadata';
      setSeedrError(message);
      setSeedrLoading(false);
      setSeedrPrefetchLoading(false);
      return null;
    }
  }, [seedrConnected, rememberSeedrTorrentName]);
  // Keep an opened folder synchronized with the background prefetch cache.
  // Changing the selected folder no longer reruns the entire library request.
  useEffect(() => {
    if (!selectedSeedrFolderId) return;

    const cached = seedrFolderContentsCache[selectedSeedrFolderId];
    if (!cached) return;

    setSeedrFiles(cached);
    setSeedrFolderContentsLoading(false);
  }, [selectedSeedrFolderId, seedrFolderContentsCache]);
  useEffect(() => {
    if (activeTab === 'files') loadSeedrLibrary();
  }, [activeTab, loadSeedrLibrary]);
  // Load Seedr library metadata once when a personal Seedr connection becomes
  // available so Search can immediately recognize already-prepared torrents.
  useEffect(() => {
    if (seedrConnected) void loadSeedrLibrary();
  }, [seedrConnected]);

  return {
    loadSeedrLibrary,
  };
}
