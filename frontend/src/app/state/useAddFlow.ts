import { useEffect, useCallback } from 'react';
import { api } from '../../api/client.ts';
import { dispatchBrowserNotification, playNotificationSound } from '../../utils/notifications.ts';
import { useFileExplorerState } from './useFileExplorerState.ts';
import { useLibraryDataState } from './useLibraryDataState.ts';
import { useSeedrState } from './useSeedrState.ts';
import { useSeedrFolderGroups } from './useSeedrFolderGroups.ts';
import { useTransferRefs } from './useTransferRefs.ts';
import { useTransferPolling } from './useTransferPolling.ts';
import { useAppShellState } from './useAppShellState.ts';
import { useSeedrConnectionState } from './useSeedrConnectionState.ts';
import { useSeedrLibrary } from './useSeedrLibrary.ts';
import { useAddMagnetOpeners } from './useAddMagnetOpeners.ts';

export function useAddFlow({ torrents, setFiles, setStorageStats, setNotifications, setTorrents, setActivityLogs, activityStorageKey, activeUser, files, prevTorrentStates, pendingTransferStates, currentFolder, seedrPrepareGenerationRef, seedrNotice, seedrPrepareWaiters, setSeedrNotice, setSeedrAddBlockedNotice, setSeedrQuota, setSeedrInsufficientSpacePrompt, seedrNoticeStorageKey, setSeedrFolderContentsCache, selectedSeedrFolderId, setSeedrFiles, setSeedrFolderContentsLoading, setSeedrLibraryFolders, setActiveSeedrFolderOpen, seedrDownloadActive, seedrConnected, setSeedrConnectError, setSeedrOnboardingOpen, forgetSeedrFolders, rememberSeedrTorrentName, setActiveTab, loadSeedrLibrary }: Pick<ReturnType<typeof useLibraryDataState>, 'torrents' | 'setFiles' | 'setStorageStats' | 'setNotifications' | 'setTorrents' | 'setActivityLogs' | 'activityStorageKey' | 'activeUser' | 'files'> & Pick<ReturnType<typeof useTransferRefs>, 'prevTorrentStates' | 'pendingTransferStates'> & Pick<ReturnType<typeof useFileExplorerState>, 'currentFolder'> & Pick<ReturnType<typeof useSeedrState>, 'seedrPrepareGenerationRef' | 'seedrNotice' | 'seedrPrepareWaiters' | 'setSeedrNotice' | 'setSeedrAddBlockedNotice' | 'setSeedrQuota' | 'setSeedrInsufficientSpacePrompt' | 'seedrNoticeStorageKey' | 'setSeedrFolderContentsCache' | 'selectedSeedrFolderId' | 'setSeedrFiles' | 'setSeedrFolderContentsLoading' | 'setSeedrLibraryFolders' | 'setActiveSeedrFolderOpen'> & Pick<ReturnType<typeof useAddMagnetOpeners>, 'seedrDownloadActive'> & Pick<ReturnType<typeof useSeedrConnectionState>, 'seedrConnected' | 'setSeedrConnectError' | 'setSeedrOnboardingOpen'> & Pick<ReturnType<typeof useSeedrFolderGroups>, 'forgetSeedrFolders' | 'rememberSeedrTorrentName'> & Pick<ReturnType<typeof useAppShellState>, 'setActiveTab'> & Pick<ReturnType<typeof useSeedrLibrary>, 'loadSeedrLibrary'>) {
  const { appendActivityLog } = useTransferPolling({ torrents, setFiles, setStorageStats, setNotifications, setTorrents, setActivityLogs, activityStorageKey, prevTorrentStates, pendingTransferStates, currentFolder });
  const handleSearchPrepare = useCallback(async (
    result: {
      title: string;
      size: number;
      infoHash?: string;
      magnetUrl?: string;
      downloadUrl?: string;
      sourceUrl?: string;
      infoUrl?: string;
      indexer?: string;
    },
    metadata?: {
      name: string;
      hash: string;
      files: { index: number; name: string; size: number; path: string; type: string; priority?: number }[];
      totalSize: number;
    }
  ): Promise<{ files: Array<{
    id: string;
    streamId?: string;
    name: string;
    size: number;
    folderId: string;
    folderPath: string;
  }>; deletedFolderIds: string[] }> => {
    const prepareGeneration = ++seedrPrepareGenerationRef.current;
    // Defer replacement until a valid magnet has been resolved and is ready to
    // submit. This prevents a bad/unresolvable selection from cancelling the
    // currently working Seedr task.
    const replacementTaskId = seedrDownloadActive ? seedrNotice?.taskId : null;

    if (!seedrConnected) {
      // Preparing a search result requires a personal Seedr connection.
      // Open the same connection dialog used by the header instead of
      // surfacing a JavaScript error to the user.
      setSeedrConnectError('');
      setSeedrOnboardingOpen(true);
      throw new Error('Connect your Seedr account first.'); 
    }

    if (prepareGeneration !== seedrPrepareGenerationRef.current) {
      throw new Error('Seedr preparation was replaced by a newer selection.');
    }

    let magnet = String(result.magnetUrl || result.downloadUrl || '').trim();
    if (!magnet.toLowerCase().startsWith('magnet:?')) {
      magnet = result.infoHash
        ? 'magnet:?xt=urn:btih:' + result.infoHash.trim()
        : '';
    }

    // Search results now load from listing pages without waiting for every
    // provider detail page. Resolve the magnet only when the user chooses
    // Prepare, keeping slow provider pages out of the initial search request.
    if (!magnet && result.infoUrl) {
      const resolved = await api.resolveSearchMagnet(result.infoUrl, result.indexer || '');
      magnet = String(resolved?.magnet || '').trim();
    }

    if (!magnet.toLowerCase().startsWith('magnet:?')) {
      throw new Error('This search result does not contain a usable magnet link.');
    }

    if (prepareGeneration !== seedrPrepareGenerationRef.current) {
      throw new Error('Seedr preparation was replaced by a newer selection.');
    }

    let resolvedMetadata = metadata;
    // Seedr can resolve metadata itself. When the search provider already
    // supplied a title and byte size, do not block Prepare on a separate
    // libtorrent/DHT metadata lookup that may hang on stale or weak swarms.
    if (!resolvedMetadata && !(Number(result.size) > 0 && String(result.title || '').trim())) {
      resolvedMetadata = await api.inspectMagnet(
        magnet,
        'Downloads',
        result.sourceUrl || '',
        ''
      );
    }

    const torrentName =
      String(resolvedMetadata?.name || '').trim() ||
      String(result.title || '').trim() ||
      'Torrent';
    const requiredBytes = Number(resolvedMetadata?.totalSize || result.size || 0);

    if (prepareGeneration !== seedrPrepareGenerationRef.current) {
      throw new Error('Seedr preparation was replaced by a newer selection.');
    }

    const prepared = await api.prepareSeedrMagnet(
      magnet,
      requiredBytes,
      torrentName,
      replacementTaskId == null ? undefined : replacementTaskId
    );

    // The backend is authoritative for task replacement and also catches a
    // stale task left behind after a page refresh. Reject the older UI waiter
    // so its card stops spinning, without treating that cancellation as an
    // error for the newly selected torrent.
    const cancelledTaskIds = new Set<string>(
      ((Array.isArray(prepared?.cancelledTasks) ? prepared.cancelledTasks : []) as any[])
        .map((task: any) => String(task?.taskId ?? task?.task_id ?? task?.id ?? '').trim())
        .filter(Boolean)
    );
    for (const cancelledTaskId of cancelledTaskIds) {
      const waiter = seedrPrepareWaiters.current[cancelledTaskId];
      if (!waiter) continue;
      delete seedrPrepareWaiters.current[cancelledTaskId];
      waiter.reject(new Error('Seedr preparation was cancelled by another selection.'));
    }
    if (seedrNotice?.taskId != null && cancelledTaskIds.has(String(seedrNotice.taskId))) {
      setSeedrNotice(null);
    }

    // Prepare can automatically remove older completed Seedr folders to make
    // room for the new torrent. Remove those folders from every local cache
    // immediately so Search cannot keep showing stale Play/Download/Copy
    // buttons for files that no longer exist in Seedr.
    const deletedFolderIds = Array.from(new Set<string>(
      ((Array.isArray(prepared?.deletedFolders) ? prepared.deletedFolders : []) as any[])
        .map((folder: any) => String(folder?.folder_id ?? folder?.folderId ?? folder?.id ?? '').trim())
        .filter(Boolean)
    ));

    if (deletedFolderIds.length > 0) {
      forgetSeedrFolders(deletedFolderIds);
    }

    const taskId = prepared?.seedrTaskId;
    if (taskId == null || taskId === '') {
      throw new Error('Seedr accepted the request but did not return a task id.');
    }

    const taskKey = String(taskId);
    const waitForCompletion = new Promise<{ files: Array<{
      id: string;
      streamId?: string;
      name: string;
      size: number;
      folderId: string;
      folderPath: string;
    }> }>((resolve, reject) => {
      seedrPrepareWaiters.current[taskKey] = { resolve, reject };
    });

    const initialName = torrentName || String(prepared.seedrFolderName || '').trim() || 'Seedr download';
    setSeedrNotice({
      taskId,
      name: initialName,
      folderName: '',
      folderId: String(prepared.seedrFolderId || '').trim(),
      status: 'waiting',
      progress: 0,
      downloadUrl: null,
      files: [],
      seedrReply: 'Seedr accepted the torrent. Preparing download…',
    });

    const completed = await waitForCompletion;
    return {
      ...completed,
      deletedFolderIds,
    };
  }, [
    seedrConnected,
    seedrDownloadActive,
    seedrNotice,
    rememberSeedrTorrentName,
    forgetSeedrFolders
  ]);
  const handleSearchAdd = async (
    source: string,
    size: number,
    title: string,
    infoHash?: string,
    sourceUrl?: string,
    descriptorUrl?: string,
    metadata?: {
      name: string;
      hash: string;
      files: { index: number; name: string; size: number; path: string; type: string; priority?: number }[];
      totalSize: number;
    }
  ) => {
    const trimmedSource = source.trim();
    const seedrSource =
      source.toLowerCase().startsWith('magnet:?')
        ? source
        : infoHash
          ? `magnet:?xt=urn:btih:${infoHash.trim()}`
          : trimmedSource;

    // Search-result Add is a direct Seedr action. Do not open the manual
    // magnet modal and do not ask the user to paste the magnet again.
    if (!seedrSource) {
      setSeedrAddBlockedNotice('This search result does not contain a usable magnet link.');
      setActiveTab('search');
      window.setTimeout(() => setSeedrAddBlockedNotice(null), 5000);
      return;
    }

    // Search results use metadata before starting Seedr. The search panel
    // may already have this cached from its background prefetch.
    let resolvedMetadata = metadata;
    if (!resolvedMetadata) {
      try {
        resolvedMetadata = await api.inspectMagnet(
          seedrSource,
          'Downloads',
          sourceUrl || '',
          descriptorUrl || ''
        );
      } catch (error: any) {
        setSeedrAddBlockedNotice(error?.message || 'Could not resolve torrent metadata.');
        setActiveTab('search');
        window.setTimeout(() => setSeedrAddBlockedNotice(null), 5000);
        return;
      }
    }

    // Seedr receives the original search magnet unchanged. Metadata is used
    // only to make the transfer name available immediately.
    const torrentName =
      String(resolvedMetadata?.name || '').trim() ||
      String(title || '').trim() ||
      'Torrent';

    await handleAddMagnet(
      seedrSource,
      'video',
      undefined,
      undefined,
      infoHash || resolvedMetadata?.hash || undefined,
      'seedr',
      undefined,
      undefined,
      torrentName,
      Number(resolvedMetadata?.totalSize || size || 0)
    );
  };
  const handleAddMagnet = async (
    magnet: string,
    category: string,
    selectedFiles?: number[],
    manifest?: { index?: number; name: string; size: number; priority: number }[],
    existingHash?: string,
    forceBackend?: 'seedr' | 'qbittorrent',
    selectedNames?: string[],
    seedrTaskId?: number | string,
    torrentName?: string,
    requiredBytes?: number
  ) => {
    try {
      if (seedrDownloadActive && forceBackend !== 'qbittorrent') {
        const error = new Error(
          'A Seedr download is already in progress. Free Seedr accounts allow one parallel download. Wait for it to finish before adding another magnet link.'
        );
        (error as any).code = 'SEEDR_PARALLEL_DOWNLOAD_LIMIT';
        throw error;
      }

      // Pre-check Seedr quota before creating the task. Seedr can reject an
      // over-quota torrent with a provider-specific 413 reason, so relying
      // only on the provider response made the warning inconsistent.
      if (forceBackend !== 'qbittorrent') {
        let required = Number(requiredBytes || 0);
        if (!required && Array.isArray(manifest)) {
          required = manifest
            .filter(file => Number(file.priority || 0) > 0)
            .reduce((sum, file) => sum + Math.max(0, Number(file.size || 0)), 0);
        }

        if (required > 0) {
          try {
            const quota = await api.getSeedrQuota();
            setSeedrQuota({
              maxSpace: quota.maxSpace,
              usedSpace: quota.usedSpace,
              remainingSpace: quota.remainingSpace,
            });

            if (quota.remainingSpace < required) {
              setActiveTab('search');
              setSeedrInsufficientSpacePrompt({
                requiredBytes: required,
                remainingBytes: quota.remainingSpace,
                magnet,
                category,
                selectedFiles,
                manifest,
                existingHash,
              });
              return;
            }
          } catch {
            // If quota lookup is temporarily unavailable, let Seedr make the
            // authoritative decision below rather than blocking the add.
          }
        }
      }

      const result = await api.addMagnet(
        magnet,
        category,
        selectedFiles,
        manifest,
        existingHash,
        forceBackend,
        selectedNames,
        seedrTaskId,
        torrentName
      );
      if (result.backend === 'seedr') {
        const initialTorrentName = String(torrentName || '').trim();
        const returnedFolderId = String((result as any).seedrFolderId || (result as any).seedrResponse?.folder_id || '').trim();
        if (returnedFolderId && initialTorrentName) {
          rememberSeedrTorrentName(returnedFolderId, initialTorrentName);
        }

        setSeedrNotice({
          taskId: result.seedrTaskId ?? null,
          folderId: returnedFolderId,
          name: String(torrentName || '').trim() || (() => {
            const response: any = result.seedrResponse;
            const responseName = String(
              response?.name ??
              response?.task?.name ??
              response?.title ??
              ''
            ).trim();
            if (responseName) return responseName;

            const selectedManifest = (manifest || []).filter(file => Number(file.priority || 0) > 0);
            if (selectedManifest.length === 1) return selectedManifest[0].name;
            if (selectedManifest.length > 1) {
              return selectedManifest[0].name + ` + ${selectedManifest.length - 1} more`;
            }

            return 'Waiting for torrent name…';
          })(),
          folderName: '',
          status: 'waiting',
          progress: 0,
          downloadUrl: null,
          // Only the files selected in the manifest are represented in the
          // pending UI. The backend applies the Seedr unwanted-file bitmap
          // immediately after creating the task; no pause/resume is used.
          files: (manifest || [])            .map((file, index) => ({ file, index }))
            .filter(({ file }) => Number(file.priority || 0) > 0)
            .map(({ file, index }) => ({
              id: `pending-${result.seedrTaskId ?? 'task'}-${index}`,
              name: file.name,              size: Number(file.size || 0),
              folderId: '__pending__',
              folderPath: '/Currently Downloading',
              url: null,
              available: false,
            })),
          seedrReply: (() => {
            const response: any = result.seedrResponse;
            const state = response?.state ?? response?.task?.state ?? response?.status ?? response?.task?.status;
            return state ? `Seedr replied: ${String(state)}` : 'Seedr replied: task accepted';
          })(),
          selectionApplied: Boolean((result as any).selectionApplied),
          selectionError: (result as any).selectionError || null,
        });;
      } else {
        setSeedrNotice(null);
      }
      if (result.backend === 'seedr') {
        const loggedName =
          String(torrentName || '').trim() ||
          String(result.seedrResponse?.name || result.seedrResponse?.task?.name || '').trim() ||
          'Torrent';

        const taskId = result.seedrTaskId ?? result.seedrResponse?.task_id ?? result.seedrResponse?.id ?? '';
        const folderId = result.seedrFolderId ?? result.seedrResponse?.folder_id ?? result.seedrResponse?.task?.folder_id ?? '';

        appendActivityLog({
          id: `seedr-add-${taskId || Date.now()}-${Date.now()}`,
          timestamp: Date.now(),
          type: 'torrent',
          userName: activeUser?.name || 'Seedr User',
          userId: activeUser?.id || 'seedr-user',
          action: 'Torrent added to Seedr',
          details: `${loggedName}${taskId ? ` • Task ${taskId}` : ''}${folderId ? ` • Folder ${folderId}` : ''} • Auto-delete in 2 hours`,
          status: 'success'
        });
      }

      // The add response is the important operation. Refresh secondary UI
      // state in the background so the Add button does not stay blocked on
      // extra qBittorrent/Seedr requests.
      void api.getTorrents()
        .then(setTorrents)
        .catch((refreshError) =>
          console.warn('Torrent added, but transfers could not be refreshed yet:', refreshError)
        );

      void api.getStorageStats()
        .then(setStorageStats)
        .catch((refreshError) =>
          console.warn('Torrent added, but storage stats could not be refreshed yet:', refreshError)
        );

      setActiveTab('files');
    } catch (error: any) {
      if (error?.code === 'SEEDR_INSUFFICIENT_SPACE') {
        let required = Number(error.requiredBytes || requiredBytes || 0);
        if (!required && Array.isArray(manifest)) {
          required = manifest
            .filter(file => Number(file.priority || 0) > 0)
            .reduce((sum, file) => sum + Math.max(0, Number(file.size || 0)), 0);
        }

        let remaining = Number(error.remainingSpace || 0);
        if (!remaining) {
          try {
            const quota = await api.getSeedrQuota();
            remaining = Number(quota.remainingSpace || 0);
            setSeedrQuota({
              maxSpace: Number(quota.maxSpace || 0),
              usedSpace: Number(quota.usedSpace || 0),
              remainingSpace: remaining,
            });
          } catch {
            // Keep the provider error visible even if quota refresh fails.
          }
        }

        setActiveTab('search');
        setSeedrInsufficientSpacePrompt({
          requiredBytes: required,
          remainingBytes: remaining,
          magnet,
          category,
          selectedFiles,
          manifest,
          existingHash,
        });
        return;
      }
      throw error;
    }
  };
  useEffect(() => {
    try {
      if (seedrNotice?.taskId != null && seedrNotice.status !== 'completed') {
        window.localStorage.setItem(seedrNoticeStorageKey, JSON.stringify(seedrNotice));
      } else {
        window.localStorage.removeItem(seedrNoticeStorageKey);
      }
    } catch {
      // Local storage may be unavailable in restricted browser contexts.
    }
  }, [seedrNotice]);
  // Completed Seedr notices are only a short-lived confirmation. Keep the
  // transfer screen clean by removing the card automatically after 3 seconds.
  useEffect(() => {
    if (!seedrNotice?.taskId || seedrNotice.status !== 'completed') return;

    const timeoutId = window.setTimeout(() => {
      setSeedrNotice(null);
    }, 8000);

    return () => window.clearTimeout(timeoutId);
  }, [seedrNotice?.taskId, seedrNotice?.status]);
  useEffect(() => {
    if (!seedrNotice?.taskId || seedrNotice.status === 'completed') return;

    let active = true;
    let timeoutId: number | null = null;

    const scheduleNextPoll = (delayMs: number) => {
      if (!active) return;
      timeoutId = window.setTimeout(poll, delayMs);
    };

    const applyProgress = (result: {
      status: 'waiting' | 'downloading' | 'completed' | 'not_found';
      progress: number;
      name?: string;
      folderId?: string;
    }) => {
      const progress = Math.max(0, Math.min(100, Number(result.progress) || 0));
      const completed = result.status === 'completed';

      setSeedrNotice(prev => {
        if (!prev) return null;

        const canonicalName = String(prev.name || '').trim() || String(result.name || '').trim();
        const resolvedFolderId = String(result.folderId || prev.folderId || '').trim();

        if (
          resolvedFolderId &&
          canonicalName &&
          canonicalName !== 'Waiting for torrent name…' &&
          canonicalName !== 'Waiting for Seedr metadata…'
        ) {
          rememberSeedrTorrentName(resolvedFolderId, canonicalName);
        }

        return {
          ...prev,
          name: canonicalName,
          folderId: resolvedFolderId,
          // Keep the polling effect alive long enough to fetch the completed
          // task details and promote the folder into the library. Marking the
          // notice "completed" here causes React to tear down this effect
          // immediately, which can abort the rest of the completion flow.
          status: completed ? 'downloading' : result.status,
          progress: completed ? 100 : progress,
        };
      });

      return completed;
    };

    const poll = async () => {
      if (!active) return;

      try {
        // This endpoint only asks Seedr for task state/progress, so it is much
        // faster than loading task contents, folder names, and file URLs.
        const progressResult = await api.getSeedrTaskProgress(seedrNotice.taskId!);
        if (!active) return;

        if (progressResult.status === 'not_found') {
          const waiterKey = String(seedrNotice.taskId);
          const waiter = seedrPrepareWaiters.current[waiterKey];
          if (waiter) {
            delete seedrPrepareWaiters.current[waiterKey];
            waiter.reject(new Error('Seedr could not find the loading task.'));
          }
          setSeedrNotice(null);
          setSeedrAddBlockedNotice(null);
          try {
            window.localStorage.removeItem(seedrNoticeStorageKey);
          } catch {}
          return;
        }

        const completed = applyProgress(progressResult);

        if (!completed) {
          // Poll frequently so the visible progress bar moves as soon as Seedr
          // reports a newer value.
          scheduleNextPoll(progressResult.status === 'waiting' ? 10000 : 4000);
          return;
        }

        // Only when complete do we make the heavier request for the final
        // files/download URLs before promoting the task into the library.
        const result = await api.getSeedrTask(seedrNotice.taskId!);
        if (!active) return;

        setSeedrNotice(prev => {
          if (!prev) return null;

          const resolvedFolderId = String(
            (result as any).folderId ||
            progressResult.folderId ||
            prev.folderId ||
            ''
          ).trim();
          const canonicalName = String(
            prev.name ||
            (result as any).name ||
            progressResult.name ||
            ''
          ).trim();

          if (
            resolvedFolderId &&
            canonicalName &&
            canonicalName !== 'Waiting for torrent name…' &&
            canonicalName !== 'Waiting for Seedr metadata…'
          ) {
            rememberSeedrTorrentName(resolvedFolderId, canonicalName);
          }

          return {
            ...prev,
            name: canonicalName,
            folderName: '',
            folderId: resolvedFolderId,
            // Keep the active library card mounted until the completed folder
            // has been inserted into seedrLibraryFolders below. Otherwise the
            // card can disappear for a render while Seedr's library catches up.
            status: 'downloading',
            progress: 100,
            downloadUrl: result.downloadUrl,
            files: Array.isArray(result.files) && result.files.length > 0 ? result.files : prev.files,
          };
        });

        const completedFolderId = String(
          (result as any).folderId ||
          (Array.isArray((result as any).files)
            ? (result as any).files.find((file: any) => String(file?.folderId || '').trim())?.folderId            : '') ||
          progressResult.folderId ||
          seedrNotice.folderId ||
          ''
        ).trim();
        const completedTorrentName = String(
          seedrNotice.name ||
          (result as any).name ||
          progressResult.name ||
          ''
        ).trim();

        const resolvePrepareWaiter = (files: Array<{
          id: string;
          streamId?: string;
          name: string;
          size: number;
          folderId: string;
          folderPath: string;
        }>) => {
          const waiterKey = String(seedrNotice.taskId);
          const waiter = seedrPrepareWaiters.current[waiterKey];
          if (!waiter) return;
          delete seedrPrepareWaiters.current[waiterKey];
          waiter.resolve({ files });
        };

        const refreshCompletedLibrary = async () => {
          // Seedr can report a task as complete before the new folder appears
          // in the library tree. Add the completed folder to the UI immediately
          // from the completed task/folder response, then keep reconciling with
          // the real Seedr library until it becomes visible there too.
          let eagerFiles: Array<{
            id: string;
            streamId?: string;
            name: string;
            size: number;
            folderId: string;
            folderPath: string;
          }> = [];

          let eagerFolderId = completedFolderId;

          if (completedFolderId) {
            try {
              const contents = await api.getSeedrFolderContents(completedFolderId);
              eagerFiles = contents.files.map(file => ({
                id: file.id,
                streamId: file.streamId,
                name: file.name,
                size: Number(file.size) || 0,
                folderId: file.folderId || completedFolderId,
                folderPath: '/Torrent Studio/' + (completedTorrentName || 'Downloads'),
              }));

              if (eagerFiles.length > 0) {
                setSeedrFolderContentsCache(prev => ({
                  ...prev,
                  [completedFolderId]: eagerFiles,
                }));
                if (selectedSeedrFolderId === completedFolderId) {
                  setSeedrFiles(eagerFiles);
                  setSeedrFolderContentsLoading(false);
                }
              }
            } catch (error) {
              console.warn('Completed Seedr folder is not visible yet:', error);
            }

            // Show the completed folder immediately even when the Seedr library
            // index is still lagging behind the task completion.
            const eagerSize = eagerFiles.reduce((sum, file) => sum + Number(file.size || 0), 0);
            const eagerName = completedTorrentName || 'Completed Seedr download';
            setSeedrLibraryFolders(prev => {
              const exists = prev.some(folder => String(folder.folderId || folder.id) === completedFolderId);
              if (exists) return prev;

              return [
                {
                  id: completedFolderId,
                  folderId: completedFolderId,
                  name: eagerName,
                  path: '/Torrent Studio/' + eagerName,
                  filesCount: eagerFiles.length || 1,
                  totalSize: eagerSize || Number((result as any)?.size || 0),
                  folderCount: 0,
                  active: false,
                  progress: 100,
                },
                ...prev,
              ];
            });

            // The completed folder is now present in the UI state. Only now
            // mark the transfer notice completed, so React cannot remove the
            // active card before the new folder has been mounted.
            setSeedrNotice(prev => (
              prev ? { ...prev, status: 'completed', progress: 100 } : null
            ));

            if (eagerFiles.length > 0) {
              resolvePrepareWaiter(eagerFiles);
            }
          }

          for (let attempt = 0; attempt < 12; attempt += 1) {
            const refreshed = await loadSeedrLibrary(true);

            // loadSeedrLibrary replaces the folder array with the latest API
            // response. Preserve our eager completed folder if Seedr's index is
            // still catching up.
            if (eagerFolderId) {
              const folderIdForMerge = eagerFolderId;
              const mergeName = completedTorrentName || 'Completed Seedr download';
              setSeedrLibraryFolders(prev => {
                const exists = prev.some(folder => String(folder.folderId || folder.id) === folderIdForMerge);
                if (exists) return prev;

                const mergeSize = eagerFiles.reduce((sum, file) => sum + Number(file.size || 0), 0);
                return [
                  {
                    id: folderIdForMerge,
                    folderId: folderIdForMerge,
                    name: mergeName,
                    path: '/Torrent Studio/' + mergeName,
                    filesCount: eagerFiles.length || 1,
                    totalSize: mergeSize,
                    folderCount: 0,
                    active: false,
                    progress: 100,
                  },
                  ...prev,
                ];
              });
            }

            const completedFolder = refreshed?.folders?.find(folder => {
              const folderId = String(folder.folderId || folder.id || '').trim();
              const folderName = String(folder.name || '').trim();
              return (
                (completedFolderId && folderId === completedFolderId) ||
                (!completedFolderId &&
                  completedTorrentName &&
                  folderName.toLowerCase() === completedTorrentName.toLowerCase())
              );
            });

            if (completedFolder) {
              const resolvedFolderId = String(
                completedFolder.folderId || completedFolder.id || completedFolderId || ''
              ).trim();

              // Once the real library index catches up, refresh its file rows too.
              if (resolvedFolderId) {
                try {
                  const contents = await api.getSeedrFolderContents(resolvedFolderId);
                  const mapped = contents.files.map(file => ({
                    id: file.id,
                    streamId: file.streamId,
                    name: file.name,
                    size: Number(file.size) || 0,
                    folderId: file.folderId || resolvedFolderId,
                    folderPath: completedFolder.path,
                  }));

                  setSeedrFolderContentsCache(prev => ({
                    ...prev,
                    [resolvedFolderId]: mapped,
                  }));

                  const waiterKey = String(seedrNotice.taskId);
                  const waiter = seedrPrepareWaiters.current[waiterKey];
                  if (waiter && mapped.length > 0) {
                    delete seedrPrepareWaiters.current[waiterKey];
                    waiter.resolve({ files: mapped });
                  }

                  if (selectedSeedrFolderId === resolvedFolderId) {
                    setSeedrFiles(mapped);
                    setSeedrFolderContentsLoading(false);
                  }
                } catch (error) {
                  console.warn('Failed to load completed Seedr file details:', error);
                }
              }

              break;
            }

            if (attempt < 11) {
              await new Promise(resolve => window.setTimeout(resolve, 1500));
            }
          }
        };

        void refreshCompletedLibrary();
        setActiveSeedrFolderOpen(false);

        const immediateFiles = Array.isArray((result as any).files)
          ? (result as any).files
              .filter((file: any) => String(file?.id || file?.streamId || '').trim())
              .map((file: any) => ({
                id: String(file.id || file.streamId),
                streamId: file.streamId ? String(file.streamId) : undefined,
                name: String(file.name || 'Seedr file'),
                size: Number(file.size || 0),
                folderId: String(file.folderId || completedFolderId || ''),
                folderPath: String(file.folderPath || '/Torrent Studio/' + (completedTorrentName || 'Downloads')),
              }))
          : [];

        if (immediateFiles.length > 0) {
          resolvePrepareWaiter(immediateFiles);
        }

        playNotificationSound();
        dispatchBrowserNotification(
          `Ready: ${completedTorrentName || 'Seedr download'}`,
          'Your Seedr file is ready to play, download, or copy its link.'
        );

      } catch {
        scheduleNextPoll(2500);
      }
    };

    void poll();

    return () => {
      active = false;
      if (timeoutId !== null) window.clearTimeout(timeoutId);
    };
  }, [seedrNotice?.taskId, seedrNotice?.status, loadSeedrLibrary, rememberSeedrTorrentName]);

  return {
    handleSearchPrepare,
    handleAddMagnet,
  };
}
