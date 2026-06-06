import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import React, { useCallback, useState } from 'react';
import {
  Alert,
  Linking,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { NewsCard } from '@/components/news-card';
import { useBookmarks } from '@/src/context/BookmarksContext';
import { useNewsFeed } from '@/src/hooks/useNews';
import { useReaction } from '@/src/hooks/useMarket';
import {
  Border,
  Colors,
  FontFamily,
  FontSize,
  FontWeight,
  IconSize,
  Layout,
  LetterSpacing,
  LineHeight,
  Radius,
  withAlpha13,
} from '@/src/theme';
import { News, NewsCategory, NewsImportance } from '@/src/types/news';
import { formatDateTime } from '@/utils/time';

// ── Label maps ───────────────────────────────────────────────────────────────

const IMPORTANCE_LABEL: Record<NewsImportance, string> = {
  high:   'PENTING',
  medium: 'INFO',
  low:    'UMUM',
};

const CATEGORY_LABEL: Record<NewsCategory, string> = {
  corporate_action: 'Aksi Korporasi',
  earnings:         'Kinerja Keuangan',
  market_news:      'Pasar Saham',
  regulatory:       'Regulasi',
  macro:            'Makroekonomi',
};

function formatWindow(min?: number): string {
  if (!min) return 'beberapa saat';
  if (min < 60) return `${min} menit`;
  if (min < 1440) return `${Math.round(min / 60)} jam`;
  return `${Math.round(min / 1440)} hari`;
}

// ── Not-Found fallback ───────────────────────────────────────────────────────

function NotFound() {
  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <TouchableOpacity style={styles.backBtn} onPress={() => router.back()}>
        <Ionicons name="chevron-back" size={IconSize.md} color={Colors.text.primary} />
        <Text style={styles.backLabel}>Kembali</Text>
      </TouchableOpacity>
      <View style={styles.notFound}>
        <Ionicons name="alert-circle-outline" size={48} color={Colors.text.muted} />
        <Text style={styles.notFoundTitle}>Berita tidak ditemukan</Text>
        <Text style={styles.notFoundBody}>
          Berita ini mungkin sudah dihapus atau ID tidak valid.
        </Text>
      </View>
    </SafeAreaView>
  );
}

// ── Main screen ──────────────────────────────────────────────────────────────

