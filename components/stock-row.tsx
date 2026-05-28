import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import {
  Colors,
  FontFamily,
  FontSize,
  FontWeight,
  Layout,
  Radius,
} from '@/src/theme';
import { Stock } from '@/src/types/stock';

interface Props {
  stock: Stock;
  onPress?: (ticker: string) => void;
}

const SPARKLINE_H = 28;
const BAR_W = 5;

function formatIDR(price: number): string {
  return Math.round(price)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

function formatPct(pct: number): string {
  return (pct >= 0 ? '+' : '') + pct.toFixed(2).replace('.', ',') + '%';
}

function SparklineBars({ data, positive }: { data: number[]; positive: boolean }) {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const color = positive ? Colors.sentiment.positive : Colors.sentiment.negative;

  return (
    <View style={styles.sparkline}>
      {data.map((v, i) => {
        const h = Math.max(3, Math.round(((v - min) / range) * (SPARKLINE_H - 4)));
        return <View key={i} style={[styles.bar, { height: h, backgroundColor: color }]} />;
      })}
    </View>
  );
}

export const StockRow = React.memo(({ stock, onPress }: Props) => {
  const positive   = stock.changePercent >= 0;
  const changeColor = positive ? Colors.sentiment.positive : Colors.sentiment.negative;

  return (
    <TouchableOpacity
      activeOpacity={0.7}
      onPress={() => onPress?.(stock.ticker)}
      style={styles.row}
    >
      <View style={styles.left}>
        <View style={styles.tickerChip}>
          <Text style={styles.tickerText}>{stock.ticker}</Text>
        </View>
        <Text style={styles.nameText} numberOfLines={1}>{stock.name}</Text>
      </View>

      <SparklineBars data={stock.sparkline} positive={positive} />

      <View style={styles.right}>
        <Text style={styles.priceText}>Rp {formatIDR(stock.price)}</Text>
        <Text style={[styles.changeText, { color: changeColor }]}>
          {formatPct(stock.changePercent)}
        </Text>
      </View>
    </TouchableOpacity>
  );
});

StockRow.displayName = 'StockRow';

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: Layout.screenPaddingX,
    paddingVertical: 12,
    gap: Layout.contentGap,
  },
  left: {
    flex: 1,
    minWidth: 0,
    gap: 3,
  },
  tickerChip: {
    backgroundColor: Colors.border.default,
    paddingHorizontal: Layout.chipPaddingX,
    paddingVertical: Layout.chipPaddingY,
    borderRadius: Radius.chip,
    alignSelf: 'flex-start',
  },
  tickerText: {
    fontSize: FontSize.small,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    fontFamily: FontFamily.mono ?? undefined,
  },
  nameText: {
    fontSize: FontSize.body,
    color: Colors.text.secondary,
  },
  sparkline: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 2,
    width: 47,
    height: SPARKLINE_H,
    flexShrink: 0,
  },
  bar: {
    width: BAR_W,
    borderRadius: 1,
  },
  right: {
    alignItems: 'flex-end',
    gap: 2,
    flexShrink: 0,
  },
  priceText: {
    fontSize: FontSize.body,
    fontWeight: FontWeight.semibold,
    color: Colors.text.primary,
    fontFamily: FontFamily.mono ?? undefined,
  },
  changeText: {
    fontSize: FontSize.small,
    fontWeight: FontWeight.bold,
  },
});
