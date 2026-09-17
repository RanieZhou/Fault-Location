import { useEffect, useState } from 'react'
import { Checkbox, InputNumber, Modal, Select, Space, Typography, message } from 'antd'
import { apiErrorMessage } from '../api/client'
import { batchConfigEdges, updateEdgeConfig } from '../api/edges'
import { listLineModels, type LineModel } from '../api/lineModels'

const { Text } = Typography

const LINE_TYPE_OPTIONS = [
  { label: '架空导线', value: 'overhead' },
  { label: '电缆', value: 'cable' },
]

// Structural shape shared by GraphEdge and EdgeTableRow -- either can prefill the form.
export interface EdgeConfigInitial {
  line_type: string | null
  line_model_id: string | null
  length_km: number | null
}

interface Props {
  open: boolean
  edgeIds: string[]
  initialEdge?: EdgeConfigInitial
  onClose: () => void
  onSaved: () => void
}

export function EdgeConfigModal({ open, edgeIds, initialEdge, onClose, onSaved }: Props) {
  const [lineModels, setLineModels] = useState<LineModel[]>([])
  const [lineType, setLineType] = useState<string | undefined>(undefined)
  const [lineModelId, setLineModelId] = useState<string | undefined>(undefined)
  const [length, setLength] = useState<number | undefined>(undefined)
  const [applyLength, setApplyLength] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  const isBatch = edgeIds.length > 1

  useEffect(() => {
    if (!open) return
    listLineModels()
      .then(setLineModels)
      .catch((error) => message.error(apiErrorMessage(error)))
    setLineType(initialEdge?.line_type ?? undefined)
    setLineModelId(initialEdge?.line_model_id ?? undefined)
    setLength(initialEdge?.length_km ?? undefined)
    setApplyLength(!isBatch)
  }, [open, initialEdge, isBatch])

  const filteredModels = lineModels.filter(
    (m) => (m.enabled || m.line_model_id === initialEdge?.line_model_id) && (!lineType || m.line_type === lineType),
  )

  async function handleOk() {
    if (!lineModelId) {
      message.warning('请选择线路型号')
      return
    }
    setSubmitting(true)
    try {
      if (!isBatch) {
        await updateEdgeConfig(edgeIds[0], { line_model_id: lineModelId, length_km: length ?? null })
      } else {
        await batchConfigEdges({
          edge_ids: edgeIds,
          line_model_id: lineModelId,
          apply_length: applyLength,
          length_km: applyLength ? length ?? null : undefined,
        })
      }
      message.success('配置已保存')
      onSaved()
      onClose()
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={isBatch ? `批量配置 Edge（共 ${edgeIds.length} 条）` : '配置 Edge'}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div>
          <Text>线路类型</Text>
          <Select
            style={{ width: '100%' }}
            allowClear
            placeholder="全部类型"
            value={lineType}
            onChange={(v) => {
              setLineType(v)
              setLineModelId(undefined)
            }}
            options={LINE_TYPE_OPTIONS}
          />
        </div>
        <div>
          <Text>线路型号</Text>
          <Select
            style={{ width: '100%' }}
            placeholder="请选择型号"
            value={lineModelId}
            onChange={setLineModelId}
            options={filteredModels.map((m) => ({
              label: `${m.model_name}（R${m.r_ohm_per_km}/X${m.x_ohm_per_km}/C${m.c_nf_per_km} 每km）`,
              value: m.line_model_id,
            }))}
          />
        </div>
        {isBatch && (
          <Checkbox checked={applyLength} onChange={(e) => setApplyLength(e.target.checked)}>
            批量设置相同长度（默认不覆盖已有长度）
          </Checkbox>
        )}
        {(!isBatch || applyLength) && (
          <div>
            <Text>长度 (km)</Text>
            <InputNumber
              style={{ width: '100%' }}
              min={0}
              step={0.01}
              value={length}
              onChange={(v) => setLength(v ?? undefined)}
            />
          </div>
        )}
      </Space>
    </Modal>
  )
}
