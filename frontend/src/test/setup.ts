import '@testing-library/jest-dom/vitest'

import { cleanup, configure } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// The first test of a file also loads the part of the website it opens (the pharmacy's
// portal, the admin's console). On a busy laptop that alone can take the default second,
// and a test then fails for a reason that has nothing to do with what it checks.
configure({ asyncUtilTimeout: 3000 })

afterEach(() => {
  cleanup()
  // No test starts logged in because of the one before it.
  window.localStorage.clear()
  // Nor with what a page kept in this tab's storage (the reset link's token, the note
  // that an account was deleted).
  window.sessionStorage.clear()
})

// jsdom lacks these browser features, which Mantine reads.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }),
})

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver

vi.stubEnv('VITE_API_URL', 'http://api.test')
