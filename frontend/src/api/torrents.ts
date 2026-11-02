import type { TorrentItem, TorrentFileItem } from '../types/index.ts';
import { API_BASE, apiFetch } from './http.ts';

export const torrentsApi = {
  async getTorrents(filter?: string): Promise<TorrentItem[]> {
    const url = filter ? `/api/v2/torrents/info?filter=${filter}` : '/api/v2/torrents/info';
    const res = await apiFetch(url);
    if (!res.ok) throw new Error('Failed to fetch torrents');
    return res.json();
  },

  async getTorrentFiles(hash: string): Promise<TorrentFileItem[]> {
    const res = await apiFetch(`/api/v2/torrents/files?hash=${encodeURIComponent(hash)}`);
    if (!res.ok) throw new Error('Failed to fetch files');
    return res.json();
  },

  async exportTorrent(hash: string): Promise<Blob> {
    const res = await apiFetch(`/api/v2/torrents/export?hash=${encodeURIComponent(hash)}`);
    if (!res.ok) {
      const message = await res.text().catch(() => '');
      throw new Error(message || 'Failed to export torrent file');
    }
    return res.blob();
  },

  async setFilePriority(hash: string, fileIds: string, priority: number): Promise<void> {
    const res = await apiFetch('/api/v2/torrents/filePrio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hash, id: fileIds, priority })
    });
    if (!res.ok) throw new Error('Failed to set file priority');
  },

  async inspectMagnet(magnet: string, category = 'Downloads', sourceUrl = '', descriptorUrl = ''): Promise<{
    name: string;
    hash: string;
    files: { index: number; name: string; size: number; path: string; type: string; priority?: number }[];
    totalSize: number;
    source: string;
    pending?: boolean;
    createdPreview?: boolean;
    message?: string;
    jobId?: string;
  }> {
    const request = async () => {
      const res = await apiFetch('/api/v2/torrents/inspect-magnet', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          magnet,
          category,
          sourceUrl: sourceUrl || undefined,
          descriptorUrl: descriptorUrl || undefined
        })
      });
      const body = await res.text();
      let data: any = null;
      try { data = body ? JSON.parse(body) : null; } catch {}
      return { res, data, body };
    };

    const first = await request();
    if (first.res.ok && first.res.status !== 202 && Array.isArray(first.data?.files)) {
      return first.data;
    }

    if (first.res.status !== 202) {
      throw new Error(
        first.data?.error ||
        first.data?.message ||
        first.body ||
        `Torrent metadata inspection failed (HTTP ${first.res.status})`
      );
    }

    const jobId = String(first.data?.jobId || '').trim();
    if (!jobId) {
      throw new Error(first.data?.message || 'Torrent metadata is still resolving.');
    }

    // Keep the UI responsive while the backend resolver stays alive and
    // benefits from its warm libtorrent session/cache.
    // Do not keep the modal blocked for a full minute. Return a pending
    // result after a short foreground wait so the UI can move the resolver
    // into My Cloud Files and the user can continue working.
    for (let attempt = 0; attempt < 12; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 1000));

      const res = await apiFetch(
        '/api/v2/torrents/inspect-magnet/status?jobId=' + encodeURIComponent(jobId)
      );
      const body = await res.text();
      let data: any = null;
      try { data = body ? JSON.parse(body) : null; } catch {}

      if (res.ok && Array.isArray(data?.files) && data.files.length > 0) {
        return data;
      }

      if (!res.ok) {
        throw new Error(
          data?.error ||
          data?.message ||
          body ||
          `Torrent metadata inspection failed (HTTP ${res.status})`
        );
      }
    }

    return {
      name: '',
      hash: jobId,
      files: [],
      totalSize: 0,
      source: 'libtorrent_metadata',
      pending: true,
      jobId,
      message: 'Torrent metadata is still resolving in the background. Seedr has not been started.'
    };
  },

  async getTorrentMetadataJobs(): Promise<{
    jobs: Array<{
      jobId: string;
      hash: string;
      name: string;
      status: string;
      rounds: number;
      startedAt: number;
      updatedAt: number;
      deadlineAt: number;
      elapsedSeconds: number;
      remainingSeconds: number;
      fileCount: number;
      totalSize: number;
      source: string;
      error?: string | null;
    }>;
    backgroundTtlSeconds: number;
    retentionSeconds: number;
  }> {
    const res = await apiFetch('/api/v2/torrents/metadata-jobs');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      throw new Error(data?.error || data?.message || body || 'Torrent metadata jobs request failed');
    }
    return {
      jobs: Array.isArray(data?.jobs) ? data.jobs : [],
      backgroundTtlSeconds: Number(data?.backgroundTtlSeconds || 0),
      retentionSeconds: Number(data?.retentionSeconds || 0),
    };
  },

  async getTorrentMetadataStatus(jobId: string): Promise<any> {
    const res = await apiFetch(
      '/api/v2/torrents/inspect-magnet/status?jobId=' + encodeURIComponent(jobId)
    );
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      throw new Error(data?.error || data?.message || body || 'Torrent metadata status failed');
    }
    return data;
  },

  async uploadTorrentFile(file: File): Promise<{
    name: string;
    hash: string;
    files: { index: number; name: string; size: number; path: string; type: string }[];
    totalSize: number;
    magnetUri: string;
  }> {
    const arrayBuffer = await file.arrayBuffer();
    const bytes = new Uint8Array(arrayBuffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    const base64 = btoa(binary);

    const res = await apiFetch('/api/v2/torrents/upload-torrent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base64, filename: file.name })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Failed to parse torrent file' }));
      throw new Error(err.error || 'Failed to parse torrent file');
    }
    return res.json();
  },

  async prepareSeedrMagnet(
    magnet: string,
    requiredBytes = 0,
    torrentName?: string,
    replaceTaskId?: number | string
  ): Promise<any> {
    const value = String(magnet || '');
    if (!value.trim().toLowerCase().startsWith('magnet:?')) {
      throw new Error('A valid magnet URL is required');
    }

    const res = await apiFetch('/api/seedr/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        magnet: value,
        required_bytes: Math.max(0, Number(requiredBytes) || 0),
        auto_cleanup: true,
        replace_active: true,
        replace_task_id: replaceTaskId == null ? undefined : String(replaceTaskId),
        torrent_name: torrentName || undefined,
      })
    });

    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}

    if (!res.ok) {
      const error = new Error(
        data?.error || data?.message || data?.detail || body ||
        `Seedr prepare failed (HTTP ${res.status})`
      );
      Object.assign(error as any, data || {});
      if (res.status === 413) (error as any).code = data?.code || 'SEEDR_INSUFFICIENT_SPACE';
      throw error;
    }

    return {
      backend: 'seedr',
      seedrTaskId: data?.task_id ?? data?.taskId ?? data?.id ?? data?.task?.id ?? null,
      seedrResponse: data,
      seedrFolderName: data?.torrent_name || data?.name || data?.task?.name || torrentName || null,
      seedrFolderId: data?.folder_id ?? data?.folderId ?? data?.task?.folder_id ?? null,
      deletedFolders: Array.isArray(data?.deleted_folders) ? data.deleted_folders : [],
      cancelledTasks: Array.isArray(data?.cancelled_tasks) ? data.cancelled_tasks : [],
    };
  },

  async addMagnet(
    urls: string,
    category = 'Downloads',
    selectedFiles?: number[],
    manifest?: { index?: number; name: string; size: number; priority: number }[],
    existingHash?: string,
    forceBackend?: 'seedr' | 'qbittorrent',
    selectedNames?: string[],
    seedrTaskId?: number | string,
    torrentName?: string
  ): Promise<any> {
    const magnet = urls;
    if (!magnet.trim().toLowerCase().startsWith('magnet:?')) {
      throw new Error('A valid magnet URL is required');
    }

    if (forceBackend === 'seedr') {
      const res = await apiFetch('/api/seedr/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ magnet })
      });

      const body = await res.text();
      let data: any = null;
      try { data = body ? JSON.parse(body) : null; } catch {}

      if (!res.ok) {
        const error = new Error(
          data?.error || data?.message || data?.detail || body ||
          `Seedr add failed (HTTP ${res.status})`
        );
        Object.assign(error as any, data || {});
        if (res.status === 413) (error as any).code = data?.code || 'SEEDR_INSUFFICIENT_SPACE';
        throw error;
      }

      return {
        backend: 'seedr',
        seedrTaskId: data?.task_id ?? data?.taskId ?? data?.id ?? data?.task?.id ?? null,
        seedrResponse: data,
        seedrFolderName: data?.torrent_name || data?.name || data?.task?.name || null,
        seedrFolderId: data?.folder_id ?? data?.folderId ?? data?.task?.folder_id ?? null,
        selectionApplied: false,
        selectionError: null
      };
    }

    // qBittorrent path retains the existing selected-file priority behavior.
    const res = await apiFetch(API_BASE + '/api/v2/torrents/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        urls: magnet,
        category,
        selectedFiles: selectedFiles || [],
        manifest: manifest || [],
        existingHash,
        forceBackend: 'qbittorrent',
        selectedNames: selectedNames || [],
        seedrTaskId,
        torrentName
      })
    });

    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      const error = new Error(data?.error || data?.message || data?.detail || body || `Torrent add failed (HTTP ${res.status})`);
      if (res.status === 413) (error as any).code = 'SEEDR_INSUFFICIENT_SPACE';
      if (data?.code) (error as any).code = data.code;
      Object.assign(error as any, data || {});
      throw error;
    }
    return data;
  }
};
