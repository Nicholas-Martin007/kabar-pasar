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
export const API_BASE_URL = (
  process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000'
).replace(/\/+$/, '');

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
  symbol: string;
  price: number | null;
  previousClose: number | null;
  change: number | null;
  changePercent: number | null;
  currency: string | null;
  marketState: string | null;
  sparkline: (number | null)[];
}

export interface ChartResponse {
  ticker: string;
  range: string;
  currency: string | null;
  points: (number | null)[];
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
  ticker: string;
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

/** Bundled mock feed — used as an offline/dev fallback (see useNews hooks). */
export const fallbackNews: News[] = mockNews;
