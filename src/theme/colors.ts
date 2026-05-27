// Contrast ratios verified against WCAG AA (≥ 4.5:1 for normal text, ≥ 3:1 for large/UI)
// Test background: surface #0F1521 (cards), screen #080C14 (page bg)

// Internal palette — import Colors below, not these
const P = {
  // Backgrounds (dark navy)
  navy950: '#080C14', // page bg
  navy900: '#0F1521', // card surface
  navy800: '#1A2234', // unread card / elevated surface
  navy700: '#1E2D40', // border

  // Text
  slate50:  '#E8EEF4', // 15.6:1 on navy900 ✓
  slate300: '#8A99B0', //  6.3:1 on navy900 ✓
  // Fixed from #4A5B73 (was 2.6:1) → 4.6:1 on navy900, 4.9:1 on navy950
  slate400: '#6F80A2',

  // Brand / accent
  teal400:   '#00C8A0', // 8.5:1 on navy900 ✓

  // Sentiment
  green500:  '#22C55E', // 8.0:1 on navy900 ✓
  rose500:   '#F43F5E', // 5.0:1 on navy900 ✓

  // Importance
  orange500: '#F97316', // 6.5:1 on navy900 ✓
  blue400:   '#3B82F6', // 5.0:1 on navy900 ✓

  // Source brand tags — all corrected to ≥ 4.5:1 on navy900
  red400:    '#FF5252', // 5.7:1 — was #E02020 (3.8:1) — CNBC ID, Detik Finance
  sky400:    '#3B9ED6', // 6.1:1 — was #1D6FA5 (3.4:1) — Kontan
  indigo400: '#5B8EF5', // 5.8:1 — was #2563EB (3.5:1) — Bisnis Indonesia
  orange400: '#FF6C2F', // 6.5:1 — unchanged ✓ — Reuters
  blue300:   '#4D94FF', // 6.1:1 — was #0070F3 (4.0:1) — CNBC Global
} as const;

export const Colors = {
  background: {
    screen:          P.navy950,
    surface:         P.navy900,
    surfaceElevated: P.navy800,
  },
  border: {
    default: P.navy700,
  },
  text: {
    primary:   P.slate50,
    secondary: P.slate300,
    muted:     P.slate400,
  },
  brand: {
    accent: P.teal400,
  },
  sentiment: {
    positive: P.green500,
    negative: P.rose500,
  },
  importance: {
    critical: P.rose500,
    high:     P.orange500,
    medium:   P.blue400,
    low:      P.slate400,
  },
  source: {
    IDX:                P.teal400,
    'CNBC Indonesia':   P.red400,
    Kontan:             P.sky400,
    'Bisnis Indonesia': P.indigo400,
    'Detik Finance':    P.red400,
    Reuters:            P.orange400,
    'CNBC Global':      P.blue300,
  },
  tabBar: {
    background: P.navy950,
    border:     P.navy700,
  },
} as const;

// Returns a hex color with 13% opacity suffix — use for chip/badge backgrounds
export function withAlpha13(color: string): string {
  return color + '22';
}
