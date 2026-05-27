import { Ionicons } from '@expo/vector-icons';
import React, { useCallback } from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { FC } from '@/constants/financial-colors';
import { Fonts } from '@/constants/theme';
import { NewsItem, NewsSource } from '@/types/news';
import { timeAgo } from '@/utils/time';

interface Props {
  item: NewsItem;
  onPress: (id: string) => void;
  onBookmark: (id: string) => void;
}

const IMPORTANCE_COLOR: Record<NewsItem['importance'], string> = {
  critical: FC.importanceCritical,
  high: FC.importanceHigh,
  medium: FC.importanceMedium,
  low: FC.importanceLow,
};

const IMPORTANCE_LABEL: Record<NewsItem['importance'], string> = {
  critical: 'KRITIS',
  high: 'PENTING',
  medium: 'INFO',
  low: 'UMUM',
};

const SOURCE_COLOR: Record<NewsSource, string> = {
  IDX: FC.tagIDX,
  'CNBC Indonesia': FC.tagCNBCID,
  Kontan: FC.tagKontan,
  'Bisnis Indonesia': FC.tagBisnis,
  'Detik Finance': FC.tagDetik,
  Reuters: FC.tagReuters,
  'CNBC Global': FC.tagCNBCGlobal,
};

export const NewsCard = React.memo(({ item, onPress, onBookmark }: Props) => {
  const stripeColor = IMPORTANCE_COLOR[item.importance];
  const sourceColor = SOURCE_COLOR[item.source];
  const pricePositive = (item.priceChange ?? 0) >= 0;

  const handlePress = useCallback(() => onPress(item.id), [item.id, onPress]);
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
          <View style={[styles.sourceChip, { backgroundColor: sourceColor + '22' }]}>
            <Text style={[styles.sourceText, { color: sourceColor }]}>{item.source}</Text>
          </View>

          {item.importance !== 'low' && (
            <View style={[styles.importancePill, { backgroundColor: stripeColor + '22' }]}>
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
              <Text style={[styles.priceChange, { color: pricePositive ? FC.positive : FC.negative }]}>
                {pricePositive ? '▲' : '▼'} {Math.abs(item.priceChange!).toFixed(2)}%
              </Text>
            </View>
          ) : (
            <View />
          )}

          <TouchableOpacity onPress={handleBookmark} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
            <Ionicons
              name={item.isBookmarked ? 'bookmark' : 'bookmark-outline'}
              size={18}
              color={item.isBookmarked ? FC.accent : FC.textMuted}
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
    backgroundColor: FC.surface,
    borderRadius: 12,
    overflow: 'hidden',
    marginHorizontal: 16,
    marginVertical: 5,
    borderWidth: 1,
    borderColor: FC.border,
  },
  cardUnread: {
    backgroundColor: FC.surfaceElevated,
  },
  stripe: {
    width: 3,
    flexShrink: 0,
  },
  content: {
    flex: 1,
    padding: 14,
    gap: 8,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexWrap: 'wrap',
  },
  sourceChip: {
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 4,
  },
  sourceText: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  importancePill: {
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 4,
  },
  importanceText: {
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  timeText: {
    fontSize: 11,
    color: FC.textMuted,
    marginLeft: 'auto',
  },
  title: {
    fontSize: 14,
    fontWeight: '600',
    color: FC.textPrimary,
    lineHeight: 20,
  },
  titleRead: {
    color: FC.textSecondary,
    fontWeight: '500',
  },
  summaryRow: {
    flexDirection: 'row',
    gap: 6,
    alignItems: 'flex-start',
  },
  aiLabel: {
    fontSize: 9,
    fontWeight: '700',
    color: FC.accent,
    backgroundColor: FC.accent + '22',
    paddingHorizontal: 5,
    paddingVertical: 2,
    borderRadius: 3,
    marginTop: 1,
    overflow: 'hidden',
  },
  summary: {
    flex: 1,
    fontSize: 12,
    color: FC.textSecondary,
    lineHeight: 17,
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
    gap: 6,
  },
  tickerChip: {
    backgroundColor: FC.border,
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 4,
  },
  tickerText: {
    fontSize: 11,
    fontWeight: '700',
    color: FC.textPrimary,
    fontFamily: Fonts?.ios?.mono ?? 'monospace',
  },
  priceChange: {
    fontSize: 12,
    fontWeight: '600',
    fontFamily: Fonts?.ios?.mono ?? 'monospace',
  },
});
