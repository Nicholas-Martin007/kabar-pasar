export type NewsSource =
  | 'CNBC Indonesia'
  | 'Detik Finance'
  | 'Kontan'
  | 'Bisnis Indonesia'
  | 'Bloomberg Technoz'
  | 'Yahoo Finance'
  | 'CNBC Global'
  | 'BEI'
  | 'IR Emiten';

export type NewsImportance = 'high' | 'medium' | 'low';

export type NewsCategory =
  | 'corporate_action'
  | 'earnings'
  | 'market_news'
  | 'regulatory'
  | 'macro';

export interface News {
  id: string;
  title: string;
  source: NewsSource;
  publishedAt: string;
  excerpt: string;
  aiSummary: string[];
  /** One-sentence investor impact line from the backend AI summariser. */
  impact?: string;
  tickers: string[];
  importance: NewsImportance;
  category: NewsCategory;
  url?: string;
}

// Used by FeedHeader filter chips and BeritaScreen filter logic
export type FeedFilter = 'all' | 'watchlist' | 'idx' | 'macro' | 'global';
