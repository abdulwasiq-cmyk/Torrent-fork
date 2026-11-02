import { useCallback } from 'react';
import { StorageFile } from '../../types/index.ts';
import { api, API_BASE } from '../../api/client.ts';
import { useAppDialogState } from './useAppDialogState.ts';
import { useLibraryDataState } from './useLibraryDataState.ts';
import { useSeedrState } from './useSeedrState.ts';
import { useSeedrFolderGroups } from './useSeedrFolderGroups.ts';

export function useSeedrFileActions({ seedrNotice, isCancellingSeedr, setIsCancellingSeedr, seedrPrepareWaiters, setSeedrNotice, setSeedrAddBlockedNotice, setSeedrError, setCopiedSeedrFileId, seedrFolderContentsCache, setSeedrStreamLoadingId, setSeedrFolderContentsCache, setSeedrDeleteNotice, setSeedrFiles, setSeedrLibraryFolders, setSeedrQuota, setSelectedSeedrFolderId, forgetSeedrFolders, seedrAllPrefetchedFiles, seedrFolderGroups, activeUser, setActiveMediaFile, setIsPlayerMinimized }: Pick<ReturnType<typeof useSeedrState>, 'seedrNotice' | 'isCancellingSeedr' | 'setIsCancellingSeedr' | 'seedrPrepareWaiters' | 'setSeedrNotice' | 'setSeedrAddBlockedNotice' | 'setSeedrError' | 'setCopiedSeedrFileId' | 'seedrFolderContentsCache' | 'setSeedrStreamLoadingId' | 'setSeedrFolderContentsCache' | 'setSeedrDeleteNotice' | 'setSeedrFiles' | 'setSeedrLibraryFolders' | 'setSeedrQuota' | 'setSelectedSeedrFolderId'> & Pick<ReturnType<typeof useSeedrFolderGroups>, 'forgetSeedrFolders' | 'seedrAllPrefetchedFiles' | 'seedrFolderGroups'> & Pick<ReturnType<typeof useLibraryDataState>, 'activeUser'> & Pick<ReturnType<typeof useAppDialogState>, 'setActiveMediaFile' | 'setIsPlayerMinimized'>) {
  const handleCancelSeedrDownload = async () => {
    const taskId = seedrNotice?.taskId;
    if (taskId == null || isCancellingSeedr) return;

    const currentNotice = seedrNotice;
    try {
      setIsCancellingSeedr(true);
      const cancelled = await api.deleteSeedrTask(taskId);
      if (cancelled?.folderDeleted && cancelled?.folderId) {
        forgetSeedrFolders([String(cancelled.folderId)]);
      }
      const waiterKey = String(taskId);
      const waiter = seedrPrepareWaiters.current[waiterKey];
      if (waiter) {
        delete seedrPrepareWaiters.current[waiterKey];
        waiter.reject(new Error('Seedr preparation was cancelled.'));
      }
      setSeedrNotice(null);
    } catch (error: any) {
      console.error('Failed to cancel Seedr download:', error);
      setSeedrNotice(currentNotice);
      setSeedrAddBlockedNotice(
        error?.message || 'Failed to cancel the Seedr download. Please try again.'
      );
      window.setTimeout(() => setSeedrAddBlockedNotice(null), 5000);
    } finally {
      setIsCancellingSeedr(false);
    }
  };
  const handleDownloadSeedrFolder = async (folderId: string, folderName = '') => {
    try {
      // Open the navigation synchronously from the click so the browser never
      // treats it as an async popup. The backend supplies Content-Disposition
      // with the requested filename.
      const zipName = folderName && !folderName.toLowerCase().endsWith('.zip')
        ? folderName + '.zip'
        : folderName;
      api.openSeedrFolderDownload(folderId, zipName);
    } catch (error) {
      console.error('Failed to start Seedr folder download:', error);
      setSeedrError(error instanceof Error ? error.message : 'Failed to start Seedr folder download');
    }
  };
  const handleCopySeedrFileUrl = async (fileId: string) => {
    try {
      const result = await api.getSeedrFileDownload(fileId);
      await navigator.clipboard.writeText(result.url);
      setCopiedSeedrFileId(fileId);
      window.setTimeout(() => {
        setCopiedSeedrFileId(current => current === fileId ? null : current);
      }, 1800);
    } catch (error) {
      console.error('Failed to copy Seedr download link:', error);
      setSeedrError(error instanceof Error ? error.message : 'Failed to copy Seedr download link');
    }
  };
  const handleDownloadSeedrFile = async (fileId: string, fileName = '') => {
    const popup = window.open('', '_blank', 'noopener,noreferrer');
    try {
      // Resolve the temporary Seedr URL only because the user clicked Download.
      // The final transfer then goes directly from Seedr to the browser.
      const result = await api.getSeedrFileDownload(fileId);
      const target = result.url;
      if (popup) {
        popup.location.href = target;
      } else {
        window.location.href = target;
      }
    } catch (error) {
      if (popup) popup.close();
      console.error('Failed to start Seedr download:', error);
      setSeedrError(error instanceof Error ? error.message : 'Failed to start Seedr download');
    }
  };
  const findSeedrSubtitleTracks = useCallback((
    file: { id: string; name: string; folderId: string; folderPath: string },
    apiOrigin: string,
    siblingFiles?: Array<{ id: string; name: string; folderId?: string }>
  ): StorageFile['subtitleTracks'] => {
    const extension = (name: string) => name.match(/\.([^.]+)$/)?.[1]?.toLowerCase() || '';
    const videoExt = extension(file.name);
    if (!/^(mkv|mp4|m4v|webm|mov|avi|ts)$/.test(videoExt)) return [];

    const videoBase = file.name.slice(0, -(videoExt.length + 1)).trim().toLowerCase();
    const cachedSiblings = siblingFiles?.length
      ? siblingFiles
      : file.folderId
        ? (seedrFolderContentsCache[file.folderId] || [])
        : seedrAllPrefetchedFiles.filter(item =>
            item.folderPath === file.folderPath || item.folderId === file.folderId
          );

    const languageNames: Record<string, string> = {
      en: 'English', eng: 'English', hi: 'Hindi', hin: 'Hindi',
      ar: 'Arabic', ara: 'Arabic', bn: 'Bengali', ben: 'Bengali',
      es: 'Spanish', spa: 'Spanish', fr: 'French', fra: 'French',
      de: 'German', deu: 'German', it: 'Italian', ita: 'Italian',
      pt: 'Portuguese', por: 'Portuguese', ru: 'Russian', rus: 'Russian',
      ja: 'Japanese', jpn: 'Japanese', ko: 'Korean', kor: 'Korean',
      zh: 'Chinese', zho: 'Chinese'
    };

    const subtitleFiles = cachedSiblings
      .filter(item => item.id !== file.id && /\.(srt|vtt)$/i.test(item.name));
    const videoFiles = cachedSiblings
      .filter(item => /\.(mkv|mp4|m4v|webm|mov|avi|ts)$/i.test(item.name));
    const hasMultipleVideos = videoFiles.length > 1;

    return subtitleFiles
      .filter(item => {
        const subtitleExt = extension(item.name);
        const subtitleBase = item.name.slice(0, -(subtitleExt.length + 1)).trim().toLowerCase();
        const exactMatch = subtitleBase === videoBase ||
          subtitleBase.startsWith(videoBase + '.') ||
          subtitleBase.startsWith(videoBase + ' ');
        // If this folder contains only one video, any SRT/VTT beside it is a
        // valid sidecar subtitle even when the subtitle has a generic name
        // such as "English.srt" or "Subs.srt". With multiple videos, require
        // a filename match so subtitles cannot be attached to the wrong video.
        return exactMatch || !hasMultipleVideos;
      })
      .map((item, index) => {
        const subtitleExt = extension(item.name);
        const subtitleBase = item.name.slice(0, -(subtitleExt.length + 1)).trim();
        const suffix = subtitleBase.slice(videoBase.length).replace(/^[. _-]+/, '').trim();
        const languageKey = suffix.split(/[. _-]+/)[0]?.toLowerCase() || '';
        const language = languageNames[languageKey] ? languageKey : 'en';
        return {
          index,
          language,
          title: languageNames[languageKey] || suffix || subtitleBase || 'Subtitles',
          codec: subtitleExt.toUpperCase(),
          url: apiOrigin + '/api/seedr/files/' + encodeURIComponent(item.id) +
            '/subtitle?filename=' + encodeURIComponent(item.name)
        };
      });
  }, [seedrAllPrefetchedFiles, seedrFolderContentsCache]);
  const handleStreamSeedrFile = async (file: { id: string; streamId?: string; name: string; size: number; folderId: string; folderPath: string }) => {
    // Restore the tested Seedr direct-browser-stream flow. The backend chooses
    // the correct presentation: a Range-aware direct stream when Seedr gives
    // a browser-playable presentation, otherwise the HLS proxy.
    setSeedrStreamLoadingId(file.id);
    try {
      const type: StorageFile['type'] =
        /\.(mkv|mp4|m4v|webm|mov|avi|m3u8|ts)$/i.test(file.name) ? 'video' :
        /\.(mp3|wav|flac|aac|ogg|m4a)$/i.test(file.name) ? 'audio' :
        'document';

      if (type !== 'video' && type !== 'audio') {
        setSeedrError('This Seedr file is not a supported video or audio file.');
        return;
      }

      setSeedrError(null);
      const result = await api.getSeedrFileStream(file.streamId || file.id, file.name, type);
      const apiOrigin = (() => {
        try {
          return new URL(result.url, window.location.origin).origin;
        } catch {
          return window.location.origin;
        }
      })();

      let subtitleSiblings: Array<{ id: string; name: string; folderId?: string }> = [];
      if (type === 'video' && file.folderId) {
        try {
          // A torrent folder can contain the video and a separate .srt/.vtt.
          // Use the cache first, but do not trust a cache entry that contains
          // no sidecar subtitles: the folder may have been indexed before the
          // subtitle was added. In that case refresh the tiny Seedr folder
          // listing once so the player can discover the new sidecar.
          const cached = seedrFolderContentsCache[file.folderId];
          if (cached?.length) {
            subtitleSiblings = cached;

            const cachedHasSidecar = cached.some(item => /\.(srt|vtt)$/i.test(item.name));
            if (!cachedHasSidecar) {
              const contents = await api.getSeedrFolderContents(file.folderId);
              subtitleSiblings = contents.files || [];
              setSeedrFolderContentsCache(prev => ({
                ...prev,
                [file.folderId]: contents.files || [],
              }));
            }
          } else {
            const contents = await api.getSeedrFolderContents(file.folderId);
            subtitleSiblings = contents.files || [];
            setSeedrFolderContentsCache(prev => ({
              ...prev,
              [file.folderId]: contents.files || [],
            }));
          }
        } catch (subtitleFolderError) {
          console.debug('Seedr sidecar subtitle discovery skipped:', subtitleFolderError);
        }
      }

      const subtitleTracks = type === 'video'
        ? findSeedrSubtitleTracks(file, apiOrigin, subtitleSiblings)
        : [];
      const audioTracks: StorageFile['audioTracks'] = [];

      const syntheticFile: StorageFile = {
        id: 'seedr-' + file.id,
        name: result.name || file.name,
        path: file.folderPath === '/' ? '/' + file.name : file.folderPath + '/' + file.name,
        folder: file.folderPath,
        size: file.size,
        type,
        mimeType: type === 'video' ? 'video/mp4' : 'audio/mpeg',
        createdAt: Date.now(),
        ownerId: activeUser?.id || 'user_admin',
        ownerName: activeUser?.name || 'Admin',
        isStreamable: true,
        // IMPORTANT: use the backend browser URL, not the external Seedr URL.
        // For direct presentations this is /api/seedr/media/video/{id}; for
        // HLS presentations it is /api/seedr/hls/{id}.
        streamUrl: result.url,
        externalStreamUrl: result.externalUrl,
        streamId: result.resolvedFileId || file.streamId || file.id,
        audioTracks,
        subtitleTracks,
        downloadUrl: API_BASE + '/api/seedr/files/' + encodeURIComponent(file.id) + '/download',
      };

      setActiveMediaFile(syntheticFile);
      setIsPlayerMinimized(false);
    } catch (error) {
      console.error('Failed to create Seedr stream URL:', error);
      setSeedrError(error instanceof Error ? error.message : 'Failed to create Seedr stream URL');
    } finally {
      setSeedrStreamLoadingId(current => current === file.id ? null : current);
    }
  };
  const handleDeleteSeedrFile = async (file: { id: string; name: string; size: number; folderId: string; folderPath: string }) => {    setSeedrDeleteNotice('Deleting…');
    try {
      // A single-file Seedr folder is represented directly in My Cloud Files.
      // In that special case, delete the whole Seedr folder rather than only
      // the file. Files inside multi-file folders still use file deletion.
      const group = seedrFolderGroups.find(item => item.folderId === file.folderId);
      const isSingleFileFolder =
        file.folderId !== '__root__' &&
        group?.filesCount === 1;

      if (isSingleFileFolder) {
        await api.deleteSeedrFolder(file.folderId);
        setSeedrFiles(prev => prev.filter(item => item.folderId !== file.folderId));
        // The Files tab also renders the lazily-prefetched Seedr files cache.
        // Remove the deleted folder from that cache as well, otherwise the
        // deleted file remains visible at the root after returning from the
        // Seedr folder view.
        setSeedrFolderContentsCache(prev => {
          if (!(file.folderId in prev)) return prev;
          const next = { ...prev };
          delete next[file.folderId];
          return next;
        });
      } else {
        await api.deleteSeedrFile(file.id);
        setSeedrFiles(prev => prev.filter(item => item.id !== file.id));
        setSeedrFolderContentsCache(prev => {
          const cached = prev[file.folderId];
          if (!cached) return prev;
          const remaining = cached.filter(item => item.id !== file.id);
          const next = { ...prev };
          if (remaining.length > 0) {
            next[file.folderId] = remaining;
          } else {
            delete next[file.folderId];
          }
          return next;
        });
        setSeedrLibraryFolders(prev => prev.map(item =>
          (item.folderId === file.folderId || item.id === file.folderId)
            ? {
                ...item,
                filesCount: Math.max(0, Number(item.filesCount || 0) - 1),
                totalSize: Math.max(0, Number(item.totalSize || 0) - Number(file.size || 0)),
              }
            : item
        ));
      }

      setSeedrError(null);
      setSeedrDeleteNotice('Deleted successfully');
      window.setTimeout(() => setSeedrDeleteNotice(null), 1800);
      const quota = await api.getSeedrQuota().catch(() => null);
      if (quota?.configured) {
        setSeedrQuota({
          maxSpace: quota.maxSpace,
          usedSpace: quota.usedSpace,
          remainingSpace: quota.remainingSpace
        });
      }
    } catch (error) {
      setSeedrDeleteNotice(null);
      console.error('Failed to delete Seedr item:', error);
      setSeedrError(error instanceof Error ? error.message : 'Failed to delete Seedr item');
    }
  };
  const handleDeleteSeedrFolder = async (folderId: string) => {
    setSeedrDeleteNotice('Deleting…');
    try {
      await api.deleteSeedrFolder(folderId);
      setSeedrFiles(prev => prev.filter(item => item.folderId !== folderId));
      setSeedrFolderContentsCache(prev => {
        if (!(folderId in prev)) return prev;
        const next = { ...prev };
        delete next[folderId];
        return next;
      });
      setSeedrLibraryFolders(prev => prev.filter(item => item.folderId !== folderId && item.id !== folderId));
      setSelectedSeedrFolderId(prev => prev === folderId ? null : prev);
      setSeedrError(null);
      setSeedrDeleteNotice('Deleted successfully');
      window.setTimeout(() => setSeedrDeleteNotice(null), 1800);
      const quota = await api.getSeedrQuota().catch(() => null);
      if (quota?.configured) {
        setSeedrQuota({
          maxSpace: quota.maxSpace,
          usedSpace: quota.usedSpace,
          remainingSpace: quota.remainingSpace
        });
      }
    } catch (error) {
      setSeedrDeleteNotice(null);
      console.error('Failed to delete Seedr folder:', error);
      setSeedrError(error instanceof Error ? error.message : 'Failed to delete Seedr folder');
    }
  };

  return {
    handleCancelSeedrDownload,
    handleStreamSeedrFile,
    handleDeleteSeedrFile,
  };
}
