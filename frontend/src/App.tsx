import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import { NetworkImport } from './pages/NetworkImport/NetworkImport'
import { TopologyList } from './pages/TopologyList/TopologyList'
import { TopologyWorkspace } from './pages/TopologyWorkspace/TopologyWorkspace'
import { LineModelManagement } from './pages/LineModelManagement/LineModelManagement'
import { NormalDataCalibration } from './pages/NormalDataCalibration/NormalDataCalibration'

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<NetworkImport />} />
        <Route path="/topologies" element={<TopologyList />} />
        <Route path="/networks/:networkId/topology" element={<TopologyWorkspace />} />
        <Route path="/networks/:networkId/normal-data" element={<NormalDataCalibration />} />
        <Route path="/line-models" element={<LineModelManagement />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}

export default App
