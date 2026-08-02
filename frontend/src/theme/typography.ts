import { Platform } from 'react-native';

export const FontFamily = {
  sans: Platform.select({
    ios:     'system-ui',
    android: 'normal',
    web:     "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    default: 'normal',
  }),
  mono: Platform.select({
    ios:     'ui-monospace',
    android: 'monospace',
    web:     "SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace",
    default: 'monospace',
  }),
} as const;

// Named scale — based on system type ramp
export const FontSize = {
  badge:   9,  // importance/AI label badge
  caption: 10, // source chip, status text
  small:   11, // timestamp, ticker
  body:    12, // summary, date label
  filter:  13, // filter chip label
  base:    14, // card title, market change, empty state
  subhead: 16, // market index value
  title:   22, // app name
} as const;

export const FontWeight = {
  regular:   '400' as const,
  medium:    '500' as const,
  semibold:  '600' as const,
  bold:      '700' as const,
  extrabold: '800' as const,
} as const;

export const LineHeight = {
  tight:  17, // body/summary text
  normal: 20, // card title
} as const;

export const LetterSpacing = {
  tight:  -0.3, // large numerics (app name, market value)
  normal:  0,
  wide:    0.3, // source chips
  wider:   0.5, // badge labels, status text
} as const;
