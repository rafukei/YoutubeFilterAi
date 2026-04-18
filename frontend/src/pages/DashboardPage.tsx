import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'

interface UserProfile {
  id: string
  email: string
  openrouter_api_token: string | null
  created_at: string
}

interface SetupStatus {
  hasApiKey: boolean
  hasPrompts: boolean
  hasBots: boolean
  hasChannels: boolean
  hasWebViews: boolean
}

export default function DashboardPage() {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => { loadData() }, [])

  const loadData = async () => {
    try {
      const [profileRes, promptsRes, botsRes, channelsRes, viewsRes] = await Promise.all([
        api.get('/auth/me'),
        api.get('/prompts'),
        api.get('/telegram-bots'),
        api.get('/channels'),
        api.get('/web-views'),
      ])
      setProfile(profileRes.data)
      setStatus({
        hasApiKey: !!profileRes.data.openrouter_api_token,
        hasPrompts: promptsRes.data.filter((p: any) => !p.is_folder).length > 0,
        hasBots: botsRes.data.length > 0,
        hasChannels: channelsRes.data.length > 0,
        hasWebViews: viewsRes.data.length > 0,
      })
    } catch (err) {
      console.error('Failed to load dashboard data:', err)
    } finally {
      setLoading(false)
    }
  }

  const allSetup = status?.hasApiKey && status?.hasPrompts && (status?.hasBots || status?.hasWebViews)
  const progress = status ? [status.hasApiKey, status.hasPrompts, status.hasBots || status.hasWebViews, status.hasChannels].filter(Boolean).length : 0

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-400"></div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div className="text-center">
        <h1 className="text-3xl font-bold text-gray-100 mb-2">
          Welcome, {profile?.email?.split('@')[0]}! ��
        </h1>
        <p className="text-gray-400">
          AI-powered YouTube video summaries delivered to Telegram or web view
        </p>
      </div>

      {!allSetup && (
        <div className="bg-gray-800 border border-gray-700 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-3">
            <span className="font-medium text-gray-100">Initial Setup</span>
            <span className="text-sm text-gray-400">{progress}/4 complete</span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-3">
            <div className="bg-indigo-500 h-3 rounded-full transition-all duration-500"
              style={{ width: (progress / 4 * 100) + '%' }}></div>
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <SetupCard step={1} title="OpenRouter API Key"
          description="You need an OpenRouter account to use AI models. Free tier includes ~10 requests/minute."
          completed={status?.hasApiKey} linkTo="/settings" linkText="Set up API key →"
          helpContent={
            <ol className="text-sm text-gray-400 space-y-1 list-decimal list-inside">
              <li>Create an account at <a href="https://openrouter.ai" target="_blank" rel="noreferrer" className="text-indigo-400 hover:underline">openrouter.ai</a></li>
              <li>Go to API Keys and create a new key</li>
              <li>Copy the key and paste it in settings</li>
            </ol>
          } />

        <SetupCard step={2} title="Create a Prompt"
          description="A prompt tells the AI how to process videos. Choose an AI model and define routing."
          completed={status?.hasPrompts} linkTo="/prompts" linkText="Create first prompt →"
          helpContent={
            <div className="text-sm text-gray-400 space-y-2">
              <p>A prompt includes:</p>
              <ul className="list-disc list-inside space-y-1">
                <li>Instructions for the AI (e.g. "Summarize this video in 3 points")</li>
                <li>AI model selection (GPT-4, Claude, Llama...)</li>
                <li>JSON routing: where to send the response</li>
              </ul>
            </div>
          } />

        <SetupCard step={3} title="Telegram Bot or Web View"
          description="Choose where summaries are sent: to a Telegram chat or to a web browser."
          completed={status?.hasBots || status?.hasWebViews} linkTo="/bots" linkText="Add Telegram bot →"
          altLinkTo="/settings" altLinkText="or create a web view"
          helpContent={
            <div className="text-sm text-gray-400 space-y-2">
              <p><strong className="text-gray-300">Telegram:</strong> Get messages directly on your phone</p>
              <p><strong className="text-gray-300">Web View:</strong> Browse summaries in your browser</p>
            </div>
          } />

        <SetupCard step={4} title="Add YouTube Channel"
          description="Choose channels to follow and how often to check for new videos."
          completed={status?.hasChannels} linkTo="/channels" linkText="Add channel →"
          helpContent={
            <div className="text-sm text-gray-400 space-y-2">
              <p>The system checks channels automatically and processes new videos with your chosen prompt.</p>
              <p>Check interval: 5 min - 24 h</p>
            </div>
          } />
      </div>

      {allSetup && (
        <div className="bg-gradient-to-r from-indigo-900/50 to-purple-900/50 border border-indigo-700/50 rounded-2xl p-6">
          <h2 className="text-xl font-bold text-gray-100 mb-2">🎉 All set!</h2>
          <p className="text-gray-300 mb-4">
            You can now test the system with a single video or wait for automatic processing.
          </p>
          <div className="flex gap-3">
            <Link to="/prompts" className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 transition">
              Test with a video →
            </Link>
            <Link to="/summary" className="px-4 py-2 bg-gray-700 text-gray-200 rounded-lg hover:bg-gray-600 transition">
              View summaries
            </Link>
          </div>
        </div>
      )}

      <div className="bg-gray-800 border border-gray-700 rounded-2xl p-6">
        <h2 className="text-lg font-bold text-gray-100 mb-4">📖 How it works</h2>
        <div className="space-y-4">
          <ProcessStep number={1} title="New video published" description="The system checks your followed channels at the interval you set (e.g. once per hour)." />
          <ProcessStep number={2} title="Transcript fetched" description="The YouTube video's auto-generated transcript is downloaded for processing." />
          <ProcessStep number={3} title="AI processes" description="Your chosen AI model (e.g. GPT-4o) processes the transcript according to your prompt." />
          <ProcessStep number={4} title="Summary delivered" description="The finished summary is sent to your Telegram bot and/or stored in your web view." />
        </div>
        <div className="mt-4 p-4 bg-yellow-900/30 border border-yellow-700/50 rounded-lg">
          <p className="text-sm text-yellow-200">
            <strong>💡 Tip:</strong> Average processing time is 10-30 seconds depending on video length. Very long videos (2h+) may take longer or require a model with a larger context window.
          </p>
        </div>
      </div>
    </div>
  )
}

