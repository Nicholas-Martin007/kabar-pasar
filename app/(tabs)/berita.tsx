import React, { useCallback, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { router } from 'expo-router';

import { FeedHeader } from '@/components/feed-header';
import { NewsCard } from '@/components/news-card';
import { useBookmarks } from '@/src/context/BookmarksContext';
import { useNewsFeed } from '@/src/hooks/useNews';
import { useReactions } from '@/src/hooks/useMarket';
import { ReactionItem } from '@/src/services/api';
import { Colors, FontSize, Layout } from '@/src/theme';
import { FeedFilter, News, NewsCategory } from '@/src/types/news';

// Cap how many cards request a reaction (keeps the batch polite to Yahoo).
const MAX_REACTIONS = 40;

const MARKET = {
  index:  'IHSG',
  value:  7_234.12,
  change: 0.82,
  isOpen: true,
};

const CATEGORY_FOR_FILTER: Record<FeedFilter, NewsCategory[]> = {
  all:       ['corporate_action', 'earnings', 'market_news', 'regulatory', 'macro'],
  watchlist: ['corporate_action', 'earnings'],
  idx:       ['corporate_action', 'earnings', 'regulatory'],
  macro:     ['macro'],
  global:    ['market_news'],
};

export default function BeritaScreen() {
  const { data: allNews, refetch: refetchNews } = useNewsFeed();
  const { isBookmarked, toggle: handleBookmark } = useBookmarks();
  const [activeFilter,  setActiveFilter]  = useState<FeedFilter>('all');
  const [refreshing,     setRefreshing]    = useState(false);
  const [readIds,        setReadIds]       = useState(new Set<string>());

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
    setReadIds((prev) => new Set(prev).add(id));
    router.push(`/news/${id}` as never);
  }, []);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await Promise.all([refetchNews(), refetchReactions()]);
    } finally {
      setRefreshing(false);
    }
  }, [refetchNews, refetchReactions]);

  const renderItem = useCallback(
    ({ item }: { item: News }) => (
      <NewsCard
        item={item}
        isRead={readIds.has(item.id)}
        isBookmarked={isBookmarked(item.id)}
        onPress={handlePress}
        onBookmark={handleBookmark}
        reaction={reactionMap?.get(item.id)}
        reactionLoading={reactionsLoading}
      />
    ),
    [readIds, isBookmarked, handlePress, handleBookmark, reactionMap, reactionsLoading]
  );

  const renderHeader = useCallback(
    () => (
      <FeedHeader
        activeFilter={activeFilter}
        onFilterChange={setActiveFilter}
        onNotification={() => {}}
        market={MARKET}
      />
    ),
    [activeFilter]
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
