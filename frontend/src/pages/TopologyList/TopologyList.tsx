import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Empty, Popconfirm, Space, Table, Tag, Typography, message } from 'antd'
import { DeleteOutlined, EyeOutlined, PlusOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { apiErrorMessage } from '../../api/client'
import { deleteNetwork, listNetworks } from '../../api/networks'
import type { NetworkOut } from '../../api/types'
import { useCurrentNetwork } from '../../state/CurrentNetworkContext'

const { Title, Paragraph } = Typography

const STATUS_LABELS: Record<string, { color: string; text: string }> = {
  DRAFT: { color: 'default', text: '草稿' },
  CONFIGURING: { color: 'processing', text: '配置中' },
  READY: { color: 'success', text: 'READY' },
}

export function TopologyList() {
  const navigate = useNavigate()
  const { networkId: currentNetworkId, setCurrentNetwork, clearCurrentNetwork } = useCurrentNetwork()
  const [networks, setNetworks] = useState<NetworkOut[]>([])
  const [loading, setLoading] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    try {
      setNetworks(await listNetworks())
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  function handleView(network: NetworkOut) {
    setCurrentNetwork(network.network_id, network.name)
    navigate(`/networks/${network.network_id}/topology`)
  }

  async function handleDelete(network: NetworkOut) {
    setDeletingId(network.network_id)
    try {
      await deleteNetwork(network.network_id)
      message.success(`已删除网络「${network.name}」`)
      if (network.network_id === currentNetworkId) clearCurrentNetwork()
      load()
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setDeletingId(null)
    }
  }

  const columns: ColumnsType<NetworkOut> = [
    { title: '名称', dataIndex: 'name', sorter: (a, b) => a.name.localeCompare(b.name) },
    { title: 'ID', dataIndex: 'network_id' },
    {
      title: '额定电压 (kV)',
      dataIndex: 'voltage_kv',
      render: (v: number | null) => v ?? '-',
    },
    {
      title: 'Source',
      dataIndex: 'source_node_id',
      render: (v: string | null) => (v ? <Tag color="orange">已设置</Tag> : <Tag>未设置</Tag>),
    },
    {
      title: '状态',
      dataIndex: 'status',
      filters: Object.entries(STATUS_LABELS).map(([value, { text }]) => ({ text, value })),
      onFilter: (value, record) => record.status === value,
      render: (status: string) => {
        const cfg = STATUS_LABELS[status] ?? { color: 'default', text: status }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: '操作',
      render: (_, record) => (
        <Space>
          <Button size="small" type="primary" icon={<EyeOutlined />} onClick={() => handleView(record)}>
            查看拓扑
          </Button>
          <Popconfirm
            title="删除网络"
            description={`确定删除「${record.name}」吗？拓扑、监测点、历史数据和 Baseline 都会一并删除，且无法恢复。`}
            okText="删除"
            okButtonProps={{ danger: true }}
            cancelText="取消"
            onConfirm={() => handleDelete(record)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} loading={deletingId === record.network_id}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 4 }}>
        <Title level={3} style={{ margin: 0 }}>
          拓扑工作台
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/')}>
          新建网络
        </Button>
      </Space>
      <Paragraph type="secondary">已上传的所有拓扑网络，点击"查看拓扑"进入对应的拓扑工作台。</Paragraph>

      <Table
        rowKey="network_id"
        columns={columns}
        dataSource={networks}
        loading={loading}
        pagination={{ pageSize: 20 }}
        locale={{
          emptyText: (
            <Empty description="还没有任何网络">
              <Button type="primary" onClick={() => navigate('/')}>
                去创建一个
              </Button>
            </Empty>
          ),
        }}
      />
    </div>
  )
}
