import { API_BASE, apiFetch, makeSeedrError, setSeedrCsrfToken } from './http.ts';

export const seedrApi = {
  async getSeedrSession(): Promise<{
    connected: boolean;
    csrfToken: string;
  }> {
    const res = await apiFetch('/api/seedr/session');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) throw makeSeedrError(data, body, res.status, 'Failed to initialize Seedr session');

    const csrfToken = typeof data?.csrfToken === 'string' ? data.csrfToken : '';
    setSeedrCsrfToken(csrfToken);
    return {
      connected: Boolean(data?.connected),
      csrfToken,
    };
  },

  async connectSeedrPat(pat: string): Promise<{
    status: 'connected' | 'error';
    connected: boolean;
  }> {
    const value = String(pat || '').trim();
    if (!value) throw new Error('Enter your Seedr Personal Access Token.');

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 15000);
    let res: Response;
    try {
      res = await apiFetch('/api/seedr/connect/pat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pat: value }),
        signal: controller.signal,
      });
    } catch (error: any) {
      if (error?.name === 'AbortError') {
        throw new Error('Seedr connection timed out. The server could not validate the token in time; please retry.');
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      throw makeSeedrError(data, body, res.status, 'Seedr rejected this Personal Access Token.');
    }
    return {
      status: data?.status === 'connected' ? 'connected' : 'error',
      connected: Boolean(data?.connected),
    };
  },

  async startSeedrConnection(): Promise<{
    status: 'pending' | 'connected' | 'error';
    connected: boolean;
    userCode?: string;
    verificationUrl?: string;
    expiresIn?: number;
    interval?: number;
  }> {
    const res = await apiFetch('/api/seedr/connect/start', { method: 'POST' });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) throw makeSeedrError(data, body, res.status, 'Failed to start Seedr account connection');
    return data;
  },

  async pollSeedrConnection(): Promise<{
    status: 'idle' | 'pending' | 'connected' | 'expired' | 'error';
    connected: boolean;
    message?: string;
    code?: string;
    expiresIn?: number;
  }> {
    const res = await apiFetch('/api/seedr/connect/status');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) throw makeSeedrError(data, body, res.status, 'Failed to check Seedr connection');
    return data;
  },

  async disconnectSeedr(): Promise<void> {
    const res = await apiFetch('/api/seedr/connect/disconnect', { method: 'POST' });
    const body = await res.text();
    if (!res.ok) {
      let data: any = null;
      try { data = body ? JSON.parse(body) : null; } catch {}
      throw makeSeedrError(data, body, res.status, 'Failed to disconnect Seedr account');
    }
  },

  async getSeedrTokenDiagnostic(): Promise<any> {
    const res = await apiFetch('/api/seedr/token-diagnostic');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw makeSeedrError(data, body, res.status, 'Failed to diagnose Seedr token');
    return data;
  },

  async getSeedrAuthStatus(): Promise<{
    configured: boolean;
    authenticated: boolean;
    code: string;
    message?: string;
  }> {
    const res = await apiFetch('/api/seedr/auth-status');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw makeSeedrError(data, body, res.status, 'Failed to check Seedr authentication');
    return {
      configured: Boolean(data?.configured),
      authenticated: Boolean(data?.authenticated),
      code: String(data?.code || ''),
      message: typeof data?.message === 'string' ? data.message : undefined,
    };
  },

  async getSeedrQuota(): Promise<{
    configured: boolean;
    maxSpace: number;
    usedSpace: number;
    remainingSpace: number;
  }> {
    const res = await apiFetch('/api/seedr/quota');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw makeSeedrError(data, body, res.status, 'Failed to fetch Seedr quota');
    return {
      configured: Boolean(data?.configured),
      maxSpace: Number(data?.maxSpace || 0),
      usedSpace: Number(data?.usedSpace || 0),
      remainingSpace: Number(data?.remainingSpace || 0),
    };
  },

  async getSeedrLibrary(fresh = false): Promise<{
    configured: boolean;
    root: {
      id: string;
      folderId: string;
      name: string;
      path: string;
      filesCount: number;
      totalSize: number;
      folderCount: number;
    } | null;
    folders: Array<{
      id: string;
      folderId: string;
      name: string;
      torrentName?: string;
      path: string;
      filesCount: number;
      totalSize: number;
      folderCount: number;
    }>;
  }> {
    const res = await apiFetch('/api/seedr/library' + (fresh ? '?fresh=1' : ''));
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw makeSeedrError(data, body, res.status, 'Failed to fetch Seedr library metadata');
    return {
      configured: Boolean(data?.configured),
      root: data?.root || null,
      folders: Array.isArray(data?.folders) ? data.folders : [],
    };
  },

  async getSeedrFolderContents(folderId: string): Promise<{
    configured: boolean;
    folderId: string;
    files: Array<{ id: string; streamId?: string; name: string; size: number; folderId: string; folderPath: string; url?: string | null }>;
    folders: Array<{ id: string; folderId: string; name: string }>;
  }> {
    const res = await apiFetch('/api/seedr/folders/' + encodeURIComponent(folderId) + '/contents');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw makeSeedrError(data, body, res.status, 'Failed to load Seedr folder contents');
    return {
      configured: Boolean(data?.configured),
      folderId: String(data?.folderId || folderId),
      // The backend does not send folderPath for folder contents; default it so
      // the value matches the declared type.
      files: (Array.isArray(data?.files) ? data.files : []).map((file: any) => ({
        ...file,
        folderPath: String(file?.folderPath ?? ''),
      })),
      folders: Array.isArray(data?.folders) ? data.folders : [],
    };
  },

  async getSeedrFiles(): Promise<{
    configured: boolean;
    files: Array<{ id: string; name: string; size: number; folderId: string; folderPath: string }>;
  }> {
    const res = await apiFetch('/api/seedr/files');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw makeSeedrError(data, body, res.status, 'Failed to fetch Seedr files');
    return {
      configured: Boolean(data?.configured),
      files: Array.isArray(data?.files) ? data.files : [],
    };
  },

  openSeedrFileDownload(fileId: string, filename = ''): void {
    const query = filename ? '?filename=' + encodeURIComponent(filename) : '';
    const url = '/api/seedr/files/' + encodeURIComponent(fileId) + '/download' + query;
    window.open(API_BASE + url, '_blank', 'noopener,noreferrer');
  },

  async getSeedrFileDownload(fileId: string): Promise<{ url: string; name: string }> {
    const res = await apiFetch('/api/seedr/files/' + encodeURIComponent(fileId) + '/download/url');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw new Error(data?.error || body || 'Failed to create Seedr download link');
    return data;
  },

  async getSeedrFileStream(fileId: string, fileName: string, type: 'video' | 'audio'): Promise<{ url: string; externalUrl?: string; name: string; resolvedFileId?: string }> {
    const params = new URLSearchParams({
      type,
      file_id: fileId,
      name: fileName
    });
    const res = await apiFetch('/api/seedr/files/stream?' + params.toString());
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw new Error(data?.error || body || 'Failed to create Seedr stream URL');
    const streamUrl = typeof data?.url === 'string' && data.url.startsWith('/')
      ? API_BASE + data.url
      : data?.url;
    return {
      ...data,
      url: streamUrl,
      externalUrl: data?.externalUrl
    };
  },

  async getSeedrMediaInfo(fileId: string): Promise<{
    name: string;
    audioTracks: Array<{
      index: number;
      streamIndex?: number;
      language: string;
      title: string;
      codec: string;
      channels: number;
      default: boolean;
    }>;
    subtitleTracks: Array<{
      index: number;
      streamIndex?: number;
      language: string;
      title: string;
      codec: string;
      url: string;
    }>;
  }> {
    const res = await apiFetch('/api/seedr/media-info/' + encodeURIComponent(fileId));
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }

    if (!res.ok) {
      throw new Error(data?.error || data?.message || body || 'Failed to inspect Seedr media tracks');
    }

    const subtitleTracks = Array.isArray(data?.subtitleTracks)
      ? data.subtitleTracks.map((track: any) => ({
          ...track,
          url: typeof track?.url === 'string' && track.url.startsWith('/')
            ? API_BASE + track.url
            : track?.url,
        }))
      : [];

    return {
      name: String(data?.name || fileId),
      audioTracks: Array.isArray(data?.audioTracks) ? data.audioTracks : [],
      subtitleTracks,
    };
  },

  openSeedrFolderDownload(folderId: string, filename = ''): void {
    const query = filename ? '?filename=' + encodeURIComponent(filename) : '';
    const url = '/api/seedr/folders/' + encodeURIComponent(folderId) + '/download' + query;
    window.open(API_BASE + url, '_blank', 'noopener,noreferrer');
  },

  async getSeedrFolderDownload(folderId: string): Promise<{ url: string }> {
    const res = await apiFetch('/api/seedr/folders/' + encodeURIComponent(folderId) + '/download/url');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw new Error(data?.error || body || 'Failed to create Seedr folder download');
    return data;
  },

  async deleteSeedrFolder(folderId: string): Promise<void> {
    const res = await apiFetch('/api/seedr/folders/' + encodeURIComponent(folderId), { method: 'DELETE' });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw new Error(data?.error || body || 'Failed to delete Seedr folder');
  },

  async deleteSeedrTask(taskId: number | string): Promise<any> {
    const res = await apiFetch('/api/seedr/tasks/' + encodeURIComponent(String(taskId)), { method: 'DELETE' });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch {}
    if (!res.ok) {
      throw new Error(data?.error || data?.detail || body || 'Failed to delete Seedr task');
    }
    return data || {};
  },

  async deleteSeedrFile(fileId: string): Promise<void> {
    const res = await apiFetch('/api/seedr/files/' + encodeURIComponent(fileId), { method: 'DELETE' });
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw new Error(data?.error || body || 'Failed to delete Seedr file');
  },

  async getSeedrTaskProgress(taskId: number | string): Promise<{
    taskId: number | string;
    name?: string;
    folderId?: string;
    status: 'waiting' | 'downloading' | 'completed' | 'not_found';
    progress: number;
  }> {
    const res = await apiFetch('/api/seedr/tasks/' + encodeURIComponent(String(taskId)) + '/progress');
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw new Error(data?.error || body || 'Failed to check Seedr task progress');
    return {
      taskId: data?.taskId ?? taskId,
      name: typeof data?.name === 'string' ? data.name : '',
      folderId: typeof data?.folderId === 'string' ? data.folderId : '',
      status: data?.status || 'downloading',
      progress: Math.max(0, Math.min(100, Number(data?.progress) || 0)),
    };
  },

  async getSeedrTask(taskId: number | string): Promise<{
    taskId: number | string;
    name?: string;
    folderName?: string;
    folderId?: string;
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
  }> {
    const res = await apiFetch('/api/seedr/tasks/' + encodeURIComponent(String(taskId)));
    const body = await res.text();
    let data: any = null;
    try { data = body ? JSON.parse(body) : null; } catch { data = null; }
    if (!res.ok) throw new Error(data?.error || body || 'Failed to check Seedr task');
    return data;
  }
};
