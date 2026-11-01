import { useState } from 'react';
import { TorrentItem, StorageFile, StorageFolder } from '../../types/index.ts';
import type { MediaPlayerSource } from '../../components/media-player/types.ts';

export function useAppDialogState() {
  // Modals & Drawers
  const [isAddMagnetOpen, setIsAddMagnetOpen] = useState(false);
  const [initialMagnet, setInitialMagnet] = useState('');
  const [prioTorrent, setPrioTorrent] = useState<TorrentItem | null>(null);
  const [isCleanupOpen, setIsCleanupOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackType, setFeedbackType] = useState<'review' | 'suggestion' | 'bug'>('review');
  const [feedbackRating, setFeedbackRating] = useState(5);
  const [feedbackMessage, setFeedbackMessage] = useState('');
  const [feedbackName, setFeedbackName] = useState('');
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [feedbackSuccess, setFeedbackSuccess] = useState('');
  const [feedbackError, setFeedbackError] = useState('');
  const [shareFolder, setShareFolder] = useState<StorageFolder | null>(null);
  const [isCreateFolderOpen, setIsCreateFolderOpen] = useState(false);
  const [moveFile, setMoveFile] = useState<StorageFile | null>(null);
  const [renameItem, setRenameItem] = useState<{ id: string; name: string; isFolder: boolean } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{
    type: 'file' | 'torrent';
    id: string;
    name: string;
    details?: string;
  } | null>(null);
  // Media Player State
  const [activeMediaFile, setActiveMediaFile] = useState<StorageFile | null>(null);
  const [activeMediaSource, setActiveMediaSource] = useState<MediaPlayerSource | null>(null);
  const [isPlayerMinimized, setIsPlayerMinimized] = useState(false);

  return {
    isAddMagnetOpen,
    setIsAddMagnetOpen,
    initialMagnet,
    setInitialMagnet,
    prioTorrent,
    setPrioTorrent,
    isCleanupOpen,
    setIsCleanupOpen,
    isNotificationsOpen,
    setIsNotificationsOpen,
    feedbackOpen,
    setFeedbackOpen,
    feedbackType,
    setFeedbackType,
    feedbackRating,
    setFeedbackRating,
    feedbackMessage,
    setFeedbackMessage,
    feedbackName,
    setFeedbackName,
    feedbackSubmitting,
    setFeedbackSubmitting,
    feedbackSuccess,
    setFeedbackSuccess,
    feedbackError,
    setFeedbackError,
    shareFolder,
    setShareFolder,
    isCreateFolderOpen,
    setIsCreateFolderOpen,
    moveFile,
    setMoveFile,
    renameItem,
    setRenameItem,
    deleteTarget,
    setDeleteTarget,
    activeMediaFile,
    setActiveMediaFile,
    activeMediaSource,
    setActiveMediaSource,
    isPlayerMinimized,
    setIsPlayerMinimized,
  };
}
