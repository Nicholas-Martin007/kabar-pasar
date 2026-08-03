import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import React, { useCallback, useState } from 'react';
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { CommodityStrip } from '@/components/commodity-strip';
import { NewsCard } from '@/components/news-card';
import { StockRow } from '@/components/stock-row';
import { useNewsFeed } from '@/src/hooks/useNews';
import { useIndex, useQuotes, useReactions } from '@/src/hooks/useMarket';
import { ReactionItem } from '@/src/services/api';
import { mockStocks } from '@/src/data/mockStocks';
import { useBookmarks } from '@/src/context/BookmarksContext';
import { useLive, useLiveState } from '@/src/context/LiveContext';
import { useRead } from '@/src/context/ReadContext';
import { useWatchlist } from '@/src/context/WatchlistContext';
import {
  Border,
  Colors,
  FontFamily,
  FontSize,
  FontWeight,
  IconSize,
  Layout,
  LetterSpacing,
  Radius,
} from '@/src/theme';
import { News } from '@/src/types/news';
import { Stock } from '@/src/types/stock';
import { getGreeting, getMarketStatus } from '@/utils/market';

// ── Mock IHSG snapshot — fallback when the market API is unreachable ─────────
const IHSG_FALLBACK = { value: 7_234.56, changePercent: 0.42 };
const UNREAD_COUNT = 3;

function formatIHSG(value: number): string {
  const [int, dec] = value.toFixed(2).split('.');
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, '.') + ',' + dec;
}

/** Connection indicator for the live WebSocket stream. */
function LiveBadge() {
  const status = useLive();
  const isLive = status === 'open';
  const color = isLive ? Colors.sentiment.positive : Colors.text.muted;
  const label =
    status === 'open' ? 'LANGSUNG' : status === 'connecting' ? 'MENYAMBUNG' : 'OFFLINE';
  return (
    <View style={styles.liveBadge}>
      <View style={[styles.liveDot, { backgroundColor: color }]} />
      <Text style={[styles.liveText, { color }]}>{label}</Text>
    </View>
  );
}

// ────────────────────────────────────────────────────────────────────────────

