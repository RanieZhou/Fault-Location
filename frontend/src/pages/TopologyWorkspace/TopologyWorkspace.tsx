import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
  type OnSelectionChangeParams,
} from 'reactflow'
import 'reactflow/dist/style.css'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Segmented,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { apiErrorMessage } from '../../api/client'
import { getEdgesTable, updateEdgeConfig, type EdgeTableRow } from '../../api/edges'
import { deleteMonitor, listMonitors, type Monitor } from '../../api/monitors'
import { getGraph, getNetwork, getValidation, setSource } from '../../api/networks'
import type { GraphEdge, GraphNode, NetworkGraph, NetworkOut, TopologyValidationSummary } from '../../api/types'
import { layoutWithDagre, routeEdgeTypes } from '../../components/dagreLayout'
import { EdgeConfigModal, type EdgeConfigInitial } from '../../components/EdgeConfigModal'
import { MonitorModal } from '../../components/MonitorModal'
import { topologyNodeTypes, type TopologyNodeData } from '../../components/TopologyNode'
import { useCurrentNetwork } from '../../state/CurrentNetworkContext'
import { palette } from '../../theme'

const { Text, Title } = Typography

const LINE_TYPE_LABELS: Record<string, string> = {
  overhead: '架空导线',
  cable: '电缆',
}

function buildElements(
  graph: NetworkGraph,
  highlightUnconfigured: boolean,
  selectedNodeId: string | null,
  selectedEdgeIds: Set<string>,
  direction: 'TB' | 'LR',
): { nodes: RFNode<TopologyNodeData>[]; edges: RFEdge[] } {
  const nodes: RFNode<TopologyNodeData>[] = graph.nodes.map((n) => ({
    id: n.node_id,
    type: 'topologyNode',
    data: { label: n.node_key, isSource: n.is_source, hasMonitor: n.has_monitor, direction },
    position: { x: 0, y: 0 },
    selected: n.node_id === selectedNodeId,
  }))

  const edges: RFEdge[] = graph.edges.map((e) => {
    const directed = Boolean(e.source_node_id && e.target_node_id)
    const isOpen = e.status === 'open'
    const unconfigured = !e.line_model_id || e.length_km == null
    const emphasize = highlightUnconfigured && unconfigured && !isOpen
    return {
      id: e.edge_id,
      type: 'step',
      source: e.source_node_id ?? e.node_a_id,
      target: e.target_node_id ?? e.node_b_id,
      label: e.edge_key ?? undefined,
      selected: selectedEdgeIds.has(e.edge_id),
      style: {
        stroke: isOpen ? palette.mutedEdge : emphasize ? palette.warningAccent : palette.primary,
        strokeDasharray: isOpen || !directed ? '6 4' : undefined,
        strokeWidth: emphasize ? 3 : 1.5,
      },
      markerEnd: directed && !isOpen ? { type: MarkerType.ArrowClosed, color: palette.primary } : undefined,
    }
  })

  return { nodes, edges }
}

export function TopologyWorkspace() {
  return (
    <ReactFlowProvider>
      <TopologyWorkspaceInner />
    </ReactFlowProvider>
  )
}

