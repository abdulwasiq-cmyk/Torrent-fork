import { useEffect, useState } from 'react';
import { isPresetSearchLabel } from '../formatting.tsx';
import { apiFetchRecent } from '../helpers.ts';

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
  useEffect(() => {
    let cancelled = false;

    apiFetchRecent('/api/search/recent')
      .then(response => response.ok ? response.json() : null)
      .then(data => {
        if (cancelled) return;
        const serverRecents = Array.isArray(data?.searches)
          ? data.searches.filter((value: unknown): value is string => typeof value === 'string' && !isPresetSearchLabel(value)).slice(0, 7)
          : [];
        if (serverRecents.length > 0) {
          setRecentSearches(serverRecents);
          try {
            localStorage.setItem('seedflow_recent_searches', JSON.stringify(serverRecents));
          } catch {}
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, []);
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

      void apiFetchRecent('/api/search/recent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ search: normalized })
      }).catch(() => {});

      return next;
    });
  };

  return {
    recentSearches,
    setRecentSearches,
    saveRecentSearch,
  };
}
