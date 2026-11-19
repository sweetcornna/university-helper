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
      <div role="alert" className="flex min-h-screen items-center justify-center bg-background p-6">
        <div className="ui-index-card w-full max-w-md space-y-4 p-6">
          <h1 className="font-display text-xl font-bold text-text">页面出现了一点意外</h1>
          <p className="ui-well break-words px-3 py-2 font-code text-xs text-text-muted">
            {error?.message || '未知错误'}
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <button type="button" onClick={this.reset} className="ui-btn-primary">
              重试
            </button>
            <button type="button" onClick={() => window.location.assign('/login')} className="ui-btn-secondary">
              回到登录
            </button>
          </div>
        </div>
      </div>
    )
  }
}
