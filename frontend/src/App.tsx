import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ExperimentsPage } from './pages/ExperimentsPage'
import { ExperimentDetailPage } from './pages/ExperimentDetailPage'
import { CreateExperimentPage } from './pages/CreateExperimentPage'
import { PricingPage } from './pages/PricingPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/experiments" replace />} />
          <Route path="experiments" element={<ExperimentsPage />} />
          <Route path="experiments/new" element={<CreateExperimentPage />} />
          <Route path="experiments/:name" element={<ExperimentDetailPage />} />
          <Route path="pricing" element={<PricingPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
