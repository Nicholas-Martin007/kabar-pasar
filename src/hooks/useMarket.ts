import { useQuery } from '@tanstack/react-query';

import {
  ChartRange,
  fetchChart,
  fetchIndex,
  fetchQuote,
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
