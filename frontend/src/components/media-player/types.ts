import { StorageFile } from '../../types/index.ts';

export interface MediaPlayerSource {
  provider: 'TorrServer' | 'WebTorrent' | 'Webtor';
  kind: 'url' | 'webtorrent' | 'webtor';
  streamUrl?: string;
  downloadUrl?: string;
  magnet?: string;
  attachVideo?: (video: HTMLVideoElement) => void | (() => void);
  download?: () => Promise<void>;
  dispose?: () => void;
  subscribeStatus?: (listener: (status: string) => void) => () => void;
}

export interface TorrentPlaybackResult {
  provider: MediaPlayerSource['provider'];
  fileName: string;
  fileSize?: number;
  source: MediaPlayerSource;
}

export interface MediaPlayerModalProps {
  file: StorageFile | null;
  source?: MediaPlayerSource | null;
  onClose: () => void;
  onPlaybackStarted?: () => void;
  isMinimized: boolean;
  onToggleMinimize: () => void;
}
