// Tight layout for the focus mode + filtered-full mode subset.
//
// Two strategies, chosen automatically from the visible graph:
//
//   1. radial (preferred when there's a clear "hub"): the highest-degree
//      node sits at origin, its direct neighbors are placed around it on
//      a circle, and any remaining nodes go in a row below. This is what
//      "Pepper + her three godmothers + Carrot" wants — Pepper at the
//      center, the four others on a + pattern, every edge a clean short
//      spoke with a readable label at the midpoint. The current focus
//      layout put all five in a row, which made the Cayenne→Pepper and
//      Thyme→Pepper edges route under Cumin and Carrot respectively.
//
//   2. kind-grid (fallback): three horizontal rows — covens above,
//      characters in the middle (familiars adjacent to their owner),
//      places below. Used when no node has enough incident edges to
//      anchor a useful radial layout (e.g. only covens visible, no
//      structural relationships).
//
// Same export name as before, same return type. Callers don't change.

import type { WorldEdge, WorldKind, WorldNode } from '../../api/types';

const COL_GAP = 180; // horizontal spacing in a row
const ROW_GAP = 280; // vertical distance from main row to coven/place rows
const RADIAL_RADIUS = 220; // distance from hub to its neighbors
const RADIAL_FALLOUT_GAP = 200; // distance from radial cluster to the row of unrelated nodes
const MIN_HUB_DEGREE = 3; // hub needs at least this many visible incident edges

export function computeFocusLayout(
  entities: WorldNode[],
  edges: WorldEdge[],
): Map<string, { x: number; y: number }> {
  if (entities.length === 0) return new Map();

  // Score every visible node by how many visible edges touch it. A hub
  // we can build a radial around needs at least MIN_HUB_DEGREE — fewer
  // than that and we fall back to the kind-grid because radial-around-
  // a-leaf is uglier than a row.
  const visibleIds = new Set(entities.map((e) => e.id));
  const degree = new Map<string, number>();
  const incident = new Map<string, WorldEdge[]>();
  for (const edge of edges) {
    if (!visibleIds.has(edge.source) || !visibleIds.has(edge.target)) continue;
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    if (!incident.has(edge.source)) incident.set(edge.source, []);
    if (!incident.has(edge.target)) incident.set(edge.target, []);
    incident.get(edge.source)!.push(edge);
    incident.get(edge.target)!.push(edge);
  }

  const hub = pickHub(entities, degree);
  if (hub && (degree.get(hub.id) ?? 0) >= MIN_HUB_DEGREE) {
    return radialLayout(entities, incident, hub);
  }
  return kindGridLayout(entities, edges);
}

// Prefer the highest-degree node; on ties prefer character > coven > place >
// creature > object, then alphabetical, so the layout is stable across
// re-renders even when degree counts collide.
const KIND_TIEBREAK: Record<WorldKind, number> = {
  character: 0,
  coven: 1,
  place: 2,
  creature: 3,
  object: 4,
};

function pickHub(
  entities: WorldNode[],
  degree: Map<string, number>,
): WorldNode | null {
  let best: WorldNode | null = null;
  let bestKey: [number, number, string] = [-1, 99, ''];
  for (const entity of entities) {
    const deg = degree.get(entity.id) ?? 0;
    const key: [number, number, string] = [
      deg,
      // higher degree wins; on tie, lower kind index wins (so negate)
      KIND_TIEBREAK[entity.kind],
      entity.name,
    ];
    if (
      key[0] > bestKey[0] ||
      (key[0] === bestKey[0] && key[1] < bestKey[1]) ||
      (key[0] === bestKey[0] &&
        key[1] === bestKey[1] &&
        key[2] < bestKey[2])
    ) {
      best = entity;
      bestKey = key;
    }
  }
  return best;
}

