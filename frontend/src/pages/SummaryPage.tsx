import { useState, useEffect } from 'react'
import api from '../api'

interface Message {
  id: string; source_video_url: string; source_video_title?: string;
  ai_response: string; visibility: boolean; created_at: string
}
interface WebView { id: string; name: string }

export default function SummaryPage() {
  const [views, setViews] = useState<WebView[]>([])
  const [activeView, setActiveView] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [showHidden, setShowHidden] = useState(false)

  useEffect(() => { api.get('/web-views').then(r => setViews(r.data)) }, [])
  useEffect(() => {
    const params: Record<string, string> = {}
    if (activeView) params.web_view_id = activeView
    if (showHidden) params.show_hidden = 'true'
    api.get('/messages', { params }).then(r => setMessages(r.data))
  }, [activeView, showHidden])

  const toggleVis = async (id: string) => {
    await api.patch(`/messages/${id}/visibility`)
    setMessages(msgs => msgs.map(m => m.id === id ? { ...m, visibility: !m.visibility } : m))
  }
  const del = async (id: string) => {
    await api.delete(`/messages/${id}`)
    setMessages(msgs => msgs.filter(m => m.id !== id))
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex gap-2 mb-4 flex-wrap">
        <button onClick={() => setActiveView(null)} className={`px-3 py-1 rounded-full text-sm ${!activeView ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}>All</button>
        {views.map(v => (
          <button key={v.id} onClick={() => setActiveView(v.id)} className={`px-3 py-1 rounded-full text-sm ${activeView === v.id ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}>{v.name}</button>
        ))}
        <label className="ml-auto flex items-center gap-1 text-sm text-gray-300">
          <input type="checkbox" checked={showHidden} onChange={e => setShowHidden(e.target.checked)} className="h-4 w-4 text-indigo-500 rounded border-gray-600 bg-gray-700 focus:ring-indigo-500" /> Show hidden
        </label>
      </div>
      <div className="space-y-3">
        {messages.map(m => (
          <div key={m.id} className={`p-4 rounded-xl shadow border ${m.visibility ? 'bg-gray-800 border-gray-700' : 'bg-gray-800/50 border-gray-700/50 opacity-60'}`}>
            <p className="whitespace-pre-wrap text-gray-100">{m.ai_response}</p>
            <div className="mt-2 flex items-center gap-3 text-xs text-gray-500">
              <a href={m.source_video_url} target="_blank" rel="noreferrer" className="text-indigo-400 hover:underline">🔗 Source video</a>
              <span>{new Date(m.created_at).toLocaleString()}</span>
              <button onClick={() => toggleVis(m.id)} className="hover:underline text-gray-400">{m.visibility ? 'Hide' : 'Show'}</button>
              <button onClick={() => del(m.id)} className="text-red-400 hover:underline">Delete</button>
            </div>
          </div>
        ))}
        {messages.length === 0 && <p className="text-center text-gray-500 py-12">No messages yet</p>}
      </div>
    </div>
  )
}
