import { useQuery } from '@tanstack/react-query';

import { CommodityQuote, fetchCommodities } from '@/src/services/api';

// Initial-load / offline staleness. Live updates arrive over the WebSocket
// (useLiveStream writes straight to this ['commodities'] cache), so we don't
// need aggressive polling here — the socket keeps it fresh when connected.
const STALE_MS = 60_000;

/**
 * Tracked commodity prices. First paint comes from this REST call; thereafter
 * the live stream pushes updates into the same cache key.
 *
 * Remember: items with `isProxy: true` are miner share prices, not spot prices.
 */
export function useCommodities() {
  return useQuery<CommodityQuote[]>({
    queryKey: ['commodities'],
    queryFn: fetchCommodities,
    staleTime: STALE_MS,
    // Gentle fallback poll in case the socket is down; the WS is the primary path.
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    retry: 1,
  });
}
