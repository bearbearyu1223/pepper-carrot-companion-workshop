// React-flow canvas: curated-layout avatar nodes + low-key bezier edges,
// with a soft fade-in animation when newly-revealed nodes/edges debut on
// the current spread (Post 9 polish — the user's pick).
//
// The fade-in implementation is intentionally CSS-driven rather than a
// state-machine: when a new graph snapshot arrives, we diff its ids
// against the previous snapshot's ids, mark anything new as `new=true`,
// and let CSS `@keyframes` handle the animation. The diff is cheap; the
// animation is GPU-cheap; the parent doesn't have to know.

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Controls,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { api } from '../../api/client';
import type {
  WorldGraph as WorldGraphData,
  WorldNode,
} from '../../api/types';
import { AvatarNode, type AvatarNodeData } from './AvatarNode';
import { InfoCard } from './InfoCard';

interface WorldGraphProps {
  episodeSlug: string;
  page: number;
  onAskInWiki: (entityName: string) => void;
}

const NODE_TYPES = { avatar: AvatarNode };

// Edge styling — bezier curves over right-angles read more like inked
// lines than CAD'd connectors, which fits the comic's aesthetic.
const EDGE_COLOR_DEFAULT = 'rgb(110, 80, 50)';
const EDGE_COLOR_FOCUSED = 'var(--accent)';
const EDGE_OPACITY_DEFAULT = 0.5;
const EDGE_OPACITY_FOCUSED = 0.9;
const EDGE_OPACITY_DIMMED = 0.18;

