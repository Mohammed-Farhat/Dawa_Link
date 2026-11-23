import { afterEach, describe, expect, it, vi } from 'vitest'

import { RELOAD_GUARD_MS, reloadOnceWhenAPartFails } from './reload'

function partFails(): Event {
  const event = new Event('vite:preloadError', { cancelable: true })
  window.dispatchEvent(event)
  return event
}

describe('A part of the website that is gone after a release (A#4)', () => {
  let stop = () => {}
  afterEach(() => {
    stop()
    window.sessionStorage.clear()
  })

  it('reloads the page once, and the failure is not thrown to the page', () => {
    const reload = vi.fn()
    stop = reloadOnceWhenAPartFails(reload, () => 1_000_000)

    const event = partFails()

    expect(reload).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
  })

  it('never reloads in a loop: a second failure goes on to the page, which offers the button', () => {
    const reload = vi.fn()
    let now = 1_000_000
    stop = reloadOnceWhenAPartFails(reload, () => now)

    partFails()
    now += RELOAD_GUARD_MS - 1
    const second = partFails()

    expect(reload).toHaveBeenCalledTimes(1)
    expect(second.defaultPrevented).toBe(false)
  })

  it('reloads again for a later release', () => {
    const reload = vi.fn()
    let now = 1_000_000
    stop = reloadOnceWhenAPartFails(reload, () => now)

    partFails()
    now += RELOAD_GUARD_MS + 1
    partFails()

    expect(reload).toHaveBeenCalledTimes(2)
  })
})
