import { useState, useRef } from 'react';

export function useSeedrState() {
  type SeedrNotice = {
    taskId: number | string | null;
    name: string;
    folderName: string;
    folderId: string;
    status: 'waiting' | 'downloading' | 'completed' | 'not_found';
    progress: number;
    downloadUrl: string | null;
    files: Array<{
      id: string;
      name: string;
      size: number;
      folderId: string;
      folderPath: string;
      url: string | null;
      available?: boolean;
    }>;
    seedrReply: string;
    selectionApplied?: boolean;
    selectionError?: string | null;
  };
  const seedrNoticeStorageKey = 'seedflow_seedr_notice';
  const seedrPrepareWaiters = useRef<Record<string, {
    resolve: (value: { files: Array<{
      id: string;
      streamId?: string;
      name: string;
      size: number;
      folderId: string;
      folderPath: string;
    }> }) => void;
    reject: (reason?: unknown) => void;
  }>>({});
  const [seedrNotice, setSeedrNotice] = useState<SeedrNotice | null>(() => {
    try {
      const raw = window.localStorage.getItem(seedrNoticeStorageKey);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || parsed.taskId == null) return null;      return {        taskId: parsed.taskId,
        name: String(parsed.name || 'Seedr download'),
        folderName: String(parsed.folderName || ''),
        folderId: String(parsed.folderId || ''),
        status: parsed.status === 'completed' ? 'completed' : parsed.status === 'downloading' ? 'downloading' : 'waiting',
        progress: Math.max(0, Math.min(100, Number(parsed.progress) || 0)),
        downloadUrl: typeof parsed.downloadUrl === 'string' ? parsed.downloadUrl : null,
        files: Array.isArray(parsed.files) ? parsed.files : [],
        seedrReply: String(parsed.seedrReply || ''),
      };
    } catch {
      return null;
    }
  });
  const [seedrFiles, setSeedrFiles] = useState<Array<{ id: string; streamId?: string; name: string; size: number; folderId: string; folderPath: string }>>([]);
  const [seedrDeletedFolderIds, setSeedrDeletedFolderIds] = useState<string[]>([]);
  const [seedrLibraryRoot, setSeedrLibraryRoot] = useState<{
    id: string;
    folderId: string;
    name: string;
    path: string;
    filesCount: number;
    totalSize: number;
    folderCount: number;
  } | null>(null);
  const [seedrLibraryFolders, setSeedrLibraryFolders] = useState<Array<{
    id: string;
    folderId: string;
    name: string;
    path: string;
    filesCount: number;
    totalSize: number;
    folderCount: number;
    active?: boolean;
    progress?: number;
  }>>([]);
  const [seedrFolderContentsLoading, setSeedrFolderContentsLoading] = useState(false);
  const [seedrPrefetchLoading, setSeedrPrefetchLoading] = useState(false);
  const [seedrFolderContentsCache, setSeedrFolderContentsCache] = useState<Record<string, Array<{
    id: string;
    streamId?: string;
    name: string;
    size: number;
    folderId: string;
    folderPath: string;
  }>>>({});
  // Track background folder-content requests so clicking a folder while its
  // automatic prefetch is still running reuses the same promise instead of
  // issuing a duplicate API request.
  const seedrFolderContentsRequests = useRef<Record<string, Promise<Array<{
    id: string;
    streamId?: string;
    name: string;
    size: number;
    folderId: string;
    folderPath: string;
  }>>>>({});
  const [seedrQuota, setSeedrQuota] = useState<{ maxSpace: number; usedSpace: number; remainingSpace: number } | null>(null);
  const [seedrQuotaError, setSeedrQuotaError] = useState<string | null>(null);
  const [seedrLoading, setSeedrLoading] = useState(false);
  const [seedrError, setSeedrError] = useState<string | null>(null);
  const [seedrDeleteNotice, setSeedrDeleteNotice] = useState<string | null>(null);
  const [copiedSeedrFileId, setCopiedSeedrFileId] = useState<string | null>(null);
  const [seedrAddBlockedNotice, setSeedrAddBlockedNotice] = useState<string | null>(null);
  const [seedrInsufficientSpacePrompt, setSeedrInsufficientSpacePrompt] = useState<{
    requiredBytes: number;
    remainingBytes: number;
    magnet: string;
    category: string;
    selectedFiles?: number[];
    manifest?: { index?: number; name: string; size: number; priority: number }[];
    existingHash?: string;
  } | null>(null);
  // Two-stage Seedr playback UX: first show progress while resolving the
  // stream URL, then the player shows its own browser-loading state.
  const [seedrStreamLoadingId, setSeedrStreamLoadingId] = useState<string | null>(null);
  const [isCancellingSeedr, setIsCancellingSeedr] = useState(false);
  const seedrPrepareGenerationRef = useRef(0);
  const [activeSeedrFolderOpen, setActiveSeedrFolderOpen] = useState(false);
  const [selectedSeedrFolderId, setSelectedSeedrFolderId] = useState<string | null>(() => {
    try {
      return window.localStorage.getItem('seedflow_seedr_folder') || null;
    } catch {
      return null;
    }
  });
  const seedrTorrentNamesKey = 'seedflow_seedr_torrent_names';
  const [seedrTorrentNames, setSeedrTorrentNames] = useState<Record<string, string>>(() => {
    try {
      const raw = window.localStorage.getItem(seedrTorrentNamesKey);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  });

  return {
    seedrNoticeStorageKey,
    seedrPrepareWaiters,
    seedrNotice,
    setSeedrNotice,
    setSeedrFiles,
    seedrDeletedFolderIds,
    setSeedrDeletedFolderIds,
    seedrLibraryRoot,
    setSeedrLibraryRoot,
    seedrLibraryFolders,
    setSeedrLibraryFolders,
    setSeedrFolderContentsLoading,
    seedrPrefetchLoading,
    setSeedrPrefetchLoading,
    seedrFolderContentsCache,
    setSeedrFolderContentsCache,
    seedrFolderContentsRequests,
    seedrQuota,
    setSeedrQuota,
    seedrQuotaError,
    setSeedrQuotaError,
    seedrLoading,
    setSeedrLoading,
    seedrError,
    setSeedrError,
    seedrDeleteNotice,
    setSeedrDeleteNotice,
    setCopiedSeedrFileId,
    seedrAddBlockedNotice,
    setSeedrAddBlockedNotice,
    seedrInsufficientSpacePrompt,
    setSeedrInsufficientSpacePrompt,
    seedrStreamLoadingId,
    setSeedrStreamLoadingId,
    isCancellingSeedr,
    setIsCancellingSeedr,
    seedrPrepareGenerationRef,
    setActiveSeedrFolderOpen,
    selectedSeedrFolderId,
    setSelectedSeedrFolderId,
    seedrTorrentNamesKey,
    seedrTorrentNames,
    setSeedrTorrentNames,
  };
}
