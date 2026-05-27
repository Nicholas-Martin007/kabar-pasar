import React, { useCallback, useState } from 'react';
import { FlatList, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { FeedHeader } from '@/components/feed-header';
import { NewsCard } from '@/components/news-card';
import { Colors, FontSize, Layout } from '@/src/theme';
import { MOCK_NEWS } from '@/data/mock-news';
import { FeedFilter, NewsItem } from '@/types/news';

const MARKET = {
  index:  'IHSG',
  value:  7_234.12,
  change: 0.82,
  isOpen: true,
};

const CATEGORY_FOR_FILTER: Record<FeedFilter, NewsItem['category'][]> = {
  all:       ['announcement', 'market', 'macro', 'sector', 'global'],
  watchlist: ['announcement'],
  idx:       ['announcement', 'market'],
  macro:     ['macro'],
  global:    ['global'],
};

export default function BeritaScreen() {
  const [news, setNews]                = useState<NewsItem[]>(MOCK_NEWS);
  const [activeFilter, setActiveFilter] = useState<FeedFilter>('all');

  const filtered = news.filter((item) =>
    CATEGORY_FOR_FILTER[activeFilter].includes(item.category)
  );

  const handlePress = useCallback((id: string) => {
    setNews((prev) =>
      prev.map((item) => (item.id === id ? { ...item, isRead: true } : item))
    );
  }, []);

  const handleBookmark = useCallback((id: string) => {
    setNews((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, isBookmarked: !item.isBookmarked } : item
      )
    );
  }, []);

  const renderItem = useCallback(
    ({ item }: { item: NewsItem }) => (
      <NewsCard item={item} onPress={handlePress} onBookmark={handleBookmark} />
    ),
    [handlePress, handleBookmark]
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
