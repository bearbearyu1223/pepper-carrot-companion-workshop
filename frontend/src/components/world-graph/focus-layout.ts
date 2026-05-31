// Focus-mode layout: a tight kind-grid that doesn't depend on the
// curated full-world coordinates. The full-world layout puts covens
// at compass points and Pepper at origin — beautiful for the explorer
// view, but a sparse mess in focus mode where most quadrants are empty.
//
// The grid:
//   row -1: coven nodes   (y = -ROW_GAP)
//   row  0: characters    (y = 0), with familiars adjacent to their owner;
//           creatures and objects appended on the right
//   row  1: place nodes   (y = +ROW_GAP)
//
// Sorting is alphabetical for stability, except: familiars stick next
// to their owner so the familiar_of edge stays a short horizontal line.

import type { WorldEdge, WorldKind, WorldNode } from '../../api/types';

const COL_GAP = 180; // horizontal spacing between adjacent nodes in a row
const ROW_GAP = 280; // vertical distance from main row to coven/place rows

export function computeFocusLayout(
  entities: WorldNode[],
  edges: WorldEdge[],
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  if (entities.length === 0) return positions;

  // Bucket by kind. Use a typed empty as the default so we don't have to
  // .get(...).push(...).slice() three times.
  const byKind: Record<WorldKind, WorldNode[]> = {
    character: [],
    creature: [],
    place: [],
    coven: [],
    object: [],
  };
  for (const e of entities) byKind[e.kind].push(e);

  // Map familiar → owner so we can interleave them in the character row.
  // We only consider familiar_of edges where both endpoints are visible.
  const visibleIds = new Set(entities.map((e) => e.id));
  const familiarOf = new Map<string, string>();
  for (const e of edges) {
    if (
      e.kind === 'familiar_of' &&
      visibleIds.has(e.source) &&
      visibleIds.has(e.target)
    ) {
      familiarOf.set(e.source, e.target);
    }
  }

  const chars = byKind.character;
  const familiars = chars.filter((c) => familiarOf.has(c.id));
  const familiarIds = new Set(familiars.map((f) => f.id));
  const nonFamiliarChars = chars
    .filter((c) => !familiarIds.has(c.id))
    .sort((a, b) => a.name.localeCompare(b.name));

  // Insert each familiar right after its owner.
  const orderedChars: WorldNode[] = [];
  for (const owner of nonFamiliarChars) {
    orderedChars.push(owner);
    for (const fam of familiars) {
      if (familiarOf.get(fam.id) === owner.id) orderedChars.push(fam);
    }
  }
  // Orphan familiars (owner not in the focus set) go at the end.
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
  const covens = byKind.coven.slice().sort((a, b) => a.name.localeCompare(b.name));
  const places = byKind.place.slice().sort((a, b) => a.name.localeCompare(b.name));

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
  // Center the row around x=0 so fitView frames the whole thing.
  const offset = ((items.length - 1) * COL_GAP) / 2;
  items.forEach((e, i) => {
    out.set(e.id, { x: i * COL_GAP - offset, y });
  });
}