function TopologyWorkspaceInner() {
  const { networkId } = useParams<{ networkId: string }>()
  const { fitView } = useReactFlow()
  const { setCurrentNetwork } = useCurrentNetwork()

  const [network, setNetworkState] = useState<NetworkOut | null>(null)
  const [graph, setGraph] = useState<NetworkGraph | null>(null)
  const [loading, setLoading] = useState(false)
  const [highlightUnconfigured, setHighlightUnconfigured] = useState(false)
  const [layoutDirection, setLayoutDirection] = useState<'TB' | 'LR'>('LR')
  const [panelCollapsed, setPanelCollapsed] = useState(false)

  const [nodes, setNodes, onNodesChange] = useNodesState<TopologyNodeData>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [selectedEdges, setSelectedEdges] = useState<GraphEdge[]>([])

  const [validation, setValidation] = useState<TopologyValidationSummary | null>(null)
  const [validationOpen, setValidationOpen] = useState(false)

  const [viewMode, setViewMode] = useState<'canvas' | 'table'>('canvas')
  const [edgeTableRows, setEdgeTableRows] = useState<EdgeTableRow[]>([])
  const [edgeTableLoading, setEdgeTableLoading] = useState(false)
  const [tableSearch, setTableSearch] = useState('')
  const [tableSelectedIds, setTableSelectedIds] = useState<string[]>([])

  const [configModalOpen, setConfigModalOpen] = useState(false)
  const [configEdgeIds, setConfigEdgeIds] = useState<string[]>([])
  const [configInitialEdge, setConfigInitialEdge] = useState<EdgeConfigInitial | undefined>(undefined)

  const [monitors, setMonitors] = useState<Monitor[]>([])
  const [monitorModalOpen, setMonitorModalOpen] = useState(false)
  const [editingMonitor, setEditingMonitor] = useState<Monitor | undefined>(undefined)

  const loadGraph = useCallback(async () => {
    if (!networkId) return
    setLoading(true)
    try {
      const [net, g, m] = await Promise.all([getNetwork(networkId), getGraph(networkId), listMonitors(networkId)])
      setNetworkState(net)
      setGraph(g)
      setMonitors(m)
      setCurrentNetwork(net.network_id, net.name)
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setLoading(false)
    }
    // setCurrentNetwork identity is stable (Context), safe to omit from deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [networkId])

  useEffect(() => {
    loadGraph()
  }, [loadGraph])

  // Mirrors selectedNode/selectedEdges so the graph-reload effect below can
  // read the latest selection synchronously without depending on it (which
  // would make the effect re-run on every selection change).
  const selectionRef = useRef<{ nodeId: string | null; edgeIds: string[] }>({ nodeId: null, edgeIds: [] })
  // Only the first graph load for a given network should recenter the
  // camera. Every later reload (saving one edge/monitor, resolving an
  // unmatched name, ...) re-runs this same effect and must leave the user's
  // current pan/zoom alone instead of snapping back to a fitted view.
  const fittedNetworkIdRef = useRef<string | null>(null)

  useEffect(() => {
    if (!graph) return
    // Re-resolve the current selection against the freshly loaded graph
    // instead of clearing it, so saving a monitor/edge config doesn't kick
    // the user back to the empty properties panel. The resolved ids are
    // baked into the rebuilt elements' `selected` flag up front -- if they
    // were applied only via React state afterwards, React Flow would see
    // the fresh node/edge objects as unselected and immediately emit an
    // onSelectionChange([]) that clobbers the restore.
    const { nodeId, edgeIds } = selectionRef.current
    const resolvedNode = nodeId ? (graph.nodes.find((n) => n.node_id === nodeId) ?? null) : null
    const resolvedEdgeIds = new Set(edgeIds.filter((id) => graph.edges.some((e) => e.edge_id === id)))
    const resolvedEdges = graph.edges.filter((e) => resolvedEdgeIds.has(e.edge_id))

    const { nodes: rawNodes, edges: rawEdges } = buildElements(
      graph,
      highlightUnconfigured,
      resolvedNode?.node_id ?? null,
      resolvedEdgeIds,
      layoutDirection,
    )
    const laidOutNodes = layoutWithDagre(rawNodes, rawEdges, layoutDirection)
    setNodes(laidOutNodes)
    setEdges(routeEdgeTypes(rawEdges, laidOutNodes, layoutDirection))
    setSelectedNode(resolvedNode)
    setSelectedEdges(resolvedEdges)
    selectionRef.current = { nodeId: resolvedNode?.node_id ?? null, edgeIds: resolvedEdges.map((e) => e.edge_id) }
    if (fittedNetworkIdRef.current !== graph.network_id) {
      fittedNetworkIdRef.current = graph.network_id
      window.setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 50)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph])

  useEffect(() => {
    if (!graph) return
    const { edgeIds } = selectionRef.current
    const { edges: rawEdges } = buildElements(
      graph,
      highlightUnconfigured,
      selectionRef.current.nodeId,
      new Set(edgeIds),
      layoutDirection,
    )
    setEdges(routeEdgeTypes(rawEdges, nodes, layoutDirection))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightUnconfigured])

  const nodeKeyById = useMemo(() => new Map(graph?.nodes.map((n) => [n.node_id, n.node_key]) ?? []), [graph])

  function handleAutoLayout() {
    const laidOutNodes = layoutWithDagre(nodes, edges, layoutDirection)
    setNodes(laidOutNodes)
    setEdges(routeEdgeTypes(edges, laidOutNodes, layoutDirection))
    window.setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 50)
  }

  function handleLayoutDirectionChange(direction: 'TB' | 'LR') {
    setLayoutDirection(direction)
    // Handle positions live on each node's data (see TopologyNode), so the
    // direction change has to be stamped onto every node here too -- just
    // re-running dagre would move the boxes but leave the connectors wired
    // to the old top/bottom (or left/right) anchors.
    const redirected = nodes.map((n) => ({ ...n, data: { ...n.data, direction } }))
    const laidOutNodes = layoutWithDagre(redirected, edges, direction)
    setNodes(laidOutNodes)
    setEdges(routeEdgeTypes(edges, laidOutNodes, direction))
    window.setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 50)
  }

  const handleSelectionChange = useCallback(
    (params: OnSelectionChangeParams) => {
      if (!graph) return
      const nodeIds = new Set(params.nodes.map((n) => n.id))
      const edgeIds = new Set(params.edges.map((e) => e.id))
      const selEdges = graph.edges.filter((e) => edgeIds.has(e.edge_id))
      // A drag box almost always sweeps up the edges' endpoint nodes too. Edge
      // batch-config is the point of that gesture, so let edges win the panel
      // whenever any came along -- only treat this as a node selection when
      // the box (or click) caught no edges at all.
      const node = selEdges.length === 0 ? graph.nodes.find((n) => nodeIds.has(n.node_id)) ?? null : null
      selectionRef.current = { nodeId: node?.node_id ?? null, edgeIds: selEdges.map((e) => e.edge_id) }
      setSelectedNode(node)
      setSelectedEdges(selEdges)
      // A manually collapsed panel has nothing to show; picking something on
      // the canvas is an explicit request to look at it, so it should never
      // stay hidden behind a stale collapse from earlier.
      if (node || selEdges.length > 0) {
        setPanelCollapsed(false)
      }
    },
    [graph],
  )

  async function applySource(nodeId: string) {
    if (!networkId) return
    try {
      await setSource(networkId, nodeId)
      message.success('Source 设置成功，Edge 方向已重新计算')
      await loadGraph()
    } catch (error) {
      message.error(apiErrorMessage(error))
    }
  }

  function handleSetSource(nodeId: string) {
    if (network?.source_node_id && network.source_node_id !== nodeId) {
      Modal.confirm({
        title: '更换 Source 节点',
        content: '当前 Network 已设置 Source，更换后将重新计算所有 Edge 的运行方向，确定继续吗？',
        okText: '确定更换',
        cancelText: '取消',
        onOk: () => applySource(nodeId),
      })
    } else {
      applySource(nodeId)
    }
  }

  function openMonitorModal(editing?: Monitor) {
    setEditingMonitor(editing)
    setMonitorModalOpen(true)
  }

  async function handleDeleteMonitor(monitor: Monitor) {
    try {
      await deleteMonitor(monitor.monitor_id)
      message.success('监测点已删除')
      loadGraph()
    } catch (error) {
      message.error(apiErrorMessage(error))
    }
  }

  async function handleValidate() {
    if (!networkId) return
    try {
      const summary = await getValidation(networkId)
      setValidation(summary)
      setValidationOpen(true)
    } catch (error) {
      message.error(apiErrorMessage(error))
    }
  }

  const loadEdgeTable = useCallback(async () => {
    if (!networkId) return
    setEdgeTableLoading(true)
    try {
      setEdgeTableRows(await getEdgesTable(networkId))
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setEdgeTableLoading(false)
    }
  }, [networkId])

  useEffect(() => {
    if (viewMode === 'table') loadEdgeTable()
  }, [viewMode, loadEdgeTable])

  function openConfigModal(edgeIds: string[], initialEdge?: EdgeConfigInitial) {
    setConfigEdgeIds(edgeIds)
    setConfigInitialEdge(initialEdge)
    setConfigModalOpen(true)
  }

  function handleConfigSaved() {
    loadGraph()
    if (viewMode === 'table') loadEdgeTable()
    setTableSelectedIds([])
  }

  // Keystroke-level drafts for the table view's inline length editor, kept in
  // a ref (not state) so typing doesn't re-render the whole table -- only the
  // committed value on blur/Enter needs to reach edgeTableRows and the server.
  const lengthDraftsRef = useRef<Record<string, number | null>>({})

  function handleInlineLengthCommit(record: EdgeTableRow) {
    const draft = lengthDraftsRef.current[record.edge_id]
    if (draft === undefined || draft === record.length_km) return
    updateEdgeConfig(record.edge_id, { line_model_id: record.line_model_id, length_km: draft })
      .then(() => {
        setEdgeTableRows((rows) =>
          rows.map((r) =>
            r.edge_id === record.edge_id ? { ...r, length_km: draft, configured: !!r.line_model_id && !!draft } : r,
          ),
        )
        // The canvas view reads from `graph`, a separate fetch from the edge
        // table -- without this, a length typed here would only ever show up
        // after some other action happened to reload the graph.
        loadGraph()
      })
      .catch((error) => message.error(apiErrorMessage(error)))
  }

  const filteredTableRows = edgeTableRows.filter((row) => {
    if (!tableSearch) return true
    const haystack = `${row.edge_key ?? ''} ${row.edge_id} ${row.node_a_key} ${row.node_b_key}`.toLowerCase()
    return haystack.includes(tableSearch.toLowerCase())
  })

  const edgeTableColumns: ColumnsType<EdgeTableRow> = [
    { title: 'Edge', dataIndex: 'edge_key', render: (v, r) => v ?? r.edge_id, sorter: (a, b) => (a.edge_key ?? a.edge_id).localeCompare(b.edge_key ?? b.edge_id) },
    { title: 'From', dataIndex: 'node_a_key' },
    { title: 'To', dataIndex: 'node_b_key' },
    {
      title: '类型',
      dataIndex: 'line_type',
      filters: [
        { text: '架空导线', value: 'overhead' },
        { text: '电缆', value: 'cable' },
        { text: '未配置', value: '__none__' },
      ],
      onFilter: (value, record) => (value === '__none__' ? !record.line_type : record.line_type === value),
      render: (v: string | null) => (v ? LINE_TYPE_LABELS[v] ?? v : '-'),
    },
    {
      title: '型号',
      dataIndex: 'model_name',
      filters: Array.from(new Set(edgeTableRows.map((r) => r.model_name).filter((v): v is string => !!v))).map((v) => ({
        text: v,
        value: v,
      })),
      onFilter: (value, record) => record.model_name === value,
      render: (v: string | null) => v ?? '-',
    },
    {
      title: '长度 (km)',
      dataIndex: 'length_km',
      sorter: (a, b) => (a.length_km ?? -1) - (b.length_km ?? -1),
      render: (_: number | null, record) => (
        <InputNumber
          size="small"
          min={0}
          step={0.01}
          style={{ width: 110 }}
          placeholder="未配置"
          defaultValue={record.length_km ?? undefined}
          onChange={(v) => {
            lengthDraftsRef.current[record.edge_id] = v
          }}
          onBlur={() => handleInlineLengthCommit(record)}
          onPressEnter={(e) => (e.target as HTMLInputElement).blur()}
        />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      filters: [
        { text: 'closed', value: 'closed' },
        { text: 'open', value: 'open' },
      ],
      onFilter: (value, record) => record.status === value,
      render: (v: string) => <Tag color={v === 'open' ? 'default' : 'green'}>{v}</Tag>,
    },
    {
      title: '配置状态',
      dataIndex: 'configured',
      filters: [
        { text: '已配置', value: true },
        { text: '未配置', value: false },
      ],
      onFilter: (value, record) => record.configured === value,
      render: (v: boolean) => <Tag color={v ? 'green' : 'orange'}>{v ? '已配置' : '未配置'}</Tag>,
    },
    {
      title: '操作',
      render: (_, record) => (
        <Button
          size="small"
          onClick={() =>
            openConfigModal([record.edge_id], {
              line_type: record.line_type,
              line_model_id: record.line_model_id,
              length_km: record.length_km,
            })
          }
        >
          配置
        </Button>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <div
        style={{
          padding: '8px 16px',
          borderBottom: '1px solid #f0f0f0',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <Title
          level={5}
          style={{ margin: 0, flexShrink: 0, whiteSpace: 'nowrap', maxWidth: 240 }}
          ellipsis={{ tooltip: network?.name }}
        >
          {network?.name}
        </Title>
        {network && <Tag style={{ flexShrink: 0 }}>{network.network_id}</Tag>}
        <span style={{ flexShrink: 0 }}>
          {network?.source_node_id ? (
            <Tag color="orange">Source: {nodeKeyById.get(network.source_node_id)}</Tag>
          ) : (
            <Tag color="red">未设置 Source</Tag>
          )}
        </span>
        <div style={{ flex: 1, minWidth: 0 }} />
        <Button onClick={() => setViewMode((v) => (v === 'canvas' ? 'table' : 'canvas'))}>
          {viewMode === 'canvas' ? '表格视图' : '画布视图'}
        </Button>
        {viewMode === 'canvas' && (
          <Segmented
            value={layoutDirection}
            onChange={(value) => handleLayoutDirectionChange(value as 'TB' | 'LR')}
            options={[
              { label: '垂直', value: 'TB' },
              { label: '水平', value: 'LR' },
            ]}
          />
        )}
        {viewMode === 'canvas' && <Button onClick={handleAutoLayout}>自动布局</Button>}
        {viewMode === 'canvas' && (
          <Button
            type={highlightUnconfigured ? 'primary' : 'default'}
            onClick={() => setHighlightUnconfigured((v) => !v)}
          >
            查看未配置 Edge
          </Button>
        )}
        <Button onClick={handleValidate}>校验</Button>
        <Button onClick={() => message.success('拓扑数据已自动保存')}>保存</Button>
      </div>

      <Spin spinning={loading} fullscreen />
      {viewMode === 'table' ? (
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 16 }}>
          <Space style={{ marginBottom: 12 }}>
            <Input.Search
              placeholder="搜索 Node / Edge"
              allowClear
              style={{ width: 240 }}
              value={tableSearch}
              onChange={(e) => setTableSearch(e.target.value)}
            />
            <Button
              type="primary"
              disabled={tableSelectedIds.length === 0}
              onClick={() => openConfigModal(tableSelectedIds)}
            >
              批量配置已选中（{tableSelectedIds.length}）
            </Button>
          </Space>
          <Table
            rowKey="edge_id"
            loading={edgeTableLoading}
            columns={edgeTableColumns}
            dataSource={filteredTableRows}
            pagination={{ pageSize: 50 }}
            rowSelection={{ selectedRowKeys: tableSelectedIds, onChange: (keys) => setTableSelectedIds(keys as string[]) }}
          />
        </div>
      ) : (
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
          <div style={{ flex: 1 }}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onSelectionChange={handleSelectionChange}
              nodeTypes={topologyNodeTypes}
              selectionOnDrag
              panOnDrag={[1, 2]}
              fitView
            >
              <Background />
              <Controls />
            </ReactFlow>
          </div>

          <div
            style={{
              width: panelCollapsed ? 40 : 320,
              flexShrink: 0,
              borderLeft: '1px solid #f0f0f0',
              position: 'relative',
              transition: 'width 0.2s',
              overflow: 'hidden',
            }}
          >
            <Button
              type="text"
              size="small"
              icon={panelCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setPanelCollapsed((v) => !v)}
              style={{ position: 'absolute', top: 8, left: 8, zIndex: 1 }}
            />
            <div
              style={{
                padding: 16,
                paddingTop: 48,
                overflowY: 'auto',
                height: '100%',
                boxSizing: 'border-box',
                width: 320,
                visibility: panelCollapsed ? 'hidden' : 'visible',
              }}
            >
            <Title level={5}>Properties</Title>
            {!selectedNode && selectedEdges.length === 0 && (
              <Empty description="点击节点或线路查看详情，支持 Shift/框选多选 Edge" />
            )}

            {selectedNode && (
              <Card size="small" title={`Node: ${selectedNode.node_key}`}>
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="node_id">{selectedNode.node_id}</Descriptions.Item>
                  <Descriptions.Item label="node_key">{selectedNode.node_key}</Descriptions.Item>
                </Descriptions>
                <Button
                  type="primary"
                  block
                  style={{ marginTop: 12 }}
                  disabled={selectedNode.is_source}
                  onClick={() => handleSetSource(selectedNode.node_id)}
                >
                  {selectedNode.is_source ? '当前电源节点' : '设为电源节点'}
                </Button>

                <div style={{ marginTop: 16 }}>
                  <Text strong>监测点</Text>
                  <List
                    size="small"
                    locale={{ emptyText: '未绑定监测点' }}
                    dataSource={monitors.filter((m) => m.node_id === selectedNode.node_id)}
                    renderItem={(m) => (
                      <List.Item
                        actions={[
                          <a key="edit" onClick={() => openMonitorModal(m)}>
                            编辑
                          </a>,
                          <a key="delete" onClick={() => handleDeleteMonitor(m)}>
                            删除
                          </a>,
                        ]}
                      >
                        <Space direction="vertical" size={0}>
                          <Text>
                            {m.canonical_name} {!m.enabled && <Tag color="default">已停用</Tag>}
                          </Text>
                          {m.aliases.map((alias) => (
                            <Tag key={alias} style={{ marginTop: 4 }}>
                              {alias}
                            </Tag>
                          ))}
                        </Space>
                      </List.Item>
                    )}
                  />
                  <Button block style={{ marginTop: 8 }} onClick={() => openMonitorModal()}>
                    + 添加监测点
                  </Button>
                </div>
              </Card>
            )}

            {!selectedNode && selectedEdges.length === 1 && (
              <Card size="small" title={`Edge: ${selectedEdges[0].edge_id}`}>
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="edge_key">{selectedEdges[0].edge_key ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="连接">
                    {nodeKeyById.get(selectedEdges[0].node_a_id)} ↔ {nodeKeyById.get(selectedEdges[0].node_b_id)}
                  </Descriptions.Item>
                  <Descriptions.Item label="方向">
                    {selectedEdges[0].source_node_id
                      ? `${nodeKeyById.get(selectedEdges[0].source_node_id)} → ${nodeKeyById.get(selectedEdges[0].target_node_id!)}`
                      : '未定向'}
                  </Descriptions.Item>
                  <Descriptions.Item label="状态">
                    <Tag color={selectedEdges[0].status === 'open' ? 'default' : 'green'}>
                      {selectedEdges[0].status}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="线路类型">
                    {selectedEdges[0].line_type ? LINE_TYPE_LABELS[selectedEdges[0].line_type] : '未配置'}
                  </Descriptions.Item>
                  <Descriptions.Item label="线路型号">{selectedEdges[0].model_name ?? '未配置'}</Descriptions.Item>
                  <Descriptions.Item label="长度 (km)">{selectedEdges[0].length_km ?? '未配置'}</Descriptions.Item>
                  <Descriptions.Item label="R / X / C">
                    {selectedEdges[0].r_ohm != null ? (
                      `${selectedEdges[0].r_ohm.toFixed(3)}Ω / ${selectedEdges[0].x_ohm!.toFixed(3)}Ω / ${selectedEdges[0].c_nf!.toFixed(1)}nF`
                    ) : selectedEdges[0].r_ohm_per_km != null ? (
                      <>
                        {`${selectedEdges[0].r_ohm_per_km.toFixed(3)}Ω / ${selectedEdges[0].x_ohm_per_km!.toFixed(3)}Ω / ${selectedEdges[0].c_nf_per_km!.toFixed(1)}nF`}
                        <Text type="secondary" style={{ display: 'block', fontSize: 12 }}>
                          （每 km，缺少长度，暂无法计算该段总参数）
                        </Text>
                      </>
                    ) : (
                      '未配置'
                    )}
                  </Descriptions.Item>
                </Descriptions>
                <Button
                  type="primary"
                  block
                  style={{ marginTop: 12 }}
                  onClick={() => openConfigModal([selectedEdges[0].edge_id], selectedEdges[0])}
                >
                  配置线路型号 / 长度
                </Button>
              </Card>
            )}

            {!selectedNode && selectedEdges.length > 1 && (
              <Card size="small" title={`已选中 ${selectedEdges.length} 条 Edge`}>
                <List
                  size="small"
                  dataSource={selectedEdges}
                  renderItem={(e) => (
                    <List.Item>
                      <Space direction="vertical" size={0}>
                        <Text strong>{e.edge_key ?? e.edge_id}</Text>
                        <Text type="secondary">
                          {nodeKeyById.get(e.node_a_id)} ↔ {nodeKeyById.get(e.node_b_id)}
                        </Text>
                      </Space>
                    </List.Item>
                  )}
                />
                <Button
                  type="primary"
                  block
                  style={{ marginTop: 12 }}
                  onClick={() => openConfigModal(selectedEdges.map((e) => e.edge_id))}
                >
                  批量配置线路型号 / 长度
                </Button>
              </Card>
            )}
            </div>
          </div>
      </div>
      )}

      <EdgeConfigModal
        open={configModalOpen}
        edgeIds={configEdgeIds}
        initialEdge={configInitialEdge}
        onClose={() => setConfigModalOpen(false)}
        onSaved={handleConfigSaved}
      />

      {selectedNode && (
        <MonitorModal
          open={monitorModalOpen}
          networkId={networkId!}
          nodeId={selectedNode.node_id}
          editing={editingMonitor}
          onClose={() => setMonitorModalOpen(false)}
          onSaved={loadGraph}
        />
      )}

      <Drawer title="拓扑校验" open={validationOpen} onClose={() => setValidationOpen(false)} width={400}>
        {validation && (
          <>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="Nodes">{validation.nodes}</Descriptions.Item>
              <Descriptions.Item label="Edges">{validation.edges}</Descriptions.Item>
              <Descriptions.Item label="Components">{validation.components}</Descriptions.Item>
              <Descriptions.Item label="Cycles">{validation.cycles}</Descriptions.Item>
              <Descriptions.Item label="Open edges">{validation.open_edges}</Descriptions.Item>
              <Descriptions.Item label="Source">{validation.source_set ? '已设置' : '未设置'}</Descriptions.Item>
            </Descriptions>
            <List
              style={{ marginTop: 16 }}
              dataSource={validation.warnings}
              renderItem={(issue) => (
                <List.Item>
                  <Alert type="warning" showIcon message={issue.message} style={{ width: '100%' }} />
                </List.Item>
              )}
            />
          </>
        )}
      </Drawer>
    </div>
  )
}
