import { useState } from 'react'
import api from '../api'

interface Props { onLogin: (token: string) => void }

export default function LoginPage({ onLogin }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isRegister, setIsRegister] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const url = isRegister ? '/auth/register' : '/auth/login'
      const { data } = await api.post(url, { email, password })
      onLogin(data.access_token)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900">
      <form onSubmit={submit} className="bg-gray-800 border border-gray-700 rounded-2xl shadow-xl p-8 w-full max-w-md space-y-4">
        <h1 className="text-2xl font-bold text-center text-indigo-400">YoutubeFilterAi</h1>
        <p className="text-center text-gray-400">{isRegister ? 'Create account' : 'Sign in'}</p>
        {error && <p className="text-red-400 text-sm text-center">{error}</p>}
        <input 
          className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-gray-100 placeholder-gray-400 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none" 
          placeholder="Email" 
          value={email} 
          onChange={e => setEmail(e.target.value)} 
        />
        <input 
          className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2 text-gray-100 placeholder-gray-400 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none" 
          type="password" 
          placeholder="Password" 
          value={password} 
          onChange={e => setPassword(e.target.value)} 
        />
        <button className="w-full bg-indigo-600 text-white rounded-lg py-2 hover:bg-indigo-500 transition-colors font-semibold" type="submit">
          {isRegister ? 'Register' : 'Login'}
        </button>
        <p className="text-sm text-center text-gray-400">
          <button type="button" className="text-indigo-400 hover:text-indigo-300" onClick={() => setIsRegister(!isRegister)}>
            {isRegister ? 'Already have an account? Login' : "Don't have an account? Register"}
          </button>
        </p>
      </form>
    </div>
  )
}
