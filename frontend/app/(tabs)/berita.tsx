import React, { useCallback, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { router } from 'expo-router';

import { FeedHeader } from '@/components/feed-header';
import { NewsCard } from '@/components/news-card';
import { useBookmarks } from '@/src/context/BookmarksContext';
import { useLiveState } from '@/src/context/LiveContext';
import { useRead } from '@/src/context/ReadContext';
import { useNewsFeed } from '@/src/hooks/useNews';
import { useIndex, useReactions } from '@/src/hooks/useMarket';
import { ReactionItem } from '@/src/services/api';
import { Colors, FontSize, Layout } from '@/src/theme';
import { FeedFilter, News, NewsCategory } from '@/src/types/news';
import { getMarketStatus } from '@/utils/market';

// Cap how many cards request a reaction (keeps the batch polite to Yahoo).
const MAX_REACTIONS = 40;

// Fallback used only when the live IHSG quote is unavailable (offline).
const IHSG_FALLBACK = { value: 7_234.12, change: 0.82 };

const CATEGORY_FOR_FILTER: Record<FeedFilter, NewsCategory[]> = {
  all:       ['corporate_action', 'earnings', 'market_news', 'regulatory', 'macro'],
  watchlist: ['corporate_action', 'earnings'],
  idx:       ['corporate_action', 'earnings', 'regulatory'],
  macro:     ['macro'],
  global:    ['market_news'],
};

export default function BeritaScreen() {
  const { data: allNews, refetch: refetchNews } = useNewsFeed();
  const { data: indexQuote, refetch: refetchIndex } = useIndex();
  const { isBookmarked, toggle: handleBookmark } = useBookmarks();
  const { isRead, markRead } = useRead();
  const { isFresh } = useLiveState();
  const [activeFilter,  setActiveFilter]  = useState<FeedFilter>('all');
  const [refreshing,     setRefreshing]    = useState(false);

  const filtered = React.useMemo(
    () =>
      [...allNews]
        .sort(
          (a, b) =>
            new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime()
        )
        .filter((item) =>
          CATEGORY_FOR_FILTER[activeFilter].includes(item.category)
        ),
    [allNews, activeFilter]
  );

  // Batch one reaction request for the visible cards that have a ticker.
  const reactionItems: ReactionItem[] = React.useMemo(
    () =>
      filtered
        .filter((n) => n.tickers.length > 0)
        .slice(0, MAX_REACTIONS)
        .map((n) => ({ key: n.id, ticker: n.tickers[0], at: n.publishedAt })),
    [filtered]
  );
  const { data: reactionMap, isLoading: reactionsLoading, refetch: refetchReactions } =
    useReactions(reactionItems);

  const handlePress = useCallback((id: string) => {
    markRead(id);
    router.push(`/news/${id}` as never);
  }, [markRead]);

  // Live IHSG snapshot for the header (mock fallback when offline).
  const market = React.useMemo(
    () => ({
      index: 'IHSG',
      value: indexQuote?.price ?? IHSG_FALLBACK.value,
      change: indexQuote?.changePercent ?? IHSG_FALLBACK.change,
      isOpen: getMarketStatus().isOpen,
    }),
    [indexQuote]
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await Promise.all([refetchNews(), refetchReactions(), refetchIndex()]);
    } finally {
      setRefreshing(false);
    }
  }, [refetchNews, refetchReactions, refetchIndex]);

  const renderItem = useCallback(
    ({ item }: { item: News }) => (
      <NewsCard
        item={item}
        isRead={isRead(item.id)}
        isBookmarked={isBookmarked(item.id)}
        onPress={handlePress}
        onBookmark={handleBookmark}
        reaction={reactionMap?.get(item.id)}
        reactionLoading={reactionsLoading}
        isFresh={isFresh(item.id)}
      />
    ),
    // isFresh must stay in here: it changes identity when a live item arrives,
    // and without it this callback keeps a stale closure and the flash never
    // fires.
    [isRead, isBookmarked, handlePress, handleBookmark, reactionMap, reactionsLoading, isFresh]
  );

  const renderHeader = useCallback(
    () => (
      <FeedHeader
        activeFilter={activeFilter}
        onFilterChange={setActiveFilter}
        onNotification={() => {}}
        market={market}
      />
    ),
    [activeFilter, market]
  );

  const renderEmpty = () => (
    <View style={styles.emptyState}>
      <Text style={styles.emptyText}>Tidak ada berita untuk filter ini.</Text>
    </View>
  );

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <FlatList
        data={filtered}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        ListHeaderComponent={renderHeader}
        ListEmptyComponent={renderEmpty}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={Colors.brand.accent}
            colors={[Colors.brand.accent]}
          />
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Colors.background.screen,
  },
  listContent: {
    paddingBottom: Layout.listPaddingBottom,
  },
  separator: {
    height: 0,
  },
  emptyState: {
    alignItems: 'center',
    paddingTop: Layout.emptyPaddingTop,
  },
  emptyText: {
    color: Colors.text.muted,
    fontSize: FontSize.base,
  },
});
