import { Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import SummaryPage from './pages/SummaryPage'
import PromptsPage from './pages/PromptsPage'
import ChannelsPage from './pages/ChannelsPage'
import BotsPage from './pages/BotsPage'
import SettingsPage from './pages/SettingsPage'
import AdminLoginPage from './pages/AdminLoginPage'
import AdminUsersPage from './pages/AdminUsersPage'
import AdminSettingsPage from './pages/AdminSettingsPage'
import Layout from './components/Layout'

function App() {
  const [token, setToken] = useState(localStorage.getItem('token'))

  useEffect(() => {
    const handler = () => setToken(localStorage.getItem('token'))
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  const login = (t: string) => {
    localStorage.setItem('token', t)
    setToken(t)
  }
  const logout = () => {
    localStorage.removeItem('token')
    setToken(null)
  }

  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={token ? <Navigate to="/" /> : <LoginPage onLogin={login} />} />
      <Route path="/admin/login" element={token ? <Navigate to="/admin/users" /> : <AdminLoginPage onLogin={login} />} />

      {/* Protected user routes */}
      <Route element={token ? <Layout onLogout={logout} /> : <Navigate to="/login" />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/summary" element={<SummaryPage />} />
        <Route path="/prompts" element={<PromptsPage />} />
        <Route path="/channels" element={<ChannelsPage />} />
        <Route path="/bots" element={<BotsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      {/* Protected admin routes */}
      <Route element={token ? <Layout onLogout={logout} isAdmin /> : <Navigate to="/admin/login" />}>
        <Route path="/admin/users" element={<AdminUsersPage />} />
        <Route path="/admin/settings" element={<AdminSettingsPage />} />
      </Route>
    </Routes>
  )
}

export default App
