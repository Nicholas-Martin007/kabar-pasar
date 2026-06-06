import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import React, { useState } from 'react';
import {
  Alert,
  FlatList,
  Modal,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  type ImportanceFilter,
  type Language,
  type QuietHours,
  type ThemePreference,
  useSettings,
} from '@/src/context/SettingsContext';
import { useTelegramLink } from '@/src/context/TelegramLinkContext';
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
import { NewsCategory } from '@/src/types/news';

const APP_VERSION = '0.1.0 (mock)';

// ── Mock user ────────────────────────────────────────────────────────────────

const MOCK_USER = {
  name:   'Nicholas Martin',
  email:  'nicholas.martin1012@gmail.com',
  initials: 'NM',
};

// ── Reusable section / row primitives ───────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.sectionCard}>{children}</View>
    </View>
  );
}

interface RowProps {
  label:    string;
  sublabel?: string;
  left?:    React.ReactNode;
  right?:   React.ReactNode;
  onPress?: () => void;
  danger?:  boolean;
  last?:    boolean;
}

function Row({ label, sublabel, left, right, onPress, danger, last }: RowProps) {
  const content = (
    <View style={[styles.row, !last && styles.rowBorder]}>
      {left && <View style={styles.rowLeft}>{left}</View>}
      <View style={styles.rowMiddle}>
        <Text style={[styles.rowLabel, danger && styles.rowLabelDanger]}>{label}</Text>
        {sublabel && <Text style={styles.rowSublabel}>{sublabel}</Text>}
      </View>
      {right && <View style={styles.rowRight}>{right}</View>}
      {onPress && !right && (
        <Ionicons name="chevron-forward" size={16} color={Colors.text.muted} />
      )}
    </View>
  );

  if (onPress) {
    return (
      <TouchableOpacity activeOpacity={0.7} onPress={onPress}>
        {content}
      </TouchableOpacity>
    );
  }
  return content;
}

function Toggle({
  label,
  sublabel,
  value,
  onValueChange,
  disabled,
  last,
}: {
  label: string;
  sublabel?: string;
  value: boolean;
  onValueChange: (v: boolean) => void;
  disabled?: boolean;
  last?: boolean;
}) {
  return (
    <Row
      label={label}
      sublabel={sublabel}
      last={last}
      right={
        <Switch
          value={value}
          onValueChange={onValueChange}
          disabled={disabled}
          trackColor={{ false: Colors.border.default, true: withAlpha13(Colors.brand.accent) + 'ff' }}
          thumbColor={value ? Colors.brand.accent : Colors.text.muted}
          ios_backgroundColor={Colors.border.default}
        />
      }
    />
  );
}

// ── Hour picker modal ────────────────────────────────────────────────────────

const HOURS = Array.from({ length: 24 }, (_, i) => i);

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

function HourPickerModal({
  visible,
  title,
  value,
  onSelect,
  onClose,
}: {
  visible: boolean;
  title: string;
  value: number;
  onSelect: (h: number) => void;
  onClose: () => void;
}) {
  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <SafeAreaView style={styles.pickerScreen} edges={['top', 'bottom']}>
        <View style={styles.pickerHeader}>
          <Text style={styles.pickerTitle}>{title}</Text>
          <TouchableOpacity onPress={onClose} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
            <Ionicons name="close" size={IconSize.md} color={Colors.text.primary} />
          </TouchableOpacity>
        </View>
        <FlatList
          data={HOURS}
          keyExtractor={(h) => String(h)}
          renderItem={({ item: h }) => (
            <TouchableOpacity
              style={[styles.hourRow, h === value && styles.hourRowSelected]}
              onPress={() => { onSelect(h); onClose(); }}
              activeOpacity={0.7}
            >
              <Text style={[styles.hourText, h === value && styles.hourTextSelected]}>
                {pad(h)}:00
              </Text>
              {h === value && (
                <Ionicons name="checkmark" size={IconSize.sm} color={Colors.brand.accent} />
              )}
            </TouchableOpacity>
          )}
          showsVerticalScrollIndicator={false}
          contentContainerStyle={styles.pickerList}
        />
      </SafeAreaView>
    </Modal>
  );
}

