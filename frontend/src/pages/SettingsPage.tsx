import { useEffect, useState } from 'react'
import api from '../api'

interface UserProfile {
  id: string
  email: string
  openrouter_api_token: string | null
  gdpr_consent_at: string | null
  created_at: string
}

export default function SettingsPage() {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Form state
  const [openrouterToken, setOpenrouterToken] = useState('')
  const [showToken, setShowToken] = useState(false)

  useEffect(() => {
    loadProfile()
  }, [])

  const loadProfile = async () => {
    try {
      setLoading(true)
      const res = await api.get('/auth/me')
      setProfile(res.data)
      // Don't populate token field for security - user must enter new one
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load profile')
    } finally {
      setLoading(false)
    }
  }

  const handleSaveToken = async () => {
    if (!openrouterToken.trim()) {
      setError('Please enter your OpenRouter API token')
      return
    }

    try {
      setSaving(true)
      setError(null)
      setSuccess(null)

      await api.patch('/auth/me', {
        openrouter_api_token: openrouterToken
      })

      setSuccess('OpenRouter API token saved successfully!')
      setOpenrouterToken('')  // Clear for security
      loadProfile()  // Refresh
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save token')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteToken = async () => {
    if (!confirm('Are you sure you want to remove your OpenRouter API token?')) {
      return
    }

    try {
      setSaving(true)
      await api.patch('/auth/me', {
        openrouter_api_token: null
      })
      setSuccess('OpenRouter API token removed')
      loadProfile()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to remove token')
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
    <div className="max-w-2xl mx-auto space-y-8">
      <h1 className="text-2xl font-bold text-gray-100">Settings</h1>

      {/* Messages */}
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

      {/* Profile Info */}
      <div className="bg-gray-800 border border-gray-700 rounded-2xl shadow-lg p-6">
        <h2 className="text-lg font-semibold text-gray-100 mb-4">Profile</h2>
        <div className="space-y-3 text-gray-300">
          <p><span className="font-medium text-gray-100">Email:</span> {profile?.email}</p>
          <p><span className="font-medium text-gray-100">Member since:</span> {profile?.created_at ? new Date(profile.created_at).toLocaleDateString() : '-'}</p>
        </div>
      </div>

      {/* OpenRouter API Token */}
      <div className="bg-gray-800 border border-gray-700 rounded-2xl shadow-lg p-6">
        <h2 className="text-lg font-semibold text-gray-100 mb-2">OpenRouter API Token</h2>
        <p className="text-sm text-gray-400 mb-4">
          To use AI video summarization, you need an OpenRouter API key. 
          Get one free at <a href="https://openrouter.ai/keys" target="_blank" rel="noopener noreferrer" className="text-indigo-400 hover:text-indigo-300">openrouter.ai/keys</a>
        </p>

        {/* Current status */}
        <div className="mb-4 p-3 bg-gray-700/50 rounded-lg border border-gray-600">
          <p className="text-sm">
            <span className="font-medium text-gray-100">Status: </span>
            {profile?.openrouter_api_token ? (
              <span className="text-green-400">✓ Token configured</span>
            ) : (
              <span className="text-yellow-400">⚠ No token set - AI features disabled</span>
            )}
          </p>
        </div>

        {/* Token input */}
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              {profile?.openrouter_api_token ? 'Update API Token' : 'Enter API Token'}
            </label>
            <div className="relative">
              <input
                type={showToken ? 'text' : 'password'}
                value={openrouterToken}
                onChange={(e) => setOpenrouterToken(e.target.value)}
                placeholder="sk-or-v1-..."
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent pr-20"
              />
              <button
                type="button"
                onClick={() => setShowToken(!showToken)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-sm text-gray-400 hover:text-gray-200"
              >
                {showToken ? 'Hide' : 'Show'}
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Your token is encrypted and stored securely. It's only used to call OpenRouter on your behalf.
            </p>
          </div>

          <div className="flex gap-3">
            <button
              onClick={handleSaveToken}
              disabled={saving || !openrouterToken.trim()}
              className="px-4 py-2 bg-indigo-600 text-white font-semibold rounded-lg hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              {saving ? 'Saving...' : 'Save Token'}
            </button>
            
            {profile?.openrouter_api_token && (
              <button
                onClick={handleDeleteToken}
                disabled={saving}
                className="px-4 py-2 bg-red-900/50 text-red-300 border border-red-700 font-semibold rounded-lg hover:bg-red-800/50 disabled:opacity-50 transition"
              >
                Remove Token
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Data Export & Import */}
      <div className="bg-gray-800 border border-gray-700 rounded-2xl shadow-lg p-6">
        <h2 className="text-lg font-semibold text-gray-100 mb-2">Export & Import Data</h2>
        <p className="text-sm text-gray-400 mb-4">
          Download a backup of your prompts and channel subscriptions, or restore from a previous export.
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            onClick={async () => {
              try {
                setError(null)
                const res = await api.get('/export')
                const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                a.download = `my_data_${new Date().toISOString().slice(0, 10)}.json`
                a.click()
                URL.revokeObjectURL(url)
                setSuccess('Data exported successfully!')
              } catch (err: any) {
                setError(err.response?.data?.detail || 'Export failed')
              }
            }}
            className="px-4 py-2 bg-indigo-600 text-white font-semibold rounded-lg hover:bg-indigo-500 transition"
          >
            Export Prompts & Channels
          </button>

          <label className="px-4 py-2 bg-green-700 text-white font-semibold rounded-lg hover:bg-green-600 transition cursor-pointer">
            Import from File
            <input
              type="file"
              accept=".json"
              className="hidden"
              onChange={async (e) => {
                const file = e.target.files?.[0]
                if (!file) return
                try {
                  setError(null)
                  setSuccess(null)
                  const text = await file.text()
                  const data = JSON.parse(text)
                  const payload = {
                    prompts: (data.prompts || []).map((p: any) => ({
                      name: p.name,
                      is_folder: p.is_folder || false,
                      body: p.body || null,
                      ai_model: p.ai_model || 'openai/gpt-3.5-turbo',
                      fallback_ai_model: p.fallback_ai_model || null,
                    })),
                    channels: (data.channels || []).map((c: any) => ({
                      channel_id: c.channel_id,
                      channel_name: c.channel_name,
                      check_interval_minutes: c.check_interval_minutes || 60,
                    })),
                  }
                  const res = await api.post('/import', payload)
                  const r = res.data
                  setSuccess(
                    `Imported ${r.prompts_imported} prompts, ${r.channels_imported} channels. ` +
                    `Skipped ${r.prompts_skipped} duplicate prompts, ${r.channels_skipped} duplicate channels.`
                  )
                } catch (err: any) {
                  setError(err.response?.data?.detail || err.message || 'Import failed')
                }
                e.target.value = ''
              }}
            />
          </label>
        </div>
      </div>

      {/* Help Section */}
      <div className="bg-indigo-900/30 border border-indigo-700/50 rounded-2xl p-6">
        <h3 className="font-semibold text-indigo-300 mb-2">How to get an OpenRouter API key</h3>
        <ol className="text-sm text-indigo-200/80 space-y-2 list-decimal list-inside">
          <li>Go to <a href="https://openrouter.ai" target="_blank" rel="noopener noreferrer" className="underline hover:text-indigo-300">openrouter.ai</a> and create an account</li>
          <li>Navigate to <a href="https://openrouter.ai/keys" target="_blank" rel="noopener noreferrer" className="underline hover:text-indigo-300">API Keys</a></li>
          <li>Click "Create Key" and copy the generated key</li>
          <li>Paste it above and click "Save Token"</li>
          <li>Free tier includes ~10 requests/minute with GPT-3.5</li>
        </ol>
      </div>
    </div>
  )
}
