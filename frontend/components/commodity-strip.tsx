import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { useCommodities } from '@/src/hooks/useCommodities';
import { CommodityQuote } from '@/src/services/api';
import {
  Border,
  Colors,
  FontSize,
  FontWeight,
  Layout,
  LetterSpacing,
  Radius,
  withAlpha13,
} from '@/src/theme';

// Short, localised labels per tracked symbol. Proxies carry the underlying
// commodity in `proxyFor` so the chip can say "Batu bara · proxy" rather than
// pretending a miner's share price is a spot price.
const LABELS: Record<string, { label: string; proxyFor?: string }> = {
  'GC=F': { label: 'Emas' },
  'CL=F': { label: 'Minyak WTI' },
  'BZ=F': { label: 'Minyak Brent' },
  'ADRO.JK': { label: 'Adaro', proxyFor: 'Batu bara' },
  'PTBA.JK': { label: 'Bukit Asam', proxyFor: 'Batu bara' },
  'ITMG.JK': { label: 'ITMG', proxyFor: 'Batu bara' },
  'INCO.JK': { label: 'Vale ID', proxyFor: 'Nikel' },
  'ANTM.JK': { label: 'Antam', proxyFor: 'Nikel' },
};

function formatPrice(value: number, currency: string): string {
  const decimals = currency === 'IDR' ? 0 : 2;
  const [int, dec] = value.toFixed(decimals).split('.');
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, '.'); // Indonesian grouping
  return dec ? `${grouped},${dec}` : grouped;
}

function CommodityChip({ q }: { q: CommodityQuote }) {
  const meta = LABELS[q.symbol] ?? { label: q.name };
  const pct = q.changePercent;
  const pctColor =
    pct == null
      ? Colors.text.muted
      : pct >= 0
        ? Colors.sentiment.positive
        : Colors.sentiment.negative;
  const pctText =
    pct == null ? '—' : `${pct >= 0 ? '+' : ''}${pct.toFixed(2).replace('.', ',')}%`;

  return (
    <View style={styles.chip}>
      <View style={styles.chipTop}>
        <Text style={styles.chipLabel} numberOfLines={1}>
          {meta.label}
        </Text>
        {q.isProxy && <Text style={styles.proxyTag}>proxy</Text>}
      </View>
      <Text style={styles.chipPrice} numberOfLines={1}>
        {formatPrice(q.price, q.currency)}
        <Text style={styles.chipCurrency}> {q.currency}</Text>
      </Text>
      <Text style={[styles.chipChange, { color: pctColor }]} numberOfLines={1}>
        {pctText}
        {meta.proxyFor ? <Text style={styles.chipSub}>  ·  {meta.proxyFor}</Text> : null}
      </Text>
    </View>
  );
}

/**
 * Horizontal strip of live commodity prices. Self-contained: pulls from the
 * ['commodities'] query (seeded by REST, kept live by the WebSocket stream) and
 * renders nothing until there's data, so it never shows an empty section.
 */
export function CommodityStrip() {
  const { data } = useCommodities();
  if (!data || data.length === 0) return null;

  // Real futures first, proxies after — they're different kinds of number.
  const ordered = [...data].sort((a, b) => Number(a.isProxy) - Number(b.isProxy));

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>Komoditas</Text>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.scroll}
      >
        {ordered.map((q) => (
          <CommodityChip key={q.symbol} q={q} />
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
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
  scroll: {
    paddingHorizontal: Layout.screenPaddingX,
    gap: 10,
  },
  chip: {
    minWidth: 132,
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.card,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 4,
  },
  chipTop: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 6,
  },
  chipLabel: {
    flexShrink: 1,
    fontSize: FontSize.caption,
    fontWeight: FontWeight.semibold,
    color: Colors.text.secondary,
    letterSpacing: LetterSpacing.wide,
  },
  proxyTag: {
    fontSize: FontSize.badge,
    fontWeight: FontWeight.bold,
    color: Colors.text.muted,
    backgroundColor: withAlpha13(Colors.text.muted),
    borderRadius: Radius.badge,
    paddingHorizontal: Layout.badgePaddingX,
    paddingVertical: Layout.badgePaddingY,
    overflow: 'hidden',
    textTransform: 'uppercase',
  },
  chipPrice: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.extrabold,
    color: Colors.text.primary,
    letterSpacing: LetterSpacing.tight,
  },
  chipCurrency: {
    fontSize: FontSize.badge,
    fontWeight: FontWeight.semibold,
    color: Colors.text.muted,
  },
  chipChange: {
    fontSize: FontSize.caption,
    fontWeight: FontWeight.bold,
  },
  chipSub: {
    fontWeight: FontWeight.semibold,
    color: Colors.text.muted,
  },
});
