import { useCallback, useEffect, useRef, useState } from 'react';
import type { TorrentSearchResult } from '../../../api/client.ts';
import type { TorrentPlaybackResult } from '../../media-player/types.ts';
import {
  createWebTorrentPlayback,
  downloadBrowserTorrentFile,
  playableVideoFiles,
  shouldShowTorrentFileSelection,
  startBrowserWebTorrent,
  type BrowserTorrentFile,
  type BrowserTorrentSession,
} from '../webTorrentEngine.ts';

export interface WebTorrentFileSelection {
  title: string;
  files: BrowserTorrentFile[];
  playableFiles: BrowserTorrentFile[];
}

export function useWebTorrentFlow(
  onOpenPlayback?: (playback: TorrentPlaybackResult) => void | Promise<void>,
) {
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [fileSelection, setFileSelection] = useState<WebTorrentFileSelection | null>(null);
  const [selectingFile, setSelectingFile] = useState(false);
  const pendingSessionRef = useRef<BrowserTorrentSession | null>(null);
  const selectingFileRef = useRef(false);

  const disposePendingSession = useCallback(() => {
    pendingSessionRef.current?.dispose();
    pendingSessionRef.current = null;
  }, []);

  useEffect(() => disposePendingSession, [disposePendingSession]);

  const openFile = useCallback(async (file: BrowserTorrentFile) => {
    const session = pendingSessionRef.current;
    if (!session || selectingFileRef.current) return;
    selectingFileRef.current = true;
    setSelectingFile(true);
    const playback = createWebTorrentPlayback(file, session, setError);

    try {
      await onOpenPlayback?.(playback);
      pendingSessionRef.current = null;
      setFileSelection(null);
      setError('');
    } catch (playError) {
      setError(playError instanceof Error ? playError.message : String(playError));
    } finally {
      selectingFileRef.current = false;
      setSelectingFile(false);
    }
  }, [onOpenPlayback]);

  const start = useCallback(async (result: TorrentSearchResult) => {
    const magnet = String(result.magnetUrl || '').trim();
    const torrentKey = result.infoHash || magnet || result.title;
    if (!magnet.toLowerCase().startsWith('magnet:?') || loadingKey === torrentKey) return;

    disposePendingSession();
    setError('');
    setStatus('Loading WebTorrent…');
    setFileSelection(null);
    setLoadingKey(torrentKey);

    try {
      const session = await startBrowserWebTorrent(magnet, { onStatus: setStatus });
      pendingSessionRef.current = session;
      const videoFiles = playableVideoFiles(session.files);
      if (!shouldShowTorrentFileSelection(session.files, videoFiles)) {
        await openFile(videoFiles[0]);
      } else {
        setFileSelection({
          title: session.torrent.name || result.title,
          files: session.files,
          playableFiles: videoFiles,
        });
      }
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : String(startError));
      setStatus('');
    } finally {
      setLoadingKey(current => current === torrentKey ? null : current);
    }
  }, [disposePendingSession, loadingKey, openFile]);

  const downloadFile = useCallback(async (file: BrowserTorrentFile) => {
    setError('');
    try {
      await downloadBrowserTorrentFile(file);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : String(downloadError));
    }
  }, []);

  const closeFileSelection = useCallback(() => {
    setFileSelection(null);
    setStatus('');
    disposePendingSession();
  }, [disposePendingSession]);

  return {
    webTorrentLoadingKey: loadingKey,
    webTorrentError: error,
    webTorrentStatus: status,
    webTorrentFileSelection: fileSelection,
    webTorrentSelectingFile: selectingFile,
    startWebTorrent: start,
    selectWebTorrentFile: openFile,
    downloadWebTorrentFile: downloadFile,
    closeWebTorrentFileSelection: closeFileSelection,
  };
}
