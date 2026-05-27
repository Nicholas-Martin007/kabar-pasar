import { Ionicons } from '@expo/vector-icons';
import React, { useCallback } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import {
  Border,
  Colors,
  FontFamily,
  FontSize,
  FontWeight,
  IconSize,
  Layout,
  LineHeight,
  LetterSpacing,
  Radius,
  withAlpha13,
} from '@/src/theme';
import { NewsItem, NewsSource } from '@/types/news';
import { timeAgo } from '@/utils/time';

interface Props {
  item: NewsItem;
  onPress: (id: string) => void;
  onBookmark: (id: string) => void;
}

const IMPORTANCE_COLOR: Record<NewsItem['importance'], string> = {
  critical: Colors.importance.critical,
  high:     Colors.importance.high,
  medium:   Colors.importance.medium,
  low:      Colors.importance.low,
};

const IMPORTANCE_LABEL: Record<NewsItem['importance'], string> = {
  critical: 'KRITIS',
  high:     'PENTING',
  medium:   'INFO',
  low:      'UMUM',
};

const SOURCE_COLOR: Record<NewsSource, string> = {
  IDX:                Colors.source.IDX,
  'CNBC Indonesia':   Colors.source['CNBC Indonesia'],
  Kontan:             Colors.source.Kontan,
  'Bisnis Indonesia': Colors.source['Bisnis Indonesia'],
  'Detik Finance':    Colors.source['Detik Finance'],
  Reuters:            Colors.source.Reuters,
  'CNBC Global':      Colors.source['CNBC Global'],
};

export const NewsCard = React.memo(({ item, onPress, onBookmark }: Props) => {
  const stripeColor = IMPORTANCE_COLOR[item.importance];
  const sourceColor = SOURCE_COLOR[item.source];
  const pricePositive = (item.priceChange ?? 0) >= 0;

  const handlePress    = useCallback(() => onPress(item.id),    [item.id, onPress]);
  const handleBookmark = useCallback(() => onBookmark(item.id), [item.id, onBookmark]);

  return (
    <TouchableOpacity
      activeOpacity={0.75}
      onPress={handlePress}
      style={[styles.card, !item.isRead && styles.cardUnread]}
    >
      <View style={[styles.stripe, { backgroundColor: stripeColor }]} />

      <View style={styles.content}>
        <View style={styles.metaRow}>
          <View style={[styles.sourceChip, { backgroundColor: withAlpha13(sourceColor) }]}>
            <Text style={[styles.sourceText, { color: sourceColor }]}>{item.source}</Text>
          </View>

          {item.importance !== 'low' && (
            <View style={[styles.importancePill, { backgroundColor: withAlpha13(stripeColor) }]}>
              <Text style={[styles.importanceText, { color: stripeColor }]}>
                {IMPORTANCE_LABEL[item.importance]}
              </Text>
            </View>
          )}

          <Text style={styles.timeText}>{timeAgo(item.publishedAt)}</Text>
        </View>

        <Text style={[styles.title, item.isRead && styles.titleRead]} numberOfLines={2}>
          {item.title}
        </Text>

        <View style={styles.summaryRow}>
          <Text style={styles.aiLabel}>AI</Text>
          <Text style={styles.summary} numberOfLines={3}>
            {item.aiSummary}
          </Text>
        </View>

        <View style={styles.bottomRow}>
          {item.ticker ? (
            <View style={styles.tickerGroup}>
              <View style={styles.tickerChip}>
                <Text style={styles.tickerText}>{item.ticker}</Text>
              </View>
              <Text
                style={[
                  styles.priceChange,
                  { color: pricePositive ? Colors.sentiment.positive : Colors.sentiment.negative },
                ]}
              >
                {pricePositive ? '▲' : '▼'} {Math.abs(item.priceChange!).toFixed(2)}%
              </Text>
            </View>
          ) : (
            <View />
          )}

          <TouchableOpacity
            onPress={handleBookmark}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          >
            <Ionicons
              name={item.isBookmarked ? 'bookmark' : 'bookmark-outline'}
              size={IconSize.sm}
              color={item.isBookmarked ? Colors.brand.accent : Colors.text.muted}
            />
          </TouchableOpacity>
        </View>
      </View>
    </TouchableOpacity>
  );
});

NewsCard.displayName = 'NewsCard';

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.card,
    overflow: 'hidden',
    marginHorizontal: Layout.screenPaddingX,
    marginVertical: Layout.cardMarginV,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
  },
  cardUnread: {
    backgroundColor: Colors.background.surfaceElevated,
  },
  stripe: {
    width: Border.stripeWidth,
    flexShrink: 0,
  },
  content: {
    flex: 1,
    padding: Layout.cardPadding,
    gap: Layout.contentGap,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Layout.rowGap,
    flexWrap: 'wrap',
  },
  sourceChip: {
    paddingHorizontal: Layout.chipPaddingX,
    paddingVertical: Layout.chipPaddingY,
    borderRadius: Radius.chip,
  },
  sourceText: {
    fontSize: FontSize.caption,
    fontWeight: FontWeight.bold,
    letterSpacing: LetterSpacing.wide,
  },
  importancePill: {
    paddingHorizontal: Layout.chipPaddingX,
    paddingVertical: Layout.chipPaddingY,
    borderRadius: Radius.chip,
  },
  importanceText: {
    fontSize: FontSize.badge,
    fontWeight: FontWeight.bold,
    letterSpacing: LetterSpacing.wider,
  },
  timeText: {
    fontSize: FontSize.small,
    color: Colors.text.muted,
    marginLeft: 'auto',
  },
  title: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.semibold,
    color: Colors.text.primary,
    lineHeight: LineHeight.normal,
  },
  titleRead: {
    color: Colors.text.secondary,
    fontWeight: FontWeight.medium,
  },
  summaryRow: {
    flexDirection: 'row',
    gap: Layout.rowGap,
    alignItems: 'flex-start',
  },
  aiLabel: {
    fontSize: FontSize.badge,
    fontWeight: FontWeight.bold,
    color: Colors.brand.accent,
    backgroundColor: withAlpha13(Colors.brand.accent),
    paddingHorizontal: Layout.badgePaddingX,
    paddingVertical: Layout.badgePaddingY,
    borderRadius: Radius.badge,
    marginTop: 1,
    overflow: 'hidden',
  },
  summary: {
    flex: 1,
    fontSize: FontSize.body,
    color: Colors.text.secondary,
    lineHeight: LineHeight.tight,
  },
  bottomRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 2,
  },
  tickerGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Layout.rowGap,
  },
  tickerChip: {
    backgroundColor: Colors.border.default,
    paddingHorizontal: Layout.chipPaddingX,
    paddingVertical: Layout.chipPaddingY + 1,
    borderRadius: Radius.chip,
  },
  tickerText: {
    fontSize: FontSize.small,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    fontFamily: FontFamily.mono ?? undefined,
  },
  priceChange: {
    fontSize: FontSize.body,
    fontWeight: FontWeight.semibold,
    fontFamily: FontFamily.mono ?? undefined,
  },
});
