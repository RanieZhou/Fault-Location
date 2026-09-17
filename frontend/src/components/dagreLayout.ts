import dagre from '@dagrejs/dagre'
import type { Edge, Node } from 'reactflow'
import { NODE_HEIGHT, NODE_WIDTH } from './topologyLayoutConstants'

const NODE_SEPARATION_PX = 56
const RANK_SEPARATION_PX = 96

// dagre only minimizes edge crossings within each rank; it never tries to
// keep a "main trunk" on one straight line, so a node with even one side
// branch can get nudged off-axis from its parent/child. Right-angle (step)
// edges are extremely sensitive to that: a one-pixel misalignment turns a
// straight connector into a down-right-up detour. Weighting each edge by
// the size of the subtree it leads to tells dagre which edges matter most
// to keep straight -- the branch feeding the most downstream nodes (i.e.
// the trunk) wins the straight line, and smaller side branches get pushed
// out to the side instead.
function computeSubtreeSizes(nodeIds: string[], edges: Edge[]): Map<string, number> {
  const children = new Map<string, string[]>()
  edges.forEach((edge) => {
    if (!children.has(edge.source)) children.set(edge.source, [])
    children.get(edge.source)!.push(edge.target)
  })

  const sizes = new Map<string, number>()
  const visiting = new Set<string>()

  function visit(nodeId: string): number {
    if (sizes.has(nodeId)) return sizes.get(nodeId)!
    if (visiting.has(nodeId)) return 0 // guard against cycle-closing edges
    visiting.add(nodeId)
    let size = 1
    for (const child of children.get(nodeId) ?? []) {
      size += visit(child)
    }
    visiting.delete(nodeId)
    sizes.set(nodeId, size)
    return size
  }

  nodeIds.forEach((id) => visit(id))
  return sizes
}

function buildChildren(edges: Edge[]): Map<string, string[]> {
  const children = new Map<string, string[]>()
  edges.forEach((edge) => {
    if (!children.has(edge.source)) children.set(edge.source, [])
    children.get(edge.source)!.push(edge.target)
  })
  return children
}

// Dagre decides the cross-axis position of every rank independently. That is
// useful for avoiding crossings, but it can leave the feeder's main route
// slightly zig-zagged. Follow the largest downstream subtree at each branch;
// this is the same trunk preference used for edge weights above, now made
// explicit so the final coordinates are deterministic.
function findMainPaths(nodeIds: string[], edges: Edge[], subtreeSizes: Map<string, number>): string[][] {
  const children = buildChildren(edges)
  const incoming = new Set(edges.map((edge) => edge.target))
  const roots = nodeIds.filter((nodeId) => !incoming.has(nodeId))
  const startNodes = roots.length > 0 ? roots : nodeIds
  const paths: string[][] = []

  startNodes.forEach((startNode) => {
    const path: string[] = []
    const visited = new Set<string>()
    let current: string | undefined = startNode

    while (current && !visited.has(current)) {
      visited.add(current)
      path.push(current)

      const next: string | undefined = (children.get(current) ?? [])
        .filter((nodeId) => !visited.has(nodeId))
        .sort((a, b) => (subtreeSizes.get(b) ?? 0) - (subtreeSizes.get(a) ?? 0))[0]
      current = next
    }

    if (path.length > 0) paths.push(path)
  })

  return paths
}

function alignMainPaths<T>(
  positionedNodes: Node<T>[],
  nodeIds: string[],
  edges: Edge[],
  direction: 'TB' | 'LR',
  subtreeSizes: Map<string, number>,
): Node<T>[] {
  const positionById = new Map(positionedNodes.map((node) => [node.id, node.position]))
  const mainNodeIds = new Set<string>()

  findMainPaths(nodeIds, edges, subtreeSizes).forEach((path) => {
    path.forEach((nodeId) => mainNodeIds.add(nodeId))
    const anchor = positionById.get(path[0])
    if (!anchor) return

    path.slice(1).forEach((nodeId) => {
      const position = positionById.get(nodeId)
      if (!position) return
      if (direction === 'TB') position.x = anchor.x
      else position.y = anchor.y
    })
  })

  return resolveNodeOverlaps(positionedNodes, mainNodeIds, direction)
}

