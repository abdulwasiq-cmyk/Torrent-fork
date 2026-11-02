import { useEffect, useCallback, useMemo } from 'react';
import { api } from '../api/client.ts';
import { useAppDialogState } from './state/useAppDialogState.ts';
import { useFileExplorerState } from './state/useFileExplorerState.ts';
import { useLibraryDataState } from './state/useLibraryDataState.ts';
import { useSeedrState } from './state/useSeedrState.ts';
import { useSeedrFolderGroups } from './state/useSeedrFolderGroups.ts';
import { useSeedrFileActions } from './state/useSeedrFileActions.ts';
import { useTransferRefs } from './state/useTransferRefs.ts';
import { useTorrentActions } from './state/useTorrentActions.ts';
import { useAppShellState } from './state/useAppShellState.ts';
import { useSeedrConnectionState } from './state/useSeedrConnectionState.ts';
import { useLibraryActions } from './state/useLibraryActions.ts';
import { useSeedrLibrary } from './state/useSeedrLibrary.ts';
import { useLibraryLoading } from './state/useLibraryLoading.ts';
import { useAddMagnetOpeners } from './state/useAddMagnetOpeners.ts';
import { useAddFlow } from './state/useAddFlow.ts';

export function useAppModel() {
  const { productWelcomeOpen, setProductWelcomeOpen, seedrOnboardingOpen, setSeedrOnboardingOpen, seedrOnboardingSeenKey, seedrConnected, setSeedrConnected, seedrSessionReady, setSeedrSessionReady, seedrPat, setSeedrPat, seedrPatSubmitting, setSeedrPatSubmitting, seedrConnectError, setSeedrConnectError, seedrConfigured, setSeedrConfigured } = useSeedrConnectionState();
  const markSeedrOnboardingSeen = useCallback(() => {
    try {
      window.localStorage.setItem(seedrOnboardingSeenKey, '1');
    } catch {
      // Storage can be unavailable in private/sandboxed contexts.
    }
    setSeedrOnboardingOpen(false);
  }, []);
  useEffect(() => {
    let stopped = false;
    void api.getSeedrSession()
      .then(session => {
        if (stopped) return;
        setSeedrSessionReady(true);
        if (session.connected) {
          setSeedrConnected(true);
          setSeedrConfigured(true);
        }
      })
      .catch(() => {
        if (!stopped) setSeedrSessionReady(true);
      });

    return () => {
      stopped = true;
    };
  }, [markSeedrOnboardingSeen]);
  const connectSeedrWithPat = useCallback(async () => {
    const pat = seedrPat.trim();
    if (!pat) {
      setSeedrConnectError('Paste your Seedr token.');
      return;
    }

    setSeedrPatSubmitting(true);
    setSeedrConnectError('');
    try {
      const result = await api.connectSeedrPat(pat);
      if (!result.connected) {
        throw new Error('Seedr did not accept the Personal Access Token.');
      }
      setSeedrPat('');
      setSeedrConnected(true);
      setSeedrConfigured(true);
    } catch (error: any) {
      setSeedrConnectError(
        String(error?.message || 'Seedr rejected the Personal Access Token.')
      );
    } finally {
      setSeedrPatSubmitting(false);
    }
  }, [seedrPat]);
  const { activeTab, setActiveTab, backgroundMetadataJob, setBackgroundMetadataJob, initialSourceUrl, setInitialSourceUrl, initialDescriptorUrl, setInitialDescriptorUrl, theme, setTheme } = useAppShellState();
  const { torrents, setTorrents, files, setFiles, folders, setFolders, users, setUsers, activeUser, setActiveUser, storageStats, setStorageStats, activityStorageKey, setActivityLogs, notifications, setNotifications, cleanupSettings, setCleanupSettings } = useLibraryDataState();
  const { seedrNoticeStorageKey, seedrPrepareWaiters, seedrNotice, setSeedrNotice, setSeedrFiles, seedrDeletedFolderIds, setSeedrDeletedFolderIds, seedrLibraryRoot, setSeedrLibraryRoot, seedrLibraryFolders, setSeedrLibraryFolders, setSeedrFolderContentsLoading, seedrPrefetchLoading, setSeedrPrefetchLoading, seedrFolderContentsCache, setSeedrFolderContentsCache, seedrFolderContentsRequests, seedrQuota, setSeedrQuota, seedrQuotaError, setSeedrQuotaError, seedrLoading, setSeedrLoading, seedrError, setSeedrError, seedrDeleteNotice, setSeedrDeleteNotice, setCopiedSeedrFileId, seedrAddBlockedNotice, setSeedrAddBlockedNotice, seedrInsufficientSpacePrompt, setSeedrInsufficientSpacePrompt, seedrStreamLoadingId, setSeedrStreamLoadingId, isCancellingSeedr, setIsCancellingSeedr, seedrPrepareGenerationRef, setActiveSeedrFolderOpen, selectedSeedrFolderId, setSelectedSeedrFolderId, seedrTorrentNamesKey, seedrTorrentNames, setSeedrTorrentNames } = useSeedrState();
  const { rememberSeedrTorrentName, forgetSeedrFolders, toSeedrStorageFile, seedrAllPrefetchedFiles, seedrFolderGroups } = useSeedrFolderGroups({ setSeedrTorrentNames, seedrTorrentNamesKey, setSeedrDeletedFolderIds, setSeedrFolderContentsCache, setSeedrLibraryFolders, setSeedrFiles, setSelectedSeedrFolderId, seedrFolderContentsCache, seedrLibraryFolders, seedrTorrentNames, seedrNotice, selectedSeedrFolderId });
  const { currentFolder, setCurrentFolder, fileSearch, setFileSearch, fileTypeFilter, setFileTypeFilter } = useFileExplorerState();
  // The Files tab is reserved for completed/stored files and folders.
  // Active qBittorrent downloads belong only in the Transfers tab.
  const visibleFiles = useMemo(() => {
    const source = currentFolder === '/' && seedrAllPrefetchedFiles.length > 0
      ? seedrAllPrefetchedFiles.map(toSeedrStorageFile)
      : files;

    const search = fileSearch.trim().toLowerCase();
    const filtered = source.filter(file => {
      const matchesType = fileTypeFilter === 'all' || file.type === fileTypeFilter;
      const matchesSearch = !search || file.name.toLowerCase().includes(search);
      return matchesType && matchesSearch;
    });

    // Keep root/"outside folder" files deterministic and easy to scan.
    if (currentFolder !== '/' || seedrAllPrefetchedFiles.length === 0) return filtered;

    return [...filtered].sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' })
    );
  }, [currentFolder, seedrAllPrefetchedFiles, files, toSeedrStorageFile, fileTypeFilter, fileSearch]);
  const { isAddMagnetOpen, setIsAddMagnetOpen, initialMagnet, setInitialMagnet, prioTorrent, setPrioTorrent, isCleanupOpen, setIsCleanupOpen, isNotificationsOpen, setIsNotificationsOpen, feedbackOpen, setFeedbackOpen, feedbackType, setFeedbackType, feedbackRating, setFeedbackRating, feedbackMessage, setFeedbackMessage, feedbackName, setFeedbackName, feedbackSubmitting, setFeedbackSubmitting, feedbackSuccess, setFeedbackSuccess, feedbackError, setFeedbackError, shareFolder, setShareFolder, isCreateFolderOpen, setIsCreateFolderOpen, moveFile, setMoveFile, renameItem, setRenameItem, deleteTarget, setDeleteTarget, activeMediaFile, setActiveMediaFile, isPlayerMinimized, setIsPlayerMinimized } = useAppDialogState();
  const { prevTorrentStates, pendingTransferStates } = useTransferRefs();
  // Persist navigation so a browser refresh returns to the same page.
  useEffect(() => {
    try {
      window.localStorage.setItem('seedflow_active_tab', activeTab);
    } catch {
      // Storage may be unavailable in restricted browser contexts.
    }
  }, [activeTab]);
  useEffect(() => {
    try {
      if (selectedSeedrFolderId) {
        window.localStorage.setItem('seedflow_seedr_folder', selectedSeedrFolderId);
      } else {
        window.localStorage.removeItem('seedflow_seedr_folder');
      }
    } catch {
      // Storage may be unavailable in restricted browser contexts.
    }
  }, [selectedSeedrFolderId]);
  // Keep the dark/dim theme preference in sync.
  useEffect(() => {
    try {
      window.localStorage.setItem('seedflow_theme', theme);
    } catch {}
    try {
      const root = document.documentElement;
      root.classList.remove('dark', 'dim');
      if (theme === 'dark') {
        root.classList.add('dark');
        root.style.backgroundColor = '#020617';
      } else {
        root.classList.add('dark');
        root.style.backgroundColor = '#0f172a';
      }
    } catch {}
  }, [theme]);
  const { seedrDownloadActive, openMetadataSelector, openAddMagnet } = useAddMagnetOpeners({ seedrNotice, setSeedrAddBlockedNotice, setInitialMagnet, setIsAddMagnetOpen, setInitialSourceUrl, setInitialDescriptorUrl, setBackgroundMetadataJob, setActiveTab });
  useLibraryLoading({ setUsers, setActiveUser, setStorageStats, setFolders, activityStorageKey, setActivityLogs, setNotifications, setCleanupSettings, folders, setFiles, currentFolder, fileSearch, fileTypeFilter, activeTab });
  const { loadSeedrLibrary } = useSeedrLibrary({ seedrConnected, setSeedrConfigured, setSeedrLoading, setSeedrError, setSeedrQuotaError, setSeedrQuota, seedrNotice, setSeedrNotice, setSeedrLibraryRoot, setSeedrLibraryFolders, setSeedrDeletedFolderIds, setSeedrFolderContentsCache, setSeedrPrefetchLoading, seedrFolderContentsRequests, selectedSeedrFolderId, seedrFolderContentsCache, setSeedrFiles, setSeedrFolderContentsLoading, setSelectedSeedrFolderId, rememberSeedrTorrentName, seedrFolderGroups, activeTab });
  const { handleSearchPrepare, handleAddMagnet } = useAddFlow({ torrents, setFiles, setStorageStats, setNotifications, setTorrents, setActivityLogs, activityStorageKey, activeUser, files, prevTorrentStates, pendingTransferStates, currentFolder, seedrPrepareGenerationRef, seedrNotice, seedrPrepareWaiters, setSeedrNotice, setSeedrAddBlockedNotice, setSeedrQuota, setSeedrInsufficientSpacePrompt, seedrNoticeStorageKey, setSeedrFolderContentsCache, selectedSeedrFolderId, setSeedrFiles, setSeedrFolderContentsLoading, setSeedrLibraryFolders, setActiveSeedrFolderOpen, seedrDownloadActive, seedrConnected, setSeedrConnectError, setSeedrOnboardingOpen, forgetSeedrFolders, rememberSeedrTorrentName, setActiveTab, loadSeedrLibrary });
  const { handleCancelSeedrDownload, handleStreamSeedrFile, handleDeleteSeedrFile } = useSeedrFileActions({ seedrNotice, isCancellingSeedr, setIsCancellingSeedr, seedrPrepareWaiters, setSeedrNotice, setSeedrAddBlockedNotice, setSeedrError, setCopiedSeedrFileId, seedrFolderContentsCache, setSeedrStreamLoadingId, setSeedrFolderContentsCache, setSeedrDeleteNotice, setSeedrFiles, setSeedrLibraryFolders, setSeedrQuota, setSelectedSeedrFolderId, forgetSeedrFolders, seedrAllPrefetchedFiles, seedrFolderGroups, activeUser, setActiveMediaFile, setIsPlayerMinimized });
  const { handleUpdateFilePriority } = useTorrentActions({ activeUser, torrents, setTorrents, setActiveMediaFile, setIsPlayerMinimized, setDeleteTarget, pendingTransferStates });
  const { handleConfirmDelete, handleCreateFolder, handleMoveFile, handleRename, handleFolderShareSave, handleRunCleanup, submitFeedback, unreadNotifsCount, currentFolderPrefix } = useLibraryActions({ files, setFiles, setStorageStats, setTorrents, setFolders, activeUser, setActiveUser, activityStorageKey, setActivityLogs, torrents, notifications, setDeleteTarget, deleteTarget, feedbackMessage, setFeedbackError, setFeedbackSubmitting, setFeedbackSuccess, feedbackType, feedbackRating, feedbackName, setFeedbackMessage, setFeedbackName, setFeedbackRating, currentFolder });
  const visibleFolders = folders
    .filter(folder => folder.path !== '/' && folder.path.startsWith(currentFolderPrefix))
    .filter(folder => {
      const remainder = folder.path.slice(currentFolderPrefix.length);
      return remainder.length > 0 && !remainder.includes('/');
    });

  return {
    productWelcomeOpen,
    setProductWelcomeOpen,
    seedrOnboardingOpen,
    setSeedrOnboardingOpen,
    seedrConnected,
    seedrSessionReady,
    seedrPat,
    setSeedrPat,
    seedrPatSubmitting,
    seedrConnectError,
    setSeedrConnectError,
    connectSeedrWithPat,
    activeTab,
    setActiveTab,
    backgroundMetadataJob,
    setBackgroundMetadataJob,
    initialSourceUrl,
    setInitialSourceUrl,
    initialDescriptorUrl,
    setInitialDescriptorUrl,
    theme,
    setTheme,
    files,
    folders,
    users,
    activeUser,
    storageStats,
    notifications,
    setNotifications,
    cleanupSettings,
    setCleanupSettings,
    seedrNotice,
    seedrDeletedFolderIds,
    seedrLibraryRoot,
    seedrLibraryFolders,
    seedrPrefetchLoading,
    seedrConfigured,
    seedrQuota,
    seedrQuotaError,
    seedrLoading,
    seedrError,
    setSeedrError,
    seedrDeleteNotice,
    seedrAddBlockedNotice,
    seedrInsufficientSpacePrompt,
    setSeedrInsufficientSpacePrompt,
    seedrStreamLoadingId,
    setSeedrStreamLoadingId,
    isCancellingSeedr,
    seedrAllPrefetchedFiles,
    currentFolder,
    setCurrentFolder,
    fileSearch,
    setFileSearch,
    fileTypeFilter,
    setFileTypeFilter,
    visibleFiles,
    isAddMagnetOpen,
    setIsAddMagnetOpen,
    initialMagnet,
    setInitialMagnet,
    prioTorrent,
    setPrioTorrent,
    isCleanupOpen,
    setIsCleanupOpen,
    isNotificationsOpen,
    setIsNotificationsOpen,
    feedbackOpen,
    setFeedbackOpen,
    feedbackType,
    setFeedbackType,
    feedbackRating,
    setFeedbackRating,
    feedbackMessage,
    setFeedbackMessage,
    feedbackName,
    setFeedbackName,
    feedbackSubmitting,
    feedbackSuccess,
    setFeedbackSuccess,
    feedbackError,
    setFeedbackError,
    shareFolder,
    setShareFolder,
    isCreateFolderOpen,
    setIsCreateFolderOpen,
    moveFile,
    setMoveFile,
    renameItem,
    setRenameItem,
    deleteTarget,
    setDeleteTarget,
    activeMediaFile,
    setActiveMediaFile,
    isPlayerMinimized,
    setIsPlayerMinimized,
    seedrDownloadActive,
    openMetadataSelector,
    openAddMagnet,
    loadSeedrLibrary,
    handleSearchPrepare,
    handleAddMagnet,
    handleCancelSeedrDownload,
    handleUpdateFilePriority,
    handleStreamSeedrFile,
    handleDeleteSeedrFile,
    handleConfirmDelete,
    handleCreateFolder,
    handleMoveFile,
    handleRename,
    handleFolderShareSave,
    submitFeedback,
    handleRunCleanup,
    unreadNotifsCount,
    visibleFolders,
  };
}

export type PanelModel = ReturnType<typeof useAppModel>;
