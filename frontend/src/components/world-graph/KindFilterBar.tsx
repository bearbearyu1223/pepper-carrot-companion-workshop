// Kind-filter chips above the graph canvas. Toggling a chip filters
// nodes of that kind; edges with a hidden endpoint are dropped
// automatically in WorldGraph. Default state is "all on" — the filter
// is for cutting the graph down when it's too busy, not a wall the
// reader has to climb before seeing anything.

import type { CSSProperties } from 'react';
import type { WorldKind } from '../../api/types';
import { KIND_COLOR_VAR, KIND_LABEL } from './constants';

interface KindFilterBarProps {
  active: Set<WorldKind>;
  counts: Record<WorldKind, number>;
  onToggle: (kind: WorldKind) => void;
}

// Order kinds so the most plot-relevant ones (characters, covens) sit first.
const ORDERED_KINDS: WorldKind[] = [
  'character',
  'coven',
  'place',
  'creature',
  'object',
];

export function KindFilterBar({ active, counts, onToggle }: KindFilterBarProps) {
  return (
    <div className="world-filter-bar" role="group" aria-label="Filter by kind">
      {ORDERED_KINDS.map((kind) => {
        const count = counts[kind] ?? 0;
        if (count === 0) return null;
        const isActive = active.has(kind);
        return (
          <button
            key={kind}
            type="button"
            className={`world-filter-chip ${
              isActive ? 'world-filter-chip--active' : 'world-filter-chip--off'
            }`}
            style={{ '--chip-color': KIND_COLOR_VAR[kind] } as CSSProperties}
            onClick={() => onToggle(kind)}
            aria-pressed={isActive}
          >
            <span className="world-filter-chip__dot" aria-hidden="true" />
            <span>{KIND_LABEL[kind]}</span>
            <span className="world-filter-chip__count">{count}</span>
          </button>
        );
      })}
    </div>
  );
}
