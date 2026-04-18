import { useState, useEffect } from 'react'
import api from '../api'

interface Bot { 
  id: string
  bot_name: string
  chat_id: string | null
  created_at: string 
}

export default function BotsPage() {
  const [bots, setBots] = useState<Bot[]>([])
  const [token, setToken] = useState('')
  const [name, setName] = useState('')
  const [adding, setAdding] = useState(false)
  const [showGuide, setShowGuide] = useState(true)
  const [testingBot, setTestingBot] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [addError, setAddError] = useState<string | null>(null)
  const [refreshingBot, setRefreshingBot] = useState<string | null>(null)

  const load = () => api.get('/telegram-bots').then(r => setBots(r.data))
  useEffect(() => { load() }, [])

  const add = async () => {
    if (!token) return
    setAdding(true)
    setAddError(null)
    try {
      await api.post('/telegram-bots', { 
        bot_token: token,
        bot_name: name || null,
      })
      setToken('')
      setName('')
      load()
    } catch (err: any) {
      setAddError(err.response?.data?.detail || 'Failed to add bot')
    } finally {
      setAdding(false)
    }
  }

  const remove = async (id: string) => {
    if (!confirm('Are you sure you want to remove this bot?')) return
    await api.delete(`/telegram-bots/${id}`)
    load()
  }

  const testBot = async (botId: string, botName: string) => {
    setTestingBot(botId)
    setTestResult(null)
    try {
      await api.post(`/telegram-bots/${botId}/test`)
      setTestResult({ success: true, message: `Test message sent to ${botName}! Check Telegram.` })
    } catch (err: any) {
      setTestResult({ success: false, message: err.response?.data?.detail || 'Test failed' })
    } finally {
      setTestingBot(null)
    }
  }

  const refreshChatId = async (botId: string) => {
    setRefreshingBot(botId)
    setTestResult(null)
    try {
      await api.post(`/telegram-bots/${botId}/refresh`)
      setTestResult({ success: true, message: 'Chat ID updated!' })
      load()
    } catch (err: any) {
      setTestResult({ success: false, message: err.response?.data?.detail || 'Could not find Chat ID — send /start to the bot first' })
    } finally {
      setRefreshingBot(null)
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-100">Telegram Bots</h1>
        <p className="text-gray-400 mt-1">
          Receive AI summaries directly in your Telegram chat
        </p>
      </div>

      {/* Guide Section */}
      <div className="bg-gray-800 border border-gray-700 rounded-2xl overflow-hidden">
        <button
          onClick={() => setShowGuide(!showGuide)}
          className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-gray-700/50 transition"
        >
          <div className="flex items-center gap-3">
            <span className="text-2xl">📱</span>
            <div>
              <h2 className="font-semibold text-gray-100">How does the Telegram bot work?</h2>
              <p className="text-sm text-gray-400">Step-by-step guide to creating and pairing a bot</p>
            </div>
          </div>
          <span className="text-gray-400">{showGuide ? '▼' : '▶'}</span>
        </button>

        {showGuide && (
          <div className="px-6 pb-6 border-t border-gray-700">
            <div className="mt-4 space-y-4">
              <GuideStep
                number={1}
                title="Create a bot with BotFather"
                content={
                  <div className="space-y-2">
                    <p>1. Open Telegram and search for <code className="bg-gray-900 px-1 rounded">@BotFather</code></p>
                    <p>2. Send the command <code className="bg-gray-900 px-1 rounded">/newbot</code></p>
                    <p>3. Give the bot a name and username (must end with "_bot")</p>
                    <p>4. You will receive a message with the <strong className="text-indigo-400">API token</strong> — copy it!</p>
                    <div className="mt-3 p-3 bg-gray-900 rounded-lg">
                      <p className="text-xs text-gray-500">Example token:</p>
                      <code className="text-green-400 text-sm">1234567890:ABCdefGHIjklMNOpqrsTUVwxyz</code>
                    </div>
                  </div>
                }
              />

              <GuideStep
                number={2}
                title="Send /start to your bot in Telegram"
                content={
                  <div className="space-y-2">
                    <p>1. Open the bot you just created in Telegram</p>
                    <p>2. Press <strong className="text-indigo-400">Start</strong> or send <code className="bg-gray-900 px-1 rounded">/start</code></p>
                    <p className="text-sm text-gray-400 mt-2">This enables automatic Chat ID detection.</p>
                    <div className="mt-3 p-3 bg-indigo-900/30 border border-indigo-700/50 rounded-lg">
                      <p className="text-sm text-indigo-200">
                        <strong>💡 Groups & channels:</strong> Add the bot to a group/channel as admin and send a message before adding the bot here.
                      </p>
                    </div>
                  </div>
                }
              />

              <GuideStep
                number={3}
                title="Paste the token in the field below"
                content={
                  <div className="space-y-2">
                    <p>Paste the token you received from BotFather and click "Add bot".</p>
                    <p className="text-sm text-gray-400">
                      The system will automatically fetch the bot name and Chat ID — you don't need to enter them manually!
                    </p>
                  </div>
                }
              />

              <GuideStep
                number={4}
                title="Use in prompts"
                content={
                  <div className="space-y-2">
                    <p>When creating a prompt, add the JSON routing at the end:</p>
                    <div className="mt-2 p-3 bg-gray-900 rounded-lg overflow-x-auto">
                      <pre className="text-sm text-green-400">{`{
  "message": "...",
  "telegram_bots": ["bot_name"],
  "web_views": [],
  "visibility": true
}`}</pre>
                    </div>
                  </div>
                }
              />
            </div>
          </div>
        )}
      </div>

      {/* Add Bot Form */}
      <div className="bg-gray-800 border border-gray-700 rounded-2xl p-6">
        <h2 className="font-semibold text-gray-100 mb-4">Add new bot</h2>
        
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              API Token <span className="text-gray-500">(from BotFather)</span>
            </label>
            <input
              type="password"
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              placeholder="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
              value={token}
              onChange={e => setToken(e.target.value)}
            />
            <p className="text-xs text-gray-500 mt-1">
              Bot name and Chat ID are fetched automatically from the token
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Custom name <span className="text-gray-500">(optional — fetched automatically)</span>
            </label>
            <input
              className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              placeholder="e.g. news_bot (leave empty = fetched from Telegram)"
              value={name}
              onChange={e => setName(e.target.value)}
            />
          </div>

          {addError && (
            <div className="p-3 bg-red-900/50 border border-red-700 rounded-lg">
              <p className="text-sm text-red-300">{addError}</p>
            </div>
          )}

          <button
            onClick={add}
            disabled={!token || adding}
            className="w-full bg-indigo-600 text-white py-2 rounded-lg hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition font-medium"
          >
            {adding ? '⏳ Fetching info and adding...' : 'Add bot'}
          </button>
        </div>
      </div>

      {/* Test Result */}
      {testResult && (
        <div className={`p-4 rounded-lg ${testResult.success ? 'bg-green-900/50 border border-green-700' : 'bg-red-900/50 border border-red-700'}`}>
          <p className={testResult.success ? 'text-green-300' : 'text-red-300'}>{testResult.message}</p>
        </div>
      )}

      {/* Bots List */}
      {bots.length > 0 && (
        <div className="bg-gray-800 border border-gray-700 rounded-2xl p-6">
          <h2 className="font-semibold text-gray-100 mb-4">Your bots ({bots.length})</h2>
          <ul className="space-y-3">
            {bots.map(b => (
              <li key={b.id} className="flex items-center justify-between bg-gray-900/50 p-4 rounded-lg border border-gray-700">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-lg">🤖</span>
                    <span className="font-medium text-gray-100">{b.bot_name}</span>
                  </div>
                  <p className="text-sm text-gray-500 mt-1">
                    Chat ID: {b.chat_id 
                      ? <code className="bg-gray-800 px-1 rounded">{b.chat_id}</code>
                      : <span className="text-yellow-400">⚠️ Not found — send /start to the bot, then click Refresh</span>
                    }
                  </p>
                  <p className="text-xs text-gray-600 mt-1">
                    Added: {new Date(b.created_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {!b.chat_id && (
                    <button
                      onClick={() => refreshChatId(b.id)}
                      disabled={refreshingBot === b.id}
                      className="px-3 py-1 text-sm bg-yellow-600 text-white rounded hover:bg-yellow-500 disabled:opacity-50"
                    >
                      {refreshingBot === b.id ? 'Refreshing...' : '🔄 Refresh'}
                    </button>
                  )}
                  <button
                    onClick={() => testBot(b.id, b.bot_name)}
                    disabled={testingBot === b.id}
                    className="px-3 py-1 text-sm bg-gray-700 text-gray-300 rounded hover:bg-gray-600 disabled:opacity-50"
                  >
                    {testingBot === b.id ? 'Testing...' : 'Test'}
                  </button>
                  <button
                    onClick={() => remove(b.id)}
                    className="px-3 py-1 text-sm text-red-400 hover:text-red-300 hover:bg-red-900/30 rounded"
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Empty State */}
      {bots.length === 0 && (
        <div className="text-center py-12">
          <span className="text-4xl">🤖</span>
          <p className="text-gray-400 mt-2">No bots added yet</p>
          <p className="text-sm text-gray-500">Add your first bot using the form above</p>
        </div>
      )}
    </div>
  )
}

function GuideStep({ number, title, content }: { 
  number: number
  title: string
  content: React.ReactNode 
}) {
  return (
    <div className="flex gap-4">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white font-bold text-sm">
        {number}
      </div>
      <div className="flex-1">
        <h3 className="font-medium text-gray-100 mb-2">{title}</h3>
        <div className="text-gray-300">{content}</div>
      </div>
    </div>
  )
}
