// React-flow canvas: avatar nodes at curated positions + low-key bezier
// edges that brighten on the selected node's incidents. Two modes:
//
//   focus — only on-page characters + 1-hop structural neighbors. The
//           viewport auto-fits whenever the node set changes so the
//           handful of relevant entities sits centered. Layout is
//           computed fresh (kind-grid) rather than reusing the
//           full-world coordinates, where most quadrants would be empty.
//   full  — every spoiler-safe entity. Curated YAML positions are
//           honored; the user pans/zooms freely.
//
// A kind-filter bar above the canvas lets the reader narrow the visible
// kinds (characters only, places only, …). Newly-revealed entities and
// edges fade in softly when the reader flips into new territory — the
// diff happens in JS; the animation is pure CSS @keyframes.

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { api } from '../../api/client';
import type {
  WorldEdge,
  WorldGraph as WorldGraphData,
  WorldGraphMode,
  WorldKind,
  WorldNode,
} from '../../api/types';
import { AvatarNode, type AvatarNodeData } from './AvatarNode';
import { InfoCard } from './InfoCard';
import { KindFilterBar } from './KindFilterBar';
import { edgeColorFor } from './constants';
import { computeFocusLayout } from './focus-layout';

interface WorldGraphProps {
  episodeSlug: string;
  page: number;
  // Right page of the two-page spread; defaults to `page` for single-page
  // mode. Focus seeding uses [page, rightPage] so a landscape reader sees
  // the union of both pages' characters.
  rightPage?: number;
  onAskInWiki: (entityName: string) => void;
}

const NODE_TYPES = { avatar: AvatarNode };
const ALL_KINDS: WorldKind[] = ['character', 'creature', 'place', 'coven', 'object'];

// Edge-styling regimes. The strokes lean a hair thicker than the
// geometric defaults so the lines read as inked rather than CAD'd
// against the parchment background.
const EDGE_OPACITY_DEFAULT = 0.55;
const EDGE_OPACITY_FOCUSED = 0.9;
const EDGE_OPACITY_DIMMED = 0.18;
const EDGE_STROKE_DEFAULT = 1.6;
const EDGE_STROKE_FOCUSED = 2.25;
const EDGE_STROKE_DIMMED = 1;
const EDGE_COLOR_NEUTRAL = 'rgb(110, 80, 50)';

// Imperative auto-fit. Mounts inside ReactFlowProvider so it can grab
// the fitView function via the hook. Re-fits whenever the node-id set
// changes — small focus subsets get centered without the user pan-and-
// zooming to find them, and the whole-world view fits its bounding box
// instead of stranding nodes off the right edge of the panel at the
// default viewport offset.
function FitOnNodesChange({ nodeIds }: { nodeIds: string[] }) {
  const rf = useReactFlow();
  const key = nodeIds.join('|');
  useEffect(() => {
    if (nodeIds.length === 0) return;
    // requestAnimationFrame gives react-flow a tick to lay out the
    // nodes before we measure them — calling fitView synchronously can
    // fit to an empty bounding box and leave the panel showing nothing.
    const handle = requestAnimationFrame(() => {
      rf.fitView({ padding: 0.25, duration: 350, maxZoom: 1.0 });
    });
    return () => cancelAnimationFrame(handle);
  }, [key, rf, nodeIds.length]);
  return null;
}

