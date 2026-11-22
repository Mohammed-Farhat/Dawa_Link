import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { parseEvent } from '../../api/chatStream'
import { AppRoutes } from '../../app/App'
import { dayAndClock, directionsUrl, lbp } from '../../format'
import { strings } from '../../strings/en'
import {
  accessibilityProblems,
  CLIENT,
  CONFIG,
  loggedIn,
  pretendApi,
  refusal,
  renderApp,
  RESERVATION,
} from '../../test/render'

const s = strings.ticket
const PATH = `/reservations/${RESERVATION.id}`

describe('The pickup ticket', () => {
  it('shows the order number, what to pay and what is saved', async () => {
    loggedIn()
    pretendApi({ 'GET /api/v1/auth/me': CLIENT, [`GET /api/v1${PATH}`]: RESERVATION })

    const { container } = renderApp(<AppRoutes />, { path: PATH })

    expect(await screen.findByText('R-7K3Q2F')).toBeInTheDocument()
    expect(screen.getByText('600,000 LBP')).toBeInTheDocument()
    expect(screen.getByText('400,000 LBP')).toBeInTheDocument()
    expect(screen.getByText(s.prescription)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: s.call })).toHaveAttribute('href', 'tel:+961 1 000 000')
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it("opens directions to the pharmacy's pin, and never says where the client is", async () => {
    loggedIn()
    pretendApi({ 'GET /api/v1/auth/me': CLIENT, [`GET /api/v1${PATH}`]: RESERVATION })
    renderApp(<AppRoutes />, { path: PATH })

    // Its spoken name starts with its visible word, and says that it opens a new tab.
    const link = await screen.findByRole('link', { name: `${s.directions} ${strings.common.opensNewTab}` })

    // Google Maps, with the pharmacy as the destination and nothing else (BLD-D43):
    // the map fills "from" itself, on the client's own device.
    expect(link).toHaveAttribute('href', directionsUrl(RESERVATION.pharmacy.pin))
    expect(link).toHaveAttribute(
      'href',
      'https://www.google.com/maps/dir/?api=1&destination=33.897%2C35.484',
    )
    expect(link.getAttribute('href')).not.toMatch(/origin=|from=/)
    expect(link).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
  })

  it('cancels after asking, and then says it is cancelled', async () => {
    loggedIn()
    const api = pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      [`GET /api/v1${PATH}`]: RESERVATION,
      [`POST /api/v1${PATH}/cancel`]: {
        ...RESERVATION,
        state: 'CANCELLED_BY_CLIENT',
        status_text: 'Cancelled by you',
      },
      'GET /api/v1/reservations': { items: [], next_cursor: null, server_now: CONFIG.server_now },
    })
    renderApp(<AppRoutes />, { path: PATH })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: s.cancel }))
    expect(api.sent('POST', '/api/v1/reservations')).toEqual([])
    await user.click(await screen.findByRole('button', { name: s.cancelConfirm }))

    expect(await screen.findByText('Cancelled by you')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: s.cancel })).not.toBeInTheDocument()
  })

  it('names what the page is in its heading (A#39)', async () => {
    loggedIn()
    pretendApi({ 'GET /api/v1/auth/me': CLIENT, [`GET /api/v1${PATH}`]: RESERVATION })
    renderApp(<AppRoutes />, { path: PATH })

    expect(await screen.findByRole('heading', { level: 1, name: s.header })).toBeInTheDocument()
    expect(screen.getByText(s.pay)).toBeInTheDocument()
  })

  it('says first that a reservation is no longer waiting, with no "show this at the counter" (A#36)', async () => {
    loggedIn()
    // The server's older words: the page calls it a missed pickup all the same (B#13).
    const missed = {
      ...RESERVATION,
      state: 'EXPIRED_NO_SHOW',
      status_text: "Expired: it wasn't picked up in time",
      deadline: null,
    }
    pretendApi({ 'GET /api/v1/auth/me': CLIENT, [`GET /api/v1${PATH}`]: missed })
    const { container } = renderApp(<AppRoutes />, { path: PATH })

    expect(await screen.findByRole('heading', { level: 1, name: s.ended.EXPIRED_NO_SHOW })).toBeInTheDocument()
    expect(screen.getByText(s.missedPickup)).toBeInTheDocument()
    expect(screen.queryByText(/^Expired/)).not.toBeInTheDocument()
    expect(screen.queryByText(s.header)).not.toBeInTheDocument()
    expect(screen.queryByText(s.pay)).not.toBeInTheDocument()
    expect(screen.queryByText(s.youSave)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: s.cancel })).not.toBeInTheDocument()
    // Directions and Call are still there, as plain buttons.
    expect(screen.getByRole('link', { name: new RegExp(`^${s.directions}`) })).toHaveClass('pill-button--dark')
    expect(screen.getByRole('link', { name: s.call })).toHaveClass('pill-button--dark')
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('goes Home on Close when the ticket was opened straight from a link', async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': CLIENT,
      [`GET /api/v1${PATH}`]: RESERVATION,
      'GET /api/v1/reservations': { items: [], next_cursor: null, server_now: CONFIG.server_now },
    })
    renderApp(<AppRoutes />, { path: PATH })

    await userEvent.click(await screen.findByRole('button', { name: strings.common.close }))

    expect(await screen.findByRole('heading', { name: strings.home.title })).toBeInTheDocument()
  })

  it("says so when the reservation isn't the client's", async () => {
    loggedIn()
    pretendApi({ 'GET /api/v1/auth/me': CLIENT, [`GET /api/v1${PATH}`]: refusal(404, 'NOT_FOUND') })

    renderApp(<AppRoutes />, { path: PATH })

    expect(await screen.findByRole('alert')).toHaveTextContent(s.notFound)
  })
})

describe('How things are written', () => {
  it('writes money with separators and times in Beirut time', () => {
    expect(lbp(1776000)).toBe('1,776,000 LBP')
    // 19:00 UTC is 21:00 in Beirut in November.
    expect(dayAndClock('2026-11-16T19:00:00Z', '2026-11-16T08:00:00Z')).toBe('Today 21:00')
    expect(dayAndClock('2026-11-17T08:00:00Z', '2026-11-16T08:00:00Z')).toBe('Tomorrow 10:00')
    expect(dayAndClock('2026-11-20T08:00:00Z', '2026-11-16T08:00:00Z')).toBe('Fri 20 Nov 10:00')
  })

  it('writes a deadline at midnight as the end of that day', () => {
    // 22:00 UTC is 00:00 the next day in Beirut: the pharmacy closes at midnight today.
    expect(dayAndClock('2026-11-16T22:00:00Z', '2026-11-16T08:00:00Z')).toBe('Today 24:00')
  })

  it('reads the events of a chat stream', () => {
    expect(parseEvent('event: progress\ndata: {"label": "Searching…"}')).toEqual({
      name: 'progress',
      data: { label: 'Searching…' },
    })
    expect(parseEvent(': heartbeat')).toBeNull()
  })
})
