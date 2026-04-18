import { useState, useEffect } from 'react'
import api from '../api'

interface User { id: string; email: string; is_active: boolean; is_approved: boolean; created_at: string }

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [newEmail, setNewEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const load = () => api.get('/admin/users').then(r => setUsers(r.data))
  useEffect(() => { load() }, [])

  const toggle = async (id: string, field: 'is_approved' | 'is_active', value: boolean) => {
    await api.patch(`/admin/users/${id}`, null, { params: { [field]: value } })
    load()
  }

  const createUser = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(''); setSuccess('')
    if (!newEmail || !newPassword) return
    try {
      await api.post('/admin/users', { email: newEmail, password: newPassword })
      setSuccess(`User ${newEmail} created!`)
      setNewEmail(''); setNewPassword('')
      load()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create user')
    }
  }

  const deleteUser = async (id: string, email: string) => {
    if (!confirm(`Delete user ${email}? This will remove ALL their data.`)) return
    await api.delete(`/admin/users/${id}`)
    load()
  }

  return (
    <div className="max-w-3xl mx-auto">
      <h2 className="text-xl font-bold mb-4 text-gray-100">User Management</h2>
      
      {/* Create user form */}
      <form onSubmit={createUser} className="bg-gray-800 rounded-lg shadow border border-gray-700 p-4 mb-6">
        <h3 className="font-semibold mb-3 text-gray-100">Create New User</h3>
        {error && <p className="text-red-400 text-sm mb-2">{error}</p>}
        {success && <p className="text-green-400 text-sm mb-2">{success}</p>}
        <div className="flex gap-2">
          <input 
            className="bg-gray-700 border border-gray-600 rounded px-3 py-2 flex-1 text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent" 
            placeholder="Email" 
            type="email"
            value={newEmail} 
            onChange={e => setNewEmail(e.target.value)} 
          />
          <input 
            className="bg-gray-700 border border-gray-600 rounded px-3 py-2 flex-1 text-gray-100 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent" 
            placeholder="Password (min 8 chars)" 
            type="password"
            value={newPassword} 
            onChange={e => setNewPassword(e.target.value)} 
          />
          <button type="submit" className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-500">
            Create
          </button>
        </div>
      </form>

      {/* Users table */}
      <table className="w-full bg-gray-800 rounded-lg shadow border border-gray-700 text-sm">
        <thead className="bg-gray-700">
          <tr>
            <th className="p-2 text-left text-gray-100">Email</th>
            <th className="text-gray-100">Active</th>
            <th className="text-gray-100">Approved</th>
            <th className="text-gray-100">Registered</th>
            <th className="text-gray-100">Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.map(u => (
            <tr key={u.id} className="border-t border-gray-700">
              <td className="p-2 text-gray-100">{u.email}</td>
              <td className="text-center">
                <input type="checkbox" checked={u.is_active} onChange={e => toggle(u.id, 'is_active', e.target.checked)} className="h-4 w-4 text-indigo-500 rounded border-gray-600 bg-gray-700 focus:ring-indigo-500" />
              </td>
              <td className="text-center">
                <input type="checkbox" checked={u.is_approved} onChange={e => toggle(u.id, 'is_approved', e.target.checked)} className="h-4 w-4 text-indigo-500 rounded border-gray-600 bg-gray-700 focus:ring-indigo-500" />
              </td>
              <td className="text-center text-xs text-gray-400">{new Date(u.created_at).toLocaleDateString()}</td>
              <td className="text-center">
                <button onClick={() => deleteUser(u.id, u.email)} className="text-red-400 text-xs hover:underline">Delete</button>
              </td>
            </tr>
          ))}
          {users.length === 0 && (
            <tr><td colSpan={5} className="text-center py-4 text-gray-500">No users yet</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
