import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  List,
  Space,
  Steps,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd/es/upload/interface'
import { createNetwork, importMapping } from '../../api/networks'
import { apiErrorMessage } from '../../api/client'
import type { MappingImportResult, NetworkOut } from '../../api/types'
import { useCurrentNetwork } from '../../state/CurrentNetworkContext'

const { Dragger } = Upload
const { Title, Paragraph, Text } = Typography

export function NetworkImport() {
  const navigate = useNavigate()
  const { setCurrentNetwork } = useCurrentNetwork()
  const [network, setNetwork] = useState<NetworkOut | null>(null)
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [sheetName, setSheetName] = useState('Edges')
  const [result, setResult] = useState<MappingImportResult | null>(null)

  async function handleCreateNetwork(values: { name: string; voltage_kv?: number; frequency_hz?: number }) {
    setCreating(true)
    try {
      const created = await createNetwork(values)
      setNetwork(created)
      setCurrentNetwork(created.network_id, created.name)
      message.success(`Network 已创建：${created.network_id}`)
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setCreating(false)
    }
  }

  async function handleImport() {
    if (!network || fileList.length === 0 || !fileList[0].originFileObj) {
      message.warning('请先选择要导入的 Excel 文件')
      return
    }
    setImporting(true)
    setResult(null)
    try {
      const importResult = await importMapping(network.network_id, fileList[0].originFileObj, sheetName)
      setResult(importResult)
      if (importResult.imported) {
        message.success('拓扑映射表导入成功')
      } else {
        message.error('导入未通过校验，请查看下方错误信息')
      }
    } catch (error) {
      message.error(apiErrorMessage(error))
    } finally {
      setImporting(false)
    }
  }

  const currentStep = !network ? 0 : !result?.imported ? 1 : 2

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '24px 16px' }}>
      <Title level={3}>网络初始化 · 拓扑映射导入</Title>
      <Steps
        current={currentStep}
        items={[{ title: '创建 Network' }, { title: '上传拓扑映射表' }, { title: '进入拓扑工作台' }]}
        style={{ marginBottom: 24 }}
      />

      {!network && (
        <Card title="1. 创建 Network">
          <Form layout="vertical" onFinish={handleCreateNetwork} initialValues={{ frequency_hz: 50 }}>
            <Form.Item label="Network 名称" name="name" rules={[{ required: true, message: '请输入名称' }]}>
              <Input placeholder="例如：火龙线 10kV 配电网" />
            </Form.Item>
            <Form.Item label="额定电压 (kV)" name="voltage_kv">
              <InputNumber style={{ width: '100%' }} min={0} placeholder="可选" />
            </Form.Item>
            <Form.Item label="额定频率 (Hz)" name="frequency_hz">
              <InputNumber style={{ width: '100%' }} min={0} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={creating}>
              创建
            </Button>
          </Form>
        </Card>
      )}

      {network && (
        <Card
          title="2. 上传拓扑映射表 (Topology_Mapping.xlsx)"
          extra={<Tag color="blue">{network.network_id}</Tag>}
          style={{ marginTop: 16 }}
        >
          <Paragraph type="secondary">
            映射表只描述连接关系（node_1 / node_2 / status / edge_key），不要填写线路长度、型号或监测点。
            可下载{' '}
            <a href="/templates/Topology_Mapping_Template.xlsx" download>
              标准模板
            </a>
            。
          </Paragraph>
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
              <p>点击或拖拽 .xlsx 文件到此处</p>
            </Dragger>
            <Space>
              <Text>工作表名称：</Text>
              <Input
                style={{ width: 200 }}
                value={sheetName}
                onChange={(e) => setSheetName(e.target.value)}
                placeholder="Edges"
              />
              <Button type="primary" onClick={handleImport} loading={importing}>
                导入
              </Button>
            </Space>
          </Space>

          {result && (
            <div style={{ marginTop: 24 }}>
              <Descriptions
                bordered
                size="small"
                column={3}
                title={result.imported ? 'Mapping imported' : 'Mapping import failed'}
              >
                <Descriptions.Item label="Nodes">{result.nodes}</Descriptions.Item>
                <Descriptions.Item label="Edges">{result.edges}</Descriptions.Item>
                <Descriptions.Item label="Components">{result.components}</Descriptions.Item>
                <Descriptions.Item label="Cycles">{result.cycles}</Descriptions.Item>
                <Descriptions.Item label="Open edges">{result.open_edges}</Descriptions.Item>
                <Descriptions.Item label="Errors">{result.errors.length}</Descriptions.Item>
              </Descriptions>

              {result.errors.length > 0 && (
                <List
                  header={<Text strong>Errors（已阻止导入）</Text>}
                  dataSource={result.errors}
                  style={{ marginTop: 12 }}
                  renderItem={(issue) => (
                    <List.Item>
                      <Alert
                        type="error"
                        showIcon
                        message={issue.message}
                        description={issue.rows ? `行号：${issue.rows.join(', ')}` : undefined}
                        style={{ width: '100%' }}
                      />
                    </List.Item>
                  )}
                />
              )}

              {result.warnings.length > 0 && (
                <List
                  header={<Text strong>Warnings</Text>}
                  dataSource={result.warnings}
                  style={{ marginTop: 12 }}
                  renderItem={(issue) => (
                    <List.Item>
                      <Alert
                        type="warning"
                        showIcon
                        message={issue.message}
                        description={issue.rows ? `行号：${issue.rows.join(', ')}` : undefined}
                        style={{ width: '100%' }}
                      />
                    </List.Item>
                  )}
                />
              )}

              {result.imported && (
                <Button
                  type="primary"
                  style={{ marginTop: 16 }}
                  onClick={() => navigate(`/networks/${network.network_id}/topology`)}
                >
                  进入拓扑工作台
                </Button>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
