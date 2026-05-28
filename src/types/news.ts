export type NewsSource =
  | 'CNBC Indonesia'
  | 'Detik Finance'
  | 'Kontan'
  | 'Bisnis Indonesia'
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
  tickers: string[];
  importance: NewsImportance;
  category: NewsCategory;
}

// Used by FeedHeader filter chips and BeritaScreen filter logic
export type FeedFilter = 'all' | 'watchlist' | 'idx' | 'macro' | 'global';
