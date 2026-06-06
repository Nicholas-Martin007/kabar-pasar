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

import { useWatchlist } from '@/src/context/WatchlistContext';
import { telegramLink, telegramSync } from '@/src/services/api';

const STORAGE_KEY = 'kabarpasar.telegram.linkToken.v1';

interface TelegramLinkValue {
  isLinked: boolean;
  linking: boolean;
  error: string | null;
  /** Exchange a bot /link code; on success the watchlist auto-syncs from now on. */
  link: (code: string) => Promise<boolean>;
  unlink: () => void;
}

const TelegramLinkContext = createContext<TelegramLinkValue | null>(null);

export function TelegramLinkProvider({ children }: { children: React.ReactNode }) {
  const { items } = useWatchlist();
  const tickers = useMemo(() => items.map((i) => i.ticker), [items]);
  const tickersSig = tickers.join(',');

  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [linking, setLinking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hydrated = useRef(false);

  // Load persisted link token once.
  useEffect(() => {
    (async () => {
      try {
        const t = await AsyncStorage.getItem(STORAGE_KEY);
        if (t) setLinkToken(t);
      } catch {
        // ignore
      } finally {
        hydrated.current = true;
      }
    })();
  }, []);

  // Auto-sync the in-app watchlist to the linked chat whenever it changes.
  useEffect(() => {
    if (!linkToken) return;
    telegramSync(linkToken, tickers).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickersSig, linkToken]);

  const link = useCallback(
    async (code: string): Promise<boolean> => {
      setLinking(true);
      setError(null);
      try {
        const res = await telegramLink(code.trim(), tickers);
        if (res?.linkToken) {
          setLinkToken(res.linkToken);
          await AsyncStorage.setItem(STORAGE_KEY, res.linkToken);
          return true;
        }
        setError('Gagal menghubungkan. Coba lagi.');
        return false;
      } catch {
        setError('Kode tidak valid / kedaluwarsa, atau server tidak terjangkau.');
        return false;
      } finally {
        setLinking(false);
      }
    },
    [tickers]
  );

  const unlink = useCallback(() => {
    setLinkToken(null);
    AsyncStorage.removeItem(STORAGE_KEY).catch(() => {});
  }, []);

  const value = useMemo(
    () => ({ isLinked: !!linkToken, linking, error, link, unlink }),
    [linkToken, linking, error, link, unlink]
  );

  return (
    <TelegramLinkContext.Provider value={value}>
      {children}
    </TelegramLinkContext.Provider>
  );
}

export function useTelegramLink(): TelegramLinkValue {
  const ctx = useContext(TelegramLinkContext);
  if (!ctx)
    throw new Error('useTelegramLink must be used inside TelegramLinkProvider');
  return ctx;
}
