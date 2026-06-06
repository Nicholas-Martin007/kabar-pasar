import { Ionicons } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import React, { useCallback, useLayoutEffect, useRef, useState } from 'react';
import {
  Dimensions,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { CandlestickChart } from '@/components/candlestick-chart';
import { LineChart } from '@/components/line-chart';
import { NewsCard } from '@/components/news-card';
import { mockStocks } from '@/src/data/mockStocks';
import { mockStockStats } from '@/src/data/mockStockStats';
import { useBookmarks } from '@/src/context/BookmarksContext';
import { useWatchlist } from '@/src/context/WatchlistContext';
import { useNewsFeed } from '@/src/hooks/useNews';
import { useChart, useQuote, useReactions } from '@/src/hooks/useMarket';
import { useStockLiveActivity } from '@/src/hooks/useStockLiveActivity';
import { ReactionItem } from '@/src/services/api';
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
import { News } from '@/src/types/news';

const SCREEN_W = Dimensions.get('window').width;
const CHART_W  = SCREEN_W - Layout.screenPaddingX * 2;
const CHART_H  = 160;

const TIME_RANGES = ['1H', '1D', '1W', '1M'] as const;
type TimeRange = typeof TIME_RANGES[number];

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatIDR(price: number): string {
  return Math.round(price)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

function formatPct(pct: number): string {
  return (pct >= 0 ? '+' : '') + pct.toFixed(2).replace('.', ',') + '%';
}

function formatVolume(v: number): string {
  if (v >= 1e12) return (v / 1e12).toFixed(1).replace('.', ',') + ' T';
  if (v >= 1e9) return (v / 1e9).toFixed(1).replace('.', ',') + ' M';
  if (v >= 1e6) return (v / 1e6).toFixed(1).replace('.', ',') + ' jt';
  if (v >= 1e3) return (v / 1e3).toFixed(1).replace('.', ',') + ' rb';
  return String(v);
}

function formatRange(lo?: number | null, hi?: number | null): string {
  if (lo == null || hi == null) return '—';
  return `${formatIDR(lo)} – ${formatIDR(hi)}`;
}

// ── Not-Found ─────────────────────────────────────────────────────────────────

function NotFound({ ticker }: { ticker: string }) {
  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <TouchableOpacity style={styles.backRow} onPress={() => router.back()}>
        <Ionicons name="chevron-back" size={IconSize.md} color={Colors.text.primary} />
        <Text style={styles.backLabel}>Kembali</Text>
      </TouchableOpacity>
      <View style={styles.notFound}>
        <Ionicons name="alert-circle-outline" size={48} color={Colors.text.muted} />
        <Text style={styles.notFoundTitle}>{ticker} tidak ditemukan</Text>
        <Text style={styles.notFoundBody}>
          Saham ini tidak ada dalam data kami.
        </Text>
      </View>
    </SafeAreaView>
  );
}

// ── Key stats grid ───────────────────────────────────────────────────────────

function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.statCell}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={styles.statValue}>{value}</Text>
    </View>
  );
}

// ── Main screen ──────────────────────────────────────────────────────────────

