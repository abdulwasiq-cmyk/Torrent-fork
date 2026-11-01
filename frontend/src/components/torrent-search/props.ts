import { TorrentSearchResult } from '../../api/client.ts';
import type { TorrentPlaybackResult } from '../media-player/types.ts';

export type SeedrSearchFile = {
  id: string;
  streamId?: string;
  name: string;
  size: number;
  folderId: string;
  folderPath: string;
};


export interface TorrentSearchPanelProps {
  onPrepare: (
    result: TorrentSearchResult,
    metadata?: {
      name: string;
      hash: string;
      files: { index: number; name: string; size: number; path: string; type: string; priority?: number }[];
      totalSize: number;
    }
  ) => Promise<{ files: SeedrSearchFile[]; deletedFolderIds?: string[] }>;
  onCancelPrepare?: () => void | Promise<void>;
  onOpenProgress?: () => void;
  seedrFiles?: SeedrSearchFile[];
  seedrDeletedFolderIds?: string[];
  onPlaySeedrFile?: (file: SeedrSearchFile) => void | Promise<void>;
  onOpenTorrentPlayback?: (playback: TorrentPlaybackResult) => void | Promise<void>;
}
