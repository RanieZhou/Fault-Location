import { useEffect, useState } from 'react'
import { Input, Modal, Select, Space, Switch, Typography, message } from 'antd'
import { apiErrorMessage } from '../api/client'
import { createMonitor, updateMonitor, type Monitor } from '../api/monitors'

const { Text } = Typography

interface Props {
  open: boolean
  networkId: string
  nodeId: string
  editing?: Monitor
  onClose: () => void
  onSaved: () => void
}

export function MonitorModal({ open, networkId, nodeId, editing, onClose, onSaved }: Props) {
  const [canonicalName, setCanonicalName] = useState('')
  const [aliases, setAliases] = useState<string[]>([])
  const [enabled, setEnabled] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setCanonicalName(editing?.canonical_name ?? '')
    setAliases(editing?.aliases ?? [])
    setEnabled(editing?.enabled ?? true)
  }, [open, editing])

  async function handleOk() {
    if (!canonicalName.trim()) {
      message.warning('请输入监测点标准名称')
      return
    }
    setSubmitting(true)
    try {
      if (editing) {
        await updateMonitor(editing.monitor_id, { canonical_name: canonicalName.trim(), aliases, enabled })
      } else {
        await createMonitor(networkId, { node_id: nodeId, canonical_name: canonicalName.trim(), aliases })
      }
      message.success('监测点已保存')
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
      title={editing ? '编辑监测点' : '添加监测点'}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div>
          <Text>监测点标准名称</Text>
          <Input
            value={canonicalName}
            onChange={(e) => setCanonicalName(e.target.value)}
            placeholder="例如：10kV火龙线#67.7支"
          />
        </div>
        <div>
          <Text>Aliases（历史生产数据中出现的其他写法）</Text>
          <Select
            mode="tags"
            style={{ width: '100%' }}
            value={aliases}
            onChange={setAliases}
            open={false}
            placeholder="输入后回车添加，如：火龙线#67.7支"
          />
        </div>
        {editing && (
          <Space>
            <Text>启用</Text>
            <Switch checked={enabled} onChange={setEnabled} />
          </Space>
        )}
      </Space>
    </Modal>
  )
}
