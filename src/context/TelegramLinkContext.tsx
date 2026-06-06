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
import {
  TelegramPrefs,
  telegramGetPrefs,
  telegramLink,
  telegramSetPrefs,
  telegramSync,
} from '@/src/services/api';

const STORAGE_KEY = 'kabarpasar.telegram.linkToken.v1';

interface TelegramLinkValue {
  isLinked: boolean;
  linking: boolean;
  error: string | null;
  /** Exchange a bot /link code; on success the watchlist auto-syncs from now on. */
  link: (code: string) => Promise<boolean>;
  unlink: () => void;
  // Bot preferences (when linked).
  prefs: TelegramPrefs | null;
  setAllNews: (on: boolean) => void;
  addMute: (topic: string) => void;
  removeMute: (topic: string) => void;
}

const TelegramLinkContext = createContext<TelegramLinkValue | null>(null);

export function TelegramLinkProvider({ children }: { children: React.ReactNode }) {
  const { items } = useWatchlist();
  const tickers = useMemo(() => items.map((i) => i.ticker), [items]);
  const tickersSig = tickers.join(',');

  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [linking, setLinking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<TelegramPrefs | null>(null);
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

  // Load bot prefs when linked.
  useEffect(() => {
    if (!linkToken) {
      setPrefs(null);
      return;
    }
    telegramGetPrefs(linkToken)
      .then(setPrefs)
      .catch(() => {});
  }, [linkToken]);

  const setAllNews = useCallback(
    (on: boolean) => {
      if (!linkToken) return;
      setPrefs((p) => (p ? { ...p, all_news: on } : p)); // optimistic
      telegramSetPrefs(linkToken, { all_news: on })
        .then(setPrefs)
        .catch(() => {});
    },
    [linkToken]
  );

  const addMute = useCallback(
    (topic: string) => {
      const t = topic.trim().toLowerCase();
      if (!linkToken || !t) return;
      const next = Array.from(new Set([...(prefs?.mute ?? []), t]));
      telegramSetPrefs(linkToken, { mute: next })
        .then(setPrefs)
        .catch(() => {});
    },
    [linkToken, prefs]
  );

  const removeMute = useCallback(
    (topic: string) => {
      if (!linkToken) return;
      const next = (prefs?.mute ?? []).filter((m) => m !== topic);
      telegramSetPrefs(linkToken, { mute: next })
        .then(setPrefs)
        .catch(() => {});
    },
    [linkToken, prefs]
  );

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
    () => ({
      isLinked: !!linkToken,
      linking,
      error,
      link,
      unlink,
      prefs,
      setAllNews,
      addMute,
      removeMute,
    }),
    [linkToken, linking, error, link, unlink, prefs, setAllNews, addMute, removeMute]
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
