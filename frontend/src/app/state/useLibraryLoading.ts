import { useEffect, useCallback } from 'react';
import { api } from '../../api/client.ts';
import { useFileExplorerState } from './useFileExplorerState.ts';
import { useLibraryDataState } from './useLibraryDataState.ts';
import { useAppShellState } from './useAppShellState.ts';

export function useLibraryLoading({ setUsers, setActiveUser, setStorageStats, setFolders, activityStorageKey, setActivityLogs, setNotifications, setCleanupSettings, folders, setFiles, currentFolder, fileSearch, fileTypeFilter, activeTab }: Pick<ReturnType<typeof useLibraryDataState>, 'setUsers' | 'setActiveUser' | 'setStorageStats' | 'setFolders' | 'activityStorageKey' | 'setActivityLogs' | 'setNotifications' | 'setCleanupSettings' | 'folders' | 'setFiles'> & Pick<ReturnType<typeof useFileExplorerState>, 'currentFolder' | 'fileSearch' | 'fileTypeFilter'> & Pick<ReturnType<typeof useAppShellState>, 'activeTab'>) {
  // Load lightweight application metadata first. The actual files for the
  // currently open folder are fetched separately, after folder metadata exists.
  const loadInitialData = useCallback(async () => {
    try {
      const [uData, sStats, foldData, logs, notifs, cleanup] = await Promise.all([
        api.getUsers(),
        api.getStorageStats(),
        api.getFolders(),
        api.getLogs(),
        api.getNotifications(),
        api.getCleanupSettings()
      ]);

      setUsers(uData.users);
      setActiveUser(uData.activeUser);
      setStorageStats(sStats);
      setFolders(foldData);
      try {
        const rawLocalLogs = window.localStorage.getItem(activityStorageKey);
        const localLogs = rawLocalLogs ? JSON.parse(rawLocalLogs) : [];
        setActivityLogs(Array.isArray(localLogs) && localLogs.length ? localLogs : logs);
      } catch {
        setActivityLogs(logs);
      }
      setNotifications(notifs);
      setCleanupSettings(cleanup);
    } catch (e) {
      console.error('Failed to load initial library metadata:', e);
    }
  }, []);
  useEffect(() => {
    loadInitialData();
  }, [loadInitialData]);
  const loadCurrentFiles = useCallback(async () => {
    try {
      const folderId = currentFolder === '/'
        ? ''
        : String(folders.find(folder => folder.path === currentFolder)?.id || '');
      const fData = await api.getFiles(currentFolder, fileSearch, fileTypeFilter, folderId);
      setFiles(fData);
    } catch (e) {
      console.error('Failed to load current folder files:', e);
      setFiles([]);
    }
  }, [currentFolder, fileSearch, fileTypeFilter, folders]);
  useEffect(() => {
    if (activeTab === 'files') {
      loadCurrentFiles();
    }
  }, [activeTab, loadCurrentFiles]);

}
