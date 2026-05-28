import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react';

import { NewsCategory } from '@/src/types/news';

export type ImportanceFilter = 'all' | 'high_only';
export type ThemePreference   = 'dark' | 'light' | 'system';
export type Language           = 'id' | 'en';

export interface QuietHours {
  enabled: boolean;
  from: number; // 0–23
  to: number;   // 0–23
}

export interface NotificationSettings {
  pushEnabled:      boolean;
  importanceFilter: ImportanceFilter;
  categories:       Record<NewsCategory, boolean>;
  quietHours:       QuietHours;
}

export interface SettingsContextValue {
  notifications: NotificationSettings;
  theme:         ThemePreference;
  language:      Language;
  setPushEnabled:      (v: boolean) => void;
  setImportanceFilter: (v: ImportanceFilter) => void;
  toggleCategory:      (cat: NewsCategory) => void;
  setQuietHours:       (v: QuietHours) => void;
  setTheme:            (v: ThemePreference) => void;
  setLanguage:         (v: Language) => void;
}

const DEFAULT_NOTIFICATIONS: NotificationSettings = {
  pushEnabled:      true,
  importanceFilter: 'all',
  categories: {
    corporate_action: true,
    earnings:         true,
    market_news:      true,
    regulatory:       true,
    macro:            false,
  },
  quietHours: {
    enabled: true,
    from:    22,
    to:      7,
  },
};

const SettingsContext = createContext<SettingsContextValue | null>(null);

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] =
    useState<NotificationSettings>(DEFAULT_NOTIFICATIONS);
  const [theme,    setTheme]    = useState<ThemePreference>('dark');
  const [language, setLanguage] = useState<Language>('id');

  const setPushEnabled = useCallback((v: boolean) => {
    setNotifications((prev) => ({ ...prev, pushEnabled: v }));
  }, []);

  const setImportanceFilter = useCallback((v: ImportanceFilter) => {
    setNotifications((prev) => ({ ...prev, importanceFilter: v }));
  }, []);

  const toggleCategory = useCallback((cat: NewsCategory) => {
    setNotifications((prev) => ({
      ...prev,
      categories: { ...prev.categories, [cat]: !prev.categories[cat] },
    }));
  }, []);

  const setQuietHours = useCallback((v: QuietHours) => {
    setNotifications((prev) => ({ ...prev, quietHours: v }));
  }, []);

  const value = useMemo<SettingsContextValue>(
    () => ({
      notifications,
      theme,
      language,
      setPushEnabled,
      setImportanceFilter,
      toggleCategory,
      setQuietHours,
      setTheme,
      setLanguage,
    }),
    [
      notifications,
      theme,
      language,
      setPushEnabled,
      setImportanceFilter,
      toggleCategory,
      setQuietHours,
    ]
  );

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error('useSettings must be used inside SettingsProvider');
  return ctx;
}
