import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import {
  Border,
  Colors,
  FontSize,
  FontWeight,
  IconSize,
  Layout,
  LetterSpacing,
  Radius,
  withAlpha13,
} from '@/src/theme';
import { FeedFilter } from '@/types/news';

interface MarketSnapshot {
  index: string;
  value: number;
  change: number;
  isOpen: boolean;
}

interface Props {
  activeFilter: FeedFilter;
  onFilterChange: (filter: FeedFilter) => void;
  onNotification: () => void;
  market: MarketSnapshot;
}

const FILTERS: { key: FeedFilter; label: string }[] = [
  { key: 'all',       label: 'Semua' },
  { key: 'watchlist', label: 'Watchlist' },
  { key: 'idx',       label: 'IDX/BEI' },
  { key: 'macro',     label: 'Makro' },
  { key: 'global',    label: 'Global' },
];

const DAYS_ID   = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu'];
const MONTHS_ID = [
  'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
  'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember',
];

function formatDateID(): string {
  const d = new Date();
  return `${DAYS_ID[d.getDay()]}, ${d.getDate()} ${MONTHS_ID[d.getMonth()]} ${d.getFullYear()}`;
}

export function FeedHeader({ activeFilter, onFilterChange, onNotification, market }: Props) {
  const pricePositive = market.change >= 0;

  return (
    <View style={styles.container}>
      <View style={styles.topRow}>
        <View>
          <Text style={styles.appName}>Kabar Pasar</Text>
          <Text style={styles.dateText}>{formatDateID()}</Text>
        </View>
        <TouchableOpacity onPress={onNotification} style={styles.notifButton}>
          <Ionicons name="notifications-outline" size={IconSize.md} color={Colors.text.secondary} />
        </TouchableOpacity>
      </View>

      <View style={styles.marketBar}>
        <View style={styles.marketLeft}>
          <Text style={styles.marketLabel}>{market.index}</Text>
          <Text style={styles.marketValue}>
            {market.value.toLocaleString('id-ID', { minimumFractionDigits: 2 })}
          </Text>
        </View>
        <View style={styles.marketRight}>
          <Text
            style={[
              styles.marketChange,
              { color: pricePositive ? Colors.sentiment.positive : Colors.sentiment.negative },
            ]}
          >
            {pricePositive ? '▲' : '▼'} {Math.abs(market.change).toFixed(2)}%
          </Text>
          <View
            style={[
              styles.statusDot,
              { backgroundColor: market.isOpen ? Colors.sentiment.positive : Colors.text.muted },
            ]}
          />
          <Text
            style={[
              styles.statusText,
              { color: market.isOpen ? Colors.sentiment.positive : Colors.text.muted },
            ]}
          >
            {market.isOpen ? 'BUKA' : 'TUTUP'}
          </Text>
        </View>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.filtersContent}
      >
        {FILTERS.map((f) => {
          const active = f.key === activeFilter;
          return (
            <TouchableOpacity
              key={f.key}
              onPress={() => onFilterChange(f.key)}
              style={[styles.filterChip, active && styles.filterChipActive]}
            >
              <Text style={[styles.filterText, active && styles.filterTextActive]}>
                {f.label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: Colors.background.screen,
    paddingTop: Layout.screenPaddingX,
    paddingBottom: Layout.contentGap,
    gap: Layout.sectionGap,
  },
  topRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingHorizontal: Layout.screenPaddingX,
  },
  appName: {
    fontSize: FontSize.title,
    fontWeight: FontWeight.extrabold,
    color: Colors.text.primary,
    letterSpacing: LetterSpacing.tight,
  },
  dateText: {
    fontSize: FontSize.body,
    color: Colors.text.muted,
    marginTop: 2,
  },
  notifButton: {
    padding: Layout.badgePaddingY,
  },
  marketBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginHorizontal: Layout.screenPaddingX,
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.component,
    paddingHorizontal: Layout.componentPaddingX,
    paddingVertical: Layout.componentPaddingY,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
  },
  marketLeft: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: Layout.contentGap,
  },
  marketLabel: {
    fontSize: FontSize.caption,
    fontWeight: FontWeight.bold,
    color: Colors.brand.accent,
    letterSpacing: LetterSpacing.wider,
  },
  marketValue: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    letterSpacing: LetterSpacing.tight,
  },
  marketRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Layout.contentGap,
  },
  marketChange: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.semibold,
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  statusText: {
    fontSize: FontSize.caption,
    fontWeight: FontWeight.bold,
    letterSpacing: LetterSpacing.wider,
  },
  filtersContent: {
    paddingHorizontal: Layout.screenPaddingX,
    gap: Layout.contentGap,
  },
  filterChip: {
    paddingHorizontal: Layout.filterChipPaddingX,
    paddingVertical: Layout.filterChipPaddingY,
    borderRadius: Radius.pill,
    backgroundColor: Colors.background.surface,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
  },
  filterChipActive: {
    backgroundColor: withAlpha13(Colors.brand.accent),
    borderColor: Colors.brand.accent,
  },
  filterText: {
    fontSize: FontSize.filter,
    fontWeight: FontWeight.medium,
    color: Colors.text.secondary,
  },
  filterTextActive: {
    color: Colors.brand.accent,
    fontWeight: FontWeight.bold,
  },
});
