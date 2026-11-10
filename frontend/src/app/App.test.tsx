import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { strings } from '../strings/en'
import { accessibilityProblems, apiAnswers, renderApp } from '../test/render'
import { AppRoutes } from './App'

describe('AppRoutes', () => {
  it('shows the status page at the home address', async () => {
    apiAnswers({ status: 'ok', db: 'ok', version: 'dev' })

    renderApp(<AppRoutes />, { path: '/' })

    expect(await screen.findByRole('heading', { name: strings.status.title })).toBeInTheDocument()
  })

  it('shows a clear page for an address that does not exist', async () => {
    const { container } = renderApp(<AppRoutes />, { path: '/no-such-page' })

    expect(screen.getByRole('heading', { name: strings.notFound.title })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: strings.notFound.back })).toHaveAttribute('href', '/')
    expect(await accessibilityProblems(container)).toEqual([])
  })
})
