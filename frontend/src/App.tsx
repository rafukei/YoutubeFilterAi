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
import LogsPage from './pages/LogsPage'

function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'))
  const [tokenPayload, setTokenPayload] = useState<any | null>(null)

  // Decode JWT payload (very small helper - no verification) so routes can check is_admin
  const decodePayload = (t?: string | null) => {
    if (!t) return null
    try {
      const parts = t.split('.')
      if (parts.length < 2) return null
      const b = parts[1].replace(/-/g, '+').replace(/_/g, '/')
      const json = decodeURIComponent(atob(b).split('').map(function(c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
      }).join(''))
      return JSON.parse(json)
    } catch {
      return null
    }
  }

  useEffect(() => {
    const handler = () => {
      const t = localStorage.getItem('token')
      setToken(t)
      setTokenPayload(decodePayload(t))
    }
    handler()
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  const login = (t: string) => {
    localStorage.setItem('token', t)
    setToken(t)
    setTokenPayload(decodePayload(t))
  }
  const logout = () => {
    localStorage.removeItem('token')
    setToken(null)
    setTokenPayload(null)
  }

  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={token ? <Navigate to="/" /> : <LoginPage onLogin={login} />} />
      {/* Only redirect to admin area if token exists AND claims include is_admin */}
      <Route
        path="/admin/login"
        element={token && tokenPayload?.is_admin ? <Navigate to="/admin/users" /> : <AdminLoginPage onLogin={login} />}
      />

      {/* Protected user routes */}
      <Route element={token ? <Layout onLogout={logout} /> : <Navigate to="/login" />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/summary" element={<SummaryPage />} />
        <Route path="/prompts" element={<PromptsPage />} />
        <Route path="/channels" element={<ChannelsPage />} />
        <Route path="/bots" element={<BotsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/logs" element={<LogsPage />} />
      </Route>

      {/* Protected admin routes */}
      <Route element={token && tokenPayload?.is_admin ? <Layout onLogout={logout} isAdmin /> : <Navigate to="/admin/login" />}>
        <Route path="/admin/users" element={<AdminUsersPage />} />
        <Route path="/admin/settings" element={<AdminSettingsPage />} />
      </Route>
    </Routes>
  )
}

export default App
