import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import 'react-native-reanimated';

import { useColorScheme } from '@/hooks/use-color-scheme';
import { BookmarksProvider } from '@/src/context/BookmarksContext';
import { ReadProvider } from '@/src/context/ReadContext';
import { SettingsProvider } from '@/src/context/SettingsContext';
import { TelegramLinkProvider } from '@/src/context/TelegramLinkContext';
import { WatchlistProvider } from '@/src/context/WatchlistContext';

export const unstable_settings = {
  anchor: '(tabs)',
};

// Single client for the whole app — created once at module scope.
const queryClient = new QueryClient();

export default function RootLayout() {
  const colorScheme = useColorScheme();

  return (
    <QueryClientProvider client={queryClient}>
    <SettingsProvider>
    <WatchlistProvider>
    <BookmarksProvider>
    <ReadProvider>
    <TelegramLinkProvider>
      <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
        <Stack>
          <Stack.Screen name="(tabs)"        options={{ headerShown: false }} />
          <Stack.Screen name="news/[id]"     options={{ headerShown: false }} />
          <Stack.Screen name="stock/[ticker]" options={{ headerShown: false }} />
          <Stack.Screen name="saved"         options={{ headerShown: false }} />
          <Stack.Screen name="modal"         options={{ presentation: 'modal', title: 'Modal' }} />
        </Stack>
        <StatusBar style="auto" />
      </ThemeProvider>
    </TelegramLinkProvider>
    </ReadProvider>
    </BookmarksProvider>
    </WatchlistProvider>
    </SettingsProvider>
    </QueryClientProvider>
  );
}