export function WorldGraph({
  episodeSlug,
  page,
  rightPage,
  onAskInWiki,
}: WorldGraphProps) {
  const [data, setData] = useState<WorldGraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  // Default to 'focus' — show what's on this page, not the whole universe.
  const [mode, setMode] = useState<WorldGraphMode>('focus');
  // Active kinds — start all-on. Toggle via KindFilterBar.
  const [activeKinds, setActiveKinds] = useState<Set<WorldKind>>(
    () => new Set(ALL_KINDS),
  );

  // ─── Fade-in diff (Post 9 polish) ──────────────────────────────────
  // Track the previous snapshot's ids so we can mark newly-revealed
  // entities + edges with a one-render class that drives a CSS keyframe.
  const previousIdsRef = useRef<{ nodes: Set<string>; edges: Set<string> }>({
    nodes: new Set(),
    edges: new Set(),
  });
  const [newlyRevealed, setNewlyRevealed] = useState<{
    nodes: Set<string>;
    edges: Set<string>;
  }>({ nodes: new Set(), edges: new Set() });

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .fetchWorldGraph(episodeSlug, page, mode, rightPage)
      .then((res) => {
        if (cancelled) return;
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
        // First load (prev.nodes empty): treat everything as already-known
        // so we don't animate every node on first paint. The fade-in is
        // reserved for the debut-on-flip moment.
        setNewlyRevealed(
          prev.nodes.size === 0
            ? { nodes: new Set(), edges: new Set() }
            : { nodes: newNodes, edges: newEdges },
        );
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
  }, [episodeSlug, page, mode, rightPage]);

  // Episode change resets the previous-ids snapshot so entities shared
  // across episodes don't animate when the reader switches books.
  useEffect(() => {
    previousIdsRef.current = { nodes: new Set(), edges: new Set() };
  }, [episodeSlug]);

  // Pre-filter the API response by active kinds. Edges are kept only
  // when both endpoints survive the kind filter — same shape as the
  // backend's spoiler filter, just layered for client-side narrowing.
  const filtered = useMemo<{ nodes: WorldNode[]; edges: WorldEdge[] }>(() => {
    if (!data) return { nodes: [], edges: [] };
    const visibleNodes = data.nodes.filter((n) => activeKinds.has(n.kind));
    const visibleNodeIds = new Set(visibleNodes.map((n) => n.id));
    const visibleEdges = data.edges.filter(
      (e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target),
    );
    return { nodes: visibleNodes, edges: visibleEdges };
  }, [data, activeKinds]);

  // Per-kind counts for the filter bar. Use the unfiltered API response
  // so toggling a chip off doesn't make the chip vanish.
  const counts = useMemo(() => {
    const out: Record<WorldKind, number> = {
      character: 0,
      creature: 0,
      place: 0,
      coven: 0,
      object: 0,
    };
    for (const n of data?.nodes ?? []) out[n.kind] = (out[n.kind] ?? 0) + 1;
    return out;
  }, [data]);

  // Decide which layout to use for the visible subset.
  //
  //   - focus mode: always compute (radial-around-hub if there's one,
  //     kind-grid otherwise). The curated YAML coords are sparse for a
  //     small focus set.
  //   - full mode with NO kind filter: keep the curated YAML coords —
  //     the compass-point arrangement is the artistic point of the
  //     explorer view.
  //   - full mode WITH a kind filter active: compute a tight layout
  //     too. Without this, narrowing to e.g. "covens + places only"
  //     leaves a few nodes scattered at their full-world coordinates
  //     with most of the panel empty and edges so long they're barely
  //     readable. The kind filter is a focusing affordance; the layout
  //     should follow.
  const useComputedLayout =
    mode === 'focus' ||
    (mode === 'full' && data !== null && activeKinds.size < ALL_KINDS.length);
  const computedPositions = useMemo(
    () =>
      useComputedLayout
        ? computeFocusLayout(filtered.nodes, filtered.edges)
        : null,
    [filtered.nodes, filtered.edges, useComputedLayout],
  );

  // Translate API rows → react-flow Node[]. The fade-in class is mounted
  // for one render cycle so the CSS keyframe plays once per debut.
  const nodes: Node<AvatarNodeData>[] = useMemo(() => {
    return filtered.nodes.map((entity) => {
      const pos =
        computedPositions?.get(entity.id) ?? { x: entity.x, y: entity.y };
      return {
        id: entity.id,
        type: 'avatar',
        position: pos,
        data: { entity },
        // Curated positions are the point in full mode; in focus we
        // computed positions from kind. Either way: no dragging.
        draggable: false,
        selected: entity.id === selectedNodeId,
        className: newlyRevealed.nodes.has(entity.id) ? 'world-node--new' : '',
      };
    });
  }, [filtered.nodes, computedPositions, selectedNodeId, newlyRevealed.nodes]);

  // Position lookup so edges can pick the handle side that produces the
  // most natural bezier given the source/target geometry. Computed from
  // the same node array we hand to ReactFlow so the lookup never lags.
  const positionById = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    for (const n of nodes) map.set(n.id, n.position);
    return map;
  }, [nodes]);

  const edges: Edge[] = useMemo(() => {
    // Labels are always on in focus mode (the canvas is small enough to
    // read them) and on-demand in full mode (a wall of labels otherwise).
    // A focused edge always shows its label regardless of mode.
    const labelsAlwaysOn = mode === 'focus';
    return filtered.edges.map((edge) => {
      const focused =
        selectedNodeId !== null &&
        (edge.source === selectedNodeId || edge.target === selectedNodeId);
      const dimmed = selectedNodeId !== null && !focused;
      const showLabel = focused || labelsAlwaysOn;
      const kindColor = edgeColorFor(edge.kind);

      // Pick handles based on the dominant axis between source and
      // target: a mostly-horizontal pair gets right→left handles (clean
      // side-to-side curve), a mostly-vertical pair gets bottom→top
      // (clean north–south curve). Falls back to bottom→top when either
      // node hasn't been positioned yet.
      const sp = positionById.get(edge.source);
      const tp = positionById.get(edge.target);
      let sourceHandle = 's-bottom';
      let targetHandle = 't-top';
      if (sp && tp) {
        const dx = tp.x - sp.x;
        const dy = tp.y - sp.y;
        if (Math.abs(dx) > Math.abs(dy)) {
          sourceHandle = dx > 0 ? 's-right' : 's-left';
          targetHandle = dx > 0 ? 't-left' : 't-right';
        } else {
          sourceHandle = dy > 0 ? 's-bottom' : 's-top';
          targetHandle = dy > 0 ? 't-top' : 't-bottom';
        }
      }

      const baseClass = newlyRevealed.edges.has(edge.id) ? 'world-edge--new' : '';

      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle,
        targetHandle,
        // Bezier curves (the 'default' edge type) read more like hand-
        // inked lines than the right-angle smoothstep — better fit for
        // the comic's aesthetic.
        type: 'default',
        label: showLabel ? edge.kind.replace(/_/g, ' ') : undefined,
        labelShowBg: showLabel,
        // Parchment pill keeps the label legible whether it's drawn
        // over an avatar circle, a coven halo, or empty paper.
        labelBgStyle: {
          fill: 'rgba(251, 242, 221, 0.92)',
          stroke: focused ? kindColor : 'rgba(120, 90, 60, 0.25)',
          strokeWidth: focused ? 1.25 : 0.75,
        },
        labelBgPadding: [4, 6] as [number, number],
        labelBgBorderRadius: 6,
        labelStyle: {
          fill: focused ? kindColor : 'rgb(120, 90, 60)',
          fontSize: focused ? 10 : 9,
          fontWeight: focused ? 600 : 500,
          fontFamily: 'var(--font-ui)',
          letterSpacing: '0.01em',
          opacity: focused ? 1 : dimmed ? 0.35 : 0.85,
        },
        style: {
          stroke: focused ? kindColor : EDGE_COLOR_NEUTRAL,
          opacity: focused
            ? EDGE_OPACITY_FOCUSED
            : dimmed
              ? EDGE_OPACITY_DIMMED
              : EDGE_OPACITY_DEFAULT,
          strokeWidth: focused
            ? EDGE_STROKE_FOCUSED
            : dimmed
              ? EDGE_STROKE_DIMMED
              : EDGE_STROKE_DEFAULT,
          // Keep strokes the same on-screen pixel width regardless of
          // react-flow's zoom — without this, a fit-view that zooms out
          // to frame a wide-spread subset shrinks the strokes to ~0.5 px
          // and the edges disappear into the parchment.
          vectorEffect: 'non-scaling-stroke',
          transition: 'opacity 180ms ease, stroke-width 180ms ease, stroke 180ms ease',
        },
        className: baseClass,
      } satisfies Edge;
    });
  }, [filtered.edges, selectedNodeId, mode, positionById, newlyRevealed.edges]);

  const selectedEntity = useMemo(() => {
    if (!data || !selectedNodeId) return null;
    return data.nodes.find((n) => n.id === selectedNodeId) ?? null;
  }, [data, selectedNodeId]);

  const handleToggleKind = (kind: WorldKind) => {
    setActiveKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) {
        // Don't allow turning off the last active kind — an empty graph
        // is confusing to recover from.
        if (next.size === 1) return prev;
        next.delete(kind);
      } else {
        next.add(kind);
      }
      return next;
    });
    // Clear selection when the visible set changes; a stale selection
    // renders confusingly when its node disappears.
    setSelectedNodeId(null);
  };

  // Stable list of node ids for the auto-fit child. Identity changes
  // when the focus subset changes (or when the user toggles a kind),
  // which is exactly when we want to re-fit.
  const nodeIdList = useMemo(
    () => filtered.nodes.map((n) => n.id),
    [filtered.nodes],
  );

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
      <div className="world-graph__toolbar">
        <KindFilterBar
          active={activeKinds}
          counts={counts}
          onToggle={handleToggleKind}
        />
        <div
          className="world-mode-toggle"
          role="group"
          aria-label="Graph view mode"
        >
          <button
            type="button"
            className={`world-mode-toggle__pill ${
              mode === 'focus' ? 'world-mode-toggle__pill--active' : ''
            }`}
            onClick={() => setMode('focus')}
            aria-pressed={mode === 'focus'}
            title="Show entities on this page and their immediate connections"
          >
            This page
          </button>
          <button
            type="button"
            className={`world-mode-toggle__pill ${
              mode === 'full' ? 'world-mode-toggle__pill--active' : ''
            }`}
            onClick={() => setMode('full')}
            aria-pressed={mode === 'full'}
            title="Show every entity introduced up to this page"
          >
            Whole world
          </button>
        </div>
      </div>
      <div className="world-graph__canvas">
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            fitView={false}
            defaultViewport={{ x: 280, y: 240, zoom: 0.55 }}
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
            <FitOnNodesChange nodeIds={nodeIdList} />
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
