import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import React, { useCallback, useMemo } from 'react';
import { FlatList, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { NewsCard } from '@/components/news-card';
import { useBookmarks } from '@/src/context/BookmarksContext';
import { useRead } from '@/src/context/ReadContext';
import { useNewsFeed } from '@/src/hooks/useNews';
import {
  Border,
  Colors,
  FontSize,
  FontWeight,
  IconSize,
  Layout,
  LetterSpacing,
} from '@/src/theme';
import { News } from '@/src/types/news';

export default function SavedScreen() {
  const { data: allNews } = useNewsFeed({ limit: 200 });
  const { ids, toggle } = useBookmarks();
  const { isRead, markRead } = useRead();

  const saved = useMemo(
    () =>
      allNews
        .filter((n) => ids.has(n.id))
        .sort(
          (a, b) =>
            new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime()
        ),
    [allNews, ids]
  );

  const handlePress = useCallback(
    (id: string) => {
      markRead(id);
      router.push(`/news/${id}` as never);
    },
    [markRead]
  );

  const renderItem = useCallback(
    ({ item }: { item: News }) => (
      <NewsCard
        item={item}
        isRead={isRead(item.id)}
        isBookmarked
        onPress={handlePress}
        onBookmark={toggle}
      />
    ),
    [isRead, handlePress, toggle]
  );

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <View style={styles.navbar}>
        <TouchableOpacity
          style={styles.navBtn}
          onPress={() => router.back()}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Ionicons name="chevron-back" size={IconSize.md} color={Colors.text.primary} />
          <Text style={styles.backLabel}>Kembali</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Tersimpan</Text>
        <View style={styles.navSpacer} />
      </View>

      <FlatList
        data={saved}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Ionicons name="bookmark-outline" size={48} color={Colors.text.muted} />
            <Text style={styles.emptyTitle}>Belum ada berita tersimpan</Text>
            <Text style={styles.emptyBody}>
              Ketuk ikon bookmark pada berita untuk menyimpannya di sini.
            </Text>
          </View>
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
  navbar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Layout.screenPaddingX,
    paddingVertical: 12,
    borderBottomWidth: Border.width,
    borderBottomColor: Colors.border.default,
  },
  navBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    flex: 1,
  },
  backLabel: {
    fontSize: FontSize.base,
    color: Colors.text.primary,
    fontWeight: FontWeight.medium,
  },
  title: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    letterSpacing: LetterSpacing.tight,
  },
  navSpacer: {
    flex: 1,
  },
  listContent: {
    paddingBottom: Layout.listPaddingBottom,
  },
  empty: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: Layout.emptyPaddingTop,
    paddingHorizontal: Layout.screenPaddingX * 2,
    gap: 10,
  },
  emptyTitle: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    marginTop: 4,
  },
  emptyBody: {
    fontSize: FontSize.body,
    color: Colors.text.muted,
    textAlign: 'center',
    lineHeight: 18,
  },
});
