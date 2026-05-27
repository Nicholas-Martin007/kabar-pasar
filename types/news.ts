export type ImportanceLevel = 'critical' | 'high' | 'medium' | 'low';

export type NewsSource =
  | 'IDX'
  | 'CNBC Indonesia'
  | 'Kontan'
  | 'Bisnis Indonesia'
  | 'Detik Finance'
  | 'Reuters'
  | 'CNBC Global';

export type NewsCategory = 'announcement' | 'market' | 'macro' | 'sector' | 'global';

export type FeedFilter = 'all' | 'watchlist' | 'idx' | 'macro' | 'global';

export interface NewsItem {
  id: string;
  title: string;
  aiSummary: string;
  source: NewsSource;
  publishedAt: string;
  importance: ImportanceLevel;
  ticker?: string;
  priceChange?: number;
  category: NewsCategory;
  isRead: boolean;
  isBookmarked: boolean;
}
