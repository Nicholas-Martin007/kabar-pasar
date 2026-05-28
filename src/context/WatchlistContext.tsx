import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react';

import { mockWatchlist } from '@/src/data/mockWatchlist';
import { WatchlistItem } from '@/src/types/watchlist';

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
