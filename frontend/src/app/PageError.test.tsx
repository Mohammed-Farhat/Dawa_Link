import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { strings } from '../strings/en'
import { accessibilityProblems, loggedIn, pretendApi, renderApp } from '../test/render'
import { ADMIN } from '../test/admin'
import { AppRoutes } from './App'

// The admin's console is a part loaded on demand. Here it is gone, as after a release
// that removed the file the open tab asks for.
vi.mock('../features/admin/AdminPortal', () => {
  throw new TypeError('Failed to fetch dynamically imported module')
})

describe('A part of the website that fails to load (A#4)', () => {
  it('says the page needs reloading, with the button, never a white page', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    loggedIn()
    pretendApi({ 'GET /api/v1/auth/me': ADMIN })

    const { container } = renderApp(<AppRoutes />, { path: '/admin' })

    expect(await screen.findByRole('heading', { name: strings.shell.reloadTitle })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: strings.shell.reload })).toBeInTheDocument()
    expect(await accessibilityProblems(container)).toEqual([])
  })
})
