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

const STORAGE_KEY = 'kabarpasar.read.v1';
const MAX_TRACKED = 500; // cap stored ids so storage doesn't grow unbounded

interface ReadContextValue {
  isRead: (id: string) => boolean;
  markRead: (id: string) => void;
}

const ReadContext = createContext<ReadContextValue | null>(null);

export function ReadProvider({ children }: { children: React.ReactNode }) {
  const [ids, setIds] = useState<Set<string>>(new Set());
  const hydrated = useRef(false);

  useEffect(() => {
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) setIds(new Set(parsed));
        }
      } catch {
        // ignore
      } finally {
        hydrated.current = true;
      }
    })();
  }, []);

  useEffect(() => {
    if (!hydrated.current) return;
    // Keep only the most-recent MAX_TRACKED ids.
    const arr = [...ids].slice(-MAX_TRACKED);
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(arr)).catch(() => {});
  }, [ids]);

  const markRead = useCallback((id: string) => {
    setIds((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  }, []);

  const isRead = useCallback((id: string) => ids.has(id), [ids]);

  const value = useMemo(() => ({ isRead, markRead }), [isRead, markRead]);

  return <ReadContext.Provider value={value}>{children}</ReadContext.Provider>;
}

export function useRead(): ReadContextValue {
  const ctx = useContext(ReadContext);
  if (!ctx) throw new Error('useRead must be used inside ReadProvider');
  return ctx;
}
