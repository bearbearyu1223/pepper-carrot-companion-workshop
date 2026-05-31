// Shared kind→color mapping used across the graph node, the info card,
// the kind filter bar, and the fallback icons. The CSS vars resolve at
// render time, so swapping a hex value in global.css ripples through
// consistently.

import type { WorldKind } from '../../api/types';

export const KIND_COLOR_VAR: Record<WorldKind, string> = {
  character: 'var(--accent)',
  coven: 'var(--wiki)',
  creature: 'var(--accent-dim, #b8704d)',
  place: 'var(--parchment-edge)',
  object: 'var(--wiki)',
};

// Friendly label shown on the info card kind badge + the filter chips.
export const KIND_LABEL: Record<WorldKind, string> = {
  character: 'Character',
  coven: 'Coven',
  creature: 'Creature',
  place: 'Place',
  object: 'Object',
};

// The frontend fetches the larger 320px display variant by swapping the
// "-thumb" suffix for "-display" in the URL. The graph node uses the 96px
// thumb; the info card uses the display variant. The scraper guarantees
// both filenames share a slug stem, so this string swap is safe.
export function displayUrlFor(thumbUrl: string): string {
  return thumbUrl.replace(/-thumb\.webp(\?|$)/, '-display.webp$1');
}

// Edge-kind → color. Grouped by semantic family rather than per-kind so
// the graph reads as four-or-five visual categories instead of nine
// distinct colors. Edges are dimmed by default and only colorized when
// the reader selects an incident node, so this palette only renders on
// focus.
export const EDGE_KIND_COLOR: Record<string, string> = {
  // structural — coven & institution membership
  member_of: 'var(--accent)',
  located_in: 'var(--accent)',
  // geography — physical location
  lives_in: 'var(--parchment-edge)',
  // kinship & learning — plum, the "lore" tone
  godmother_of: 'var(--wiki)',
  family_of: 'var(--wiki)',
  apprentice_of: 'var(--wiki)',
  // companions & alliances — the dimmer accent
  familiar_of: 'var(--accent-dim, #b8704d)',
  friend_of: 'var(--accent-dim, #b8704d)',
  // opposition — distinct red so rivals pop out of the field
  rival_of: '#a8362a',
};

const DEFAULT_EDGE_COLOR = 'var(--accent)';

export function edgeColorFor(kind: string): string {
  return EDGE_KIND_COLOR[kind] ?? DEFAULT_EDGE_COLOR;
}