// ── Category label map ───────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<NewsCategory, string> = {
  corporate_action: 'Aksi Korporasi',
  earnings:         'Kinerja Keuangan',
  market_news:      'Pasar Saham',
  regulatory:       'Regulasi',
  macro:            'Makroekonomi',
};

const CATEGORIES = Object.keys(CATEGORY_LABELS) as NewsCategory[];

// ── Telegram link section ────────────────────────────────────────────────────

function TelegramSection() {
  const { isLinked, linking, error, link, unlink } = useTelegramLink();
  const [modal, setModal] = useState(false);
  const [code, setCode] = useState('');

  const handleLink = async () => {
    const ok = await link(code);
    if (ok) {
      setModal(false);
      setCode('');
      Alert.alert(
        'Telegram tersambung',
        'Watchlist kamu akan otomatis tersinkron. Kamu akan menerima notifikasi berita di Telegram.'
      );
    }
  };

  const confirmUnlink = () =>
    Alert.alert('Putuskan Telegram', 'Berhenti sinkron watchlist ke Telegram?', [
      { text: 'Batal', style: 'cancel' },
      { text: 'Putuskan', style: 'destructive', onPress: unlink },
    ]);

  return (
    <Section title="Telegram">
      {isLinked ? (
        <>
          <Row
            label="Telegram tersambung"
            sublabel="Watchlist tersinkron otomatis"
            left={
              <Ionicons name="checkmark-circle" size={IconSize.sm} color={Colors.brand.accent} />
            }
          />
          <Row label="Putuskan Telegram" danger last onPress={confirmUnlink} />
        </>
      ) : (
        <Row
          label="Hubungkan Telegram"
          sublabel="Terima notifikasi berita watchlist di Telegram (gratis)"
          left={
            <Ionicons name="paper-plane-outline" size={IconSize.sm} color={Colors.brand.accent} />
          }
          onPress={() => setModal(true)}
          last
        />
      )}

      <Modal
        visible={modal}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setModal(false)}
      >
        <SafeAreaView style={styles.pickerScreen} edges={['top', 'bottom']}>
          <View style={styles.pickerHeader}>
            <Text style={styles.pickerTitle}>Hubungkan Telegram</Text>
            <TouchableOpacity
              onPress={() => setModal(false)}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            >
              <Ionicons name="close" size={IconSize.md} color={Colors.text.primary} />
            </TouchableOpacity>
          </View>
          <View style={styles.tgBody}>
            <Text style={styles.tgHelp}>
              1. Buka bot Kabar Pasar di Telegram, kirim{'  '}
              <Text style={styles.tgMono}>/link</Text>
              {'\n'}2. Masukkan kode 6 digit yang dikirim bot di bawah ini.
            </Text>
            <TextInput
              style={styles.tgInput}
              value={code}
              onChangeText={(t) => setCode(t.replace(/\D/g, '').slice(0, 6))}
              placeholder="123456"
              placeholderTextColor={Colors.text.muted}
              keyboardType="number-pad"
              maxLength={6}
            />
            {error && <Text style={styles.tgError}>{error}</Text>}
            <TouchableOpacity
              style={[styles.tgBtn, (linking || code.length < 6) && styles.tgBtnDisabled]}
              disabled={linking || code.length < 6}
              onPress={handleLink}
              activeOpacity={0.8}
            >
              <Text style={styles.tgBtnText}>
                {linking ? 'Menghubungkan…' : 'Hubungkan'}
              </Text>
            </TouchableOpacity>
          </View>
        </SafeAreaView>
      </Modal>
    </Section>
  );
}

// ── Profile screen ───────────────────────────────────────────────────────────

