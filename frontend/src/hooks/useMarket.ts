import { useQuery } from '@tanstack/react-query';

import {
  ChartRange,
  fetchChart,
  fetchIndex,
  fetchQuote,
  fetchQuotes,
  fetchReaction,
  fetchReactions,
  Quote,
  ReactionItem,
} from '@/src/services/api';

// Quotes refresh often during market hours; keep cache short.
const STALE_MS = 30_000;

/** IHSG index quote. Returns undefined data while loading / on error. */
export function useIndex() {
  return useQuery({
    queryKey: ['market', 'index'],
    queryFn: fetchIndex,
    staleTime: STALE_MS,
    retry: 1,
  });
}

/** Live quote for a single stock. */
export function useQuote(ticker?: string) {
  return useQuery({
    queryKey: ['market', 'quote', ticker],
    queryFn: () => fetchQuote(ticker!),
    enabled: !!ticker,
    staleTime: STALE_MS,
    retry: 1,
  });
}

/** Batched live quotes for a watchlist. Returns a ticker -> Quote Map. */
export function useQuotes(tickers: string[]) {
  const sig = [...tickers].sort().join(',');
  return useQuery({
    queryKey: ['market', 'quotes', sig],
    queryFn: () => fetchQuotes(tickers),
    enabled: tickers.length > 0,
    staleTime: STALE_MS,
    retry: 1,
    select: (list): Map<string, Quote> => {
      const map = new Map<string, Quote>();
      for (const q of list) if (q.ticker) map.set(q.ticker, q);
      return map;
    },
  });
}

/** Sparkline points for a ticker over a range. */
export function useChart(ticker?: string, range: ChartRange = '1M') {
  return useQuery({
    queryKey: ['market', 'chart', ticker, range],
    queryFn: () => fetchChart(ticker!, range),
    enabled: !!ticker,
    staleTime: STALE_MS,
    retry: 1,
  });
}

/**
 * Price reaction after a news item. Historical once computed, so cache long.
 */
export function useReaction(ticker?: string, atISO?: string, windowMin = 60) {
  return useQuery({
    queryKey: ['market', 'reaction', ticker, atISO, windowMin],
    queryFn: () => fetchReaction(ticker!, atISO!, windowMin),
    enabled: !!ticker && !!atISO,
    staleTime: 5 * 60_000,
    retry: 1,
  });
}

/**
 * Batched reactions for a list of news items (one request). Returns a Map keyed
 * by each item's `key` for easy per-card lookup. Cache long — historical data.
 */
export function useReactions(items: ReactionItem[]) {
  const keySig = items.map((i) => `${i.key}:${i.ticker}:${i.at}`).join('|');
  return useQuery({
    queryKey: ['market', 'reactions', keySig],
    queryFn: () => fetchReactions(items),
    enabled: items.length > 0,
    staleTime: 5 * 60_000,
    retry: 1,
    select: (list) => {
      const map = new Map<string, (typeof list)[number]>();
      for (const r of list) if (r.key) map.set(r.key, r);
      return map;
    },
  });
}
