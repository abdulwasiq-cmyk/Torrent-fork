import { useCallback, useEffect, useRef, useState } from 'react';
import { api, TorrentSearchResult, TorrServerFile } from '../../../api/client.ts';
import type { TorrentPlaybackResult } from '../../media-player/types.ts';
import { playableVideoFiles } from '../webTorrentEngine.ts';

type TorrentFileSelection = {
  title: string;
  files: TorrServerFile[];
};

function torrServerPlayback(file: TorrServerFile): TorrentPlaybackResult {
  const fileName = file.path.split('/').pop() || file.path;
  return {
    provider: 'TorrServer',
    fileName,
    fileSize: file.length,
    source: {
      provider: 'TorrServer',
      kind: 'url',
      streamUrl: file.streamUrl,
      downloadUrl: file.streamUrl,
    },
  };
}

export function useTorrServerFlow(onOpenPlayback?: (playback: TorrentPlaybackResult) => void | Promise<void>) {
  const [enabled, setEnabled] = useState(false);
  const [loadingTorrentKey, setLoadingTorrentKey] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [fileSelection, setFileSelection] = useState<TorrentFileSelection | null>(null);
  const [selectingFileId, setSelectingFileId] = useState<number | null>(null);
  const [selectingFile, setSelectingFile] = useState(false);
  const selectingFileRef = useRef(false);

  useEffect(() => {
    let active = true;
    void api.getTorrServerStatus()
      .then(status => {
        if (active) {
          setEnabled(status.enabled);
          if (status.error) setError(status.error);
        }
      })
      .catch(statusError => {
        if (active) setError(statusError instanceof Error ? statusError.message : String(statusError));
      });
    return () => {
      active = false;
    };
  }, []);

  const playTorrent = useCallback(async (result: TorrentSearchResult) => {
    const magnet = String(result.magnetUrl || '').trim();
    const torrentKey = result.infoHash || magnet || result.title;
    if (!magnet.toLowerCase().startsWith('magnet:?') || loadingTorrentKey === torrentKey) return;

    setError('');
    setFileSelection(null);
    setLoadingTorrentKey(torrentKey);
    try {
      let torrent = await api.addTorrServerTorrent(magnet);
      for (let attempt = 0; torrent.files.length === 0 && attempt < 20; attempt++) {
        await new Promise(resolve => window.setTimeout(resolve, 1000));
        torrent = await api.getTorrServerTorrent(torrent.hash);
      }

      const videoFiles = playableVideoFiles(torrent.files);
      if (videoFiles.length === 0) {
        throw new Error('TorrServer did not find a playable video file in this torrent.');
      }
      if (videoFiles.length === 1) {
        await onOpenPlayback?.(torrServerPlayback(videoFiles[0]));
      } else {
        setFileSelection({ title: torrent.title || result.title, files: videoFiles });
      }
    } catch (playError) {
      setError(playError instanceof Error ? playError.message : String(playError));
    } finally {
      setLoadingTorrentKey(current => current === torrentKey ? null : current);
    }
  }, [loadingTorrentKey, onOpenPlayback]);

  const selectFile = useCallback(async (file: TorrServerFile) => {
    if (selectingFileRef.current) return;
    selectingFileRef.current = true;
    setSelectingFile(true);
    setSelectingFileId(file.id);
    setError('');
    try {
      await onOpenPlayback?.(torrServerPlayback(file));
      setFileSelection(null);
    } catch (playError) {
      setError(playError instanceof Error ? playError.message : String(playError));
    } finally {
      selectingFileRef.current = false;
      setSelectingFile(false);
      setSelectingFileId(null);
    }
  }, [onOpenPlayback]);

  return {
    torrServerEnabled: enabled,
    torrServerLoadingKey: loadingTorrentKey,
    torrServerError: error,
    torrServerFileSelection: fileSelection,
    torrServerSelectingFileId: selectingFileId,
    torrServerSelectingFile: selectingFile,
    playTorrentWithTorrServer: playTorrent,
    selectTorrServerFile: selectFile,
    closeTorrServerFileSelection: () => setFileSelection(null),
  };
}
