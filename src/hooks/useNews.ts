import { useQuery } from '@tanstack/react-query';

import { fallbackNews, fetchNews, NewsQuery } from '@/src/services/api';
import { News } from '@/src/types/news';

// News goes stale quickly — keep cache short so pulls/refocus refetch.
const STALE_MS = 60_000;

/**
 * Live news feed via React Query.
 *
 * Falls back to bundled mock data when the backend is unreachable or returns
 * nothing, so the app stays usable offline and before the API is running.
 * `isFallback` lets the UI surface a "demo data" hint if desired.
 */
export function useNewsFeed(params: NewsQuery = {}) {
  const query = useQuery({
    queryKey: ['news', params],
    queryFn: () => fetchNews(params),
    staleTime: STALE_MS,
    retry: 1,
  });

  const hasLive = !!query.data && query.data.length > 0;
  const data: News[] = hasLive ? query.data! : fallbackNews;

  return { ...query, data, isFallback: !hasLive };
}

/** A single news item, resolved from the (cached) feed. */
export function useNewsItem(id?: string) {
  const { data, ...rest } = useNewsFeed({ limit: 200 });
  const item = id ? data.find((n) => n.id === id) : undefined;
  return { ...rest, news: item, allNews: data };
}
