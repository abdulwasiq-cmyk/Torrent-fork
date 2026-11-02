import { api, TorrentSearchResult } from '../../../api/client.ts';
import { PLAYABLE_FILE_PATTERN } from '../ottProviders.ts';
import { normalizeMatchText } from '../helpers.ts';
import { useMoviePreviewState } from './useMoviePreviewState.ts';
import { useCatalogueNavigationState } from './useCatalogueNavigationState.ts';
import { useSearchInputState } from './useSearchInputState.ts';
import { SeedrSearchFile, TorrentSearchPanelProps } from '../props.ts';
import { usePrepareState } from './usePrepareState.ts';

export function usePrepareActions({ preparedByKeyRef, preparingTorrentKey, setPrepareError, setPreparingTorrentKey, setPrepareWaitTitle, setPrepareWaitOpen, playingTorrentKey, copiedTorrentKey, setPlayingTorrentKey, setCopiedTorrentKey, setMovieTorrentSearchError, metadataCacheRef, error, seedrFiles, seedrDeletedFolderIds, onPrepare, onPlaySeedrFile }: Pick<ReturnType<typeof usePrepareState>, 'preparedByKeyRef' | 'preparingTorrentKey' | 'setPrepareError' | 'setPreparingTorrentKey' | 'setPrepareWaitTitle' | 'setPrepareWaitOpen' | 'playingTorrentKey' | 'copiedTorrentKey' | 'setPlayingTorrentKey' | 'setCopiedTorrentKey'> & Pick<ReturnType<typeof useMoviePreviewState>, 'setMovieTorrentSearchError'> & Pick<ReturnType<typeof useSearchInputState>, 'metadataCacheRef'> & Pick<ReturnType<typeof useCatalogueNavigationState>, 'error'> & Pick<TorrentSearchPanelProps, 'onPrepare' | 'onPlaySeedrFile'> & Required<Pick<TorrentSearchPanelProps, 'seedrFiles' | 'seedrDeletedFolderIds'>>) {
  const findPreparedFiles = (result: TorrentSearchResult): SeedrSearchFile[] => {
    const title = normalizeMatchText(result.title);
    if (!title || title.length < 4) return [];

    // Only auto-associate an existing Seedr file when the torrent title matches
    // the actual Seedr folder/file name exactly. The previous fuzzy fallback
    // could make one downloaded torrent appear as "Play" on several different
    // search results for the same movie (e.g. different qualities/releases).
    return seedrFiles.filter(file => {
      const folderPath = String(file.folderPath || '');
      const folderName = folderPath.split('/').filter(Boolean).pop() || '';
      const fileName = normalizeMatchText(file.name);
      const folder = normalizeMatchText(folderName);

      return folder === title || fileName === title;
    });
  };
  const preparedForResult = (result: TorrentSearchResult): SeedrSearchFile[] => {
    const key = result.infoHash || result.magnetUrl || result.downloadUrl || result.sourceUrl || result.title;
    const deletedIds = new Set(seedrDeletedFolderIds.map(id => String(id)));
    const local = preparedByKeyRef.current.get(key);
    const localFiles = local?.files?.filter(file => !deletedIds.has(String(file.folderId))) || [];
    return localFiles.length ? localFiles : findPreparedFiles(result);
  };
  const prepareMovieTorrent = async (result: TorrentSearchResult) => {
    const source = result.magnetUrl || result.downloadUrl || result.sourceUrl;
    const torrentKey = result.infoHash || source || result.title;
    if (!source || preparingTorrentKey === torrentKey) return;

    setPrepareError('');
    setMovieTorrentSearchError('');
    setPreparingTorrentKey(torrentKey);
    setPrepareWaitTitle(result.title);
    setPrepareWaitOpen(false);
    const longWaitTimer = window.setTimeout(() => setPrepareWaitOpen(true), 30000);

    try {
      const metadata = metadataCacheRef.current.get(torrentKey);
      const prepared = await onPrepare(result, metadata);
      const deletedFolderIds = new Set(
        (prepared?.deletedFolderIds || []).map(id => String(id).trim()).filter(Boolean)
      );
      if (deletedFolderIds.size > 0) {
        for (const [key, entry] of preparedByKeyRef.current.entries()) {
          if (entry.files.some(file => deletedFolderIds.has(String(file.folderId)))) {
            preparedByKeyRef.current.delete(key);
          }
        }
      }
      if (prepared?.files?.length) {
        preparedByKeyRef.current.set(torrentKey, { files: prepared.files });
      }
      setPrepareWaitOpen(false);
    } catch (error: any) {
      const message = String(error?.message || 'Could not prepare this torrent.');
      if (!message.toLowerCase().includes('cancelled by another selection')) {
        setPrepareError(message);
      }
    } finally {
      window.clearTimeout(longWaitTimer);
      setPreparingTorrentKey(current => current === torrentKey ? null : current);
    }
  };
  // Everything the shared movie cards need to know about one torrent result.
  // Used by every movie section so Prepare / Play / Download / Copy behave the same.
  const prepareStateFor = (result: TorrentSearchResult) => {
    const source = result.magnetUrl || result.downloadUrl || result.sourceUrl;
    const torrentKey = result.infoHash || source || result.title;
    const preparedFiles = preparedForResult(result);
    const primaryFile = preparedFiles.find(file => PLAYABLE_FILE_PATTERN.test(file.name)) || preparedFiles[0];
    return { source, torrentKey, isPreparing: preparingTorrentKey === torrentKey, primaryFile };
  };
  const preparedActionsFor = (torrentKey: string, primaryFile: SeedrSearchFile) => ({
    isPlaying: playingTorrentKey === torrentKey,
    isCopied: copiedTorrentKey === torrentKey,
    onPlay: async () => {
      if (playingTorrentKey === torrentKey) return;
      setPlayingTorrentKey(torrentKey);
      try {
        await onPlaySeedrFile?.(primaryFile);
      } finally {
        setPlayingTorrentKey(current => current === torrentKey ? null : current);
      }
    },
    onDownload: () => api.openSeedrFileDownload(primaryFile.id, primaryFile.name),
    onCopy: async () => {
      try {
        const data = await api.getSeedrFileDownload(primaryFile.id);
        await navigator.clipboard.writeText(data.url);
        setCopiedTorrentKey(torrentKey);
        window.setTimeout(() => {
          setCopiedTorrentKey(current => current === torrentKey ? null : current);
        }, 2000);
      } catch {
        setPrepareError('Could not copy the download link.');
      }
    },
  });

  return {
    preparedForResult,
    prepareMovieTorrent,
    prepareStateFor,
    preparedActionsFor,
  };
}
