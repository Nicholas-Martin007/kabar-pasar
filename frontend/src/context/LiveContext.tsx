import React, { createContext, useContext } from 'react';

import { LiveStatus, useLiveStream } from '@/src/hooks/useLiveStream';

/**
 * Holds the single app-wide live WebSocket connection. Mount once, high in the
 * tree and INSIDE QueryClientProvider (the stream writes to the query cache).
 * Any screen can read the connection status via `useLive()` for a LIVE badge.
 */
const LiveContext = createContext<LiveStatus>('connecting');

export function LiveProvider({ children }: { children: React.ReactNode }) {
  const status = useLiveStream();
  return <LiveContext.Provider value={status}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveStatus {
  return useContext(LiveContext);
}
