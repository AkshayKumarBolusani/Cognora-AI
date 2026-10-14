import { Component, type ErrorInfo, type ReactNode } from 'react'

type State = { error: Error | null }

export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Cognora rendering error', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <main className="render-error" role="alert">
          <h1>This view could not be displayed</h1>
          <p>{this.state.error.message || 'An unexpected rendering error occurred.'}</p>
          <button onClick={() => window.location.reload()}>Reload Cognora</button>
        </main>
      )
    }
    return this.props.children
  }
}
