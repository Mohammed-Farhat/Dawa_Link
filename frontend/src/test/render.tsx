import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import axe from 'axe-core'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { theme } from '../theme/theme'

/** Renders a screen inside the same providers the real app uses. */
export function renderApp(ui: ReactNode, { path = '/' }: { path?: string } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MantineProvider theme={theme} forceColorScheme="light">
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  )
}

/** The accessibility problems axe finds in a rendered screen (docs/11 §9). */
export async function accessibilityProblems(container: HTMLElement): Promise<string[]> {
  const results = await axe.run(container, {
    // jsdom doesn't lay out or paint, so color contrast can't be computed here.
    rules: { 'color-contrast': { enabled: false } },
  })
  return results.violations.map((violation) => `${violation.id}: ${violation.help}`)
}

/** Makes the next API calls answer with this JSON body. */
export function apiAnswers(body: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
  )
}

export function apiIsUnreachable() {
  return vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
}