function radialLayout(
  entities: WorldNode[],
  incident: Map<string, WorldEdge[]>,
  hub: WorldNode,
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  positions.set(hub.id, { x: 0, y: 0 });

  // Collect the hub's direct neighbors via visible edges. Group by edge
  // kind so same-kind neighbors sit next to each other on the circle —
  // the three godmother_of edges become a contiguous arc, the lone
  // familiar_of sits on its own side.
  const hubEdges = incident.get(hub.id) ?? [];
  const byKind = new Map<string, string[]>();
  for (const edge of hubEdges) {
    const neighborId = edge.source === hub.id ? edge.target : edge.source;
    if (neighborId === hub.id) continue; // defensive: no self-loops in this UI
    if (!byKind.has(edge.kind)) byKind.set(edge.kind, []);
    const list = byKind.get(edge.kind)!;
    if (!list.includes(neighborId)) list.push(neighborId);
  }
  // Flatten: edge-kinds sorted alphabetically for stability, then
  // neighbors within each kind in their original order. Dedupe in case
  // two different edge kinds connect to the same neighbor.
  const seen = new Set<string>();
  const orderedNeighbors: string[] = [];
  for (const kind of [...byKind.keys()].sort()) {
    for (const neighborId of byKind.get(kind)!) {
      if (seen.has(neighborId)) continue;
      seen.add(neighborId);
      orderedNeighbors.push(neighborId);
    }
  }

  // Spread the neighbors around the hub. Start at the top (-π/2) and
  // walk clockwise so the first neighbor in the ordered list reads as
  // "first" visually too.
  const count = orderedNeighbors.length;
  orderedNeighbors.forEach((id, i) => {
    const angle = -Math.PI / 2 + (i / count) * 2 * Math.PI;
    positions.set(id, {
      x: Math.cos(angle) * RADIAL_RADIUS,
      y: Math.sin(angle) * RADIAL_RADIUS,
    });
  });

  // Anything not connected to the hub goes in a row below the radial
  // cluster so the visual hierarchy stays "hub-centric, then the rest".
  const placed = new Set(positions.keys());
  const unplaced = entities
    .filter((e) => !placed.has(e.id))
    .sort((a, b) => a.name.localeCompare(b.name));
  if (unplaced.length > 0) {
    const y = RADIAL_RADIUS + RADIAL_FALLOUT_GAP;
    const offset = ((unplaced.length - 1) * COL_GAP) / 2;
    unplaced.forEach((entity, i) => {
      positions.set(entity.id, { x: i * COL_GAP - offset, y });
    });
  }

  return positions;
}

function kindGridLayout(
  entities: WorldNode[],
  edges: WorldEdge[],
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();

  // Bucket by kind for the three-row layout.
  const byKind: Record<WorldKind, WorldNode[]> = {
    character: [],
    creature: [],
    place: [],
    coven: [],
    object: [],
  };
  for (const entity of entities) byKind[entity.kind].push(entity);

  // Map familiar → owner so we can interleave familiars next to their
  // owner in the character row (keeps the familiar_of edge short).
  const visibleIds = new Set(entities.map((e) => e.id));
  const familiarOf = new Map<string, string>();
  for (const edge of edges) {
    if (
      edge.kind === 'familiar_of' &&
      visibleIds.has(edge.source) &&
      visibleIds.has(edge.target)
    ) {
      familiarOf.set(edge.source, edge.target);
    }
  }

  const chars = byKind.character;
  const familiars = chars.filter((c) => familiarOf.has(c.id));
  const familiarIds = new Set(familiars.map((f) => f.id));
  const nonFamiliarChars = chars
    .filter((c) => !familiarIds.has(c.id))
    .sort((a, b) => a.name.localeCompare(b.name));

  const orderedChars: WorldNode[] = [];
  for (const owner of nonFamiliarChars) {
    orderedChars.push(owner);
    for (const fam of familiars) {
      if (familiarOf.get(fam.id) === owner.id) orderedChars.push(fam);
    }
  }
  for (const fam of familiars) {
    const ownerId = familiarOf.get(fam.id);
    if (!nonFamiliarChars.some((c) => c.id === ownerId)) {
      orderedChars.push(fam);
    }
  }

  const mainRow: WorldNode[] = [
    ...orderedChars,
    ...byKind.creature.slice().sort((a, b) => a.name.localeCompare(b.name)),
    ...byKind.object.slice().sort((a, b) => a.name.localeCompare(b.name)),
  ];
  const covens = byKind.coven
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name));
  const places = byKind.place
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name));

  placeRow(covens, -ROW_GAP, positions);
  placeRow(mainRow, 0, positions);
  placeRow(places, ROW_GAP, positions);

  return positions;
}

function placeRow(
  items: WorldNode[],
  y: number,
  out: Map<string, { x: number; y: number }>,
): void {
  if (items.length === 0) return;
  const offset = ((items.length - 1) * COL_GAP) / 2;
  items.forEach((entity, i) => {
    out.set(entity.id, { x: i * COL_GAP - offset, y });
  });
}
