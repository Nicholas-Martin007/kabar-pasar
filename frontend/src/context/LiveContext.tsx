import React, { createContext, useContext, useMemo } from 'react';

import { LiveState, LiveStatus, useLiveStream } from '@/src/hooks/useLiveStream';

interface LiveContextValue extends LiveState {
  /** True while an item should still show its "just arrived" highlight. */
  isFresh: (id: string) => boolean;
}

/**
 * Holds the single app-wide live WebSocket connection. Mount once, high in the
 * tree and INSIDE QueryClientProvider (the stream writes to the query cache).
 * Screens read connection status for the LIVE badge and `isFresh` for the
 * new-item flash.
 */
const LiveContext = createContext<LiveContextValue>({
  status: 'connecting',
  freshIds: new Set(),
  isFresh: () => false,
});

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const { status, freshIds } = useLiveStream();

  const value = useMemo<LiveContextValue>(
    () => ({ status, freshIds, isFresh: (id: string) => freshIds.has(id) }),
    [status, freshIds]
  );

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

/** Connection status only — for the LIVE badge. */
export function useLive(): LiveStatus {
  return useContext(LiveContext).status;
}

/** Full live state, including the fresh-item helper. */
export function useLiveState(): LiveContextValue {
  return useContext(LiveContext);
}
