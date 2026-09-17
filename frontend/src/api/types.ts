export interface NetworkOut {
  network_id: string
  name: string
  voltage_kv: number | null
  frequency_hz: number
  source_node_id: string | null
  status: string
}

export interface ValidationIssue {
  level: 'ERROR' | 'WARNING' | 'INFO'
  code: string
  message: string
  rows?: number[] | null
}

export interface MappingImportResult {
  imported: boolean
  network_id: string
  nodes: number
  edges: number
  components: number
  cycles: number
  open_edges: number
  errors: ValidationIssue[]
  warnings: ValidationIssue[]
}

export interface GraphNode {
  node_id: string
  node_key: string
  label: string | null
  is_source: boolean
  has_monitor: boolean
}

export interface GraphEdge {
  edge_id: string
  edge_key: string | null
  node_a_id: string
  node_b_id: string
  source_node_id: string | null
  target_node_id: string | null
  status: 'closed' | 'open'
  line_model_id: string | null
  length_km: number | null
  line_type: string | null
  model_name: string | null
  r_ohm: number | null
  x_ohm: number | null
  c_nf: number | null
}

export interface NetworkGraph {
  network_id: string
  source_node_id: string | null
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface TopologyValidationSummary {
  network_id: string
  nodes: number
  edges: number
  components: number
  cycles: number
  open_edges: number
  source_set: boolean
  warnings: ValidationIssue[]
}
