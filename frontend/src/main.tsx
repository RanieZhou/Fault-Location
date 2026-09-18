import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import './index.css'
import App from './App.tsx'
import { CurrentNetworkProvider } from './state/CurrentNetworkContext'
import { themeConfig } from './theme'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={themeConfig}>
      <BrowserRouter>
        <CurrentNetworkProvider>
          <App />
        </CurrentNetworkProvider>
      </BrowserRouter>
    </ConfigProvider>
  </StrictMode>,
)
