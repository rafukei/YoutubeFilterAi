import { Outlet, Link, useLocation } from 'react-router-dom'

interface LayoutProps {
  onLogout: () => void
  isAdmin?: boolean
}

export default function Layout({ onLogout, isAdmin }: LayoutProps) {
  const location = useLocation()
  
  const navLinks = isAdmin
    ? [
        { to: '/admin/users', label: 'Users', icon: '👥' },
        { to: '/admin/settings', label: 'Settings', icon: '⚙️' },
      ]
    : [
        { to: '/', label: 'Home', icon: '🏠' },
        { to: '/summary', label: 'Summaries', icon: '📋' },
        { to: '/prompts', label: 'Prompts', icon: '📝' },
        { to: '/channels', label: 'Channels', icon: '📺' },
        { to: '/bots', label: 'Telegram', icon: '🤖' },
        { to: '/settings', label: 'Settings', icon: '⚙️' },
      ]

  return (
    <div className="min-h-screen flex flex-col bg-gray-900">
      <nav className="bg-gray-800 text-gray-100 px-6 py-3 flex items-center gap-1 border-b border-gray-700">
        <Link to="/" className="font-bold text-lg text-indigo-400 mr-6">
          📺 YoutubeFilterAi
        </Link>
        {navLinks.map((l) => (
          <Link
            key={l.to}
            to={l.to}
            className={`px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 text-sm ${
              location.pathname === l.to
                ? 'bg-indigo-600 text-white'
                : 'hover:bg-gray-700 text-gray-300'
            }`}
          >
            <span>{l.icon}</span>
            <span>{l.label}</span>
          </Link>
        ))}
        <button
          onClick={onLogout}
          className="ml-auto px-3 py-1.5 text-sm text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded-lg transition-colors"
        >
          Log out
        </button>
      </nav>
      <main className="flex-1 p-6 bg-gray-900">
        <Outlet />
      </main>
    </div>
  )
}
