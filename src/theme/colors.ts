// Contrast ratios verified against WCAG AA (≥ 4.5:1 for normal text, ≥ 3:1 for large/UI)
// Test backgrounds: surface #0F1521 (cards), screen #080C14 (page bg)

// Internal palette — components import from Colors below, not from P
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
  teal400: '#00C8A0', // 8.5:1 on navy900 ✓

  // Sentiment
  green500: '#22C55E', // 8.0:1 on navy900 ✓
  rose500:  '#F43F5E', // 5.0:1 on navy900 ✓

  // Importance (3-level)
  // high uses rose — most urgent; critical folded in
  blue400: '#3B82F6', // 5.0:1 on navy900 ✓ — medium importance

  // Source brand tags — all verified ≥ 4.5:1 on navy900
  red400:    '#FF5252', // 5.7:1 — CNBC Indonesia, Detik Finance
  sky400:    '#3B9ED6', // 6.1:1 — Kontan
  indigo400: '#5B8EF5', // 5.8:1 — Bisnis Indonesia
  amber400:  '#F5A623', // ~9.6:1 — Bloomberg Technoz
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
  // 3-level importance: critical folded into high
  importance: {
    high:   P.rose500,  // most urgent — red
    medium: P.blue400,  // noteworthy — blue
    low:    P.slate400, // general — muted
  },
  // Sources matching NewsSource in src/types/news.ts
  source: {
    'CNBC Indonesia':   P.red400,
    'Detik Finance':    P.red400,
    Kontan:             P.sky400,
    'Bisnis Indonesia': P.indigo400,
    'Bloomberg Technoz': P.amber400, // ~9.6:1 ✓
    BEI:                P.teal400,   // 8.5:1 ✓
    'IR Emiten':        P.slate300,  // 6.3:1 ✓ — neutral for corporate IR
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
