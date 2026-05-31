// Custom react-flow node: a 72px circular avatar with the entity name
// underneath. The image gets a kind-colored border; if no image, the
// kind-based SVG fallback is rendered on the same circle. Hover/selected
// scales subtly (1.08x) and brightens the border.
//
// Eight invisible handles (one source + one target on each of the four
// sides) let WorldGraph pick the side that makes the bezier read most
// naturally for the source/target geometry. Each handle has a unique id
// so edges can address them via sourceHandle / targetHandle.

import { useState } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { WorldNode as WorldNodeData } from '../../api/types';
import { KIND_COLOR_VAR } from './constants';
import { KindFallbackIcon } from './fallback-icons';

const AVATAR_SIZE = 72;
const ICON_INSET = 12;

// react-flow's Node generic requires `data` to extend Record<string, unknown>.
// The only key we actually read is `entity`, but the index signature keeps
// this type assignable to react-flow's internal Node<TData> shape.
export type AvatarNodeData = {
  entity: WorldNodeData;
} & Record<string, unknown>;

const SIDES = ['top', 'right', 'bottom', 'left'] as const;
const SIDE_TO_POSITION: Record<(typeof SIDES)[number], Position> = {
  top: Position.Top,
  right: Position.Right,
  bottom: Position.Bottom,
  left: Position.Left,
};

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
      {/* 4 target + 4 source handles, all invisible. WorldGraph picks the
          side per-edge based on the source/target geometry so the bezier
          curves stay clean. */}
      {SIDES.map((side) => (
        <Handle
          key={`t-${side}`}
          type="target"
          id={`t-${side}`}
          position={SIDE_TO_POSITION[side]}
          style={{ opacity: 0, pointerEvents: 'none' }}
        />
      ))}
      {SIDES.map((side) => (
        <Handle
          key={`s-${side}`}
          type="source"
          id={`s-${side}`}
          position={SIDE_TO_POSITION[side]}
          style={{ opacity: 0, pointerEvents: 'none' }}
        />
      ))}

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
