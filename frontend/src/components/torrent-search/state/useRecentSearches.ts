import { useState } from 'react';
import { isPresetSearchLabel } from '../formatting.tsx';

export function useRecentSearches() {
  const [recentSearches, setRecentSearches] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem('seedflow_recent_searches');
      const parsed = saved ? JSON.parse(saved) : [];
      return Array.isArray(parsed)
        ? parsed.filter((value): value is string => typeof value === 'string' && !isPresetSearchLabel(value)).slice(0, 10)
        : [];
    } catch {
      return [];
    }
  });
  const saveRecentSearch = (value: string) => {
    const normalized = value.trim();
    if (!normalized) return;

    setRecentSearches(prev => {
      const next = [
        normalized,
        ...prev.filter(item => item.toLowerCase() !== normalized.toLowerCase())
      ].slice(0, 7);

      try {
        localStorage.setItem('seedflow_recent_searches', JSON.stringify(next));
      } catch {}

      return next;
    });
  };

  return {
    recentSearches,
    setRecentSearches,
    saveRecentSearch,
  };
}
