import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { strings } from '../strings/en'
import { accessibilityProblems } from '../test/render'
import { Pager } from './Pager'
import { offsetOf, PAGE_MAX, PAGE_ROWS, pageCount, pagerItems, readPage, usePage } from './usePage'

const s = strings.pager

/** A list page as the portals build one: its page in the address, the pager under it. */
function List({ total, settled = true }: { total: number | undefined; settled?: boolean }) {
  const paging = usePage()
  const { search } = useLocation()
  const navigate = useNavigate()
  return (
    <main>
      <h1>A list</h1>
      <p data-testid="address">{search}</p>
      <p data-testid="offset">{paging.offset}</p>
      <button type="button" onClick={() => paging.choose('status', 'OPEN')}>
        Only the open ones
      </button>
      <button type="button" onClick={() => navigate(-1)}>
        Go back
      </button>
      <button type="button" onClick={() => paging.setPage(1)}>
        Page one again
      </button>
      <button type="button" onClick={() => paging.firstPage()}>
        A letter typed
      </button>
      <Pager paging={paging} total={total} settled={settled} />
    </main>
  )
}

function show(total: number | undefined, path = '/list', settled = true) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <List total={total} settled={settled} />
    </MemoryRouter>,
  )
}

const address = () => screen.getByTestId('address').textContent
const pager = () => screen.getByRole('navigation', { name: s.label })
const current = () => within(pager()).getByRole('button', { current: 'page' })

describe('The numbers of a page', () => {
  it('reads only a whole page number from the address, and never one the API would refuse', () => {
    for (const odd of [null, '', 'abc', '0', '-3', '2.5', '1e9', ' 2', '0x10', '9999999999']) {
      expect(readPage(odd), String(odd)).toBe(1)
    }
    expect(readPage('3')).toBe(3)
    expect(readPage('999999')).toBe(PAGE_MAX)
    // The last page the API can reach skips no more than its 1,000,000 rows.
    expect(offsetOf(PAGE_MAX)).toBeLessThanOrEqual(1_000_000)
  })

  it('counts the pages, one at least, and the rows a page skips', () => {
    expect(PAGE_ROWS).toBe(25)
    expect([pageCount(0), pageCount(1), pageCount(25), pageCount(26), pageCount(134)]).toEqual([1, 1, 1, 2, 6])
    expect([offsetOf(1), offsetOf(2), offsetOf(7)]).toEqual([0, 25, 150])
  })

  it('shows the first, the last, and the page with its neighbours; a gap is never one page', () => {
    expect(pagerItems(1, 1)).toEqual([1])
    expect(pagerItems(4, 7)).toEqual([1, 2, 3, 4, 5, 6, 7])
    expect(pagerItems(1, 12)).toEqual([1, 2, 'gap', 12])
    expect(pagerItems(4, 12)).toEqual([1, 2, 3, 4, 5, 'gap', 12])
    expect(pagerItems(6, 12)).toEqual([1, 'gap', 5, 6, 7, 'gap', 12])
    expect(pagerItems(12, 12)).toEqual([1, 'gap', 11, 12])
  })
})

