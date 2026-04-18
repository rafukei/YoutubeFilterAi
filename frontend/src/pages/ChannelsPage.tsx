import { useState, useEffect } from 'react'
import api from '../api'

interface Prompt { id: string; name: string; parent_id: string | null; is_folder: boolean }

interface Channel {
  id: string
  channel_id: string
  channel_name: string
  check_interval_minutes: number
  is_active: boolean
  last_checked_at: string | null
  last_video_id: string | null
  prompt_id: string | null
  added_at: string
}

export default function ChannelsPage() {
  const [channels, setChannels] = useState<Channel[]>([])
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [allPrompts, setAllPrompts] = useState<Prompt[]>([])
  const [channelId, setChannelId] = useState('')
  const [channelName, setChannelName] = useState('')
  const [checkInterval, setCheckInterval] = useState(60)
  const [selectedPrompt, setSelectedPrompt] = useState('')
  const [showGuide, setShowGuide] = useState(true)
  const [editingChannel, setEditingChannel] = useState<string | null>(null)

  const load = async () => {
    const [channelsRes, promptsRes] = await Promise.all([
      api.get('/channels'),
      api.get('/prompts')
    ])
    setChannels(channelsRes.data)
    const all = promptsRes.data as Prompt[]
    setAllPrompts(all)
    // Include both prompts and folders — folders run all child prompts
    setPrompts(all)
  }
  useEffect(() => { load() }, [])

  const add = async () => {
    if (!channelId || !channelName) return
    try {
      await api.post('/channels', {
        channel_id: channelId,
        channel_name: channelName,
        check_interval_minutes: checkInterval,
        prompt_id: selectedPrompt || null
      })
      setChannelId('')
      setChannelName('')
      setCheckInterval(60)
      setSelectedPrompt('')
      load()
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to add channel')
    }
  }

  const remove = async (id: string) => {
    if (!confirm('Are you sure you want to remove this channel?')) return
    await api.delete('/channels/' + id)
    load()
  }

  const updateChannel = async (id: string, updates: Partial<Channel>) => {
    await api.patch('/channels/' + id, updates)
    setEditingChannel(null)
    load()
  }

  const getPromptPath = (promptId: string | null): string => {
    if (!promptId) return 'Not selected'
    const buildPath = (id: string): string => {
      const p = allPrompts.find(x => x.id === id)
      if (!p) return 'Unknown'
      if (p.parent_id) return buildPath(p.parent_id) + '/' + p.name
      return '/' + p.name
    }
    return buildPath(promptId)
  }

  const formatInterval = (minutes: number) => {
    if (minutes < 60) return minutes + ' min'
    if (minutes === 60) return '1 hour'
    if (minutes < 1440) return Math.floor(minutes / 60) + ' hours'
    return Math.floor(minutes / 1440) + ' days'
  }

  const formatLastChecked = (timestamp: string | null) => {
    if (!timestamp) return 'Not checked yet'
    // Backend stores UTC without Z suffix — append it for correct parsing
    const utcTimestamp = timestamp.endsWith('Z') ? timestamp : timestamp + 'Z'
    const date = new Date(utcTimestamp)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return diffMins + ' min ago'
    if (diffMins < 1440) return Math.floor(diffMins / 60) + 'h ago'
    return date.toLocaleDateString()
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-100">YouTube Channels</h1>
        <p className="text-gray-400 mt-1">Follow channels and process new videos automatically</p>
      </div>

      {/* Guide */}
      <div className="bg-gray-800 border border-gray-700 rounded-2xl overflow-hidden">
        <button onClick={() => setShowGuide(!showGuide)}
          className="w-full px-6 py-4 flex items-center justify-between text-left hover:bg-gray-700/50 transition">
          <div className="flex items-center gap-3">
            <span className="text-2xl">📺</span>
            <div>
              <h2 className="font-semibold text-gray-100">How channel monitoring works</h2>
              <p className="text-sm text-gray-400">Guide to adding channels and scheduling</p>
            </div>
          </div>
          <span className="text-gray-400">{showGuide ? '▼' : '▶'}</span>
        </button>
        {showGuide && (
          <div className="px-6 pb-6 border-t border-gray-700">
            <div className="mt-4 space-y-4">
              <GuideStep number={1} title="Find the channel ID" content={
                <div className="space-y-2">
                  <p>The YouTube channel ID can be found in the channel URL:</p>
                  <div className="mt-2 p-3 bg-gray-900 rounded-lg overflow-x-auto">
                    <p className="text-sm text-gray-400">Format 1 (newer):</p>
                    <code className="text-green-400 text-sm">youtube.com/@ChannelName</code>
                    <p className="text-xs text-gray-500 mt-1">→ Use: <strong>@ChannelName</strong></p>
                  </div>
                  <div className="mt-2 p-3 bg-gray-900 rounded-lg overflow-x-auto">
                    <p className="text-sm text-gray-400">Format 2 (older):</p>
                    <code className="text-green-400 text-sm">youtube.com/channel/UCxxxxxxxxxxxxxxxx</code>
                    <p className="text-xs text-gray-500 mt-1">→ Use: <strong>UCxxxxxxxxxxxxxxxx</strong></p>
                  </div>
                  <div className="mt-3 p-3 bg-indigo-900/30 border border-indigo-700/50 rounded-lg">
                    <p className="text-sm text-indigo-200"><strong>💡 Tip:</strong> You can also paste the full URL — the system will try to extract the channel ID automatically.</p>
                  </div>
                </div>
              } />
              <GuideStep number={2} title="Choose check interval" content={
                <div className="space-y-2">
                  <p>Set how often the system checks for new videos:</p>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    <div className="p-2 bg-gray-900 rounded text-sm"><strong className="text-indigo-400">5-15 min</strong><p className="text-gray-500 text-xs">Real-time monitoring, uses more resources</p></div>
                    <div className="p-2 bg-gray-900 rounded text-sm"><strong className="text-indigo-400">30-60 min</strong><p className="text-gray-500 text-xs">Recommended for most users</p></div>
                    <div className="p-2 bg-gray-900 rounded text-sm"><strong className="text-indigo-400">2-6 h</strong><p className="text-gray-500 text-xs">For less frequent channels</p></div>
                    <div className="p-2 bg-gray-900 rounded text-sm"><strong className="text-indigo-400">12-24 h</strong><p className="text-gray-500 text-xs">Daily summary</p></div>
                  </div>
                </div>
              } />
              <GuideStep number={3} title="Link to a prompt or folder" content={
                <div className="space-y-2">
                  <p>Choose which prompt processes this channel's videos:</p>
                  <ul className="list-disc list-inside space-y-1 text-gray-400">
                    <li>Select a <strong>single prompt</strong> to run one AI analysis per video</li>
                    <li>Select a <strong>folder</strong> to run ALL prompts inside it against each video</li>
                    <li>Different channels can use different prompts/folders</li>
                    <li>The prompt defines the AI model and routing</li>
                  </ul>
                  <div className="mt-2 p-3 bg-yellow-900/30 border border-yellow-700/50 rounded-lg">
                    <p className="text-sm text-yellow-200"><strong>⚠️ Note:</strong> Create a prompt on the "Prompts" page before adding a channel.</p>
                  </div>
                </div>
              } />
            </div>
          </div>
        )}
      </div>

      {/* Add Channel Form */}
      <div className="bg-gray-800 border border-gray-700 rounded-2xl p-6">
        <h2 className="font-semibold text-gray-100 mb-4">Add new channel</h2>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Channel ID or @handle</label>
              <input className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="@MrBeast or UCxxxxxx" value={channelId} onChange={e => setChannelId(e.target.value)} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Channel name <span className="text-gray-500">(label)</span></label>
              <input className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="e.g. MrBeast" value={channelName} onChange={e => setChannelName(e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Check interval</label>
              <select className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-gray-100 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                value={checkInterval} onChange={e => setCheckInterval(Number(e.target.value))}>
                <option value={5}>5 minutes</option>
                <option value={15}>15 minutes</option>
                <option value={30}>30 minutes</option>
                <option value={60}>1 hour</option>
                <option value={120}>2 hours</option>
                <option value={360}>6 hours</option>
                <option value={720}>12 hours</option>
                <option value={1440}>24 hours</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Prompt to use</label>
              <select className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-gray-100 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                value={selectedPrompt} onChange={e => setSelectedPrompt(e.target.value)}>
                <option value="">-- Select prompt or folder --</option>
                {prompts.map(p => <option key={p.id} value={p.id}>{p.is_folder ? '📁 ' : '📝 '}{getPromptPath(p.id)}</option>)}
              </select>
            </div>
          </div>
          <button onClick={add} disabled={!channelId || !channelName}
            className="w-full bg-indigo-600 text-white py-2 rounded-lg hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition font-medium">
            Add channel to monitoring
          </button>
        </div>
      </div>

      {/* Channels List */}
      {channels.length > 0 && (
        <div className="bg-gray-800 border border-gray-700 rounded-2xl p-6">
          <h2 className="font-semibold text-gray-100 mb-4">Monitored channels ({channels.length})</h2>
          <ul className="space-y-3">
            {channels.map(c => (
              <li key={c.id} className="bg-gray-900/50 p-4 rounded-lg border border-gray-700">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-lg">📺</span>
                      <span className="font-medium text-gray-100">{c.channel_name}</span>
                      {c.is_active
                        ? <span className="px-2 py-0.5 text-xs bg-green-900/50 text-green-400 rounded-full">Active</span>
                        : <span className="px-2 py-0.5 text-xs bg-gray-700 text-gray-400 rounded-full">Paused</span>}
                    </div>
                    <p className="text-sm text-gray-500 mt-1">ID: <code className="bg-gray-800 px-1 rounded">{c.channel_id}</code></p>

                    {editingChannel === c.id ? (
                      <div className="mt-3 space-y-3 p-3 bg-gray-800 rounded-lg">
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="block text-xs text-gray-400 mb-1">Check interval</label>
                            <select className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100"
                              defaultValue={c.check_interval_minutes}
                              onChange={e => updateChannel(c.id, { check_interval_minutes: Number(e.target.value) })}>
                              <option value={5}>5 min</option><option value={15}>15 min</option>
                              <option value={30}>30 min</option><option value={60}>1 h</option>
                              <option value={120}>2 h</option><option value={360}>6 h</option>
                              <option value={720}>12 h</option><option value={1440}>24 h</option>
                            </select>
                          </div>
                          <div>
                            <label className="block text-xs text-gray-400 mb-1">Prompt</label>
                            <select className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-gray-100"
                              defaultValue={c.prompt_id || ''}
                              onChange={e => updateChannel(c.id, { prompt_id: e.target.value || null })}>
                              <option value="">-- Not selected --</option>
                              {prompts.map(p => <option key={p.id} value={p.id}>{p.is_folder ? '📁 ' : '📝 '}{getPromptPath(p.id)}</option>)}
                            </select>
                          </div>
                        </div>
                        <div className="flex justify-end gap-2">
                          <button onClick={() => updateChannel(c.id, { is_active: !c.is_active })}
                            className={'px-3 py-1 text-sm rounded ' + (c.is_active ? 'bg-yellow-900/50 text-yellow-300' : 'bg-green-900/50 text-green-300')}>
                            {c.is_active ? 'Pause' : 'Activate'}
                          </button>
                          <button onClick={() => setEditingChannel(null)} className="px-3 py-1 text-sm bg-gray-700 text-gray-300 rounded">Close</button>
                        </div>
                      </div>
                    ) : (
                      <div className="mt-2 flex flex-wrap gap-3 text-xs text-gray-400">
                        <span>⏱️ Check: {formatInterval(c.check_interval_minutes)}</span>
                        <span>📝 Prompt: {getPromptPath(c.prompt_id)}</span>
                        <span>🕐 Checked: {formatLastChecked(c.last_checked_at)}</span>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 ml-4">
                    <button onClick={() => setEditingChannel(editingChannel === c.id ? null : c.id)}
                      className="px-3 py-1 text-sm bg-gray-700 text-gray-300 rounded hover:bg-gray-600">
                      {editingChannel === c.id ? 'Cancel' : 'Edit'}
                    </button>
                    <button onClick={() => remove(c.id)} className="px-3 py-1 text-sm text-red-400 hover:text-red-300 hover:bg-red-900/30 rounded">Delete</button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {channels.length === 0 && (
        <div className="text-center py-12">
          <span className="text-4xl">📺</span>
          <p className="text-gray-400 mt-2">No channels being monitored yet</p>
          <p className="text-sm text-gray-500">Add your first channel using the form above</p>
        </div>
      )}
    </div>
  )
}

function GuideStep({ number, title, content }: { number: number; title: string; content: React.ReactNode }) {
  return (
    <div className="flex gap-4">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white font-bold text-sm">{number}</div>
      <div className="flex-1">
        <h3 className="font-medium text-gray-100 mb-2">{title}</h3>
        <div className="text-gray-300">{content}</div>
      </div>
    </div>
  )
}
