import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    if (import.meta.env.DEV) {
      console.error('[ErrorBoundary]', error, info)
    }
  }

  reset = () => this.setState({ error: null })

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div role="alert" className="min-h-screen flex items-center justify-center p-6 bg-background">
        <div className="max-w-md w-full text-center space-y-4">
          <h1 className="text-2xl font-bold text-text">页面出现了一点意外</h1>
          <p className="text-sm text-text-muted break-words">
            {error?.message || '未知错误'}
          </p>
          <div className="flex gap-3 justify-center pt-2">
            <button
              type="button"
              onClick={this.reset}
              className="px-4 py-2 rounded-lg bg-primary text-white hover:opacity-90"
            >
              重试
            </button>
            <button
              type="button"
              onClick={() => window.location.assign('/login')}
              className="px-4 py-2 rounded-lg border border-border hover:bg-surface-hover"
            >
              回到登录
            </button>
          </div>
        </div>
      </div>
    )
  }
}