function SetupCard({ step, title, description, completed, linkTo, linkText, altLinkTo, altLinkText, helpContent }: {
  step: number; title: string; description: string; completed?: boolean; linkTo: string; linkText: string
  altLinkTo?: string; altLinkText?: string; helpContent?: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className={'bg-gray-800 border rounded-xl p-5 transition-all ' + (completed ? 'border-green-700/50' : 'border-gray-700')}>
      <div className="flex items-start gap-3">
        <div className={'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ' +
          (completed ? 'bg-green-600 text-white' : 'bg-gray-700 text-gray-300')}>
          {completed ? '✓' : step}
        </div>
        <div className="flex-1">
          <h3 className="font-semibold text-gray-100">{title}</h3>
          <p className="text-sm text-gray-400 mt-1">{description}</p>
          {helpContent && (
            <>
              <button onClick={() => setExpanded(!expanded)} className="text-xs text-indigo-400 hover:text-indigo-300 mt-2">
                {expanded ? '▼ Hide instructions' : '▶ Show instructions'}
              </button>
              {expanded && <div className="mt-2 p-3 bg-gray-900/50 rounded-lg">{helpContent}</div>}
            </>
          )}
          {!completed && (
            <div className="mt-3 flex items-center gap-2">
              <Link to={linkTo} className="text-sm px-3 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 transition">{linkText}</Link>
              {altLinkTo && <Link to={altLinkTo} className="text-sm text-gray-400 hover:text-gray-300">{altLinkText}</Link>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ProcessStep({ number, title, description }: { number: number; title: string; description: string }) {
  return (
    <div className="flex gap-4">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-indigo-600/50 flex items-center justify-center text-indigo-300 font-bold text-sm">{number}</div>
      <div>
        <h4 className="font-medium text-gray-100">{title}</h4>
        <p className="text-sm text-gray-400">{description}</p>
      </div>
    </div>
  )
}
