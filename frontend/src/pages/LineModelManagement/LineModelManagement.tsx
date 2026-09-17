import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { apiErrorMessage } from '../../api/client'
import {
  createLineModel,
  deleteLineModel,
  listLineModels,
  updateLineModel,
  type LineModel,
} from '../../api/lineModels'

const { Title } = Typography

const LINE_TYPE_LABELS: Record<string, string> = {
  overhead: '架空导线',
  cable: '电缆',
}

interface FormValues {
  line_type: string
  model_name: string
  r_ohm_per_km: number
  x_ohm_per_km: number
  c_nf_per_km: number
  remark?: string
}

export function LineModelManagement() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const returnTo = searchParams.get('returnTo')

  const [lineModels, setLineModels] = useState<LineModel[]>([])
  const [loading, setLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState<string | undefined>(undefined)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<LineModel | null>(null)
  const [form] = Form.useForm<FormValues>()

  async function load() {
    setLoading(true)
    try {
      const data = await listLineModels(typeFilter ? { line_type: typeFilter } : undefined)
      setLineModels(data)
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter])

  function openCreate() {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ line_type: 'overhead' })
    setModalOpen(true)
  }

  function openEdit(record: LineModel) {
    setEditing(record)
    form.setFieldsValue({ ...record, remark: record.remark ?? undefined })
    setModalOpen(true)
  }

  async function handleSubmit() {
    try {
      const values = await form.validateFields()
      if (editing) {
        await updateLineModel(editing.line_model_id, values)
        message.success('线路型号已更新')
      } else {
        await createLineModel(values)
        message.success('线路型号已创建')
      }
      setModalOpen(false)
      load()
    } catch (error) {
      if (error && typeof error === 'object' && 'errorFields' in error) return
      message.error(apiErrorMessage(error))
    }
  }

  async function handleToggleEnabled(record: LineModel, enabled: boolean) {
    try {
      await updateLineModel(record.line_model_id, { enabled })
      message.success(enabled ? '已启用' : '已停用')
      load()
    } catch (error) {
      message.error(apiErrorMessage(error))
    }
  }

  async function handleDelete(record: LineModel) {
    try {
      await deleteLineModel(record.line_model_id)
      message.success('已删除')
      load()
    } catch (error) {
      message.error(apiErrorMessage(error))
    }
  }

  const columns: ColumnsType<LineModel> = [
    { title: 'ID', dataIndex: 'line_model_id', width: 100 },
    {
      title: '类型',
      dataIndex: 'line_type',
      filters: [
        { text: '架空导线', value: 'overhead' },
        { text: '电缆', value: 'cable' },
      ],
      onFilter: (value, record) => record.line_type === value,
      render: (value: string) => <Tag>{LINE_TYPE_LABELS[value] ?? value}</Tag>,
    },
    { title: '型号名称', dataIndex: 'model_name', sorter: (a, b) => a.model_name.localeCompare(b.model_name) },
    { title: 'R (Ω/km)', dataIndex: 'r_ohm_per_km' },
    { title: 'X (Ω/km)', dataIndex: 'x_ohm_per_km' },
    { title: 'C (nF/km)', dataIndex: 'c_nf_per_km' },
    {
      title: '来源',
      dataIndex: 'source',
      render: (value: string) => <Tag color={value === 'preset' ? 'blue' : 'default'}>{value}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      render: (enabled: boolean, record) => (
        <Switch checked={enabled} onChange={(v) => handleToggleEnabled(record, v)} />
      ),
    },
    { title: '备注', dataIndex: 'remark' },
    {
      title: '操作',
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除该型号？已被引用则无法删除" onConfirm={() => handleDelete(record)}>
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }}>
        {returnTo && <Button onClick={() => navigate(returnTo)}>← 返回拓扑工作台</Button>}
        <Title level={3} style={{ margin: 0 }}>
          线路型号管理
        </Title>
      </Space>

      <Space style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="按类型筛选"
          style={{ width: 160 }}
          value={typeFilter}
          onChange={setTypeFilter}
          options={[
            { label: '架空导线', value: 'overhead' },
            { label: '电缆', value: 'cable' },
          ]}
        />
        <Button type="primary" onClick={openCreate}>
          新增型号
        </Button>
      </Space>

      <Table
        rowKey="line_model_id"
        columns={columns}
        dataSource={lineModels}
        loading={loading}
        pagination={{ pageSize: 20 }}
      />

      <Modal
        title={editing ? '编辑线路型号' : '新增线路型号'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSubmit}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item label="线路类型" name="line_type" rules={[{ required: true }]}>
            <Select disabled={!!editing} options={[{ label: '架空导线', value: 'overhead' }, { label: '电缆', value: 'cable' }]} />
          </Form.Item>
          <Form.Item label="型号名称" name="model_name" rules={[{ required: true, message: '请输入型号名称' }]}>
            <Input placeholder="例如：JKLYJ-120" />
          </Form.Item>
          <Form.Item label="R (Ω/km)" name="r_ohm_per_km" rules={[{ required: true, message: '请输入 R' }]}>
            <InputNumber style={{ width: '100%' }} min={0} step={0.001} />
          </Form.Item>
          <Form.Item label="X (Ω/km)" name="x_ohm_per_km" rules={[{ required: true, message: '请输入 X' }]}>
            <InputNumber style={{ width: '100%' }} min={0} step={0.001} />
          </Form.Item>
          <Form.Item label="C (nF/km)" name="c_nf_per_km" rules={[{ required: true, message: '请输入 C' }]}>
            <InputNumber style={{ width: '100%' }} min={0} step={0.001} />
          </Form.Item>
          <Form.Item label="备注" name="remark">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
