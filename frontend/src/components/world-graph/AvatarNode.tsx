// Custom react-flow node: a 72px circular avatar with the entity name
// underneath. The image gets a kind-colored border; if no image, the
// kind-based SVG fallback is rendered on the same circle.

import { useState } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { WorldNode as WorldNodeData } from '../../api/types';
import { KIND_COLOR_VAR } from './constants';
import { KindFallbackIcon } from './fallback-icons';

const AVATAR_SIZE = 72;
const ICON_INSET = 12;

// react-flow's Node generic requires `data` to extend Record<string, unknown>.
// The only key we actually read is `entity`, but keeping the index signature
// makes this type assignable to react-flow's internal Node<TData> shape
// without a cast.
export type AvatarNodeData = {
  entity: WorldNodeData;
} & Record<string, unknown>;

export function AvatarNode({ data, selected }: NodeProps) {
  const { entity } = data as unknown as AvatarNodeData;
  const [imgError, setImgError] = useState(false);
  const showImage = !!entity.image_url && !imgError;
  const borderColor = KIND_COLOR_VAR[entity.kind];

  return (
    <div
      className={`world-node ${selected ? 'world-node--selected' : ''}`}
      aria-label={`${entity.name}, ${entity.kind}`}
    >
      {/* Invisible connection handles on all four sides so react-flow can
          route edges through whichever side reads most naturally for the
          source/target geometry. We never expose draggable connections. */}
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />

      <div
        className="world-node__avatar"
        style={{
          width: AVATAR_SIZE,
          height: AVATAR_SIZE,
          borderColor,
          background: showImage ? 'var(--parchment)' : borderColor,
        }}
      >
        {showImage ? (
          <img
            src={entity.image_url ?? ''}
            alt=""
            onError={() => setImgError(true)}
            draggable={false}
          />
        ) : (
          <KindFallbackIcon
            kind={entity.kind}
            name={entity.name}
            size={AVATAR_SIZE - ICON_INSET * 2}
            color="var(--parchment)"
          />
        )}
      </div>
      <div className="world-node__label">{entity.name}</div>
    </div>
  );
}
