import React from 'react'

type Props = { children: React.ReactNode }
type State = { hasError: boolean; errorMessage: string }

export default class AppErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false, errorMessage: '' }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      errorMessage: error?.message || 'Unknown frontend error',
    }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Frontend crashed:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-gray-900 text-gray-100 flex items-center justify-center p-6">
          <div className="max-w-xl w-full bg-gray-800 border border-red-700/60 rounded-xl p-6">
            <h1 className="text-xl font-bold text-red-300 mb-2">Frontend error</h1>
            <p className="text-gray-300 mb-3">
              The app crashed while rendering. Please refresh the page. If the problem continues, send this error message.
            </p>
            <pre className="text-xs whitespace-pre-wrap bg-gray-900 rounded p-3 border border-gray-700 text-red-200">
              {this.state.errorMessage}
            </pre>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
