import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useRef } from 'react';
import { Animated, StyleSheet, Text, TouchableOpacity, View } from 'react-native';

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
import { Reaction } from '@/src/services/api';
import { News, NewsImportance, NewsSource } from '@/src/types/news';
import { formatDateTime } from '@/utils/time';

interface Props {
  item: News;
  isRead: boolean;
  isBookmarked: boolean;
  onPress: (id: string) => void;
  onBookmark: (id: string) => void;
  /** Optional post-news price reaction badge (news -> price linkage). */
  reaction?: Reaction | null;
  /** Show a shimmer placeholder while the batched reaction is resolving. */
  reactionLoading?: boolean;
}

/** Pulsing skeleton shown in place of the reaction badge while it loads. */
function ReactionSkeleton() {
  const opacity = useRef(new Animated.Value(0.4)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 1,
          duration: 700,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.4,
          duration: 700,
          useNativeDriver: true,
        }),
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);
  return <Animated.View style={[styles.reactionSkeleton, { opacity }]} />;
}

const IMPORTANCE_COLOR: Record<NewsImportance, string> = {
  high:   Colors.importance.high,
  medium: Colors.importance.medium,
  low:    Colors.importance.low,
};

const IMPORTANCE_LABEL: Record<NewsImportance, string> = {
  high:   'PENTING',
  medium: 'INFO',
  low:    'UMUM',
};

const SOURCE_COLOR: Record<NewsSource, string> = {
  'CNBC Indonesia':   Colors.source['CNBC Indonesia'],
  'Detik Finance':    Colors.source['Detik Finance'],
  Kontan:             Colors.source.Kontan,
  'Bisnis Indonesia': Colors.source['Bisnis Indonesia'],
  BEI:                Colors.source.BEI,
  'IR Emiten':        Colors.source['IR Emiten'],
};

export const NewsCard = React.memo(({ item, isRead, isBookmarked, onPress, onBookmark, reaction, reactionLoading }: Props) => {
  const stripeColor = IMPORTANCE_COLOR[item.importance];
  const sourceColor = SOURCE_COLOR[item.source];

  const reactionPct =
    reaction?.available && reaction.reactionPercent != null
      ? reaction.reactionPercent
      : null;
  // Shimmer only for cards that have a ticker and are still awaiting a result.
  const showReactionSkeleton =
    !!reactionLoading && reactionPct == null && item.tickers.length > 0;
  const reactionColor =
    reactionPct == null
      ? Colors.text.muted
      : reactionPct >= 0
        ? Colors.sentiment.positive
        : Colors.sentiment.negative;

  const handlePress    = useCallback(() => onPress(item.id),    [item.id, onPress]);
  const handleBookmark = useCallback(() => onBookmark(item.id), [item.id, onBookmark]);

  return (
    <TouchableOpacity
      activeOpacity={0.75}
      onPress={handlePress}
      style={[styles.card, !isRead && styles.cardUnread]}
    >
      {/* Importance stripe — color encodes urgency level */}
      <View style={[styles.stripe, { backgroundColor: stripeColor }]} />

      <View style={styles.content}>
        {/* Row 1: source + importance badge + timestamp */}
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

          <Text style={styles.timeText}>{formatDateTime(item.publishedAt)}</Text>
        </View>

        {/* Row 2: title */}
        <Text style={[styles.title, isRead && styles.titleRead]} numberOfLines={2}>
          {item.title}
        </Text>

        {/* Row 3: AI bullet summary */}
        <View style={styles.summaryRow}>
          <Text style={styles.aiLabel}>AI</Text>
          <View style={styles.bulletList}>
            {item.aiSummary.slice(0, 3).map((point, i) => (
              <View key={i} style={styles.bulletRow}>
                <Text style={styles.bulletDot}>·</Text>
                <Text style={styles.bulletText} numberOfLines={2}>{point}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* Row 4: tickers + reaction + bookmark */}
        <View style={styles.bottomRow}>
          <View style={styles.bottomLeft}>
            {item.tickers.length > 0 && (
              <View style={styles.tickerGroup}>
                {item.tickers.slice(0, 2).map((t) => (
                  <View key={t} style={styles.tickerChip}>
                    <Text style={styles.tickerText}>{t}</Text>
                  </View>
                ))}
                {item.tickers.length > 2 && (
                  <Text style={styles.tickerOverflow}>+{item.tickers.length - 2}</Text>
                )}
              </View>
            )}

            {reactionPct != null ? (
              <View
                style={[
                  styles.reactionBadge,
                  { backgroundColor: withAlpha13(reactionColor) },
                ]}
              >
                <Ionicons
                  name={reactionPct >= 0 ? 'trending-up' : 'trending-down'}
                  size={10}
                  color={reactionColor}
                />
                <Text style={[styles.reactionText, { color: reactionColor }]}>
                  {reactionPct >= 0 ? '+' : ''}
                  {reactionPct.toFixed(1).replace('.', ',')}%
                </Text>
              </View>
            ) : showReactionSkeleton ? (
              <ReactionSkeleton />
            ) : null}
          </View>

          <TouchableOpacity
            onPress={handleBookmark}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          >
            <Ionicons
              name={isBookmarked ? 'bookmark' : 'bookmark-outline'}
              size={IconSize.sm}
              color={isBookmarked ? Colors.brand.accent : Colors.text.muted}
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
    marginTop: 2,
    overflow: 'hidden',
  },
  bulletList: {
    flex: 1,
    gap: 3,
  },
  bulletRow: {
    flexDirection: 'row',
    gap: 4,
    alignItems: 'flex-start',
  },
  bulletDot: {
    fontSize: FontSize.body,
    color: Colors.text.muted,
    lineHeight: LineHeight.tight,
    marginTop: 0,
  },
  bulletText: {
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
  bottomLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Layout.rowGap,
    flexShrink: 1,
    flexWrap: 'wrap',
  },
  tickerGroup: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Layout.rowGap,
  },
  reactionBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    paddingHorizontal: Layout.chipPaddingX,
    paddingVertical: Layout.chipPaddingY,
    borderRadius: Radius.chip,
  },
  reactionText: {
    fontSize: FontSize.small,
    fontWeight: FontWeight.bold,
    fontFamily: FontFamily.mono ?? undefined,
  },
  reactionSkeleton: {
    width: 52,
    height: 18,
    borderRadius: Radius.chip,
    backgroundColor: Colors.border.default,
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
  tickerOverflow: {
    fontSize: FontSize.small,
    color: Colors.text.muted,
  },
});
