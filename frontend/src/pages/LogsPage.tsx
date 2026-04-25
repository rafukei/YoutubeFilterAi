import React, { useEffect, useState } from 'react'
import api from '../api'

const LEVEL_COLORS: Record<string, string> = {
  ERROR: 'bg-red-700 text-red-100',
  WARNING: 'bg-yellow-700 text-yellow-100',
  INFO: 'bg-blue-800 text-blue-100',
  DEBUG: 'bg-gray-700 text-gray-200',
}

interface Log {
  id: string
  level: string
  source: string
  message: string
  details?: string
  created_at: string
}

export default function LogsPage() {
  const [logs, setLogs] = useState<Log[]>([])
  const [level, setLevel] = useState('')
  const [source, setSource] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchLogs = async () => {
    setLoading(true)
    setError('')
    try {
      const params: any = {}
      if (level) params.level = level
      if (source) params.source = source
      const { data } = await api.get('/logs', { params })
      setLogs(data)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to load logs')
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchLogs()
    const interval = setInterval(fetchLogs, 5000)
    return () => clearInterval(interval)
    // eslint-disable-next-line
  }, [level, source])

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold mb-4 text-indigo-300">Activity Log</h1>
      <div className="flex gap-4 mb-4">
        <select value={level} onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setLevel(e.target.value)} className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-100">
          <option value="">All levels</option>
          <option value="ERROR">Error</option>
          <option value="WARNING">Warning</option>
          <option value="INFO">Info</option>
          <option value="DEBUG">Debug</option>
        </select>
        <input value={source} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSource(e.target.value)} placeholder="Source (ai, telegram...)" className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-100" />
        <button onClick={fetchLogs} className="bg-indigo-600 hover:bg-indigo-500 text-white rounded px-4 py-1 font-semibold">Reload</button>
      </div>
      {error && <div className="text-red-400 mb-2">{error}</div>}
      <div className="space-y-2">
        {loading && <div className="text-gray-400">Loading…</div>}
        {logs.length === 0 && !loading && <div className="text-gray-400">No logs found.</div>}
        {logs.map(log => (
          <div key={log.id} className={`rounded-lg px-4 py-2 shadow border border-gray-700 flex flex-col gap-1 ${LEVEL_COLORS[log.level] || 'bg-gray-800 text-gray-100'}`}>
            <div className="flex gap-4 items-center text-xs">
              <span className="font-mono text-gray-300">{new Date(log.created_at).toLocaleString()}</span>
              <span className="font-bold uppercase tracking-wide">{log.level}</span>
              <span className="italic">{log.source}</span>
            </div>
            <div className="text-sm whitespace-pre-wrap">{log.message}</div>
            {log.details && <details className="text-xs mt-1"><summary className="cursor-pointer">Details</summary><pre>{log.details}</pre></details>}
          </div>
        ))}
      </div>
    </div>
  )
}
