import { useEffect, useState } from 'react'
import api from '../api'

interface AppSettings {
  registration_enabled: boolean
  require_approval: boolean
  allow_gmail_auth: boolean
  google_client_id: string | null
  openrouter_rate_limit: number
  channel_request_delay: number
  updated_at: string | null
}

interface AdminStats {
  total_users: number
  active_users: number
  approved_users: number
  pending_approval: number
  total_prompts: number
  total_messages: number
  total_channels: number
  total_bots: number
}

export default function AdminSettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Form state for editable fields
  const [registrationEnabled, setRegistrationEnabled] = useState(true)
  const [requireApproval, setRequireApproval] = useState(true)
  const [allowGmailAuth, setAllowGmailAuth] = useState(false)
  const [googleClientId, setGoogleClientId] = useState('')
  const [googleClientSecret, setGoogleClientSecret] = useState('')
  const [openrouterRateLimit, setOpenrouterRateLimit] = useState(10)
  const [channelRequestDelay, setChannelRequestDelay] = useState(5)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      setLoading(true)
      setError(null)
      
      const [settingsRes, statsRes] = await Promise.all([
        api.get('/admin/settings'),
        api.get('/admin/stats'),
      ])
      
      const s = settingsRes.data as AppSettings
      setSettings(s)
      setRegistrationEnabled(s.registration_enabled)
      setRequireApproval(s.require_approval)
      setAllowGmailAuth(s.allow_gmail_auth)
      setOpenrouterRateLimit(s.openrouter_rate_limit)
      setChannelRequestDelay(s.channel_request_delay)
      
      setStats(statsRes.data as AdminStats)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load settings')
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    try {
      setSaving(true)
      setError(null)
      setSuccess(null)
      
      const payload: any = {
        registration_enabled: registrationEnabled,
        require_approval: requireApproval,
        allow_gmail_auth: allowGmailAuth,
        openrouter_rate_limit: openrouterRateLimit,
        channel_request_delay: channelRequestDelay,
      }
      
      // Only include OAuth credentials if provided
      if (googleClientId) {
        payload.google_client_id = googleClientId
      }
      if (googleClientSecret) {
        payload.google_client_secret = googleClientSecret
      }
      
      const res = await api.patch('/admin/settings', payload)
      setSettings(res.data)
      setSuccess('Settings saved successfully!')
      
      // Clear sensitive fields after save
      setGoogleClientId('')
      setGoogleClientSecret('')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-400"></div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-gray-100">Admin Settings</h1>

      {/* Error/Success Messages */}
      {error && (
        <div className="bg-red-900/50 border border-red-700 text-red-300 px-4 py-3 rounded-lg">
          {error}
        </div>
      )}
      {success && (
        <div className="bg-green-900/50 border border-green-700 text-green-300 px-4 py-3 rounded-lg">
          {success}
        </div>
      )}

      {/* Statistics Dashboard */}
      {stats && (
        <div className="bg-gray-800 border border-gray-700 rounded-2xl shadow-lg p-6">
          <h2 className="text-lg font-semibold text-gray-100 mb-4">System Statistics</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Total Users" value={stats.total_users} />
            <StatCard label="Active Users" value={stats.active_users} />
            <StatCard label="Approved Users" value={stats.approved_users} />
            <StatCard label="Pending Approval" value={stats.pending_approval} color="yellow" />
            <StatCard label="Total Prompts" value={stats.total_prompts} />
            <StatCard label="Total Messages" value={stats.total_messages} />
            <StatCard label="YouTube Channels" value={stats.total_channels} />
            <StatCard label="Telegram Bots" value={stats.total_bots} />
          </div>
        </div>
      )}

      {/* Settings Form */}
      <div className="bg-gray-800 border border-gray-700 rounded-2xl shadow-lg p-6">
        <h2 className="text-lg font-semibold text-gray-100 mb-6">Application Settings</h2>
        
        <div className="space-y-6">
          {/* Registration Settings */}
          <div className="border-b border-gray-700 pb-6">
            <h3 className="text-md font-medium text-gray-100 mb-4">Registration</h3>
            
            <div className="space-y-4">
              <label className="flex items-center space-x-3">
                <input
                  type="checkbox"
                  checked={registrationEnabled}
                  onChange={(e) => setRegistrationEnabled(e.target.checked)}
                  className="h-5 w-5 text-indigo-500 rounded border-gray-600 bg-gray-700 focus:ring-indigo-500"
                />
                <span className="text-gray-300">Enable user registration</span>
              </label>
              
              <label className="flex items-center space-x-3">
                <input
                  type="checkbox"
                  checked={requireApproval}
                  onChange={(e) => setRequireApproval(e.target.checked)}
                  className="h-5 w-5 text-indigo-500 rounded border-gray-600 bg-gray-700 focus:ring-indigo-500"
                />
                <span className="text-gray-300">Require admin approval for new users</span>
              </label>
            </div>
          </div>

          {/* Google OAuth Settings */}
          <div className="border-b border-gray-700 pb-6">
            <h3 className="text-md font-medium text-gray-100 mb-4">Google OAuth (Gmail Login)</h3>
            
            <div className="space-y-4">
              <label className="flex items-center space-x-3">
                <input
                  type="checkbox"
                  checked={allowGmailAuth}
                  onChange={(e) => setAllowGmailAuth(e.target.checked)}
                  className="h-5 w-5 text-indigo-500 rounded border-gray-600 bg-gray-700 focus:ring-indigo-500"
                />
                <span className="text-gray-300">Allow Google/Gmail authentication</span>
              </label>
              
              {allowGmailAuth && (
                <div className="ml-8 space-y-4">
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">
                      Current Client ID: {settings?.google_client_id || 'Not set'}
                    </label>
                    <input
                      type="text"
                      value={googleClientId}
                      onChange={(e) => setGoogleClientId(e.target.value)}
                      placeholder="Enter new Google Client ID (leave empty to keep current)"
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                  </div>
                  
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">
                      Client Secret (hidden for security)
                    </label>
                    <input
                      type="password"
                      value={googleClientSecret}
                      onChange={(e) => setGoogleClientSecret(e.target.value)}
                      placeholder="Enter new Google Client Secret (leave empty to keep current)"
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Rate Limiting */}
          <div className="pb-6">
            <h3 className="text-md font-medium text-gray-100 mb-4">Rate Limiting</h3>
            
            <div className="space-y-4">
              <div className="flex items-center space-x-4">
                <label className="text-gray-300">OpenRouter requests per minute (per user):</label>
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={openrouterRateLimit}
                  onChange={(e) => setOpenrouterRateLimit(parseInt(e.target.value) || 10)}
                  className="w-24 px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-gray-100 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                />
              </div>

              <div className="flex items-center space-x-4">
                <label className="text-gray-300">Delay between YouTube requests (seconds):</label>
                <input
                  type="number"
                  min="0"
                  max="60"
                  value={channelRequestDelay}
                  onChange={(e) => setChannelRequestDelay(parseInt(e.target.value) || 0)}
                  className="w-24 px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-gray-100 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                />
              </div>
              <p className="text-sm text-gray-500 ml-1">Higher delay reduces the risk of YouTube IP bans. Recommended: 5–15 seconds.</p>
            </div>
          </div>

          {/* Save Button */}
          <div className="flex justify-end">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-6 py-2 bg-indigo-600 text-white font-semibold rounded-lg hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              {saving ? 'Saving...' : 'Save Settings'}
            </button>
          </div>
        </div>
      </div>

      {/* Last Updated */}
      {settings?.updated_at && (
        <p className="text-sm text-gray-400 text-center">
          Last updated: {new Date(settings.updated_at).toLocaleString()}
        </p>
      )}
    </div>
  )
}

function StatCard({ label, value, color = 'indigo' }: { label: string; value: number; color?: string }) {
  const bgColor = color === 'yellow' ? 'bg-yellow-900/50' : 'bg-indigo-900/50'
  const textColor = color === 'yellow' ? 'text-yellow-400' : 'text-indigo-400'
  
  return (
    <div className={`${bgColor} rounded-lg p-4 text-center border border-gray-700`}>
      <div className={`text-2xl font-bold ${textColor}`}>{value}</div>
      <div className="text-sm text-gray-400">{label}</div>
    </div>
  )
}
