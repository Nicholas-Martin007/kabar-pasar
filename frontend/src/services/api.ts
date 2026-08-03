import Constants from 'expo-constants';

import { mockNews } from '@/src/data/mockNews';
import { News } from '@/src/types/news';

/**
 * Base URL of the Kabar Pasar FastAPI backend.
 * Configure via EXPO_PUBLIC_API_URL in `.env` (see `.env.example`).
 *
 * NOTE: on a physical device "localhost" resolves to the phone itself, not
 * your dev machine — use your computer's LAN IP instead, e.g.
 *   EXPO_PUBLIC_API_URL=http://192.168.1.10:8000
 */
/** Port the FastAPI backend listens on. */
const BACKEND_PORT = 8000;

/**
 * Best-effort LAN host of the dev machine, taken from the Expo dev-server
 * connection (e.g. hostUri "192.168.1.3:8081" -> "192.168.1.3").
 *
 * This exists because a hard-coded LAN IP in .env goes stale every time DHCP
 * hands out a new address or you move network — and the failure is silent and
 * confusing: the socket just hangs in CONNECTING until TCP times out. The
 * phone already reached Metro on the right host, so we reuse it.
 *
 * Returns null on web / production builds, where there is no dev server.
 */
function devServerHost(): string | null {
  const hostUri =
    (Constants.expoConfig as { hostUri?: string } | null)?.hostUri ??
    // Older/!== SDK shapes keep it here instead.
    (Constants as unknown as { expoGoConfig?: { debuggerHost?: string } })
      .expoGoConfig?.debuggerHost;
  if (!hostUri) return null;
  const host = hostUri.split(':')[0]?.trim();
  if (!host || host === 'localhost' || host === '127.0.0.1') return null;
  return host;
}

function resolveBaseUrl(): string {
  // Explicit override always wins — needed to point at a remote backend.
  const fromEnv = process.env.EXPO_PUBLIC_API_URL?.trim();
  if (fromEnv) return fromEnv;

  const host = devServerHost();
  if (host) return `http://${host}:${BACKEND_PORT}`;

  return `http://localhost:${BACKEND_PORT}`;
}

export const API_BASE_URL = resolveBaseUrl().replace(/\/+$/, '');

/**
 * WebSocket URL for the live event stream (news + commodity pushes).
 * Derives from API_BASE_URL: http -> ws, https -> wss (the `^http` also
 * matches the "http" inside "https", turning it into "wss").
 */
export const STREAM_WS_URL = API_BASE_URL.replace(/^http/, 'ws') + '/stream/ws';

const REQUEST_TIMEOUT_MS = 8000;

export interface NewsQuery {
  limit?: number;
  /** Backend NewsSource value, e.g. "CNBC Indonesia" */
  source?: string;
  /** "high" | "medium" | "low" */
  importance?: string;
  /** e.g. "BBCA" */
  ticker?: string;
}

