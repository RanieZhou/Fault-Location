import { useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, Select, Typography } from 'antd'
import { ApartmentOutlined, DatabaseOutlined, ImportOutlined, ToolOutlined } from '@ant-design/icons'
import { listNetworks } from '../api/networks'
import type { NetworkOut } from '../api/types'
import { useCurrentNetwork } from '../state/CurrentNetworkContext'
import { palette } from '../theme'

const { Sider, Content } = Layout
const { Text } = Typography

type MenuKey = 'import' | 'topology' | 'normal-data' | 'line-models'

export function AppLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { networkId, networkName, setCurrentNetwork } = useCurrentNetwork()
  const [networks, setNetworks] = useState<NetworkOut[]>([])

  useEffect(() => {
    listNetworks()
      .then(setNetworks)
      .catch(() => {
        // The network switcher is a convenience; a failed refresh just keeps the previous list.
      })
  }, [networkId])

  const selectedKey: MenuKey | '' = useMemo(() => {
    if (location.pathname === '/') return 'import'
    if (location.pathname === '/line-models') return 'line-models'
    if (location.pathname.includes('/normal-data')) return 'normal-data'
    if (location.pathname === '/topologies' || location.pathname.includes('/topology')) return 'topology'
    return ''
  }, [location.pathname])

  const menuItems = [
    { key: 'import', icon: <ImportOutlined />, label: '网络导入' },
    { key: 'topology', icon: <ApartmentOutlined />, label: '拓扑工作台' },
    { key: 'normal-data', icon: <DatabaseOutlined />, label: '正常数据基线', disabled: !networkId },
    { key: 'line-models', icon: <ToolOutlined />, label: '线路型号管理' },
  ]

  function handleMenuClick(key: string) {
    if (key === 'import') navigate('/')
    else if (key === 'line-models') navigate('/line-models')
    else if (key === 'topology') navigate('/topologies')
    else if (key === 'normal-data' && networkId) navigate(`/networks/${networkId}/normal-data`)
  }

  function handleNetworkSwitch(id: string) {
    const target = networks.find((n) => n.network_id === id)
    if (!target) return
    setCurrentNetwork(target.network_id, target.name)
    navigate(`/networks/${target.network_id}/topology`)
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={224} theme="dark" style={{ background: palette.sidebarBg }}>
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: 15,
            fontWeight: 600,
            letterSpacing: 0.5,
            borderBottom: `1px solid ${palette.sidebarBorder}`,
          }}
        >
          配电网故障定位
        </div>

        <div style={{ padding: '12px 16px', borderBottom: `1px solid ${palette.sidebarBorder}`, marginBottom: 8 }}>
          <Text style={{ color: 'rgba(255,255,255,0.65)', fontSize: 12, display: 'block', marginBottom: 4 }}>
            当前网络
          </Text>
          <Select
            style={{ width: '100%' }}
            size="small"
            placeholder="尚未选择网络"
            value={networkId ?? undefined}
            onChange={handleNetworkSwitch}
            options={networks.map((n) => ({ value: n.network_id, label: n.name }))}
            notFoundContent="暂无网络，请先创建"
          />
          {networkName && (
            <Text style={{ color: 'rgba(255,255,255,0.45)', fontSize: 11, display: 'block', marginTop: 4 }}>
              {networkId}
            </Text>
          )}
        </div>

        <Menu
          theme="dark"
          mode="inline"
          style={{ background: 'transparent', border: 'none' }}
          selectedKeys={selectedKey ? [selectedKey] : []}
          items={menuItems}
          onClick={({ key }) => handleMenuClick(key)}
        />
      </Sider>
      <Content style={{ background: palette.layoutBg, minHeight: '100vh', overflow: 'auto' }}>
        <Outlet />
      </Content>
    </Layout>
  )
}
