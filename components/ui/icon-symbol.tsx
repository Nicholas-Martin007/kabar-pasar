// Fallback for using Ionicons on Android and web.
// iOS uses native SF Symbols via icon-symbol.ios.tsx.

import Ionicons from '@expo/vector-icons/Ionicons';
import { SymbolViewProps, SymbolWeight } from 'expo-symbols';
import { ComponentProps } from 'react';
import { OpaqueColorValue, type StyleProp, type TextStyle } from 'react-native';

type IconMapping = Record<SymbolViewProps['name'], ComponentProps<typeof Ionicons>['name']>;
type IconSymbolName = keyof typeof MAPPING;

// SF Symbol name → Ionicons name. Outline SF names map to -outline Ionicons.
const MAPPING = {
  // Tab icons — outline (inactive) and filled (active)
  'house':           'home-outline',
  'house.fill':      'home',
  'newspaper':       'newspaper-outline',
  'newspaper.fill':  'newspaper',
  'star':            'star-outline',
  'star.fill':       'star',
  'person':          'person-outline',
  'person.fill':     'person',
  // UI icons
  'magnifyingglass': 'search-outline',
  'bell':            'notifications-outline',
  'bell.fill':       'notifications',
  'paperplane':      'paper-plane-outline',
  'paperplane.fill': 'paper-plane',
  // Navigation
  'chevron.right':                           'chevron-forward',
  'chevron.left.forwardslash.chevron.right': 'code-slash',
} as IconMapping;

export function IconSymbol({
  name,
  size = 24,
  color,
  style,
}: {
  name: IconSymbolName;
  size?: number;
  color: string | OpaqueColorValue;
  style?: StyleProp<TextStyle>;
  weight?: SymbolWeight;
}) {
  return <Ionicons color={color} size={size} name={MAPPING[name]} style={style} />;
}
