import { Component, type ErrorInfo, type ReactNode } from 'react'

import { strings } from '../strings/en'

const s = strings.shell

type Props = {
  children: ReactNode
  /** The page's address: moving to another page tries again (the back button works). */
  at: string
}

/**
 * Around every page: a part of the website that fails to load (after a new release) or
 * to show leaves a plain page that says so, with a button to reload, never a white
 * screen (A#4).
 */
export class PageError extends Component<Props, { failed: boolean; at: string }> {
  state = { failed: false, at: this.props.at }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  static getDerivedStateFromProps(props: Props, state: { at: string }) {
    return props.at === state.at ? null : { failed: false, at: props.at }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    // The browser's console only: nothing about the person is in it.
    console.error('page_failed', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main className="screen screen--plain" id="main" tabIndex={-1}>
        <h1 className="page-title">{s.reloadTitle}</h1>
        <p className="soft">{s.reloadBody}</p>
        <button
          type="button"
          className="pill-button"
          style={{ alignSelf: 'flex-start' }}
          onClick={() => window.location.reload()}
        >
          {s.reload}
        </button>
      </main>
    )
  }
}
