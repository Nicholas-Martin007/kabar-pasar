import { Tabs } from 'expo-router';
import React from 'react';

import { HapticTab } from '@/components/haptic-tab';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { Colors, FontSize, FontWeight, IconSize } from '@/src/theme';

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarButton: HapticTab,
        tabBarActiveTintColor:   Colors.brand.accent,
        tabBarInactiveTintColor: Colors.text.muted,
        tabBarStyle: {
          backgroundColor: Colors.tabBar.background,
          borderTopColor:  Colors.tabBar.border,
          borderTopWidth:  1,
        },
        tabBarLabelStyle: {
          fontSize:   FontSize.caption,
          fontWeight: FontWeight.semibold,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Home',
          tabBarIcon: ({ color, focused }) => (
            <IconSymbol
              size={IconSize.lg}
              name={focused ? 'house.fill' : 'house'}
              color={color}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="berita"
        options={{
          title: 'Berita',
          tabBarIcon: ({ color, focused }) => (
            <IconSymbol
              size={IconSize.lg}
              name={focused ? 'newspaper.fill' : 'newspaper'}
              color={color}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="watchlist"
        options={{
          title: 'Watchlist',
          tabBarIcon: ({ color, focused }) => (
            <IconSymbol
              size={IconSize.lg}
              name={focused ? 'star.fill' : 'star'}
              color={color}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: 'Profil',
          tabBarIcon: ({ color, focused }) => (
            <IconSymbol
              size={IconSize.lg}
              name={focused ? 'person.fill' : 'person'}
              color={color}
            />
          ),
        }}
      />
    </Tabs>
  );
}