export default function HomeScreen() {
  const { items: watchlistItems } = useWatchlist();
  const { isBookmarked, toggle: handleBookmark } = useBookmarks();
  const { isRead, markRead } = useRead();
  const { isFresh } = useLiveState();
  const { data: allNews, refetch } = useNewsFeed();
  const { data: indexQuote, refetch: refetchIndex } = useIndex();
  const [greeting,      setGreeting]      = useState(getGreeting);
  const [marketStatus,  setMarketStatus]  = useState(getMarketStatus);
  const [refreshing,    setRefreshing]    = useState(false);

  // Top 3 high-importance items, newest first.
  const topNews: News[] = React.useMemo(
    () =>
      allNews
        .filter((n) => n.importance === 'high')
        .sort(
          (a, b) =>
            new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime()
        )
        .slice(0, 3),
    [allNews]
  );

  // Batched price reactions for the top news cards (one request).
  const reactionItems: ReactionItem[] = React.useMemo(
    () =>
      topNews
        .filter((n) => n.tickers.length > 0)
        .map((n) => ({ key: n.id, ticker: n.tickers[0], at: n.publishedAt })),
    [topNews]
  );
  const { data: reactionMap, isLoading: reactionsLoading } =
    useReactions(reactionItems);

  const previewTickers = React.useMemo(
    () => watchlistItems.slice(0, 4).map((w) => w.ticker),
    [watchlistItems]
  );
  const { data: previewQuotes, refetch: refetchQuotes } =
    useQuotes(previewTickers);

  const watchlistPreview: Stock[] = React.useMemo(
    () =>
      watchlistItems.slice(0, 4).flatMap((w) => {
        const base = mockStocks.find((s) => s.ticker === w.ticker);
        if (!base) return [];
        const q = previewQuotes?.get(w.ticker);
        if (!q?.available) return [base];
        const pts = (q.sparkline ?? []).filter((x): x is number => x != null);
        return [
          {
            ...base,
            price: q.price ?? base.price,
            change: q.change ?? base.change,
            changePercent: q.changePercent ?? base.changePercent,
            sparkline: pts.length > 1 ? pts : base.sparkline,
          },
        ];
      }),
    [watchlistItems, previewQuotes]
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    setGreeting(getGreeting());
    setMarketStatus(getMarketStatus());
    try {
      await Promise.all([refetch(), refetchIndex(), refetchQuotes()]);
    } finally {
      setRefreshing(false);
    }
  }, [refetch, refetchIndex, refetchQuotes]);

  const handleNewsPress = useCallback((id: string) => {
    markRead(id);
    router.push(`/news/${id}` as never);
  }, [markRead]);

  const handleStockPress = useCallback((ticker: string) => {
    router.push(`/stock/${ticker}` as never);
  }, []);

  // Live IHSG with graceful fallback to mock values.
  const ihsgValue  = indexQuote?.price ?? IHSG_FALLBACK.value;
  const ihsgChange = indexQuote?.changePercent ?? IHSG_FALLBACK.changePercent;

  const statusColor  = marketStatus.isOpen ? Colors.sentiment.positive : Colors.text.muted;
  const changeColor  = ihsgChange >= 0 ? Colors.sentiment.positive : Colors.sentiment.negative;
  const changePrefix = ihsgChange >= 0 ? '+' : '';

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={Colors.brand.accent}
            colors={[Colors.brand.accent]}
          />
        }
      >
        {/* ── Header ────────────────────────────────────────────────────── */}
        <View style={styles.header}>
          <View>
            <Text style={styles.greeting}>{greeting}</Text>
            <Text style={styles.subGreeting}>Pasar bergerak, tetap waspada.</Text>
          </View>
          <View style={styles.headerRight}>
            <LiveBadge />
            <TouchableOpacity style={styles.bellWrap} activeOpacity={0.7}>
              <Ionicons
                name="notifications-outline"
                size={IconSize.md}
                color={Colors.text.primary}
              />
              {UNREAD_COUNT > 0 && (
                <View style={styles.notifBadge}>
                  <Text style={styles.notifBadgeText}>{UNREAD_COUNT}</Text>
                </View>
              )}
            </TouchableOpacity>
          </View>
        </View>

        {/* ── Market Status Card ────────────────────────────────────────── */}
        <View style={styles.marketCard}>
          <View style={styles.marketTopRow}>
            <View style={styles.marketMeta}>
              <View style={[styles.statusDot, { backgroundColor: statusColor }]} />
              <Text style={styles.marketLabel}>IDX · IHSG</Text>
              <Text style={[styles.marketOpenLabel, { color: statusColor }]}>
                {marketStatus.isOpen ? 'Buka' : 'Tutup'}
              </Text>
            </View>
            <Text style={styles.marketTimer}>{marketStatus.label}</Text>
          </View>
          <View style={styles.marketBottomRow}>
            <Text style={styles.ihsgValue}>{formatIHSG(ihsgValue)}</Text>
            <Text style={[styles.ihsgChange, { color: changeColor }]}>
              {changePrefix}{ihsgChange.toFixed(2).replace('.', ',')}%
            </Text>
          </View>
        </View>

        {/* ── Komoditas (live) ──────────────────────────────────────────── */}
        <CommodityStrip />

        {/* ── Berita Penting Hari Ini ───────────────────────────────────── */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Berita Penting Hari Ini</Text>
          {topNews.length === 0 ? (
            <Text style={styles.emptyText}>Tidak ada berita penting saat ini.</Text>
          ) : (
            topNews.map((item) => (
              <NewsCard
                key={item.id}
                item={item}
                isRead={isRead(item.id)}
                isBookmarked={isBookmarked(item.id)}
                onPress={handleNewsPress}
                onBookmark={handleBookmark}
                reaction={reactionMap?.get(item.id)}
                reactionLoading={reactionsLoading}
                isFresh={isFresh(item.id)}
              />
            ))
          )}
        </View>

        {/* ── Watchlist Preview ─────────────────────────────────────────── */}
        <View style={styles.section}>
          <View style={styles.sectionRow}>
            <Text style={styles.sectionTitle}>Watchlist Anda</Text>
            <TouchableOpacity
              activeOpacity={0.7}
              onPress={() => router.navigate('/(tabs)/watchlist' as never)}
            >
              <Text style={styles.seeAll}>Lihat semua</Text>
            </TouchableOpacity>
          </View>
          {watchlistPreview.length === 0 ? (
            <Text style={styles.emptyText}>Belum ada saham di watchlist.</Text>
          ) : (
            <View style={styles.stockCard}>
              {watchlistPreview.map((stock, i) => (
                <React.Fragment key={stock.ticker}>
                  <StockRow stock={stock} onPress={handleStockPress} />
                  {i < watchlistPreview.length - 1 && (
                    <View style={styles.stockDivider} />
                  )}
                </React.Fragment>
              ))}
            </View>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Colors.background.screen,
  },
  scroll: {
    paddingBottom: Layout.listPaddingBottom,
  },

  // Header
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: Layout.screenPaddingX,
    paddingTop: 16,
    paddingBottom: 12,
  },
  greeting: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    letterSpacing: LetterSpacing.tight,
  },
  subGreeting: {
    fontSize: FontSize.body,
    color: Colors.text.muted,
    marginTop: 2,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  liveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  liveDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
  },
  liveText: {
    fontSize: FontSize.badge,
    fontWeight: FontWeight.bold,
    letterSpacing: LetterSpacing.wider,
  },
  bellWrap: {
    position: 'relative',
    padding: 4,
  },
  notifBadge: {
    position: 'absolute',
    top: 0,
    right: 0,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: Colors.sentiment.negative,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 3,
  },
  notifBadgeText: {
    fontSize: FontSize.badge,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    lineHeight: 13,
  },

  // Market card
  marketCard: {
    marginHorizontal: Layout.screenPaddingX,
    marginBottom: 20,
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.card,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    padding: Layout.cardPadding,
    gap: 10,
  },
  marketTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  marketMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Layout.rowGap,
  },
  statusDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
  },
  marketLabel: {
    fontSize: FontSize.caption,
    fontWeight: FontWeight.semibold,
    color: Colors.text.secondary,
    letterSpacing: LetterSpacing.wide,
  },
  marketOpenLabel: {
    fontSize: FontSize.caption,
    fontWeight: FontWeight.bold,
    letterSpacing: LetterSpacing.wider,
  },
  marketTimer: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
  },
  marketBottomRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 10,
  },
  ihsgValue: {
    fontSize: FontSize.title,
    fontWeight: FontWeight.extrabold,
    color: Colors.text.primary,
    fontFamily: FontFamily.mono ?? undefined,
    letterSpacing: LetterSpacing.tight,
  },
  ihsgChange: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.bold,
    letterSpacing: LetterSpacing.tight,
  },

  // Sections
  section: {
    marginBottom: 20,
  },
  sectionTitle: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    paddingHorizontal: Layout.screenPaddingX,
    marginBottom: 10,
  },
  sectionRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: Layout.screenPaddingX,
    marginBottom: 10,
  },
  seeAll: {
    fontSize: FontSize.body,
    color: Colors.brand.accent,
    fontWeight: FontWeight.semibold,
  },
  emptyText: {
    fontSize: FontSize.body,
    color: Colors.text.muted,
    paddingHorizontal: Layout.screenPaddingX,
  },

  // Watchlist stock card
  stockCard: {
    marginHorizontal: Layout.screenPaddingX,
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.card,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    overflow: 'hidden',
  },
  stockDivider: {
    height: Border.width,
    backgroundColor: Colors.border.default,
    marginHorizontal: Layout.screenPaddingX,
  },
});