export function WorldGraph({ episodeSlug, page, onAskInWiki }: WorldGraphProps) {
  const [data, setData] = useState<WorldGraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Track the previous snapshot's ids so we can diff and mark newly-
  // revealed entities for the fade-in. Stored in a ref because we only
  // want to update on a real refetch, not on selection changes.
  const previousIdsRef = useRef<{ nodes: Set<string>; edges: Set<string> }>({
    nodes: new Set(),
    edges: new Set(),
  });
  // Anything in here gets `world-node--new` / `world-edge--new` for one
  // render cycle, which is enough for the CSS animation to play once.
  const [newlyRevealed, setNewlyRevealed] = useState<{
    nodes: Set<string>;
    edges: Set<string>;
  }>({ nodes: new Set(), edges: new Set() });

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .fetchWorldGraph(episodeSlug, page)
      .then((res) => {
        if (cancelled) return;
        // Diff: anything in the new snapshot that wasn't in the previous
        // snapshot is freshly revealed by a page flip — fade it in.
        const prev = previousIdsRef.current;
        const newNodes = new Set(
          res.nodes.filter((n) => !prev.nodes.has(n.id)).map((n) => n.id),
        );
        const newEdges = new Set(
          res.edges.filter((e) => !prev.edges.has(e.id)).map((e) => e.id),
        );
        previousIdsRef.current = {
          nodes: new Set(res.nodes.map((n) => n.id)),
          edges: new Set(res.edges.map((e) => e.id)),
        };
        setData(res);
        // First load (prev.nodes is empty): treat everything as
        // already-known so we don't animate every node on first paint.
        // The fade-in is reserved for the debut-on-flip moment.
        if (prev.nodes.size === 0) {
          setNewlyRevealed({ nodes: new Set(), edges: new Set() });
        } else {
          setNewlyRevealed({ nodes: newNodes, edges: newEdges });
        }
        setSelectedNodeId(null);
      })
      .catch((err) => {
        if (!cancelled) {
          console.warn('fetchWorldGraph failed:', err);
          setError(String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [episodeSlug, page]);

  // Reset the previous-ids snapshot when the episode changes — entities
  // shared across episodes shouldn't animate when the reader switches
  // books.
  useEffect(() => {
    previousIdsRef.current = { nodes: new Set(), edges: new Set() };
  }, [episodeSlug]);

  // Translate API rows → react-flow Node[] / Edge[]. The curated layout
  // from the YAML drives positions; selection state and the
  // newly-revealed mark ride on the node class.
  const nodes: Node<AvatarNodeData>[] = useMemo(() => {
    if (!data) return [];
    return data.nodes.map((entity) => ({
      id: entity.id,
      type: 'avatar',
      position: { x: entity.x, y: entity.y },
      data: { entity },
      draggable: false,
      selected: entity.id === selectedNodeId,
      // Layered onto the class so CSS @keyframes can drive the animation
      // without React managing per-node timers.
      className: newlyRevealed.nodes.has(entity.id) ? 'world-node--new' : '',
    }));
  }, [data, selectedNodeId, newlyRevealed.nodes]);

  const edges: Edge[] = useMemo(() => {
    if (!data) return [];
    return data.edges.map((edge) => {
      const focused =
        selectedNodeId !== null &&
        (edge.source === selectedNodeId || edge.target === selectedNodeId);
      const dimmed = selectedNodeId !== null && !focused;
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: 'default', // bezier
        label: focused ? edge.kind.replace(/_/g, ' ') : undefined,
        labelShowBg: focused,
        labelBgStyle: {
          fill: 'rgba(251, 242, 221, 0.92)',
          stroke: 'var(--accent)',
          strokeWidth: 1,
        },
        labelStyle: {
          fill: 'var(--accent)',
          fontSize: 10,
          fontWeight: 600,
          fontFamily: 'var(--font-ui)',
        },
        labelBgPadding: [4, 6] as [number, number],
        labelBgBorderRadius: 6,
        style: {
          stroke: focused ? EDGE_COLOR_FOCUSED : EDGE_COLOR_DEFAULT,
          strokeWidth: focused ? 2.25 : 1.5,
          opacity: focused
            ? EDGE_OPACITY_FOCUSED
            : dimmed
              ? EDGE_OPACITY_DIMMED
              : EDGE_OPACITY_DEFAULT,
          transition: 'opacity 180ms ease, stroke-width 180ms ease, stroke 180ms ease',
        },
        className: newlyRevealed.edges.has(edge.id) ? 'world-edge--new' : '',
      } satisfies Edge;
    });
  }, [data, selectedNodeId, newlyRevealed.edges]);

  const selectedEntity: WorldNode | null = useMemo(() => {
    if (!data || !selectedNodeId) return null;
    return data.nodes.find((n) => n.id === selectedNodeId) ?? null;
  }, [data, selectedNodeId]);

  if (error) {
    return (
      <div className="world-graph__error">Couldn't load world graph: {error}</div>
    );
  }
  if (!data) {
    return <div className="world-graph__loading">Loading world…</div>;
  }
  if (data.nodes.length === 0) {
    return (
      <div className="world-graph__empty">
        Nothing in the world yet — read on, or run the{' '}
        <code>extract-world-graph</code> skill against your ingested episodes
        to populate the graph.
      </div>
    );
  }

  return (
    <div className="world-graph">
      <div className="world-graph__canvas">
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            fitView
            fitViewOptions={{ padding: 0.25, maxZoom: 1.0 }}
            minZoom={0.3}
            maxZoom={1.6}
            panOnDrag
            zoomOnScroll
            nodesConnectable={false}
            edgesFocusable={false}
            proOptions={{ hideAttribution: true }}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId(null)}
          >
            <Controls
              showInteractive={false}
              position="bottom-right"
              style={{
                background: 'var(--parchment)',
                border: '1px solid var(--parchment-edge)',
                borderRadius: 6,
              }}
            />
          </ReactFlow>
        </ReactFlowProvider>
        {selectedEntity && (
          <InfoCard
            entity={selectedEntity}
            onClose={() => setSelectedNodeId(null)}
            onAskInWiki={onAskInWiki}
          />
        )}
      </div>
    </div>
  );
}
