import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Input,
  List,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import { CheckCircleFilled, CloseCircleFilled, InboxOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd/es/upload/interface'
import { apiErrorMessage } from '../../api/client'
import { buildBaseline, getBaseline, getReadiness, type BaselineStatOut, type NetworkReadiness } from '../../api/baseline'
import {
  getFieldMapping,
  importMeasurements,
  listUnmatchedNames,
  resolveUnmatched,
  setFieldMapping,
  type MeasurementImportResult,
  type UnmatchedNameRow,
} from '../../api/measurements'
import { listMonitors, type Monitor } from '../../api/monitors'
import { getNetwork } from '../../api/networks'
import type { NetworkOut } from '../../api/types'

const { Dragger } = Upload
const { Title, Paragraph, Text } = Typography

const FIELD_LABELS: Record<string, string> = {
  monitor_name: '监测点名称',
  device_type: '设备类型',
  terminal_status: '终端状态',
  line_status: '线路状态',
  warning_status: '预警状态',
  Va: 'A相电压',
  Vb: 'B相电压',
  Vc: 'C相电压',
  Ia: 'A相电流',
  Ib: 'B相电流',
  Ic: 'C相电流',
  phase_Va: 'A相电压相位',
  phase_Vb: 'B相电压相位',
  phase_Vc: 'C相电压相位',
  phase_Ia: 'A相电流相位',
  phase_Ib: 'B相电流相位',
  phase_Ic: 'C相电流相位',
  timestamp: '量测时间',
}

export function NormalDataCalibration() {
  const { networkId } = useParams<{ networkId: string }>()
  const navigate = useNavigate()

  const [network, setNetwork] = useState<NetworkOut | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [mappingSaving, setMappingSaving] = useState(false)

  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [sheetName, setSheetName] = useState('')
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<MeasurementImportResult | null>(null)

  const [unmatched, setUnmatched] = useState<UnmatchedNameRow[]>([])
  const [monitors, setMonitors] = useState<Monitor[]>([])
  const [resolveSelection, setResolveSelection] = useState<Record<string, string>>({})

  const [baseline, setBaseline] = useState<BaselineStatOut[]>([])
  const [buildingBaseline, setBuildingBaseline] = useState(false)
  const [readiness, setReadiness] = useState<NetworkReadiness | null>(null)

  async function loadAll() {
    if (!networkId) return
    try {
      const [net, m, u, mons, b, r] = await Promise.all([
        getNetwork(networkId),
        getFieldMapping(networkId),
        listUnmatchedNames(networkId),
        listMonitors(networkId),
        getBaseline(networkId),
        getReadiness(networkId),
      ])
      setNetwork(net)
      setMapping(m.mapping)
      setUnmatched(u)
      setMonitors(mons)
      setBaseline(b)
      setReadiness(r)
    } catch (error) {
      message.error(apiErrorMessage(error))
    }
  }

  async function handleBuildBaseline() {
    if (!networkId) return
    setBuildingBaseline(true)
    try {
      const result = await buildBaseline(networkId)
      message.success(`Baseline 已生成：${result.monitors_with_baseline} 个监测点，共 ${result.baseline_rows} 条统计`)
      loadAll()
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setBuildingBaseline(false)
    }
  }

  useEffect(() => {
    loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [networkId])

  async function handleSaveMapping() {
    if (!networkId) return
    setMappingSaving(true)
    try {
      const result = await setFieldMapping(networkId, mapping)
      setMapping(result.mapping)
      message.success('字段映射已保存')
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setMappingSaving(false)
    }
  }

  async function handleImport() {
    if (!networkId || fileList.length === 0 || !fileList[0].originFileObj) {
      message.warning('请先选择要导入的 Excel 文件')
      return
    }
    setImporting(true)
    try {
      const result = await importMeasurements(networkId, fileList[0].originFileObj, sheetName || undefined)
      setImportResult(result)
      message.success('历史数据导入完成')
      loadAll()
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setImporting(false)
    }
  }

  async function handleBind(rawName: string) {
    if (!networkId) return
    const monitorId = resolveSelection[rawName]
    if (!monitorId) {
      message.warning('请先选择要绑定的监测点')
      return
    }
    try {
      await resolveUnmatched(networkId, { monitor_name_raw: rawName, monitor_id: monitorId })
      message.success('已绑定为别名并更新历史记录')
      loadAll()
    } catch (error) {
      message.error(apiErrorMessage(error))
    }
  }

  async function handleIgnore(rawName: string) {
    if (!networkId) return
    try {
      await resolveUnmatched(networkId, { monitor_name_raw: rawName, ignore: true })
      message.success('已忽略')
      loadAll()
    } catch (error) {
      message.error(apiErrorMessage(error))
    }
  }

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '24px 16px' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button onClick={() => navigate(`/networks/${networkId}/topology`)}>← 返回拓扑工作台</Button>
        <Title level={3} style={{ margin: 0 }}>
          正常数据校准 {network && <Tag>{network.network_id}</Tag>}
        </Title>
      </Space>

      <Card title="1. 字段映射配置" style={{ marginBottom: 16 }}>
        <Paragraph type="secondary">将当前生产 Excel 的列名映射到标准字段，而非写死在代码中。</Paragraph>
        <Space direction="vertical" style={{ width: '100%' }}>
          {Object.keys(FIELD_LABELS).map((field) => (
            <Space key={field} style={{ width: '100%' }}>
              <Text style={{ width: 100, display: 'inline-block' }}>{FIELD_LABELS[field]}</Text>
              <Input
                style={{ width: 260 }}
                value={mapping[field] ?? ''}
                onChange={(e) => setMapping((prev) => ({ ...prev, [field]: e.target.value }))}
              />
            </Space>
          ))}
        </Space>
        <Button type="primary" style={{ marginTop: 12 }} loading={mappingSaving} onClick={handleSaveMapping}>
          保存映射
        </Button>
      </Card>

      <Card title="2. 上传历史正常数据" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Dragger
            multiple={false}
            maxCount={1}
            accept=".xlsx"
            fileList={fileList}
            beforeUpload={() => false}
            onChange={({ fileList: newList }) => setFileList(newList.slice(-1))}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p>点击或拖拽历史生产 Excel 文件到此处</p>
          </Dragger>
          <Space>
            <Text>工作表名称（留空使用第一个工作表）：</Text>
            <Input style={{ width: 200 }} value={sheetName} onChange={(e) => setSheetName(e.target.value)} />
            <Button type="primary" onClick={handleImport} loading={importing}>
              导入
            </Button>
          </Space>
        </Space>

        {importResult && (
          <Descriptions bordered size="small" column={3} style={{ marginTop: 16 }}>
            <Descriptions.Item label="总行数">{importResult.total_rows}</Descriptions.Item>
            <Descriptions.Item label="已匹配">{importResult.matched}</Descriptions.Item>
            <Descriptions.Item label="未匹配">{importResult.unmatched}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>

      <Card title="3. 未匹配监测点人工确认">
        {unmatched.length === 0 ? (
          <Alert type="success" showIcon message="当前没有待处理的未匹配监测点名称" />
        ) : (
          <Table
            rowKey="monitor_name_raw"
            dataSource={unmatched}
            pagination={false}
            columns={[
              { title: '原始监测点名称', dataIndex: 'monitor_name_raw' },
              { title: '出现次数', dataIndex: 'count' },
              {
                title: '绑定到监测点',
                render: (_, row) => (
                  <Select
                    style={{ width: 240 }}
                    placeholder="选择已有监测点"
                    value={resolveSelection[row.monitor_name_raw]}
                    onChange={(v) => setResolveSelection((prev) => ({ ...prev, [row.monitor_name_raw]: v }))}
                    options={monitors.map((m) => ({ label: m.canonical_name, value: m.monitor_id }))}
                  />
                ),
              },
              {
                title: '操作',
                render: (_, row) => (
                  <Space>
                    <Button size="small" type="primary" onClick={() => handleBind(row.monitor_name_raw)}>
                      绑定为别名
                    </Button>
                    <Button size="small" onClick={() => handleIgnore(row.monitor_name_raw)}>
                      忽略
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Card
        title="4. 正常运行 Baseline"
        style={{ marginTop: 16 }}
        extra={
          <Button type="primary" loading={buildingBaseline} onClick={handleBuildBaseline}>
            生成 Baseline
          </Button>
        }
      >
        <Paragraph type="secondary">
          筛选条件：设备类型=配电线路 且 终端/线路/预警状态=正常，再计算每个监测点、每个信号的 count/mean/std/median。
        </Paragraph>
        {baseline.length === 0 ? (
          <Alert type="info" showIcon message="尚未生成 Baseline" />
        ) : (
          <Table
            rowKey={(r) => `${r.monitor_id}-${r.signal}`}
            size="small"
            dataSource={baseline}
            pagination={{ pageSize: 12 }}
            columns={[
              { title: '监测点', dataIndex: 'canonical_name' },
              { title: '信号', dataIndex: 'signal' },
              { title: 'Count', dataIndex: 'count' },
              { title: 'Mean', dataIndex: 'mean', render: (v: number | null) => v?.toFixed(3) ?? '-' },
              { title: 'Std', dataIndex: 'std', render: (v: number | null) => v?.toFixed(3) ?? '-' },
              { title: 'Median', dataIndex: 'median', render: (v: number | null) => v?.toFixed(3) ?? '-' },
            ]}
          />
        )}
      </Card>

      <Card title="5. Initialization 检查清单" style={{ marginTop: 16 }}>
        {readiness && (
          <>
            <Alert
              style={{ marginBottom: 16 }}
              type={readiness.ready ? 'success' : 'warning'}
              showIcon
              message={readiness.ready ? 'NETWORK READY' : '尚未满足 NETWORK_READY 条件'}
            />
            <List
              dataSource={readiness.items}
              renderItem={(item) => (
                <List.Item>
                  <Space>
                    {item.passed ? (
                      <CheckCircleFilled style={{ color: '#52c41a' }} />
                    ) : (
                      <CloseCircleFilled style={{ color: '#ff4d4f' }} />
                    )}
                    <Text>{item.label}</Text>
                    {item.detail && <Text type="secondary">（{item.detail}）</Text>}
                  </Space>
                </List.Item>
              )}
            />
          </>
        )}
      </Card>
    </div>
  )
}
