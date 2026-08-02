import { useCallback, useRef, useState } from 'react';

import {
  areLiveActivitiesEnabled,
  endStockActivity,
  startStockActivity,
  updateStockActivity,
  type StockActivityState,
  type StockActivityStatic,
} from '@/src/services/liveActivity';

/**
 * Drive a single stock Live Activity from a screen (e.g. Stock Detail).
 *
 * Phase 1 (local updates): call `start` when the user pins a stock, `update`
 * when fresh price/news arrives while the app is foregrounded, `end` to stop.
 *
 * Phase 2 (push): replace local `update` with backend APNs pushes to the
 * activity's push token — see docs/LIVE_ACTIVITY_SETUP.md.
 */
export function useStockLiveActivity() {
  const activityId = useRef<string | null>(null);
  const [isActive, setIsActive] = useState(false);

  const start = useCallback(
    (info: StockActivityStatic, state: StockActivityState): boolean => {
      if (!areLiveActivitiesEnabled()) return false;
      if (activityId.current) return true; // already running
      const id = startStockActivity(info, state);
      if (id) {
        activityId.current = id;
        setIsActive(true);
        return true;
      }
      return false;
    },
    []
  );

  const update = useCallback((state: StockActivityState) => {
    if (activityId.current) updateStockActivity(activityId.current, state);
  }, []);

  const end = useCallback(() => {
    if (activityId.current) {
      endStockActivity(activityId.current);
      activityId.current = null;
      setIsActive(false);
    }
  }, []);

  return { isActive, start, update, end, isSupported: areLiveActivitiesEnabled };
}
