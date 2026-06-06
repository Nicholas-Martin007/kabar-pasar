import { Platform } from 'react-native';

/**
 * Typed wrapper around react-native-widget-extension for stock Live Activities.
 *
 * The lock-screen / Dynamic Island UI lives in native SwiftUI (see
 * widgets/StockLiveActivity.swift). This module only starts / updates / ends
 * the activity and ships the dynamic data.
 *
 * ⚠️ VERIFY ON DEVICE: the argument order below must match widgets/Module.swift
 * and the installed library's TS signature. See docs/LIVE_ACTIVITY_SETUP.md.
 *
 * Safe to import on Android/web — every call no-ops off iOS.
 */

// Lazy require so the app doesn't crash if the native module isn't built yet
// (e.g. running in Expo Go before a dev build exists).
type WidgetExtension = {
  areActivitiesEnabled: () => boolean;
  startActivity: (...args: unknown[]) => string;
  updateActivity: (...args: unknown[]) => void;
  endActivity: (...args: unknown[]) => void;
};

let native: WidgetExtension | null = null;
function getNative(): WidgetExtension | null {
  if (Platform.OS !== 'ios') return null;
  if (native) return native;
  try {
    // Dynamic (variable) module name so Metro does NOT statically resolve this
    // at bundle time — the package is only present on builds that include the
    // widget extension. Falls back to null elsewhere (e.g. dev app, Android).
    const moduleName = 'react-native-widget-extension';
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    native = require(moduleName) as WidgetExtension;
  } catch {
    native = null; // native module not installed / not built yet
  }
  return native;
}

export interface StockActivityStatic {
  ticker: string;
  companyName: string;
}

export interface StockActivityState {
  /** Pre-formatted price string, e.g. "Rp 10.250". */
  price: string;
  changePercent: number;
  headline: string;
  /** ISO 8601; defaults to now if omitted. */
  updatedAt?: string;
}

/** Whether the user has Live Activities enabled in iOS settings. */
export function areLiveActivitiesEnabled(): boolean {
  return getNative()?.areActivitiesEnabled() ?? false;
}

/** Start a Live Activity for a stock. Returns the activity id, or null. */
export function startStockActivity(
  info: StockActivityStatic,
  state: StockActivityState
): string | null {
  const mod = getNative();
  if (!mod) return null;
  const id = mod.startActivity(
    info.ticker,
    info.companyName,
    state.price,
    state.changePercent,
    state.headline,
    state.updatedAt ?? new Date().toISOString()
  );
  return id || null;
}

/** Update an existing Live Activity's dynamic state (local update). */
export function updateStockActivity(
  activityId: string,
  state: StockActivityState
): void {
  getNative()?.updateActivity(
    activityId,
    state.price,
    state.changePercent,
    state.headline,
    state.updatedAt ?? new Date().toISOString()
  );
}

/** End a Live Activity. */
export function endStockActivity(activityId: string): void {
  getNative()?.endActivity(activityId);
}