function getNodeBounds<T>(node: Node<T>, direction: 'TB' | 'LR') {
  const primarySize = direction === 'LR' ? NODE_WIDTH : NODE_HEIGHT
  const crossSize = direction === 'LR' ? NODE_HEIGHT : NODE_WIDTH
  const primaryStart = direction === 'LR' ? node.position.x : node.position.y
  const crossStart = direction === 'LR' ? node.position.y : node.position.x

  return {
    primaryStart,
    primaryEnd: primaryStart + primarySize,
    crossStart,
    crossEnd: crossStart + crossSize,
  }
}

function moveNodeOnCrossAxis<T>(node: Node<T>, direction: 'TB' | 'LR', amount: number) {
  if (direction === 'LR') node.position.y += amount
  else node.position.x += amount
}

function moveNodeOnPrimaryAxis<T>(node: Node<T>, direction: 'TB' | 'LR', amount: number) {
  if (direction === 'LR') node.position.x += amount
  else node.position.y += amount
}

// Aligning a main path after Dagre has run can move it into a side node's
// lane. Resolve those collisions along the cross-axis while keeping the
// main-path nodes fixed. Moving only the later node in an existing lane keeps
// Dagre's ordering, which avoids introducing new edge crossings.
function resolveNodeOverlaps<T>(nodes: Node<T>[], fixedNodeIds: Set<string>, direction: 'TB' | 'LR'): Node<T>[] {
  const maxPasses = Math.max(2, nodes.length + 1)

  for (let pass = 0; pass < maxPasses; pass += 1) {
    let moved = false

    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const first = nodes[i]
        const second = nodes[j]
        const firstBounds = getNodeBounds(first, direction)
        const secondBounds = getNodeBounds(second, direction)

        const firstFixed = fixedNodeIds.has(first.id)
        const secondFixed = fixedNodeIds.has(second.id)
        const primaryOverlap =
          Math.min(firstBounds.primaryEnd, secondBounds.primaryEnd) -
          Math.max(firstBounds.primaryStart, secondBounds.primaryStart)
        const crossOverlap =
          Math.min(firstBounds.crossEnd, secondBounds.crossEnd) -
          Math.max(firstBounds.crossStart, secondBounds.crossStart)
        if (primaryOverlap < 0 || crossOverlap < 0) continue

        const firstIsAbove = firstBounds.crossStart <= secondBounds.crossStart
        const leading = firstIsAbove ? firstBounds : secondBounds
        const trailing = firstIsAbove ? secondBounds : firstBounds
        const crossShift = leading.crossEnd + NODE_SEPARATION_PX - trailing.crossStart

        const firstIsBeforeOnPrimary = firstBounds.primaryStart <= secondBounds.primaryStart
        const primaryLeading = firstIsBeforeOnPrimary ? firstBounds : secondBounds
        const primaryTrailing = firstIsBeforeOnPrimary ? secondBounds : firstBounds
        const primaryShift = primaryLeading.primaryEnd + RANK_SEPARATION_PX - primaryTrailing.primaryStart

        // Nodes in the same rank should keep their rank and move apart on the
        // cross-axis. If two rectangles from adjacent ranks have been pushed
        // into each other, separate them on whichever axis needs less movement.
        const samePrimaryLane = Math.abs(firstBounds.primaryStart - secondBounds.primaryStart) < 1
        const moveOnCrossAxis = samePrimaryLane || crossShift <= primaryShift

        if (moveOnCrossAxis) {
          if (crossShift <= 0) continue

          if (firstFixed && !secondFixed) {
            moveNodeOnCrossAxis(second, direction, firstIsAbove ? crossShift : -crossShift)
          } else if (!firstFixed && secondFixed) {
            moveNodeOnCrossAxis(first, direction, firstIsAbove ? -crossShift : crossShift)
          } else {
            moveNodeOnCrossAxis(firstIsAbove ? second : first, direction, crossShift)
          }
        } else {
          if (primaryShift <= 0) continue

          if (firstIsBeforeOnPrimary && firstFixed && !secondFixed) {
            moveNodeOnPrimaryAxis(second, direction, primaryShift)
          } else if (firstIsBeforeOnPrimary && !firstFixed && secondFixed) {
            moveNodeOnPrimaryAxis(first, direction, -primaryShift)
          } else if (!firstIsBeforeOnPrimary && secondFixed && !firstFixed) {
            moveNodeOnPrimaryAxis(first, direction, primaryShift)
          } else if (!firstIsBeforeOnPrimary && firstFixed && !secondFixed) {
            moveNodeOnPrimaryAxis(second, direction, -primaryShift)
          } else {
            moveNodeOnPrimaryAxis(firstIsBeforeOnPrimary ? second : first, direction, primaryShift)
          }
        }

        moved = true
      }
    }

    if (!moved) break
  }

  return nodes
}

