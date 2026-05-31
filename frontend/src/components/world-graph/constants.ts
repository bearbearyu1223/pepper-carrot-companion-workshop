// Shared kind→color mapping used across the graph node, the info card,
// and the fallback icons. The CSS vars resolve at render time, so swapping
// a hex value in global.css ripples through consistently.

import type { WorldKind } from '../../api/types';

export const KIND_COLOR_VAR: Record<WorldKind, string> = {
  character: 'var(--accent)',
  coven: 'var(--wiki)',
  creature: 'var(--accent-dim)',
  place: 'var(--parchment-edge)',
  object: 'var(--wiki)',
};

// Friendly label shown on the info card kind badge.
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
