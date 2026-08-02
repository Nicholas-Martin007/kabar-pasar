import AsyncStorage from '@react-native-async-storage/async-storage';
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

const STORAGE_KEY = 'kabarpasar.bookmarks.v1';

interface BookmarksContextValue {
  ids: Set<string>;
  isBookmarked: (id: string) => boolean;
  toggle: (id: string) => void;
  count: number;
}

const BookmarksContext = createContext<BookmarksContextValue | null>(null);

export function BookmarksProvider({ children }: { children: React.ReactNode }) {
  const [ids, setIds] = useState<Set<string>>(new Set());
  const hydrated = useRef(false);

  // Load persisted bookmarks once on mount.
  useEffect(() => {
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) setIds(new Set(parsed));
        }
      } catch {
        // ignore storage errors
      } finally {
        hydrated.current = true;
      }
    })();
  }, []);

  // Persist on change (after hydration).
  useEffect(() => {
    if (!hydrated.current) return;
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify([...ids])).catch(() => {});
  }, [ids]);

  const toggle = useCallback((id: string) => {
    setIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const isBookmarked = useCallback((id: string) => ids.has(id), [ids]);

  const value = useMemo(
    () => ({ ids, isBookmarked, toggle, count: ids.size }),
    [ids, isBookmarked, toggle]
  );

  return (
    <BookmarksContext.Provider value={value}>
      {children}
    </BookmarksContext.Provider>
  );
}

export function useBookmarks(): BookmarksContextValue {
  const ctx = useContext(BookmarksContext);
  if (!ctx) throw new Error('useBookmarks must be used inside BookmarksProvider');
  return ctx;
}