export default function NewsDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: allNews } = useNewsFeed({ limit: 200 });
  const news = allNews.find((n) => n.id === id);

  // Novelty: how the primary affected stock moved after this news broke.
  const primaryTicker = news?.tickers[0];
  const { data: reaction } = useReaction(primaryTicker, news?.publishedAt);

  const { isBookmarked, toggle: handleBookmark } = useBookmarks();
  const [readIds, setReadIds] = useState(new Set<string>());

  const handleRelatedPress = useCallback((relatedId: string) => {
    setReadIds((prev) => new Set(prev).add(relatedId));
    router.push(`/news/${relatedId}` as never);
  }, []);

  if (!news) return <NotFound />;

  const importanceColor = Colors.importance[news.importance];
  const importanceLabel = IMPORTANCE_LABEL[news.importance];
  const categoryLabel   = CATEGORY_LABEL[news.category];

  const relatedNews: News[] = news.tickers.length > 0
    ? allNews
        .filter(
          (n) =>
            n.id !== news.id &&
            n.tickers.some((t) => news.tickers.includes(t))
        )
        .sort((a, b) => new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime())
        .slice(0, 3)
    : [];

  const handleShare = async () => {
    try {
      await Share.share({
        message: `${news.title}\n\nBaca selengkapnya di Kabar Pasar.`,
        url: news.url,
      });
    } catch {
      // share sheet dismissed — no-op
    }
  };

  const handleOpenSource = async () => {
    if (!news.url) return;
    const supported = await Linking.canOpenURL(news.url);
    if (supported) {
      await Linking.openURL(news.url);
    } else {
      Alert.alert('Tidak dapat membuka tautan', news.url);
    }
  };

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      {/* ── Nav bar ─────────────────────────────────────────────────────── */}
      <View style={styles.navbar}>
        <TouchableOpacity
          style={styles.navBtn}
          onPress={() => router.back()}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Ionicons name="chevron-back" size={IconSize.md} color={Colors.text.primary} />
          <Text style={styles.backLabel}>Kembali</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.navBtn}
          onPress={handleShare}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Ionicons name="share-outline" size={IconSize.sm + 2} color={Colors.text.primary} />
        </TouchableOpacity>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        {/* ── Meta: importance + category + source + time ─────────────── */}
        <View style={styles.metaRow}>
          {news.importance !== 'low' && (
            <View style={[styles.importancePill, { backgroundColor: withAlpha13(importanceColor) }]}>
              <Text style={[styles.importancePillText, { color: importanceColor }]}>
                {importanceLabel}
              </Text>
            </View>
          )}
          <View style={styles.categoryPill}>
            <Text style={styles.categoryPillText}>{categoryLabel}</Text>
          </View>
        </View>

        <View style={styles.sourceRow}>
          <Text style={[styles.sourceText, { color: Colors.source[news.source] }]}>
            {news.source}
          </Text>
          <Text style={styles.dotSep}>·</Text>
          <Text style={styles.timeText}>{formatDateTime(news.publishedAt)}</Text>
        </View>

        {/* ── Headline ────────────────────────────────────────────────── */}
        <Text style={styles.headline}>{news.title}</Text>

        {/* ── Excerpt / body ──────────────────────────────────────────── */}
        <Text style={styles.excerpt}>{news.excerpt}</Text>

        {/* ── AI Summary card ─────────────────────────────────────────── */}
        <View style={styles.aiCard}>
          <View style={styles.aiStripe} />
          <View style={styles.aiCardInner}>
            <View style={styles.aiHeader}>
              <View style={styles.aiLabelPill}>
                <Ionicons
                  name="sparkles"
                  size={11}
                  color={Colors.brand.accent}
                  style={styles.aiIcon}
                />
                <Text style={styles.aiLabelText}>Ringkasan AI</Text>
              </View>
              <Text style={styles.aiSubLabel}>Oleh Kabar Pasar AI</Text>
            </View>
            <View style={styles.aiBullets}>
              {news.aiSummary.map((point, i) => (
                <View key={i} style={styles.aiBulletRow}>
                  <View style={styles.aiBulletDot} />
                  <Text style={styles.aiBulletText}>{point}</Text>
                </View>
              ))}
            </View>
          </View>
        </View>

        {/* ── Market reaction (novelty: news ↔ price linkage) ─────────── */}
        {reaction?.available &&
          reaction.reactionPercent != null &&
          primaryTicker && (
            <View style={styles.reactionCard}>
              <View style={styles.reactionHeader}>
                <Ionicons
                  name="pulse"
                  size={13}
                  color={Colors.text.secondary}
                />
                <Text style={styles.reactionTitle}>Reaksi Pasar</Text>
              </View>
              <View style={styles.reactionBody}>
                <Text
                  style={[
                    styles.reactionPct,
                    {
                      color:
                        reaction.reactionPercent >= 0
                          ? Colors.sentiment.positive
                          : Colors.sentiment.negative,
                    },
                  ]}
                >
                  {reaction.reactionPercent >= 0 ? '+' : ''}
                  {reaction.reactionPercent.toFixed(2).replace('.', ',')}%
                </Text>
                <Text style={styles.reactionDesc}>
                  {primaryTicker}{' '}
                  {reaction.reactionPercent >= 0 ? 'bergerak naik' : 'bergerak turun'}{' '}
                  dalam {formatWindow(reaction.windowMinutes)} setelah berita ini
                </Text>
              </View>
              <Text style={styles.reactionSource}>
                Berdasarkan data harga Yahoo Finance · indikatif
              </Text>
            </View>
          )}

        {/* ── Affected tickers ────────────────────────────────────────── */}
        {news.tickers.length > 0 && (
          <View style={styles.tickersSection}>
            <Text style={styles.sectionLabel}>Saham Terdampak</Text>
            <View style={styles.tickerRow}>
              {news.tickers.map((ticker) => (
                <TouchableOpacity
                  key={ticker}
                  style={styles.tickerChip}
                  onPress={() => router.push(`/stock/${ticker}` as never)}
                  activeOpacity={0.7}
                >
                  <Text style={styles.tickerText}>{ticker}</Text>
                  <Ionicons
                    name="chevron-forward"
                    size={10}
                    color={Colors.text.muted}
                  />
                </TouchableOpacity>
              ))}
            </View>
          </View>
        )}

        {/* ── Open source button ──────────────────────────────────────── */}
        {news.url && (
          <TouchableOpacity
            style={styles.sourceBtn}
            onPress={handleOpenSource}
            activeOpacity={0.8}
          >
            <Ionicons name="open-outline" size={IconSize.sm} color={Colors.brand.accent} />
            <Text style={styles.sourceBtnText}>Buka Sumber Asli</Text>
          </TouchableOpacity>
        )}

        {/* ── Related news ────────────────────────────────────────────── */}
        {relatedNews.length > 0 && (
          <View style={styles.relatedSection}>
            <Text style={styles.sectionLabel}>Berita Terkait</Text>
            {relatedNews.map((item) => (
              <NewsCard
                key={item.id}
                item={item}
                isRead={readIds.has(item.id)}
                isBookmarked={isBookmarked(item.id)}
                onPress={handleRelatedPress}
                onBookmark={handleBookmark}
              />
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Colors.background.screen,
  },

  // Navbar
  navbar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: Layout.screenPaddingX,
    paddingVertical: 12,
    borderBottomWidth: Border.width,
    borderBottomColor: Colors.border.default,
  },
  navBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  backLabel: {
    fontSize: FontSize.base,
    color: Colors.text.primary,
    fontWeight: FontWeight.medium,
  },

  // Scroll content
  scroll: {
    paddingBottom: 48,
  },

  // Meta row
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Layout.rowGap,
    paddingHorizontal: Layout.screenPaddingX,
    paddingTop: 20,
    flexWrap: 'wrap',
  },
  importancePill: {
    paddingHorizontal: Layout.chipPaddingX,
    paddingVertical: Layout.chipPaddingY,
    borderRadius: Radius.chip,
  },
  importancePillText: {
    fontSize: FontSize.badge,
    fontWeight: FontWeight.bold,
    letterSpacing: LetterSpacing.wider,
  },
  categoryPill: {
    backgroundColor: Colors.background.surface,
    paddingHorizontal: Layout.chipPaddingX,
    paddingVertical: Layout.chipPaddingY,
    borderRadius: Radius.chip,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
  },
  categoryPillText: {
    fontSize: FontSize.badge,
    color: Colors.text.secondary,
    fontWeight: FontWeight.medium,
    letterSpacing: LetterSpacing.wide,
  },

  // Source row
  sourceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: Layout.screenPaddingX,
    marginTop: 10,
  },
  sourceText: {
    fontSize: FontSize.caption,
    fontWeight: FontWeight.bold,
    letterSpacing: LetterSpacing.wide,
  },
  dotSep: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
  },
  timeText: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
  },

  // Headline
  headline: {
    fontSize: 20,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    lineHeight: 28,
    letterSpacing: LetterSpacing.tight,
    paddingHorizontal: Layout.screenPaddingX,
    marginTop: 14,
  },

  // Excerpt
  excerpt: {
    fontSize: FontSize.base,
    color: Colors.text.secondary,
    lineHeight: 22,
    paddingHorizontal: Layout.screenPaddingX,
    marginTop: 12,
  },

  // AI card
  aiCard: {
    flexDirection: 'row',
    marginHorizontal: Layout.screenPaddingX,
    marginTop: 20,
    backgroundColor: Colors.background.surfaceElevated,
    borderRadius: Radius.card,
    borderWidth: Border.width,
    borderColor: Colors.brand.accent + '44',
    overflow: 'hidden',
  },
  aiStripe: {
    width: Border.stripeWidth + 1,
    backgroundColor: Colors.brand.accent,
    flexShrink: 0,
  },
  aiCardInner: {
    flex: 1,
    padding: Layout.cardPadding,
    gap: 10,
  },
  aiHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  aiLabelPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: withAlpha13(Colors.brand.accent),
    paddingHorizontal: Layout.chipPaddingX,
    paddingVertical: Layout.chipPaddingY,
    borderRadius: Radius.chip,
  },
  aiIcon: {
    marginTop: -1,
  },
  aiLabelText: {
    fontSize: FontSize.small,
    fontWeight: FontWeight.bold,
    color: Colors.brand.accent,
    letterSpacing: LetterSpacing.wide,
  },
  aiSubLabel: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
  },
  aiBullets: {
    gap: 8,
  },
  aiBulletRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
  },
  aiBulletDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: Colors.brand.accent,
    marginTop: 6,
    flexShrink: 0,
  },
  aiBulletText: {
    flex: 1,
    fontSize: FontSize.base,
    color: Colors.text.primary,
    lineHeight: LineHeight.normal,
  },

  // Market reaction card
  reactionCard: {
    marginHorizontal: Layout.screenPaddingX,
    marginTop: 12,
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.card,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    padding: Layout.cardPadding,
    gap: 8,
  },
  reactionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  reactionTitle: {
    fontSize: FontSize.caption,
    fontWeight: FontWeight.bold,
    color: Colors.text.secondary,
    letterSpacing: LetterSpacing.wider,
    textTransform: 'uppercase',
  },
  reactionBody: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 10,
    flexWrap: 'wrap',
  },
  reactionPct: {
    fontSize: FontSize.title,
    fontWeight: FontWeight.extrabold,
    fontFamily: FontFamily.mono ?? undefined,
    letterSpacing: LetterSpacing.tight,
  },
  reactionDesc: {
    flex: 1,
    minWidth: 140,
    fontSize: FontSize.body,
    color: Colors.text.secondary,
    lineHeight: LineHeight.normal,
  },
  reactionSource: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
  },

  // Tickers
  tickersSection: {
    paddingHorizontal: Layout.screenPaddingX,
    marginTop: 24,
    gap: 10,
  },
  sectionLabel: {
    fontSize: FontSize.caption,
    fontWeight: FontWeight.bold,
    color: Colors.text.muted,
    letterSpacing: LetterSpacing.wider,
    textTransform: 'uppercase',
  },
  tickerRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Layout.rowGap,
  },
  tickerChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: Colors.background.surface,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: Radius.chip,
  },
  tickerText: {
    fontSize: FontSize.small,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    fontFamily: FontFamily.mono ?? undefined,
  },

  // Source button
  sourceBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginHorizontal: Layout.screenPaddingX,
    marginTop: 24,
    paddingVertical: 12,
    borderRadius: Radius.component,
    borderWidth: Border.width,
    borderColor: Colors.brand.accent,
    backgroundColor: withAlpha13(Colors.brand.accent),
  },
  sourceBtnText: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.semibold,
    color: Colors.brand.accent,
  },

  // Related news
  relatedSection: {
    marginTop: 28,
    gap: 4,
  },

  // Not-found
  notFound: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    paddingHorizontal: Layout.screenPaddingX * 2,
  },
  notFoundTitle: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
  },
  notFoundBody: {
    fontSize: FontSize.body,
    color: Colors.text.muted,
    textAlign: 'center',
    lineHeight: LineHeight.normal,
  },
  backBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: Layout.screenPaddingX,
    paddingVertical: 12,
  },
});
