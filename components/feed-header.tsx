import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { FC } from '@/constants/financial-colors';
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
  { key: 'all', label: 'Semua' },
  { key: 'watchlist', label: 'Watchlist' },
  { key: 'idx', label: 'IDX/BEI' },
  { key: 'macro', label: 'Makro' },
  { key: 'global', label: 'Global' },
];

const DAYS_ID = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu'];
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
          <Ionicons name="notifications-outline" size={22} color={FC.textSecondary} />
        </TouchableOpacity>
      </View>

      <View style={styles.marketBar}>
        <View style={styles.marketLeft}>
          <Text style={styles.marketLabel}>IHSG</Text>
          <Text style={styles.marketValue}>{market.value.toLocaleString('id-ID', { minimumFractionDigits: 2 })}</Text>
        </View>
        <View style={styles.marketRight}>
          <Text style={[styles.marketChange, { color: pricePositive ? FC.positive : FC.negative }]}>
            {pricePositive ? '▲' : '▼'} {Math.abs(market.change).toFixed(2)}%
          </Text>
          <View style={[styles.statusDot, { backgroundColor: market.isOpen ? FC.positive : FC.textMuted }]} />
          <Text style={[styles.statusText, { color: market.isOpen ? FC.positive : FC.textMuted }]}>
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
              <Text style={[styles.filterText, active && styles.filterTextActive]}>{f.label}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: FC.background,
    paddingTop: 16,
    paddingBottom: 8,
    gap: 14,
  },
  topRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    paddingHorizontal: 16,
  },
  appName: {
    fontSize: 22,
    fontWeight: '800',
    color: FC.textPrimary,
    letterSpacing: -0.3,
  },
  dateText: {
    fontSize: 12,
    color: FC.textMuted,
    marginTop: 2,
  },
  notifButton: {
    padding: 4,
  },
  marketBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginHorizontal: 16,
    backgroundColor: FC.surface,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: FC.border,
  },
  marketLeft: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 8,
  },
  marketLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: FC.accent,
    letterSpacing: 0.5,
  },
  marketValue: {
    fontSize: 16,
    fontWeight: '700',
    color: FC.textPrimary,
    letterSpacing: -0.3,
  },
  marketRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  marketChange: {
    fontSize: 14,
    fontWeight: '600',
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  statusText: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  filtersContent: {
    paddingHorizontal: 16,
    gap: 8,
  },
  filterChip: {
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 20,
    backgroundColor: FC.surface,
    borderWidth: 1,
    borderColor: FC.border,
  },
  filterChipActive: {
    backgroundColor: FC.accent + '22',
    borderColor: FC.accent,
  },
  filterText: {
    fontSize: 13,
    fontWeight: '500',
    color: FC.textSecondary,
  },
  filterTextActive: {
    color: FC.accent,
    fontWeight: '700',
  },
});
