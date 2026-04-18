import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'

interface Props { onLogin: (token: string) => void }

export default function AdminLoginPage({ onLogin }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setError('')
    try {
      const { data } = await api.post('/admin/login', { username, password })
      onLogin(data.access_token)
      navigate('/admin/users')
    } catch { setError('Invalid admin credentials') }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-900">
      <form onSubmit={submit} className="bg-gray-800 text-white rounded-2xl shadow-xl p-8 w-full max-w-md space-y-4">
        <h1 className="text-2xl font-bold text-center">Admin Login</h1>
        {error && <p className="text-red-400 text-sm text-center">{error}</p>}
  <input className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2" placeholder="Admin username" value={username} onChange={e => setUsername(e.target.value)} />
        <input className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2" type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} />
        <button className="w-full bg-red-600 text-white rounded-lg py-2 hover:bg-red-700" type="submit">Login</button>
      </form>
    </div>
  )
}
