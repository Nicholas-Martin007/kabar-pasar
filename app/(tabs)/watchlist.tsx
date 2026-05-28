import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import React, { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { StockRow } from '@/components/stock-row';
import { mockNews } from '@/src/data/mockNews';
import { mockStocks } from '@/src/data/mockStocks';
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
  withAlpha13,
} from '@/src/theme';
import { Stock } from '@/src/types/stock';

function countRecentNews(ticker: string): number {
  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  return mockNews.filter(
    (n) => n.tickers.includes(ticker) && new Date(n.publishedAt).getTime() >= cutoff
  ).length;
}

// ── Add Stock Modal ──────────────────────────────────────────────────────────

interface AddStockModalProps {
  visible: boolean;
  watchlistTickers: Set<string>;
  onAdd: (ticker: string) => void;
  onClose: () => void;
}

function AddStockModal({ visible, watchlistTickers, onAdd, onClose }: AddStockModalProps) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return mockStocks;
    return mockStocks.filter(
      (s) =>
        s.ticker.toLowerCase().includes(q) ||
        s.name.toLowerCase().includes(q)
    );
  }, [query]);

  const handleClose = () => {
    setQuery('');
    onClose();
  };

  const renderStock = ({ item }: { item: Stock }) => {
    const added = watchlistTickers.has(item.ticker);
    return (
      <TouchableOpacity
        style={[styles.modalRow, added && styles.modalRowAdded]}
        onPress={() => !added && onAdd(item.ticker)}
        activeOpacity={added ? 1 : 0.7}
        disabled={added}
      >
        <View style={styles.modalRowLeft}>
          <View style={[styles.modalTickerChip, added && styles.modalTickerChipAdded]}>
            <Text style={[styles.modalTickerText, added && styles.modalTickerTextAdded]}>
              {item.ticker}
            </Text>
          </View>
          <View style={styles.modalNameBlock}>
            <Text
              style={[styles.modalName, added && styles.modalTextAdded]}
              numberOfLines={1}
            >
              {item.name}
            </Text>
            <Text style={styles.modalSector}>{item.sector}</Text>
          </View>
        </View>
        <Ionicons
          name={added ? 'checkmark-circle' : 'add-circle-outline'}
          size={IconSize.md}
          color={added ? Colors.brand.accent : Colors.text.muted}
        />
      </TouchableOpacity>
    );
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={handleClose}
    >
      <SafeAreaView style={styles.modalScreen} edges={['top', 'bottom']}>
        <KeyboardAvoidingView
          style={styles.modalContent}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >
          {/* Modal header */}
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Tambah Saham</Text>
            <TouchableOpacity
              onPress={handleClose}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            >
              <Ionicons name="close" size={IconSize.md} color={Colors.text.primary} />
            </TouchableOpacity>
          </View>

          {/* Search */}
          <View style={styles.searchWrap}>
            <Ionicons
              name="search-outline"
              size={16}
              color={Colors.text.muted}
              style={styles.searchIcon}
            />
            <TextInput
              style={styles.searchInput}
              value={query}
              onChangeText={setQuery}
              placeholder="Cari ticker atau nama perusahaan..."
              placeholderTextColor={Colors.text.muted}
              autoCapitalize="characters"
              autoCorrect={false}
              clearButtonMode="while-editing"
            />
          </View>

          <FlatList
            data={filtered}
            keyExtractor={(s) => s.ticker}
            renderItem={renderStock}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
            contentContainerStyle={styles.modalList}
            ItemSeparatorComponent={() => <View style={styles.modalDivider} />}
            ListEmptyComponent={
              <Text style={styles.modalEmpty}>Saham tidak ditemukan.</Text>
            }
          />
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}

// ── Empty State ──────────────────────────────────────────────────────────────

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <View style={styles.emptyState}>
      <Ionicons name="star-outline" size={52} color={Colors.text.muted} />
      <Text style={styles.emptyTitle}>Watchlist kosong</Text>
      <Text style={styles.emptyBody}>
        Tambah saham yang ingin kamu pantau agar tidak ketinggalan berita penting.
      </Text>
      <TouchableOpacity style={styles.emptyBtn} onPress={onAdd} activeOpacity={0.8}>
        <Text style={styles.emptyBtnText}>+ Tambah Saham</Text>
      </TouchableOpacity>
    </View>
  );
}

// ── Watchlist Screen ─────────────────────────────────────────────────────────