async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      throw new Error(`API ${res.status} ${res.statusText} on ${path}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timeout);
  }
}

function buildQuery(params: NewsQuery): string {
  const qs = new URLSearchParams();
  if (params.limit) qs.set('limit', String(params.limit));
  if (params.source) qs.set('source', params.source);
  if (params.importance) qs.set('importance', params.importance);
  if (params.ticker) qs.set('ticker', params.ticker);
  const s = qs.toString();
  return s ? `?${s}` : '';
}

/**
 * Fetch the news feed from the backend. The API already serialises camelCase
 * fields that match the `News` interface, so no field mapping is needed.
 */
export async function fetchNews(params: NewsQuery = {}): Promise<News[]> {
  return getJSON<News[]>(`/news${buildQuery(params)}`);
}

/** Manually trigger a backend fetch + AI-summarise cycle. */
export async function triggerRefresh(): Promise<Record<string, unknown>> {
  return getJSON('/refresh', { method: 'POST' });
}

// ── Market data (Yahoo Finance via backend) ──────────────────────────────────

export interface Quote {
  ticker: string;
  symbol?: string;
  available?: boolean;
  price: number | null;
  previousClose?: number | null;
  change: number | null;
  changePercent: number | null;
  currency?: string | null;
  marketState?: string | null;
  sparkline: (number | null)[];
  // Fundamentals (from Yahoo chart meta — single-quote endpoint only).
  dayLow?: number | null;
  dayHigh?: number | null;
  week52Low?: number | null;
  week52High?: number | null;
  volume?: number | null;
  longName?: string | null;
}

export interface Candle {
  o: number;
  h: number;
  l: number;
  c: number;
}

export interface ChartResponse {
  ticker: string;
  range: string;
  currency: string | null;
  points: (number | null)[];
  candles: Candle[];
}

export type ChartRange = '1H' | '1D' | '1W' | '1M' | '1Y';

/** IHSG (Jakarta Composite Index) quote. */
export async function fetchIndex(): Promise<Quote> {
  return getJSON<Quote>('/market/index');
}

/** Live quote for a single IDX stock, e.g. "BBCA". */
export async function fetchQuote(ticker: string): Promise<Quote> {
  return getJSON<Quote>(`/market/quote/${encodeURIComponent(ticker)}`);
}

/** Batched live quotes for a watchlist — one request for many tickers. */
export async function fetchQuotes(tickers: string[]): Promise<Quote[]> {
  if (tickers.length === 0) return [];
  const res = await getJSON<{ quotes: Quote[] }>(
    `/market/quotes?tickers=${encodeURIComponent(tickers.join(','))}`
  );
  return res.quotes;
}

/** Sparkline points for a ticker over a time range. */
export async function fetchChart(
  ticker: string,
  range: ChartRange = '1M'
): Promise<ChartResponse> {
  return getJSON<ChartResponse>(
    `/market/chart/${encodeURIComponent(ticker)}?range=${range}`
  );
}

export interface Reaction {
  available: boolean;
  ticker?: string;
  /** Echoed back in batch responses so callers can map to rows (e.g. news id). */
  key?: string;
  basePrice?: number | null;
  afterPrice?: number | null;
  reactionPercent?: number | null;
  windowMinutes?: number;
  interval?: string;
  reason?: string;
}

/** How a stock's price reacted in the window after a news item was published. */
export async function fetchReaction(
  ticker: string,
  atISO: string,
  windowMin = 60
): Promise<Reaction> {
  return getJSON<Reaction>(
    `/market/reaction/${encodeURIComponent(ticker)}` +
      `?at=${encodeURIComponent(atISO)}&window=${windowMin}`
  );
}

export interface ReactionItem {
  key?: string;
  ticker: string;
  at: string;
  window?: number;
}

/** Batched reaction lookup — one request for many feed cards. */
export async function fetchReactions(
  items: ReactionItem[]
): Promise<Reaction[]> {
  const res = await getJSON<{ reactions: Reaction[] }>('/market/reactions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  });
  return res.reactions;
}

// ── Commodities (yfinance via backend) ───────────────────────────────────────

export interface CommodityQuote {
  symbol: string;
  name: string;
  price: number;
  currency: string;
  change: number | null;
  changePercent: number | null;
  /**
   * TRUE = an Indonesian miner's share price standing in for a commodity that
   * has no free Yahoo futures contract (coal, nickel). It is NOT a spot price —
   * the UI must label it as a proxy. See scrapers/commodity_tracker.py.
   */
  isProxy: boolean;
  recordedAt?: string | null;
}

/**
 * Latest observed price per tracked commodity. The live WebSocket stream pushes
 * the same shape into the ['commodities'] query cache, so this REST call is just
 * the initial load / offline fallback.
 */
export async function fetchCommodities(): Promise<CommodityQuote[]> {
  const res = await getJSON<{ items: CommodityQuote[] }>('/commodities');
  return res.items ?? [];
}

// ── Telegram linking ─────────────────────────────────────────────────────────

export async function telegramEnabled(): Promise<{ enabled: boolean }> {
  return getJSON('/telegram/enabled');
}

/** Exchange a /link code (from the bot) for a persistent link token. */
export async function telegramLink(
  code: string,
  tickers: string[]
): Promise<{ ok: boolean; linkToken: string }> {
  return getJSON('/telegram/link', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, tickers }),
  });
}

/** Push the current in-app watchlist to the linked Telegram chat. */
export async function telegramSync(
  linkToken: string,
  tickers: string[]
): Promise<{ ok: boolean }> {
  return getJSON('/telegram/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ linkToken, tickers }),
  });
}

export async function telegramStatus(
  linkToken: string
): Promise<{ linked: boolean; tickers: string[] }> {
  return getJSON(`/telegram/status?linkToken=${encodeURIComponent(linkToken)}`);
}

export interface TelegramPrefs {
  tickers: string[];
  keywords: string[];
  mute: string[];
  all_news: boolean;
  high_only: boolean;
}

export async function telegramGetPrefs(linkToken: string): Promise<TelegramPrefs> {
  return getJSON(`/telegram/prefs?linkToken=${encodeURIComponent(linkToken)}`);
}

export async function telegramSetPrefs(
  linkToken: string,
  patch: { all_news?: boolean; mute?: string[]; high_only?: boolean }
): Promise<TelegramPrefs> {
  return getJSON('/telegram/prefs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ linkToken, ...patch }),
  });
}

/** Bundled mock feed — used as an offline/dev fallback (see useNews hooks). */
export const fallbackNews: News[] = mockNews;
