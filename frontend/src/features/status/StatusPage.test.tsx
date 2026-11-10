import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { strings } from '../../strings/en'
import { accessibilityProblems, apiAnswers, apiIsUnreachable, renderApp } from '../../test/render'
import { StatusPage } from './StatusPage'

const s = strings.status

describe('StatusPage', () => {
  it('says everything is running when the API and the database answer', async () => {
    const fetchSpy = apiAnswers({ status: 'ok', db: 'ok', version: '1a2b3c' })

    renderApp(<StatusPage />)

    expect(await screen.findByText(s.allGood)).toBeInTheDocument()
    expect(screen.getByText(s.version('1a2b3c'))).toBeInTheDocument()
    const request = fetchSpy.mock.calls[0][0] as Request
    expect(request.url).toBe('http://api.test/api/v1/health')
  })

  it('says the database is down when the API reports it', async () => {
    apiAnswers({ status: 'degraded', db: 'down', version: '1a2b3c' })

    renderApp(<StatusPage />)

    expect(await screen.findByText(s.databaseDown)).toBeInTheDocument()
    expect(screen.queryByText(s.allGood)).not.toBeInTheDocument()
  })

  it("says the API can't be reached when the call fails", async () => {
    apiIsUnreachable()

    renderApp(<StatusPage />)

    expect(await screen.findByText(s.apiDown)).toBeInTheDocument()
  })

  it('checks again when asked', async () => {
    apiIsUnreachable()
    renderApp(<StatusPage />)
    await screen.findByText(s.apiDown)
    apiAnswers({ status: 'ok', db: 'ok', version: '1a2b3c' })

    await userEvent.click(screen.getByRole('button', { name: s.retry }))

    expect(await screen.findByText(s.allGood)).toBeInTheDocument()
  })

  it('has no accessibility problems', async () => {
    apiAnswers({ status: 'ok', db: 'ok', version: '1a2b3c' })
    const { container } = renderApp(<StatusPage />)
    await screen.findByText(s.allGood)

    expect(await accessibilityProblems(container)).toEqual([])
  })
})
