import { useEffect, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';

import { STREAM_WS_URL, CommodityQuote } from '@/src/services/api';

export type LiveStatus = 'connecting' | 'open' | 'offline';

/** Envelope shape broadcast by backend/routers/stream.py. */
interface Envelope {
  type: 'news' | 'commodity' | 'heartbeat';
  ts: string | null;
  data: unknown;
}

// Coalesce a burst of news pushes into a single refetch.
const NEWS_DEBOUNCE_MS = 400;
// Reconnect backoff ceiling.
const MAX_BACKOFF_MS = 30_000;

/**
 * Single live WebSocket connection feeding the React Query cache.
 *
 * Design choices:
 * - **News → invalidate, don't hand-merge.** A news push just marks the
 *   `['news']` queries stale so React Query refetches the authoritative,
 *   already-deduped-and-ordered list from the backend. Debounced so a burst of
 *   new articles costs one refetch, not N.
 * - **Commodity → write straight to cache.** The payload is the full basket in
 *   final shape, so we set `['commodities']` directly — no refetch needed.
 * - **AppState aware.** iOS suspends sockets in the background anyway; we close
 *   on background (saves battery, avoids a zombie socket) and reconnect on
 *   foreground. React Query's own refetch-on-focus covers the gap.
 * - **Reconnect with exponential backoff + jitter**, reset on a clean open.
 *
 * Runs once at app root via LiveProvider. Returns the connection status for a
 * "live" indicator.
 */
export function useLiveStream(): LiveStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<LiveStatus>('connecting');

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let newsDebounce: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    // True while we intentionally don't want a socket (unmounted / backgrounded)
    // — stops onclose from scheduling a reconnect against our wishes.
    let suspended = false;
    let appState: AppStateStatus = AppState.currentState;

    const clearReconnect = () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const handle = (env: Envelope) => {
      if (env.type === 'commodity' && Array.isArray(env.data)) {
        queryClient.setQueryData<CommodityQuote[]>(
          ['commodities'],
          env.data as CommodityQuote[]
        );
      } else if (env.type === 'news') {
        if (newsDebounce) clearTimeout(newsDebounce);
        newsDebounce = setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: ['news'] });
        }, NEWS_DEBOUNCE_MS);
      }
      // heartbeat: no-op — its only job is to keep the socket & proxies alive.
    };

    const scheduleReconnect = () => {
      if (suspended || reconnectTimer) return;
      const backoff = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS);
      attempt += 1;
      const delay = backoff * (0.75 + Math.random() * 0.5); // ±25% jitter
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        open();
      }, delay);
    };

    const open = () => {
      if (suspended || ws) return;
      setStatus((s) => (s === 'open' ? s : 'connecting'));

      let sock: WebSocket;
      try {
        sock = new WebSocket(STREAM_WS_URL);
      } catch {
        scheduleReconnect();
        return;
      }
      ws = sock;

      sock.onopen = () => {
        attempt = 0;
        setStatus('open');
      };
      sock.onmessage = (e: WebSocketMessageEvent) => {
        try {
          handle(JSON.parse(e.data as string) as Envelope);
        } catch {
          // ignore malformed frame
        }
      };
      sock.onerror = () => {
        // onclose fires next and owns reconnection.
      };
      sock.onclose = () => {
        if (ws === sock) ws = null;
        if (!suspended) {
          setStatus('offline');
          scheduleReconnect();
        }
      };
    };

    const teardownSocket = () => {
      clearReconnect();
      if (ws) {
        // Detach handlers so the close we trigger can't loop back into reconnect.
        ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
        try {
          ws.close();
        } catch {
          // already closing
        }
        ws = null;
      }
    };

    // Initial connect.
    open();

    const sub = AppState.addEventListener('change', (next) => {
      const wasActive = appState === 'active';
      const nowActive = next === 'active';
      appState = next;

      if (nowActive && !wasActive) {
        suspended = false;
        attempt = 0;
        open();
      } else if (!nowActive && wasActive) {
        suspended = true;
        setStatus('offline');
        teardownSocket();
      }
    });

    return () => {
      suspended = true;
      sub.remove();
      if (newsDebounce) clearTimeout(newsDebounce);
      teardownSocket();
    };
  }, [queryClient]);

  return status;
}
