const GRAPH_NODE_MIN_GAP = 14;
const GRAPH_NODE_RELAXATION_GAP = GRAPH_NODE_MIN_GAP + 4;
const GRAPH_NODE_RELAXATION_PASSES = 128;

export interface GraphNodePosition {
  id: string;
  x: number;
  y: number;
  radius: number;
  anchored: boolean;
}

export function graphNodeDepths(
  centerId: string,
  nodeIds: readonly string[],
  edges: ReadonlyArray<{ source: string | number; target: string | number }>,
): Map<string, number> {
  const knownNodeIds = new Set(nodeIds);
  if (!knownNodeIds.has(centerId)) return new Map();
  const adjacency = new Map(nodeIds.map((id) => [id, new Set<string>()]));
  edges.forEach((edge) => {
    const source = String(edge.source);
    const target = String(edge.target);
    if (!knownNodeIds.has(source) || !knownNodeIds.has(target)) return;
    adjacency.get(source)?.add(target);
    adjacency.get(target)?.add(source);
  });

  const depths = new Map<string, number>([[centerId, 0]]);
  const pending = [centerId];
  for (let index = 0; index < pending.length; index += 1) {
    const current = pending[index];
    const nextDepth = (depths.get(current) ?? 0) + 1;
    adjacency.get(current)?.forEach((neighbor) => {
      if (depths.has(neighbor)) return;
      depths.set(neighbor, nextDepth);
      pending.push(neighbor);
    });
  }
  return depths;
}

function stablePositionHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function separateGraphNodePositions(
  source: readonly GraphNodePosition[],
): GraphNodePosition[] {
  const nodes = source
    .map((node) => ({ ...node }))
    .sort((left, right) => left.id.localeCompare(right.id, "es"));

  for (let pass = 0; pass < GRAPH_NODE_RELAXATION_PASSES; pass += 1) {
    let overlapFound = false;
    for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
        const left = nodes[leftIndex];
        const right = nodes[rightIndex];
        let deltaX = right.x - left.x;
        let deltaY = right.y - left.y;
        let distance = Math.hypot(deltaX, deltaY);
        const requiredDistance = left.radius + right.radius + GRAPH_NODE_RELAXATION_GAP;
        if (distance + 0.01 >= requiredDistance) continue;

        overlapFound = true;
        if (distance < 0.01) {
          const angle = (stablePositionHash(`${left.id}|${right.id}`) / 2 ** 32) * Math.PI * 2;
          deltaX = Math.cos(angle);
          deltaY = Math.sin(angle);
          distance = 1;
        } else {
          deltaX /= distance;
          deltaY /= distance;
        }
        const displacement = requiredDistance - distance;
        if (left.anchored) {
          right.x += deltaX * displacement;
          right.y += deltaY * displacement;
        } else if (right.anchored) {
          left.x -= deltaX * displacement;
          left.y -= deltaY * displacement;
        } else {
          const halfDisplacement = displacement / 2;
          left.x -= deltaX * halfDisplacement;
          left.y -= deltaY * halfDisplacement;
          right.x += deltaX * halfDisplacement;
          right.y += deltaY * halfDisplacement;
        }
      }
    }
    if (!overlapFound) break;
  }
  return nodes;
}
