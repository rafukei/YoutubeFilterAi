import { useState, useEffect } from 'react'
import api from '../api'

interface Prompt {
  id: string
  name: string
  parent_id: string | null
  is_folder: boolean
  body: string | null
  ai_model: string | null
  fallback_ai_model: string | null
}

interface AIModel {
  id: string
  name: string
  context_length: number
  pricing: { prompt?: number; completion?: number }
  description: string
}

const DEFAULT_ROUTING = {
  message: "...",
  telegram_bots: [],
  web_views: [],
  visibility: true
}

const PROMPT_TEMPLATES = [
  {
    name: "📰 News Summary",
    description: "Summarize a video into 3 key points",
    body: "You are an expert journalist. Analyze this YouTube video transcript and create a concise news summary.\n\nTASK:\n1. Identify the main topic and context\n2. Extract the 3 most important points/claims\n3. Write a clear, informative summary\n\nFORMAT:\n- Title (max 10 words)\n- 3 key points (bullet points)\n- Brief conclusion (1-2 sentences)",
    routing: { message: "...", telegram_bots: ["news_bot"], web_views: ["news"], visibility: true }
  },
  {
    name: "🎓 Study Notes",
    description: "Convert educational content into study notes",
    body: "You are a teacher and note-taking expert. Convert this educational video into clear study notes.\n\nTASK:\n1. Identify the topic being taught\n2. Extract key concepts and their explanations\n3. List concrete examples\n4. Identify potential exam topics",
    routing: { message: "...", telegram_bots: [], web_views: ["study"], visibility: true }
  },
  {
    name: "💰 Investment Analysis",
    description: "Analyze financial videos from an investor's perspective",
    body: "You are an experienced investment analyst. Critically analyze this financial video.\n\nTASK:\n1. Identify the investment topics discussed\n2. Evaluate the reliability of claims\n3. Identify risks and opportunities\n4. Summarize from an investor's perspective",
    routing: { message: "...", telegram_bots: ["investment_bot"], web_views: ["investments"], visibility: true }
  },
  {
    name: "🎬 Entertainment Recap",
    description: "Quick recap of entertainment videos",
    body: "Create a short and entertaining recap of this video.\n\nTASK:\n1. Describe what the video is about (1 sentence)\n2. Mention 2-3 interesting details\n3. Give a rating on an emoji scale (⭐-⭐⭐⭐⭐⭐)",
    routing: { message: "...", telegram_bots: ["entertainment_bot"], web_views: [], visibility: true }
  }
]

