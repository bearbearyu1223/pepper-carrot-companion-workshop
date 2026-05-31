// Inline SVG fallbacks for entities with no scraped artwork. One component
// per kind; the parent passes a `size` so the same icon scales from the
// 72px graph node up to the 200px info-card portrait.
//
// Every component includes a <title> child for screen readers; the parent
// also sets aria-label on the wrapping circle so the kind + name reads
// together (e.g. "Chaosah, coven").

import type { WorldKind } from '../../api/types';

interface FallbackProps {
  size: number;
  color: string;
  title: string;
}

// ── Coven: a witch's pointed hat ──
function CovenIcon({ size, color, title }: FallbackProps) {
  return (
    <svg role="img" aria-hidden="true" width={size} height={size} viewBox="0 0 64 64">
      <title>{title}</title>
      <path d="M32 8 L46 44 L18 44 Z M14 46 H50 L46 52 H18 Z" fill={color} />
      <circle cx="40" cy="22" r="2.5" fill={color} opacity="0.6" />
    </svg>
  );
}

// ── Place: a tower silhouette with a small flag ──
function PlaceIcon({ size, color, title }: FallbackProps) {
  return (
    <svg role="img" aria-hidden="true" width={size} height={size} viewBox="0 0 64 64">
      <title>{title}</title>
      <path d="M22 50 H42 V20 L36 14 H28 L22 20 Z" fill={color} />
      <rect x="29" y="32" width="6" height="10" fill="rgba(0,0,0,0.18)" />
      <path d="M36 14 V8 H44 L41 11 L44 14 Z" fill={color} />
    </svg>
  );
}

// ── Creature: a paw print ──
function CreatureIcon({ size, color, title }: FallbackProps) {
  return (
    <svg role="img" aria-hidden="true" width={size} height={size} viewBox="0 0 64 64">
      <title>{title}</title>
      <ellipse cx="32" cy="40" rx="11" ry="9" fill={color} />
      <ellipse cx="20" cy="26" rx="5" ry="6" fill={color} />
      <ellipse cx="44" cy="26" rx="5" ry="6" fill={color} />
      <ellipse cx="14" cy="38" rx="4" ry="5" fill={color} />
      <ellipse cx="50" cy="38" rx="4" ry="5" fill={color} />
    </svg>
  );
}

// ── Object: a four-point sparkle ──
function ObjectIcon({ size, color, title }: FallbackProps) {
  return (
    <svg role="img" aria-hidden="true" width={size} height={size} viewBox="0 0 64 64">
      <title>{title}</title>
      <path
        d="M32 8 L36 28 L56 32 L36 36 L32 56 L28 36 L8 32 L28 28 Z"
        fill={color}
      />
    </svg>
  );
}

// ── Character without art: first letter of the name ──
function CharacterInitialIcon({
  size,
  color,
  title,
  initial,
}: FallbackProps & { initial: string }) {
  return (
    <svg role="img" aria-hidden="true" width={size} height={size} viewBox="0 0 64 64">
      <title>{title}</title>
      <text
        x="32"
        y="32"
        dominantBaseline="central"
        textAnchor="middle"
        fontFamily="var(--font-prose), Georgia, serif"
        fontSize="36"
        fontWeight="600"
        fill={color}
      >
        {initial}
      </text>
    </svg>
  );
}

interface KindIconProps {
  kind: WorldKind;
  name: string;
  size: number;
  color: string;
}

// Public entry — picks the right icon for the kind. For `character` the
// initial of the name is used so minor characters who never had portrait
// art on the upstream wiki still render distinguishably.
export function KindFallbackIcon({ kind, name, size, color }: KindIconProps) {
  const title = `${name}, ${kind}`;
  if (kind === 'character') {
    const initial = (name.trim().charAt(0) || '?').toUpperCase();
    return (
      <CharacterInitialIcon
        size={size}
        color={color}
        title={title}
        initial={initial}
      />
    );
  }
  if (kind === 'coven') return <CovenIcon size={size} color={color} title={title} />;
  if (kind === 'place') return <PlaceIcon size={size} color={color} title={title} />;
  if (kind === 'creature') {
    return <CreatureIcon size={size} color={color} title={title} />;
  }
  return <ObjectIcon size={size} color={color} title={title} />;
}