export default function WatchlistScreen() {
  const { items, tickers: watchlistTickers, add, remove } = useWatchlist();
  const [modalVisible, setModalVisible] = useState(false);
  const [refreshing, setRefreshing]     = useState(false);

  const stocks = useMemo(
    () =>
      items.flatMap((w) => {
        const s = mockStocks.find((s) => s.ticker === w.ticker);
        return s ? [s] : [];
      }),
    [items]
  );

  const newsCountMap = useMemo(() => {
    const map: Record<string, number> = {};
    for (const { ticker } of items) {
      map[ticker] = countRecentNews(ticker);
    }
    return map;
  }, [items]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    setTimeout(() => setRefreshing(false), 1000);
  }, []);

  const handlePress = useCallback((ticker: string) => {
    router.push(`/stock/${ticker}` as never);
  }, []);

  const handleLongPress = useCallback((ticker: string) => {
    Alert.alert(
      'Hapus dari Watchlist',
      `Hapus ${ticker} dari watchlist kamu?`,
      [
        { text: 'Batal', style: 'cancel' },
        {
          text: 'Hapus',
          style: 'destructive',
          onPress: () => remove(ticker),
        },
      ]
    );
  }, [remove]);

  const handleAdd = useCallback((ticker: string) => {
    add(ticker);
    setModalVisible(false);
  }, [add]);

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Watchlist</Text>
        <TouchableOpacity
          onPress={() => setModalVisible(true)}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          activeOpacity={0.7}
        >
          <Ionicons
            name="add-circle-outline"
            size={IconSize.md + 4}
            color={Colors.brand.accent}
          />
        </TouchableOpacity>
      </View>

      {stocks.length === 0 ? (
        <EmptyState onAdd={() => setModalVisible(true)} />
      ) : (
        <ScrollView
          contentContainerStyle={styles.listContent}
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
          <Text style={styles.hint}>Tahan lama pada saham untuk menghapus dari watchlist.</Text>

          <View style={styles.stockCard}>
            {stocks.map((stock, i) => (
              <React.Fragment key={stock.ticker}>
                <StockRow
                  stock={stock}
                  newsBadge={newsCountMap[stock.ticker]}
                  onPress={handlePress}
                  onLongPress={handleLongPress}
                />
                {i < stocks.length - 1 && <View style={styles.divider} />}
              </React.Fragment>
            ))}
          </View>
        </ScrollView>
      )}

      <AddStockModal
        visible={modalVisible}
        watchlistTickers={watchlistTickers}
        onAdd={handleAdd}
        onClose={() => setModalVisible(false)}
      />
    </SafeAreaView>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Colors.background.screen,
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
  headerTitle: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    letterSpacing: LetterSpacing.tight,
  },

  // List
  listContent: {
    paddingBottom: Layout.listPaddingBottom,
  },
  hint: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
    paddingHorizontal: Layout.screenPaddingX,
    paddingBottom: 10,
  },
  stockCard: {
    marginHorizontal: Layout.screenPaddingX,
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.card,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    overflow: 'hidden',
  },
  divider: {
    height: Border.width,
    backgroundColor: Colors.border.default,
    marginHorizontal: Layout.screenPaddingX,
  },

  // Empty state
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: Layout.screenPaddingX * 2,
    gap: 12,
  },
  emptyTitle: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    marginTop: 4,
  },
  emptyBody: {
    fontSize: FontSize.body,
    color: Colors.text.muted,
    textAlign: 'center',
    lineHeight: 18,
  },
  emptyBtn: {
    marginTop: 8,
    backgroundColor: withAlpha13(Colors.brand.accent),
    borderWidth: Border.width,
    borderColor: Colors.brand.accent,
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: Radius.pill,
  },
  emptyBtnText: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.semibold,
    color: Colors.brand.accent,
  },

  // Add Stock Modal
  modalScreen: {
    flex: 1,
    backgroundColor: Colors.background.screen,
  },
  modalContent: {
    flex: 1,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: Layout.screenPaddingX,
    paddingVertical: 14,
    borderBottomWidth: Border.width,
    borderBottomColor: Colors.border.default,
  },
  modalTitle: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    letterSpacing: LetterSpacing.tight,
  },
  searchWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    margin: Layout.screenPaddingX,
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.component,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    paddingHorizontal: 12,
    gap: 8,
  },
  searchIcon: {
    flexShrink: 0,
  },
  searchInput: {
    flex: 1,
    fontSize: FontSize.base,
    color: Colors.text.primary,
    paddingVertical: 11,
    fontFamily: FontFamily.sans ?? undefined,
  },
  modalList: {
    paddingBottom: Layout.listPaddingBottom,
  },
  modalDivider: {
    height: Border.width,
    backgroundColor: Colors.border.default,
    marginHorizontal: Layout.screenPaddingX,
  },
  modalEmpty: {
    fontSize: FontSize.body,
    color: Colors.text.muted,
    textAlign: 'center',
    paddingTop: Layout.emptyPaddingTop,
  },
  modalRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Layout.screenPaddingX,
    paddingVertical: 13,
  },
  modalRowAdded: {
    opacity: 0.5,
  },
  modalRowLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Layout.contentGap,
    flex: 1,
    minWidth: 0,
  },
  modalTickerChip: {
    backgroundColor: Colors.border.default,
    paddingHorizontal: Layout.chipPaddingX,
    paddingVertical: Layout.chipPaddingY + 1,
    borderRadius: Radius.chip,
    flexShrink: 0,
  },
  modalTickerChipAdded: {
    backgroundColor: withAlpha13(Colors.brand.accent),
    borderWidth: Border.width,
    borderColor: Colors.brand.accent,
  },
  modalTickerText: {
    fontSize: FontSize.small,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    fontFamily: FontFamily.mono ?? undefined,
  },
  modalTickerTextAdded: {
    color: Colors.brand.accent,
  },
  modalNameBlock: {
    flex: 1,
    minWidth: 0,
    gap: 2,
  },
  modalName: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.medium,
    color: Colors.text.primary,
  },
  modalTextAdded: {
    color: Colors.text.muted,
  },
  modalSector: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
  },
});