export default function PromptsPage() {
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [models, setModels] = useState<AIModel[]>([])
  const [selected, setSelected] = useState<Prompt | null>(null)
  const [body, setBody] = useState('')
  const [routingJson, setRoutingJson] = useState(JSON.stringify(DEFAULT_ROUTING, null, 2))
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [aiModel, setAiModel] = useState('openai/gpt-3.5-turbo')
  const [fallbackModel, setFallbackModel] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [activeFolder, setActiveFolder] = useState<string | null>(null)
  const [showGuide, setShowGuide] = useState(false)
  const [showTemplates, setShowTemplates] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testVideoUrl, setTestVideoUrl] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ transcript?: string; response?: string; fullPrompt?: string; error?: string } | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  const load = async () => {
    const [promptsRes, modelsRes] = await Promise.all([
      api.get('/prompts'),
      api.get('/ai-models')
    ])
    setPrompts(promptsRes.data)
    setModels(modelsRes.data)
  }
  useEffect(() => { load() }, [])

  const parseBodyAndRouting = (fullBody: string | null) => {
    if (!fullBody) {
      setBody('')
      setRoutingJson(JSON.stringify(DEFAULT_ROUTING, null, 2))
      setJsonError(null)
      return
    }
    const jsonMatch = fullBody.match(/\{[^{}]*"message"[^{}]*\}\s*$/)
    if (jsonMatch) {
      const promptPart = fullBody.slice(0, jsonMatch.index).trimEnd()
      setBody(promptPart)
      try {
        const parsed = JSON.parse(jsonMatch[0])
        setRoutingJson(JSON.stringify(parsed, null, 2))
        setJsonError(null)
      } catch {
        setRoutingJson(jsonMatch[0])
        setJsonError('Invalid JSON found at end of prompt')
      }
    } else {
      setBody(fullBody)
      setRoutingJson(JSON.stringify(DEFAULT_ROUTING, null, 2))
      setJsonError(null)
    }
  }

  const select = (p: Prompt) => {
    setSelected(p)
    parseBodyAndRouting(p.body)
    setAiModel(p.ai_model || 'openai/gpt-3.5-turbo')
    setFallbackModel(p.fallback_ai_model || null)
    setTestResult(null)
    setTestVideoUrl('')
  }

  const validateRouting = (json: string): string | null => {
    try {
      const parsed = JSON.parse(json)
      if (typeof parsed.message === 'undefined') return 'Missing required field: "message"'
      if (!Array.isArray(parsed.telegram_bots)) return '"telegram_bots" must be an array'
      if (!Array.isArray(parsed.web_views)) return '"web_views" must be an array'
      if (typeof parsed.visibility !== 'boolean') return '"visibility" must be true or false'
      return null
    } catch (e: any) {
      return 'JSON syntax error: ' + e.message
    }
  }

  const handleRoutingChange = (value: string) => {
    setRoutingJson(value)
    setJsonError(validateRouting(value))
  }

  const getFullBody = () => body + '\n\n' + routingJson

  const save = async () => {
    if (!selected) return
    const routingError = validateRouting(routingJson)
    if (routingError) { setJsonError(routingError); return }
    setSaving(true)
    try {
      await api.patch('/prompts/' + selected.id, { body: getFullBody(), ai_model: aiModel, fallback_ai_model: fallbackModel || null })
      load()
    } finally { setSaving(false) }
  }

  const create = async (isFolder: boolean) => {
    if (!newName) return
    await api.post('/prompts', {
      name: newName, is_folder: isFolder,
      parent_id: activeFolder || null,
      body: isFolder ? null : '',
      ai_model: isFolder ? null : 'openai/gpt-3.5-turbo'
    })
    setNewName('')
    load()
  }

  const del = async (id: string) => {
    if (!confirm('Are you sure you want to delete this prompt?')) return
    await api.delete('/prompts/' + id)
    load()
    if (selected?.id === id) setSelected(null)
  }

  const startRename = (p: Prompt) => {
    setRenamingId(p.id)
    setRenameValue(p.name)
  }

  const commitRename = async () => {
    if (!renamingId || !renameValue.trim()) { setRenamingId(null); return }
    await api.patch('/prompts/' + renamingId, { name: renameValue.trim() })
    setRenamingId(null)
    setRenameValue('')
    load()
  }

  const applyTemplate = (template: typeof PROMPT_TEMPLATES[0]) => {
    setBody(template.body)
    setRoutingJson(JSON.stringify(template.routing, null, 2))
    setJsonError(null)
    setShowTemplates(false)
  }

  const runTest = async () => {
    if (!testVideoUrl || !selected) return
    const routingError = validateRouting(routingJson)
    if (routingError) { setJsonError(routingError); return }
    setTesting(true)
    setTestResult(null)
    try {
      const fullPromptText = getFullBody()
      const { data } = await api.post('/process', {
        video_url: testVideoUrl,
        prompt_text: fullPromptText,
        ai_model: aiModel,
      })
      setTestResult({
        fullPrompt: fullPromptText,
        transcript: data.raw_transcript,
        response: data.message?.ai_response || data.ai_response || JSON.stringify(data, null, 2)
      })
    } catch (err: any) {
      setTestResult({ error: err.response?.data?.detail || 'Test failed' })
    } finally { setTesting(false) }
  }

  const roots = prompts.filter(p => !p.parent_id)
  const children = (pid: string) => prompts.filter(p => p.parent_id === pid)

  const renderTree = (items: Prompt[], depth = 0) => (
    <ul style={{ paddingLeft: depth * 16 }}>
      {items.map(p => (
        <li key={p.id}>
          <div className={'flex items-center gap-2 py-1.5 px-2 rounded cursor-pointer transition ' +
            (selected?.id === p.id ? 'bg-indigo-600/30' : activeFolder === p.id ? 'bg-indigo-900/20 ring-1 ring-indigo-500/30' : 'hover:bg-gray-700/50')
          }>
            {renamingId === p.id ? (
              <input
                autoFocus
                className="flex-1 bg-gray-700 border border-indigo-500 rounded px-1 py-0.5 text-sm text-gray-100 focus:outline-none"
                value={renameValue}
                onChange={e => setRenameValue(e.target.value)}
                onBlur={() => commitRename()}
                onKeyDown={e => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') setRenamingId(null) }}
              />
            ) : (
              <span className="flex-1 text-gray-300" onClick={() => {
                if (p.is_folder) {
                  setActiveFolder(activeFolder === p.id ? null : p.id)
                } else {
                  select(p)
                }
              }} onDoubleClick={(e) => { e.stopPropagation(); startRename(p) }}>
                {p.is_folder ? (activeFolder === p.id ? '📂' : '📁') : '📝'} {p.name}
              </span>
            )}
            <button onClick={(e) => { e.stopPropagation(); del(p.id) }}
              className="text-xs text-red-400 hover:text-red-300 opacity-50 hover:opacity-100">✕</button>
          </div>
          {p.is_folder && renderTree(children(p.id), depth + 1)}
        </li>
      ))}
    </ul>
  )

  const getModelInfo = (modelId: string) => models.find(m => m.id === modelId)

  const formatPrice = (pricing: { prompt?: number; completion?: number } | undefined) => {
    if (!pricing || (!pricing.prompt && !pricing.completion)) return 'Free'
    const avg = ((pricing.prompt || 0) + (pricing.completion || 0)) / 2
    if (avg < 0.0001) return 'Nearly free'
    if (avg < 0.001) return '~$0.01/video'
    if (avg < 0.01) return '~$0.05/video'
    return '~$0.10+/video'
  }

  return (
    <div className="flex gap-6 h-[calc(100vh-120px)]">
      {/* Tree sidebar */}
      <div className="w-72 border-r border-gray-700 pr-4 overflow-y-auto flex flex-col">
        <h2 className="font-semibold mb-3 text-gray-100 text-lg">Prompts</h2>
        <div className="flex-1 overflow-y-auto">
          {prompts.length === 0 ? (
            <p className="text-gray-500 text-sm">No prompts yet. Create one below.</p>
          ) : renderTree(roots)}
        </div>
        <div className="mt-4 pt-4 border-t border-gray-700 space-y-2">
          {activeFolder && (
            <div className="flex items-center justify-between text-xs text-indigo-300 bg-indigo-900/20 px-2 py-1 rounded">
              <span>📂 Into: {prompts.find(p => p.id === activeFolder)?.name || '?'}</span>
              <button onClick={() => setActiveFolder(null)} className="text-gray-400 hover:text-gray-200">✕</button>
            </div>
          )}
          <input className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            placeholder="New name…" value={newName} onChange={e => setNewName(e.target.value)} />
          <div className="flex gap-2">
            <button onClick={() => create(false)} className="flex-1 text-xs bg-indigo-600 text-white px-2 py-1.5 rounded hover:bg-indigo-500">+ Prompt</button>
            <button onClick={() => create(true)} className="flex-1 text-xs bg-gray-700 text-gray-300 px-2 py-1.5 rounded hover:bg-gray-600">+ Folder</button>
          </div>
        </div>
      </div>

      {/* Editor */}
      <div className="flex-1 flex flex-col overflow-y-auto">
        {selected ? (
          <>
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-gray-100 text-lg">Edit: {selected.name}</h2>
              <button onClick={() => setShowGuide(!showGuide)} className="text-sm text-indigo-400 hover:text-indigo-300">
                {showGuide ? '▼ Hide guide' : '▶ Show guide'}
              </button>
            </div>

            {showGuide && (
              <div className="mb-4 p-4 bg-gray-800 border border-gray-700 rounded-lg">
                <h3 className="font-medium text-gray-100 mb-2">📖 How prompts work</h3>
                <div className="text-sm text-gray-400 space-y-2">
                  <p>A prompt is an instruction you give to the AI. It tells the AI how to process the video transcript.</p>
                  <p><strong className="text-gray-300">Important:</strong> The JSON routing block below defines where the AI response is sent.</p>
                  <ul className="list-disc list-inside mt-2 space-y-1">
                    <li><code className="bg-gray-900 px-1 rounded">message</code> — AI fills this with the summary</li>
                    <li><code className="bg-gray-900 px-1 rounded">telegram_bots</code> — Which bots to send to</li>
                    <li><code className="bg-gray-900 px-1 rounded">web_views</code> — Which web views to store in</li>
                    <li><code className="bg-gray-900 px-1 rounded">visibility</code> — Show in web view (true/false)</li>
                  </ul>
                </div>
              </div>
            )}

            {/* AI Model */}
            <div className="mb-4 p-4 bg-gray-800 border border-gray-700 rounded-lg">
              <div className="flex items-center justify-between mb-2">
                <label className="font-medium text-gray-100">AI Model</label>
                <span className="text-xs text-gray-500">{formatPrice(getModelInfo(aiModel)?.pricing)}</span>
              </div>
              <select className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-gray-100 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                value={aiModel} onChange={e => setAiModel(e.target.value)}>
                <optgroup label="Recommended (good value)">
                  <option value="openai/gpt-4o-mini">GPT-4o Mini — Fast & affordable</option>
                  <option value="anthropic/claude-3-haiku">Claude 3 Haiku — Fast Anthropic</option>
                  <option value="meta-llama/llama-3.1-8b-instruct">Llama 3.1 8B — Free</option>
                </optgroup>
                <optgroup label="Premium (best quality)">
                  <option value="openai/gpt-4o">GPT-4o — OpenAI best</option>
                  <option value="anthropic/claude-3.5-sonnet">Claude 3.5 Sonnet — Excellent</option>
                  <option value="google/gemini-pro-1.5">Gemini Pro 1.5 — Large context</option>
                </optgroup>
                <optgroup label="Other">
                  <option value="openai/gpt-3.5-turbo">GPT-3.5 Turbo — Classic</option>
                  <option value="mistralai/mistral-7b-instruct">Mistral 7B — Free</option>
                  <option value="qwen/qwen-2-72b-instruct">Qwen 2 72B — Multilingual</option>
                  {models.filter(m => !['openai/gpt-4o-mini','anthropic/claude-3-haiku','meta-llama/llama-3.1-8b-instruct','openai/gpt-4o','anthropic/claude-3.5-sonnet','google/gemini-pro-1.5','openai/gpt-3.5-turbo','mistralai/mistral-7b-instruct','qwen/qwen-2-72b-instruct'].includes(m.id)).map(m => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </optgroup>
              </select>
              {getModelInfo(aiModel) && (
                <p className="text-xs text-gray-500 mt-1">
                  {getModelInfo(aiModel)?.description} • Context: {(getModelInfo(aiModel)?.context_length || 0).toLocaleString()} tokens
                </p>
              )}

              {/* Fallback Model */}
              <div className="mt-4 pt-4 border-t border-gray-700">
                <div className="flex items-center justify-between mb-2">
                  <label className="font-medium text-gray-100 text-sm">Fallback AI Model <span className="text-gray-500">(optional)</span></label>
                  {fallbackModel && <button onClick={() => setFallbackModel(null)} className="text-xs text-red-400 hover:text-red-300">Clear</button>}
                </div>
                <p className="text-xs text-gray-500 mb-2">
                  If the primary model fails (e.g. transcript too long for context window), the system will automatically retry with this model.
                </p>
                <select className="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-gray-100 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  value={fallbackModel || ''} onChange={e => setFallbackModel(e.target.value || null)}>
                  <option value="">-- No fallback --</option>
                  <optgroup label="Large context (good fallbacks)">
                    <option value="google/gemini-pro-1.5">Gemini Pro 1.5 — 2M tokens context</option>
                    <option value="anthropic/claude-3.5-sonnet">Claude 3.5 Sonnet — 200K tokens</option>
                    <option value="openai/gpt-4o">GPT-4o — 128K tokens</option>
                    <option value="meta-llama/llama-3.1-70b-instruct">Llama 3.1 70B — 131K tokens</option>
                  </optgroup>
                  <optgroup label="Other">
                    {models.filter(m => m.id !== aiModel).map(m => (
                      <option key={m.id} value={m.id}>{m.name} — {(m.context_length || 0).toLocaleString()} tokens</option>
                    ))}
                  </optgroup>
                </select>
              </div>
            </div>

            {/* Templates */}
            <div className="mb-2">
              <button onClick={() => setShowTemplates(!showTemplates)} className="text-sm text-indigo-400 hover:text-indigo-300">
                📋 {showTemplates ? 'Hide templates' : 'Use a template'}
              </button>
            </div>
            {showTemplates && (
              <div className="mb-4 grid grid-cols-2 gap-2">
                {PROMPT_TEMPLATES.map((template, i) => (
                  <button key={i} onClick={() => applyTemplate(template)}
                    className="p-3 bg-gray-800 border border-gray-700 rounded-lg text-left hover:border-indigo-500 transition">
                    <div className="font-medium text-gray-100">{template.name}</div>
                    <p className="text-xs text-gray-500">{template.description}</p>
                  </button>
                ))}
              </div>
            )}

            {/* Prompt Text Editor */}
            <label className="block text-sm font-medium text-gray-300 mb-1">Prompt Instructions</label>
            <textarea
              className="flex-1 min-h-[200px] bg-gray-700 border border-gray-600 rounded-lg p-4 font-mono text-sm resize-none text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              value={body} onChange={e => setBody(e.target.value)}
              placeholder="Write your prompt instructions here...&#10;&#10;Tell the AI how to process the video transcript." />

            {/* JSON Routing Editor */}
            <div className="mt-4">
              <div className="flex items-center justify-between mb-1">
                <label className="block text-sm font-medium text-gray-300">JSON Routing Block</label>
                {jsonError
                  ? <span className="text-xs text-red-400">❌ {jsonError}</span>
                  : <span className="text-xs text-green-400">✅ Valid</span>}
              </div>
              <textarea
                className={'w-full h-32 bg-gray-900 border rounded-lg p-4 font-mono text-sm resize-none text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent ' +
                  (jsonError ? 'border-red-500' : 'border-gray-600')}
                value={routingJson} onChange={e => handleRoutingChange(e.target.value)}
                placeholder='{"message": "...", "telegram_bots": [], "web_views": [], "visibility": true}' />
              <p className="text-xs text-gray-500 mt-1">
                This JSON block tells the system where to route the AI response. It is appended to your prompt automatically.
              </p>
            </div>

            {/* Save */}
            <div className="mt-3 flex justify-end">
              <button onClick={save} disabled={saving || !!jsonError}
                className="bg-indigo-600 text-white px-6 py-2 rounded-lg hover:bg-indigo-500 disabled:opacity-50 font-medium">
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>

            {/* Test Section */}
            <div className="mt-6 p-4 bg-gray-800 border border-gray-700 rounded-lg">
              <h3 className="font-medium text-gray-100 mb-3">🧪 Test Prompt</h3>
              <p className="text-sm text-gray-400 mb-3">Test this prompt with a YouTube video to preview the AI response.</p>
              <div className="flex gap-2">
                <input className="flex-1 bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  placeholder="YouTube video URL" value={testVideoUrl} onChange={e => setTestVideoUrl(e.target.value)} />
                <button onClick={runTest} disabled={testing || !testVideoUrl || !!jsonError}
                  className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-500 disabled:opacity-50 font-medium whitespace-nowrap">
                  {testing ? '⏳ Processing...' : '▶ Run Test'}
                </button>
              </div>
              {testResult && (
                <div className="mt-4 space-y-3">
                  {testResult.error && (
                    <div className="p-3 bg-red-900/50 border border-red-700 rounded-lg">
                      <p className="text-sm text-red-300">{testResult.error}</p>
                    </div>
                  )}
                  {testResult.fullPrompt && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-300 mb-1">📤 Full Prompt Sent to AI</h4>
                      <pre className="bg-gray-900 p-3 rounded-lg text-xs max-h-60 overflow-y-auto whitespace-pre-wrap text-indigo-300 border border-gray-700">{testResult.fullPrompt}</pre>
                    </div>
                  )}
                  {testResult.transcript && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-300 mb-1">📜 Raw Transcript</h4>
                      <pre className="bg-gray-900 p-3 rounded-lg text-xs max-h-40 overflow-y-auto whitespace-pre-wrap text-gray-400 border border-gray-700">{testResult.transcript}</pre>
                    </div>
                  )}
                  {testResult.response && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-300 mb-1">📥 Complete AI Response (raw)</h4>
                      <pre className="bg-gray-900 p-3 rounded-lg text-sm max-h-80 overflow-y-auto whitespace-pre-wrap text-gray-100 border border-gray-700">{testResult.response}</pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <span className="text-4xl">📝</span>
              <p className="text-gray-400 mt-2">Select a prompt from the left to edit</p>
              <p className="text-sm text-gray-500 mt-1">or create a new one below</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
