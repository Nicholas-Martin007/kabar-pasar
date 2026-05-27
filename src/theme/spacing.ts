// Semantic layout tokens — prefer these over raw numbers in StyleSheet
export const Layout = {
  // Screen / list
  screenPaddingX:    16, // horizontal margin for full-width elements
  listPaddingBottom: 32, // FlatList bottom breathing room
  emptyPaddingTop:   60, // empty state vertical offset

  // Cards
  cardPadding:  14, // inner padding of a news card
  cardMarginV:   5, // vertical spacing between cards in the list

  // Component (market bar, etc.)
  componentPaddingX: 14,
  componentPaddingY: 10,

  // Chips (source / importance)
  chipPaddingX: 7,
  chipPaddingY: 2,

  // Filter chips (larger, pill-shaped)
  filterChipPaddingX: 14,
  filterChipPaddingY:  7,

  // Tiny badges (AI label)
  badgePaddingX: 5,
  badgePaddingY: 2,

  // Gaps
  rowGap:     6,  // between items within a row
  contentGap: 8,  // between elements within a card
  sectionGap: 14, // between sections in the header
} as const;

// Border radius scale — use semantic name, not raw number
export const Radius = {
  badge:     3,  // AI label
  chip:      4,  // source / importance pill
  component: 10, // market bar, inputs
  card:      12, // news card
  pill:      20, // filter chips
} as const;

// Border width tokens
export const Border = {
  width:       1, // default card / component border
  stripeWidth: 3, // importance stripe on news card
} as const;

// Icon sizes
export const IconSize = {
  sm: 18, // bookmark icon
  md: 22, // notification bell
  lg: 26, // tab bar icons
  xl: 28, // tab bar icons (large)
} as const;
