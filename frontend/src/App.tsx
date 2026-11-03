import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import AnalysisPage from './pages/AnalysisPage'
import CallbackPage from './pages/CallbackPage'
import ComparePage from './pages/ComparePage'
import CostsPage from './pages/CostsPage'
import LeaderboardPage from './pages/LeaderboardPage'
import LoginPage from './pages/LoginPage'
import ModelDetailPage from './pages/ModelDetailPage'
import TasksPage from './pages/TasksPage'
import { useAuthStore } from './stores/auth'

/** 路由守卫：未登录访问任意页跳 /login，并记录目标页供登录后回跳 */
function RequireAuth() {
  const isAuthed = useAuthStore((s) => s.isAuthed)
  const location = useLocation()
  if (!isAuthed()) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }
  return <Layout />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/callback" element={<CallbackPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Navigate to="/analysis" replace />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="/leaderboard" element={<LeaderboardPage />} />
        <Route path="/models/:modelId" element={<ModelDetailPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/costs" element={<CostsPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="*" element={<Navigate to="/analysis" replace />} />
      </Route>
    </Routes>
  )
}
