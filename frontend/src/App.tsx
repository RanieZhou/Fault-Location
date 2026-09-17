import { Navigate, Route, Routes } from 'react-router-dom'
import { NetworkImport } from './pages/NetworkImport/NetworkImport'
import { TopologyWorkspace } from './pages/TopologyWorkspace/TopologyWorkspace'
import { LineModelManagement } from './pages/LineModelManagement/LineModelManagement'
import { NormalDataCalibration } from './pages/NormalDataCalibration/NormalDataCalibration'

function App() {
  return (
    <Routes>
      <Route path="/" element={<NetworkImport />} />
      <Route path="/networks/:networkId/topology" element={<TopologyWorkspace />} />
      <Route path="/networks/:networkId/normal-data" element={<NormalDataCalibration />} />
      <Route path="/line-models" element={<LineModelManagement />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