export default function ProfileScreen() {
  const {
    notifications,
    theme,
    language,
    setPushEnabled,
    setImportanceFilter,
    toggleCategory,
    setQuietHours,
    setTheme,
    setLanguage,
  } = useSettings();

  const [picker, setPicker] = useState<'from' | 'to' | null>(null);

  const { pushEnabled, importanceFilter, categories, quietHours } = notifications;
  const notifDisabled = !pushEnabled;

  const handleThemeCycle = () => {
    const order: ThemePreference[] = ['dark', 'light', 'system'];
    const next = order[(order.indexOf(theme) + 1) % order.length];
    setTheme(next);
  };

  const handleLanguageCycle = () => {
    setLanguage(language === 'id' ? 'en' : 'id');
  };

  const handleLogout = () => {
    Alert.alert('Logout', 'Kamu akan keluar dari akun ini.', [
      { text: 'Batal', style: 'cancel' },
      { text: 'Logout', style: 'destructive', onPress: () => {} },
    ]);
  };

  const themeLabel: Record<ThemePreference, string> = {
    dark:   'Gelap',
    light:  'Terang',
    system: 'Ikuti Sistem',
  };

  const langLabel: Record<string, string> = {
    id: 'Bahasa Indonesia',
    en: 'English',
  };

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        {/* ── Screen title ─────────────────────────────────────────────── */}
        <Text style={styles.screenTitle}>Profil & Pengaturan</Text>

        {/* ── Profile card ─────────────────────────────────────────────── */}
        <View style={styles.profileCard}>
          <View style={styles.avatar}>
            <Text style={styles.avatarInitials}>{MOCK_USER.initials}</Text>
          </View>
          <View style={styles.profileInfo}>
            <Text style={styles.profileName}>{MOCK_USER.name}</Text>
            <Text style={styles.profileEmail}>{MOCK_USER.email}</Text>
          </View>
          <TouchableOpacity
            style={styles.editBtn}
            activeOpacity={0.7}
            onPress={() => Alert.alert('Edit Profil', 'Fitur ini segera hadir.')}
          >
            <Ionicons name="pencil-outline" size={16} color={Colors.brand.accent} />
          </TouchableOpacity>
        </View>

        {/* ── Notifikasi ───────────────────────────────────────────────── */}
        <Section title="Notifikasi">
          <Toggle
            label="Push Notification"
            sublabel="Terima berita penting di background"
            value={pushEnabled}
            onValueChange={setPushEnabled}
          />
          <Toggle
            label="Hanya Berita Penting"
            sublabel="Filter notif: high importance saja"
            value={importanceFilter === 'high_only'}
            onValueChange={(v) => setImportanceFilter(v ? 'high_only' : 'all')}
            disabled={notifDisabled}
          />

          {/* Category toggles */}
          {CATEGORIES.map((cat, i) => (
            <Toggle
              key={cat}
              label={CATEGORY_LABELS[cat]}
              value={categories[cat]}
              onValueChange={() => toggleCategory(cat)}
              disabled={notifDisabled || importanceFilter === 'high_only'}
              last={i === CATEGORIES.length - 1}
            />
          ))}
        </Section>

        {/* ── Telegram ─────────────────────────────────────────────────── */}
        <TelegramSection />

        {/* ── Quiet hours ──────────────────────────────────────────────── */}
        <Section title="Jam Tenang">
          <Toggle
            label="Aktifkan Jam Tenang"
            sublabel="Tidak ada notif selama jam yang dipilih"
            value={quietHours.enabled}
            onValueChange={(v) =>
              setQuietHours({ ...quietHours, enabled: v })
            }
            disabled={notifDisabled}
          />
          <Row
            label="Mulai"
            sublabel="Notif mulai dibisukan"
            right={
              <Text style={[styles.timeValue, (!quietHours.enabled || notifDisabled) && styles.dimmed]}>
                {pad(quietHours.from)}:00
              </Text>
            }
            onPress={
              quietHours.enabled && !notifDisabled
                ? () => setPicker('from')
                : undefined
            }
          />
          <Row
            label="Selesai"
            sublabel="Notif aktif kembali"
            last
            right={
              <Text style={[styles.timeValue, (!quietHours.enabled || notifDisabled) && styles.dimmed]}>
                {pad(quietHours.to)}:00
              </Text>
            }
            onPress={
              quietHours.enabled && !notifDisabled
                ? () => setPicker('to')
                : undefined
            }
          />
        </Section>

        {/* ── Tampilan ─────────────────────────────────────────────────── */}
        <Section title="Tampilan">
          <Row
            label="Tema"
            right={<Text style={styles.valueText}>{themeLabel[theme]}</Text>}
            onPress={handleThemeCycle}
          />
          <Row
            label="Bahasa"
            right={<Text style={styles.valueText}>{langLabel[language]}</Text>}
            onPress={handleLanguageCycle}
            last
          />
        </Section>

        {/* ── Watchlist ─────────────────────────────────────────────────── */}
        <Section title="Watchlist">
          <Row
            label="Kelola Watchlist"
            sublabel="Tambah atau hapus saham yang dipantau"
            left={
              <Ionicons name="star-outline" size={IconSize.sm} color={Colors.brand.accent} />
            }
            onPress={() => router.navigate('/(tabs)/watchlist' as never)}
            last
          />
        </Section>

        {/* ── Tentang ──────────────────────────────────────────────────── */}
        <Section title="Tentang">
          <Row
            label="Versi Aplikasi"
            right={<Text style={styles.valueText}>{APP_VERSION}</Text>}
          />
          <Row
            label="Kebijakan Privasi"
            onPress={() => Alert.alert('Kebijakan Privasi', 'Segera tersedia.')}
          />
          <Row
            label="Syarat & Ketentuan"
            onPress={() => Alert.alert('Syarat & Ketentuan', 'Segera tersedia.')}
            last
          />
        </Section>

        {/* ── Logout ───────────────────────────────────────────────────── */}
        <View style={[styles.section, { marginTop: 4 }]}>
          <View style={styles.sectionCard}>
            <Row label="Logout" danger last onPress={handleLogout} />
          </View>
        </View>

        <Text style={styles.footer}>
          Kabar Pasar · Dibuat dengan ❤ untuk investor Indonesia
        </Text>
      </ScrollView>

      {/* ── Hour picker modals ───────────────────────────────────────── */}
      <HourPickerModal
        visible={picker === 'from'}
        title="Jam Mulai Tenang"
        value={quietHours.from}
        onSelect={(h) => setQuietHours({ ...quietHours, from: h })}
        onClose={() => setPicker(null)}
      />
      <HourPickerModal
        visible={picker === 'to'}
        title="Jam Selesai Tenang"
        value={quietHours.to}
        onSelect={(h) => setQuietHours({ ...quietHours, to: h })}
        onClose={() => setPicker(null)}
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
  scroll: {
    paddingBottom: 48,
  },
  screenTitle: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    letterSpacing: -0.3,
    paddingHorizontal: Layout.screenPaddingX,
    paddingTop: 20,
    paddingBottom: 16,
  },

  // Profile card
  profileCard: {
    flexDirection: 'row',
    alignItems: 'center',
    marginHorizontal: Layout.screenPaddingX,
    marginBottom: 24,
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.card,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    padding: 14,
    gap: 12,
  },
  avatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: withAlpha13(Colors.brand.accent),
    borderWidth: Border.width,
    borderColor: Colors.brand.accent,
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  avatarInitials: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.bold,
    color: Colors.brand.accent,
    letterSpacing: LetterSpacing.wide,
  },
  profileInfo: {
    flex: 1,
    minWidth: 0,
    gap: 2,
  },
  profileName: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.semibold,
    color: Colors.text.primary,
  },
  profileEmail: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
  },
  editBtn: {
    padding: 6,
    flexShrink: 0,
  },

  // Section
  section: {
    marginHorizontal: Layout.screenPaddingX,
    marginBottom: 20,
    gap: 8,
  },
  sectionTitle: {
    fontSize: FontSize.caption,
    fontWeight: FontWeight.bold,
    color: Colors.text.muted,
    letterSpacing: LetterSpacing.wider,
    textTransform: 'uppercase',
    paddingHorizontal: 4,
  },
  sectionCard: {
    backgroundColor: Colors.background.surface,
    borderRadius: Radius.card,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    overflow: 'hidden',
  },

  // Row
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 13,
    gap: 10,
    minHeight: 52,
  },
  rowBorder: {
    borderBottomWidth: Border.width,
    borderBottomColor: Colors.border.default,
  },
  rowLeft: {
    flexShrink: 0,
    width: 20,
    alignItems: 'center',
  },
  rowMiddle: {
    flex: 1,
    minWidth: 0,
    gap: 2,
  },
  rowLabel: {
    fontSize: FontSize.base,
    color: Colors.text.primary,
    fontWeight: FontWeight.medium,
  },
  rowLabelDanger: {
    color: Colors.sentiment.negative,
    fontWeight: FontWeight.semibold,
  },
  rowSublabel: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
    lineHeight: 16,
  },
  rowRight: {
    flexShrink: 0,
  },

  // Value chips
  valueText: {
    fontSize: FontSize.body,
    color: Colors.text.muted,
    fontWeight: FontWeight.medium,
  },
  timeValue: {
    fontSize: FontSize.body,
    color: Colors.brand.accent,
    fontWeight: FontWeight.bold,
  },
  dimmed: {
    opacity: 0.4,
  },

  // Hour picker
  pickerScreen: {
    flex: 1,
    backgroundColor: Colors.background.screen,
  },
  pickerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: Layout.screenPaddingX,
    paddingVertical: 14,
    borderBottomWidth: Border.width,
    borderBottomColor: Colors.border.default,
  },
  pickerTitle: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
  },
  pickerList: {
    paddingVertical: 8,
  },
  hourRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: Layout.screenPaddingX,
    paddingVertical: 14,
  },
  hourRowSelected: {
    backgroundColor: withAlpha13(Colors.brand.accent),
  },
  hourText: {
    fontSize: FontSize.subhead,
    fontWeight: FontWeight.medium,
    color: Colors.text.secondary,
  },
  hourTextSelected: {
    color: Colors.brand.accent,
    fontWeight: FontWeight.bold,
  },

  // Telegram link modal
  tgBody: {
    padding: Layout.screenPaddingX,
    gap: 16,
  },
  tgHelp: {
    fontSize: FontSize.body,
    color: Colors.text.secondary,
    lineHeight: 22,
  },
  tgMono: {
    color: Colors.brand.accent,
    fontWeight: FontWeight.bold,
  },
  tgInput: {
    backgroundColor: Colors.background.surface,
    borderWidth: Border.width,
    borderColor: Colors.border.default,
    borderRadius: Radius.component,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: FontSize.title,
    fontWeight: FontWeight.bold,
    color: Colors.text.primary,
    letterSpacing: 8,
    textAlign: 'center',
  },
  tgError: {
    fontSize: FontSize.caption,
    color: Colors.sentiment.negative,
  },
  tgBtn: {
    backgroundColor: Colors.brand.accent,
    borderRadius: Radius.component,
    paddingVertical: 14,
    alignItems: 'center',
  },
  tgBtnDisabled: {
    opacity: 0.5,
  },
  tgBtnText: {
    fontSize: FontSize.base,
    fontWeight: FontWeight.bold,
    color: Colors.background.screen,
  },

  // Footer
  footer: {
    fontSize: FontSize.caption,
    color: Colors.text.muted,
    textAlign: 'center',
    paddingHorizontal: Layout.screenPaddingX,
    marginTop: 8,
    lineHeight: 18,
  },
});
