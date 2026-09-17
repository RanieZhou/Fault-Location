import { useEffect } from 'react'
import { Handle, Position, useStore, useUpdateNodeInternals } from 'reactflow'
import { NODE_HEIGHT, NODE_WIDTH } from './topologyLayoutConstants'

export interface TopologyNodeData {
  label: string
  isSource: boolean
  hasMonitor?: boolean
  direction?: 'TB' | 'LR'
}

export function TopologyNode({ data, id }: { data: TopologyNodeData; id: string }) {
  const isHorizontal = data.direction === 'LR'
  const sourceHandleKey = useStore((state) =>
    state.edges
      .filter((edge) => edge.source === id && edge.sourceHandle)
      .map((edge) => edge.sourceHandle as string)
      .sort()
      .join('|'),
  )
  const activeSourceHandles = new Set(sourceHandleKey ? sourceHandleKey.split('|') : [])
  const updateNodeInternals = useUpdateNodeInternals()

  // Handle bounds are part of React Flow's measured node internals. Refresh
  // them when the active side set changes so a direction switch cannot leave
  // an edge using stale handle coordinates.
  useEffect(() => {
    updateNodeInternals(id)
  }, [id, isHorizontal, sourceHandleKey, updateNodeInternals])

  return (
    <div
      style={{
        boxSizing: 'border-box',
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '0 10px',
        borderRadius: 6,
        border: data.isSource ? '2px solid #fa8c16' : '1px solid #1677ff',
        background: data.isSource ? '#fff7e6' : '#ffffff',
        fontSize: 12,
        textAlign: 'center',
        boxShadow: '0 1px 2px rgba(0,0,0,0.08)',
      }}
    >
      <Handle
        type="target"
        id="target-top"
        position={Position.Top}
        style={{ opacity: isHorizontal ? 0 : 1, pointerEvents: 'none' }}
      />
      <Handle
        type="target"
        id="target-right"
        position={Position.Right}
        style={{ opacity: 0, pointerEvents: 'none' }}
      />
      <Handle
        type="target"
        id="target-bottom"
        position={Position.Bottom}
        style={{ opacity: 0, pointerEvents: 'none' }}
      />
      <Handle
        type="target"
        id="target-left"
        position={Position.Left}
        style={{ opacity: isHorizontal ? 1 : 0, pointerEvents: 'none' }}
      />
      <span
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={data.label}
      >
        {data.isSource ? '⚡ ' : ''}
        {data.hasMonitor ? '📟 ' : ''}
        {data.label}
      </span>
      <Handle
        type="source"
        id="source-top"
        position={Position.Top}
        style={{ opacity: activeSourceHandles.has('source-top') ? 1 : 0, pointerEvents: 'none' }}
      />
      <Handle
        type="source"
        id="source-right"
        position={Position.Right}
        style={{ opacity: isHorizontal || activeSourceHandles.has('source-right') ? 1 : 0, pointerEvents: 'none' }}
      />
      <Handle
        type="source"
        id="source-bottom"
        position={Position.Bottom}
        style={{ opacity: !isHorizontal || activeSourceHandles.has('source-bottom') ? 1 : 0, pointerEvents: 'none' }}
      />
      <Handle
        type="source"
        id="source-left"
        position={Position.Left}
        style={{ opacity: activeSourceHandles.has('source-left') ? 1 : 0, pointerEvents: 'none' }}
      />
    </div>
  )
}

export const topologyNodeTypes = { topologyNode: TopologyNode }