export function layoutWithDagre<T>(
  nodes: Node<T>[],
  edges: Edge[],
  direction: 'TB' | 'LR' = 'TB',
): Node<T>[] {
  const graph = new dagre.graphlib.Graph()
  graph.setGraph({ rankdir: direction, nodesep: NODE_SEPARATION_PX, ranksep: RANK_SEPARATION_PX, edgesep: 24 })
  graph.setDefaultEdgeLabel(() => ({}))

  nodes.forEach((node) => {
    graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  })

  const subtreeSizes = computeSubtreeSizes(
    nodes.map((n) => n.id),
    edges,
  )
  edges.forEach((edge) => {
    graph.setEdge(edge.source, edge.target, { weight: subtreeSizes.get(edge.target) ?? 1 })
  })

  dagre.layout(graph)

  const laidOutNodes = nodes.map((node) => {
    const position = graph.node(node.id)
    return {
      ...node,
      position: { x: position.x - NODE_WIDTH / 2, y: position.y - NODE_HEIGHT / 2 },
    }
  })

  return alignMainPaths(laidOutNodes, nodes.map((node) => node.id), edges, direction, subtreeSizes)
}

// ReactFlow's step/smoothstep path builder always routes through an offset
// midpoint, even when the two ends are perfectly aligned -- so a straight
// vertical/horizontal run still gets drawn with a pointless little jog. The
// fix isn't a layout problem, it's a rendering one: once we know where
// dagre actually placed the nodes, edges whose endpoints line up on the
// layout axis are switched to a plain `straight` path (which is just a
// literal line, no midpoint logic to misfire), and only genuine branches
// that sit on a different row/column keep the right-angle `step` routing.
const TRUNK_ALIGNMENT_TOLERANCE_PX = 1.5

export function routeEdgeTypes<T>(edges: Edge[], laidOutNodes: Node<T>[], direction: 'TB' | 'LR'): Edge[] {
  const positionById = new Map(laidOutNodes.map((n) => [n.id, n.position]))
  return edges.map((edge) => {
    const sourcePos = positionById.get(edge.source)
    const targetPos = positionById.get(edge.target)
    const sourceCenter = sourcePos
      ? { x: sourcePos.x + NODE_WIDTH / 2, y: sourcePos.y + NODE_HEIGHT / 2 }
      : undefined
    const targetCenter = targetPos
      ? { x: targetPos.x + NODE_WIDTH / 2, y: targetPos.y + NODE_HEIGHT / 2 }
      : undefined
    const aligned =
      !!sourcePos &&
      !!targetPos &&
      (direction === 'TB'
        ? Math.abs(sourcePos.x - targetPos.x) < TRUNK_ALIGNMENT_TOLERANCE_PX
        : Math.abs(sourcePos.y - targetPos.y) < TRUNK_ALIGNMENT_TOLERANCE_PX)

    let sourceHandle: string | undefined
    let targetHandle: string | undefined
    if (sourceCenter && targetCenter) {
      if (direction === 'LR') {
        sourceHandle =
          Math.abs(sourceCenter.y - targetCenter.y) < TRUNK_ALIGNMENT_TOLERANCE_PX
            ? 'source-right'
            : targetCenter.y < sourceCenter.y
              ? 'source-top'
              : 'source-bottom'
        targetHandle = targetCenter.x >= sourceCenter.x ? 'target-left' : 'target-right'
      } else {
        sourceHandle =
          Math.abs(sourceCenter.x - targetCenter.x) < TRUNK_ALIGNMENT_TOLERANCE_PX
            ? 'source-bottom'
            : targetCenter.x < sourceCenter.x
              ? 'source-left'
              : 'source-right'
        targetHandle = targetCenter.y >= sourceCenter.y ? 'target-top' : 'target-bottom'
      }
    }

    return {
      ...edge,
      type: aligned ? 'straight' : 'step',
      sourceHandle,
      targetHandle,
    }
  })
}
