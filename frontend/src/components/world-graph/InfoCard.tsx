// Popover anchored over the canvas when a node is clicked. Shows the
// larger 320px display variant of the avatar (or the kind-based fallback),
// the name + kind badge, the summary, and an "Ask in wiki mode" button.
//
// Esc closes; outside-click closes. The keydown listener uses capture +
// stopPropagation so a node-card open doesn't leak the keypress up to
// the overlay and dismiss the whole panel.

import { useEffect, useRef, useState } from 'react';
import type { WorldNode } from '../../api/types';
import { KIND_COLOR_VAR, KIND_LABEL, displayUrlFor } from './constants';
import { KindFallbackIcon } from './fallback-icons';

interface InfoCardProps {
  entity: WorldNode;
  onClose: () => void;
  onAskInWiki: (entityName: string) => void;
}

const DISPLAY_SIZE = 200;
const ICON_INSET = 32;

export function InfoCard({ entity, onClose, onAskInWiki }: InfoCardProps) {
  const cardRef = useRef<HTMLDivElement | null>(null);
  const [imgError, setImgError] = useState(false);
  const showImage = !!entity.image_url && !imgError;
  const borderColor = KIND_COLOR_VAR[entity.kind];
  const displayUrl = entity.image_url ? displayUrlFor(entity.image_url) : null;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    }
    function onClick(e: MouseEvent) {
      if (cardRef.current && !cardRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    window.addEventListener('keydown', onKey, true);
    // mousedown so we beat the node-click handler in the same tick.
    window.addEventListener('mousedown', onClick);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('mousedown', onClick);
    };
  }, [onClose]);

  return (
    <div
      ref={cardRef}
      className="world-info-card"
      role="dialog"
      aria-label={`${entity.name} details`}
    >
      <button
        type="button"
        className="world-info-card__close"
        onClick={onClose}
        aria-label="Close"
      >
        ×
      </button>

      <div
        className="world-info-card__portrait"
        style={{
          width: DISPLAY_SIZE,
          height: DISPLAY_SIZE,
          borderColor,
          background: showImage ? 'var(--parchment)' : borderColor,
        }}
      >
        {showImage ? (
          <img
            src={displayUrl ?? ''}
            alt={entity.name}
            onError={() => setImgError(true)}
            draggable={false}
          />
        ) : (
          <KindFallbackIcon
            kind={entity.kind}
            name={entity.name}
            size={DISPLAY_SIZE - ICON_INSET * 2}
            color="var(--parchment)"
          />
        )}
      </div>

      <div className="world-info-card__heading">
        <h3>{entity.name}</h3>
        <span
          className="world-info-card__kind-badge"
          style={{ background: borderColor }}
        >
          {KIND_LABEL[entity.kind]}
        </span>
      </div>

      {entity.summary && (
        <p className="world-info-card__summary">{entity.summary}</p>
      )}

      <button
        type="button"
        className="world-info-card__ask"
        onClick={() => onAskInWiki(entity.name)}
      >
        Ask in wiki mode
      </button>
    </div>
  );
}
