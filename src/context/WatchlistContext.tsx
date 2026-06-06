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

import { mockWatchlist } from '@/src/data/mockWatchlist';
import { WatchlistItem } from '@/src/types/watchlist';

const STORAGE_KEY = 'kabarpasar.watchlist.v1';

interface WatchlistContextValue {
  items: WatchlistItem[];
  tickers: Set<string>;
  add: (ticker: string) => void;
  remove: (ticker: string) => void;
  toggle: (ticker: string) => void;
  contains: (ticker: string) => boolean;
}

const WatchlistContext = createContext<WatchlistContextValue | null>(null);

export function WatchlistProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<WatchlistItem[]>(mockWatchlist);
  const hydrated = useRef(false);

  // Load the persisted watchlist once on mount (seed it on first run).
  useEffect(() => {
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (raw != null) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) setItems(parsed);
        } else {
          await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(mockWatchlist));
        }
      } catch {
        // ignore storage errors — fall back to the in-memory seed
      } finally {
        hydrated.current = true;
      }
    })();
  }, []);

  // Persist on every change (after hydration, so we don't clobber stored data).
  useEffect(() => {
    if (!hydrated.current) return;
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(items)).catch(() => {});
  }, [items]);

  const tickers = useMemo(() => new Set(items.map((i) => i.ticker)), [items]);

  const add = useCallback((ticker: string) => {
    setItems((prev) => {
      if (prev.some((i) => i.ticker === ticker)) return prev;
      return [...prev, { ticker, addedAt: new Date().toISOString() }];
    });
  }, []);

  const remove = useCallback((ticker: string) => {
    setItems((prev) => prev.filter((i) => i.ticker !== ticker));
  }, []);

  const toggle = useCallback((ticker: string) => {
    setItems((prev) =>
      prev.some((i) => i.ticker === ticker)
        ? prev.filter((i) => i.ticker !== ticker)
        : [...prev, { ticker, addedAt: new Date().toISOString() }]
    );
  }, []);

  const contains = useCallback((ticker: string) => tickers.has(ticker), [tickers]);

  const value = useMemo(
    () => ({ items, tickers, add, remove, toggle, contains }),
    [items, tickers, add, remove, toggle, contains]
  );

  return (
    <WatchlistContext.Provider value={value}>
      {children}
    </WatchlistContext.Provider>
  );
}

export function useWatchlist(): WatchlistContextValue {
  const ctx = useContext(WatchlistContext);
  if (!ctx) throw new Error('useWatchlist must be used inside WatchlistProvider');
  return ctx;
}