describe('The pager', () => {
  it('shows nothing while the total is not known, for an empty list, or when one page holds everything', () => {
    for (const total of [undefined, 0, 1, PAGE_ROWS]) {
      const { unmount } = show(total)
      expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
      unmount()
    }
  })

  it('on the first page: Previous does nothing, page 1 is the one shown, and the total is said', async () => {
    show(134)
    expect(current()).toHaveAccessibleName(s.page(1))
    expect(screen.getByText('Page 1 of 6 · 134 in all')).toBeInTheDocument()
    const previous = within(pager()).getByRole('button', { name: s.previous })
    expect(previous).toHaveAttribute('aria-disabled', 'true')

    await userEvent.setup().click(previous)
    expect(address()).toBe('')
  })

  it('in the middle: the numbers around the page, the right rows asked for', () => {
    show(300, '/list?page=6')
    const names = within(pager())
      .getAllByRole('button')
      .map((button) => button.getAttribute('aria-label') ?? button.textContent)
    expect(names).toEqual([s.previous, s.page(1), s.page(5), s.page(6), s.page(7), s.page(12), s.next])
    expect(current()).toHaveAccessibleName(s.page(6))
    expect(screen.getByTestId('offset')).toHaveTextContent('125')
    expect(screen.getByText('Page 6 of 12 · 300 in all')).toBeInTheDocument()
  })

  it('on the last page: Next does nothing', async () => {
    show(300, '/list?page=12')
    const next = within(pager()).getByRole('button', { name: s.next })
    expect(next).toHaveAttribute('aria-disabled', 'true')
    await userEvent.setup().click(next)
    expect(address()).toBe('?page=12')
  })

  it('keeps the page in the address, never as ?page=1, and keeps the list’s own choices', async () => {
    show(134, '/list?status=OPEN')
    const user = userEvent.setup()

    await user.click(within(pager()).getByRole('button', { name: s.next }))
    expect(address()).toBe('?status=OPEN&page=2')
    await user.click(within(pager()).getByRole('button', { name: s.page(4) }))
    expect(address()).toBe('?status=OPEN&page=4')
    await user.click(within(pager()).getByRole('button', { name: s.page(1) }))
    expect(address()).toBe('?status=OPEN')
  })

  it('goes back a page with the browser’s Back, as most websites do', async () => {
    show(134)
    const user = userEvent.setup()
    await user.click(within(pager()).getByRole('button', { name: s.next }))
    await user.click(within(pager()).getByRole('button', { name: s.next }))
    expect(address()).toBe('?page=3')

    await user.click(screen.getByRole('button', { name: 'Go back' }))
    expect(address()).toBe('?page=2')
    expect(current()).toHaveAccessibleName(s.page(2))
  })

  it('adds no step to the history for the page already shown, nor for a box typed in', async () => {
    render(
      <MemoryRouter initialEntries={['/before', '/list']} initialIndex={1}>
        <Routes>
          <Route path="/before" element={<p>The page before</p>} />
          <Route path="/list" element={<List total={134} />} />
        </Routes>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    for (let typed = 0; typed < 3; typed++) await user.click(screen.getByRole('button', { name: 'Page one again' }))
    await user.click(within(pager()).getByRole('button', { name: s.page(1) }))
    await user.click(within(pager()).getByRole('button', { name: s.page(3) }))
    // Each letter typed goes back to page 1 in place of page 3, never as a new step.
    for (let typed = 0; typed < 3; typed++) await user.click(screen.getByRole('button', { name: 'A letter typed' }))
    expect(address()).toBe('')

    // Back: page 1 as it was before page 3, then the page before the list.
    await user.click(screen.getByRole('button', { name: 'Go back' }))
    expect(address()).toBe('')
    expect(screen.getByTestId('offset')).toHaveTextContent('0')
    await user.click(screen.getByRole('button', { name: 'Go back' }))
    expect(screen.getByText('The page before')).toBeInTheDocument()
  })

  it('goes back to page 1 in the same change that sets a choice of the list', async () => {
    show(134, '/list?page=3')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Only the open ones' }))
    expect(address()).toBe('?status=OPEN')
    expect(screen.getByTestId('offset')).toHaveTextContent('0')
  })

  it('moves an address past the last page to the last one, once the answer is the real one', () => {
    const { unmount } = show(134, '/list?page=99', false)
    // An answer kept on the screen from other choices doesn't count.
    expect(address()).toBe('?page=99')
    expect(current()).toHaveAccessibleName(s.page(6))
    unmount()

    show(134, '/list?page=99')
    expect(address()).toBe('?page=6')
  })

  it('works with the keyboard, and keeps the focus on the button pressed, the last page included', async () => {
    show(60)
    const user = userEvent.setup()
    const next = within(pager()).getByRole('button', { name: s.next })
    next.focus()

    await user.keyboard('{Enter}')
    expect(address()).toBe('?page=2')
    await user.keyboard(' ')
    expect(address()).toBe('?page=3')
    // Page 3 of 3: Next does nothing now, and still has the focus.
    expect(next).toHaveFocus()
    expect(next).toHaveAttribute('aria-disabled', 'true')

    await user.tab({ shift: true })
    expect(within(pager()).getByRole('button', { name: s.page(3) })).toHaveFocus()
  })

  it('has no accessibility problem axe can find', async () => {
    const { container } = show(300, '/list?page=6')
    expect(await accessibilityProblems(container)).toEqual([])
  })
})