export default function StockDetailScreen() {
  const { ticker } = useLocalSearchParams<{ ticker: string }>();
  const { contains, toggle } = useWatchlist();
  const live = useStockLiveActivity();

  const stock    = mockStocks.find((s) => s.ticker === ticker);
  const stats    = ticker ? mockStockStats[ticker] : undefined;
  const inWatchlist = ticker ? contains(ticker) : false;

  const { isBookmarked, toggle: handleBookmark } = useBookmarks();
  const [activeRange, setActiveRange] = useState<TimeRange>('1W');
  const [chartStyle, setChartStyle]   = useState<'line' | 'candle'>('line');
  const [readIds,       setReadIds]   = useState(new Set<string>());

  // Live market data (falls back to mock stock values when unavailable).
  const { data: quote } = useQuote(ticker);
  const { data: chart } = useChart(ticker, activeRange);
  const { data: allNews } = useNewsFeed({ limit: 200 });

  const handleNewsPress = useCallback((id: string) => {
    setReadIds((prev) => new Set(prev).add(id));
    router.push(`/news/${id}` as never);
  }, []);

  // Pin/unpin this stock to the iOS lock screen via a Live Activity.
  // Uses live quote data when available; no-ops until a native dev build exists.
  const handleTogglePin = useCallback(() => {
    if (!stock) return;
    if (live.isActive) {
      live.end();
      return;
    }
    const headline =
      allNews
        .filter((n) => n.tickers.includes(stock.ticker))
        .sort(
          (a, b) =>
            new Date(b.publishedAt).getTime() - new Date(a.publishedAt).getTime()
        )[0]?.title ?? 'Pantau pergerakan saham ini';
    const livePrice = quote?.price ?? stock.price;
    const livePct = quote?.changePercent ?? stock.changePercent;
    live.start(
      { ticker: stock.ticker, companyName: stock.name },
      {
        price: `Rp ${formatIDR(livePrice)}`,
        changePercent: livePct,
        headline,
      }
    );
  }, [live, stock, quote, allNews]);

  // Related news (live) — computed before the early return so the reaction
  // hook below is always called in the same order.
  const relatedNews: News[] = React.useMemo(
    () =>
      !stock
        ? []
        : allNews
            .filter((n) => n.tickers.includes(stock.ticker))
            .sort(
              (a, b) =>
                new Date(b.publishedAt).getTime() -
                new Date(a.publishedAt).getTime()
            ),
    [allNews, stock]
  );

  const relatedReactionItems: ReactionItem[] = React.useMemo(
    () =>
      relatedNews
        .slice(0, 20)
        .map((n) => ({ key: n.id, ticker: n.tickers[0], at: n.publishedAt })),
    [relatedNews]
  );
  const { data: relatedReactionMap, isLoading: relatedReactionsLoading } =
    useReactions(relatedReactionItems);

  if (!stock) return <NotFound ticker={ticker ?? '—'} />;

  // Prefer live data; fall back to the bundled mock stock.
  const price         = quote?.price ?? stock.price;
  const change        = quote?.change ?? stock.change;
  const changePercent = quote?.changePercent ?? stock.changePercent;
  const livePoints    = (chart?.points ?? []).filter(
    (p): p is number => p !== null
  );
  const sparkline     = livePoints.length > 1 ? livePoints : stock.sparkline;
  const candles       = chart?.candles ?? [];
  const canShowCandles = candles.length > 1;

  const positive    = changePercent >= 0;
  const changeColor = positive ? Colors.sentiment.positive : Colors.sentiment.negative;

  // Live Activities only work in a native build with the widget extension.
  // Until then, show a disabled "coming soon" placeholder.
  const canPin = live.isSupported();

  // Live fundamentals where Yahoo provides them; mock fallback for the rest.
  const volumeText =
    quote?.volume != null ? formatVolume(quote.volume) : stats?.volume ?? '—';
  const dayRangeText = formatRange(
    quote?.dayLow ?? stats?.dayLow,
    quote?.dayHigh ?? stats?.dayHigh
  );
  const week52Text = formatRange(
    quote?.week52Low ?? stats?.week52Low,
    quote?.week52High ?? stats?.week52High
  );

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      {/* ── Navbar ──────────────────────────────────────────────────────── */}
      <View style={styles.navbar}>
        <TouchableOpacity
          style={styles.navBtn}
          onPress={() => router.back()}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Ionicons name="chevron-back" size={IconSize.md} color={Colors.text.primary} />
          <Text style={styles.backLabel}>Kembali</Text>
        </TouchableOpacity>

        <View style={styles.navCenter}>
          <Text style={styles.navTicker}>{stock.ticker}</Text>
          <Text style={styles.navName} numberOfLines={1}>{stock.name}</Text>
        </View>

        <TouchableOpacity
          onPress={() => toggle(stock.ticker)}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          activeOpacity={0.7}
        >
          <Ionicons
            name={inWatchlist ? 'star' : 'star-outline'}
            size={IconSize.md}
            color={inWatchlist ? Colors.brand.accent : Colors.text.muted}
          />
        </TouchableOpacity>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        {/* ── Price section ───────────────────────────────────────────── */}
        <View style={styles.priceSection}>
          <Text style={styles.priceValue}>Rp {formatIDR(price)}</Text>
          <View style={styles.priceChangeRow}>
            <Text style={[styles.changeAbs, { color: changeColor }]}>
              {change >= 0 ? '+' : ''}{formatIDR(change)}
            </Text>
            <Text style={[styles.changePct, { color: changeColor }]}>
              ({formatPct(changePercent)})
            </Text>
          </View>
          <Text style={styles.sectorLabel}>{stock.sector}</Text>
        </View>

        {/* ── Pin to Lock Screen (iOS Live Activity) ──────────────────── */}
        {Platform.OS === 'ios' &&
          (canPin ? (
            <TouchableOpacity
              style={[styles.pinBtn, live.isActive && styles.pinBtnActive]}
              onPress={handleTogglePin}
              activeOpacity={0.8}
              accessibilityRole="button"
              accessibilityLabel={
                live.isActive
                  ? `Lepas ${stock.ticker} dari lock screen`
                  : `Sematkan ${stock.ticker} ke lock screen`
              }
            >
              <Ionicons
                name={live.isActive ? 'lock-open-outline' : 'lock-closed-outline'}
                size={IconSize.sm}
                color={live.isActive ? Colors.text.muted : Colors.brand.accent}
              />
              <Text
                style={[
                  styles.pinBtnText,
                  live.isActive && styles.pinBtnTextActive,
                ]}
              >
                {live.isActive
                  ? 'Lepas dari Lock Screen'
                  : 'Sematkan ke Lock Screen'}
              </Text>
            </TouchableOpacity>
          ) : (
            // Placeholder: feature needs a native build to function.
            <View
              style={[styles.pinBtn, styles.pinBtnDisabled]}
              accessibilityRole="text"
              accessibilityLabel="Live Activity lock screen, segera hadir"
            >
              <Ionicons
                name="lock-closed-outline"
                size={IconSize.sm}
                color={Colors.text.muted}
              />
              <Text style={styles.pinBtnTextDisabled}>
                Lock Screen · Segera hadir
              </Text>
            </View>
          ))}

        {/* ── Chart ───────────────────────────────────────────────────── */}
        <View style={styles.chartCard}>
          {/* Chart-style toggle: line / candlestick */}
          <View style={styles.chartStyleRow}>
            <TouchableOpacity
              style={[styles.styleBtn, chartStyle === 'line' && styles.styleBtnActive]}
              onPress={() => setChartStyle('line')}
              activeOpacity={0.7}
              accessibilityLabel="Grafik garis"
            >
              <Ionicons
                name="pulse"
                size={15}
                color={chartStyle === 'line' ? Colors.brand.accent : Colors.text.muted}
              />
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.styleBtn, chartStyle === 'candle' && styles.styleBtnActive]}
              onPress={() => setChartStyle('candle')}
              activeOpacity={0.7}
              accessibilityLabel="Grafik candlestick"
            >
              <Ionicons
                name="stats-chart"
                size={15}
                color={chartStyle === 'candle' ? Colors.brand.accent : Colors.text.muted}
              />
            </TouchableOpacity>
          </View>

          {chartStyle === 'candle' && canShowCandles ? (
            <CandlestickChart
              candles={candles}
              width={CHART_W - Layout.cardPadding * 2 - 48}
              height={CHART_H}
            />
          ) : (
            <LineChart
              data={sparkline}
              width={CHART_W - Layout.cardPadding * 2 - 48}
              height={CHART_H}
              positive={positive}
            />
          )}

          {/* Time range selector */}
          <View style={styles.rangeRow}>
            {TIME_RANGES.map((r) => (
              <TouchableOpacity
                key={r}
                style={[
                  styles.rangeBtn,
                  activeRange === r && styles.rangeBtnActive,
                ]}
                onPress={() => setActiveRange(r)}
                activeOpacity={0.7}
              >
                <Text
                  style={[
                    styles.rangeBtnText,
                    activeRange === r && styles.rangeBtnTextActive,
                  ]}
                >
                  {r}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* ── Key stats (live where free; mock fallback otherwise) ────── */}
        {(stats || quote?.available) && (
          <View style={styles.statsSection}>
            <Text style={styles.sectionLabel}>Statistik Saham</Text>
            <View style={styles.statsGrid}>
              <StatCell label="Market Cap"   value={stats?.marketCap ?? '—'} />
              <StatCell label="Volume"       value={volumeText} />
              <StatCell label="Day Range"    value={dayRangeText} />
              <StatCell label="52-Week Range" value={week52Text} />
              <StatCell
                label="PER"
                value={stats?.per != null ? `${stats.per.toFixed(1)}x` : '—'}
              />
              <StatCell
                label="Div. Yield"
                value={
                  stats?.dividendYield != null
                    ? `${stats.dividendYield.toFixed(1)}%`
                    : '—'
                }
              />
            </View>
          </View>
        )}

        {/* ── Related news ────────────────────────────────────────────── */}
        <View style={styles.newsSection}>
          <Text style={styles.sectionLabel}>Berita Terkait</Text>
          {relatedNews.length === 0 ? (
            <Text style={styles.emptyText}>
              Belum ada berita untuk {stock.ticker}.
            </Text>
          ) : (
            relatedNews.map((item) => (
              <NewsCard
                key={item.id}
                item={item}
                isRead={readIds.has(item.id)}
                isBookmarked={isBookmarked(item.id)}
                onPress={handleNewsPress}
                onBookmark={handleBookmark}
                reaction={relatedReactionMap?.get(item.id)}
                reactionLoading={relatedReactionsLoading}
              />
            ))
          )}
        </View>
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
    alignItems: 'center',
    paddingHorizontal: Layout.screenPaddingX,
    paddingVertical: 12,
    borderBottomWidth: Border.width,
    borderBottomColor: Colors.border.default,
    gap: Layout.contentGap,
  },
  navBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    flexShrink: 0,
  },
  backLabel: {
    fontSize: FontSize.base,
    color: Colors.text.primary,
    fontWeight: FontWeight.medium,
  },
  navCenter: {
    flex: 1,
    alignItems: 'center',
    minWidth: 0,
  },
  navTicker: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    fontFamily: FontFamily.mono ?? undefined,
    letterSpacing: LetterSpacing.wide,
  },
  navName: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
  },

  scroll: {
    paddingBottom: 48,
  },

  // Price
  priceSection: {
    paddingHorizontal: Layout.screenPaddingX,
    paddingTop: 20,
    paddingBottom: 4,
    gap: 4,
  },
  priceValue: {
    fontSize: 32,
    fontWeight: FontWeight.extrabold,
    color: Colors.text.primary,
    fontFamily: FontFamily.mono ?? undefined,
    letterSpacing: LetterSpacing.tight,
  },
  priceChangeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  changeAbs: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.semibold,
    fontFamily: FontFamily.mono ?? undefined,
  },
  changePct: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.semibold,
  },
  sectorLabel: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
    marginTop: 2,
    letterSpacing: LetterSpacing.wide,
  },

  // Pin to lock screen button
  pinBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginHorizontal: Layout.screenPaddingX,
    marginTop: 16,
    paddingVertical: 12,
    borderRadius: Radius.component,
    borderWidth: Border.width,
    borderColor: Colors.brand.accent,
    backgroundColor: withAlpha13(Colors.brand.accent),
  },
  pinBtnActive: {
    borderColor: Colors.border.default,
    backgroundColor: Colors.background.surface,
  },
  pinBtnText: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.semibold,
    color: Colors.brand.accent,
  },
  pinBtnTextActive: {
    color: Colors.text.muted,
  },
  pinBtnDisabled: {
    borderColor: Colors.border.default,
    borderStyle: 'dashed',
    backgroundColor: 'transparent',
  },
  pinBtnTextDisabled: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.medium,
    color: Colors.text.muted,
  },

  // Chart card
  chartCard: {
    marginHorizontal: Layout.screenPaddingX,
    marginTop: 16,
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.card,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    padding: Layout.cardPadding,
    gap: 16,
  },
  chartStyleRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 6,
    marginBottom: 4,
  },
  styleBtn: {
    padding: 6,
    borderRadius: Radius.chip,
    borderWidth: Border.width,
    borderColor: 'transparent',
  },
  styleBtnActive: {
    backgroundColor: withAlpha13(Colors.brand.accent),
    borderColor: Colors.brand.accent,
  },
  rangeRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: Layout.rowGap,
  },
  rangeBtn: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: Radius.pill,
  },
  rangeBtnActive: {
    backgroundColor: withAlpha13(Colors.brand.accent),
    borderWidth: Border.width,
    borderColor: Colors.brand.accent,
  },
  rangeBtnText: {
    fontSize: FontSize.small,
    fontWeight: FontWeight.semibold,
    color: Colors.text.muted,
    letterSpacing: LetterSpacing.wide,
  },
  rangeBtnTextActive: {
    color: Colors.brand.accent,
  },

  // Stats
  statsSection: {
    marginHorizontal: Layout.screenPaddingX,
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
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.card,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    overflow: 'hidden',
  },
  statCell: {
    width: '50%',
    padding: 14,
    borderRightWidth: Border.width,
    borderBottomWidth: Border.width,
    borderColor: Colors.border.default,
    gap: 4,
  },
  statLabel: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
    letterSpacing: LetterSpacing.wide,
  },
  statValue: {
    fontSize: FontSize.body,
    fontWeight: FontWeight.semibold,
    color: Colors.text.primary,
    fontFamily: FontFamily.mono ?? undefined,
  },

  // News
  newsSection: {
    marginTop: 28,
    gap: 4,
  },
  emptyText: {
    fontSize: FontSize.body,
    color: Colors.text.muted,
    paddingHorizontal: Layout.screenPaddingX,
    marginTop: 4,
  },

  // Not-found
  backRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: Layout.screenPaddingX,
    paddingVertical: 12,
  },
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
});
