import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../../app/App'
import { strings } from '../../strings/en'
import { BOX, PHARMACIST, PRIVATE_BOX, PROFILE, stockOf, UPLOAD } from '../../test/pharmacy'
import {
  accessibilityProblems,
  answer,
  CONFIG,
  loggedIn,
  pretendApi,
  refusal,
  renderApp,
  RESERVATION,
} from '../../test/render'

const s = strings.pharmacy
const stock = s.stock
const u = s.upload
const l = s.listing

function stockApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': PHARMACIST,
    'GET /api/v1/pharmacy/me': PROFILE,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/pharmacy/inventory': stockOf([BOX, PRIVATE_BOX]),
    'GET /api/v1/pharmacy/inventory/uploads/waiting': { upload: null },
    ...more,
  })
}

describe("The pharmacy's inventory (PS-6)", () => {
  it('lists every box with where it stands', async () => {
    stockApi()
    const { container } = renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })

    const listed = (await screen.findByText('A123')).closest('tr') as HTMLElement
    const kept = screen.getByText('Z9').closest('tr') as HTMLElement

    expect(within(listed).getByText(stock.zoneOf.NEAR_EXPIRY)).toBeInTheDocument()
    expect(within(listed).getByText(/20 days left/)).toBeInTheDocument()
    expect(within(kept).getByText(stock.zoneOf.EARLY_RELEASE)).toBeInTheDocument()
    expect(screen.getByText(stock.private)).toBeInTheDocument()
    // On a phone the medicine's column stays in place while the rest scrolls (global.css).
    expect(listed.closest('table')).toHaveClass('stock-table--pinned')
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('corrects a quantity in place, and says when reserved packs were kept', async () => {
    const api = stockApi({
      [`PATCH /api/v1/pharmacy/inventory/items/${BOX.id}`]: {
        item: { ...BOX, qty_on_hand: 2, qty_available: 0 },
        reserved_kept: true,
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    const quantity = await screen.findByLabelText(stock.quantityOf(BOX.product.name, 'A123'))
    // Five digits at most: never above what the API takes (100,000; A#35).
    expect(quantity).toHaveAttribute('maxlength', '5')
    expect(screen.queryByRole('button', { name: stock.saveQuantity })).not.toBeInTheDocument()
    await user.clear(quantity)
    await user.type(quantity, '0')
    await user.click(screen.getByRole('button', { name: stock.saveQuantity }))

    expect(await screen.findByText(stock.reservedKept(2))).toBeInTheDocument()
    expect(api.sent('PATCH', '/api/v1/pharmacy/inventory/items')[0].body).toEqual({ qty_on_hand: 0 })
  })

  it('asks the API for a zone or a name', async () => {
    const api = stockApi()
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: stock.zones.EARLY_RELEASE }))
    await user.type(screen.getByLabelText(stock.search), 'conc')

    await waitFor(() =>
      expect(api.calls.map((call) => call.path)).toContainEqual(
        expect.stringMatching(/inventory\?q=conc&zone=EARLY_RELEASE/),
      ),
    )
  })

  it('shows the boxes in numbered pages of 25, the page in the address', async () => {
    const api = stockApi({
      'GET /api/v1/pharmacy/inventory': (call: { path: string }) =>
        call.path.includes('cursor=25')
          ? { ...stockOf([PRIVATE_BOX]), total: 26 }
          : { ...stockOf([BOX]), next_cursor: '25', total: 26 },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    expect(await screen.findByText('A123')).toBeInTheDocument()
    const pages = screen.getByRole('navigation', { name: strings.pager.label })
    expect(within(pages).getByText(strings.pager.summary(1, 2, 26))).toBeInTheDocument()
    await user.click(within(pages).getByRole('button', { name: strings.pager.page(2) }))

    expect(await screen.findByText('Z9')).toBeInTheDocument()
    expect(screen.queryByText('A123')).not.toBeInTheDocument()
    // 25 a page, never more than the API allows in one call (N-31).
    const asked = api.sent('GET', '/api/v1/pharmacy/inventory?').map((call) => call.path)
    expect(asked.every((path) => path.includes('limit=25'))).toBe(true)
    expect(asked).toContainEqual(expect.stringContaining('cursor=25'))
  })

  it('puts the boxes of one medicine side by side, back on the first page', async () => {
    const api = stockApi({
      'GET /api/v1/pharmacy/inventory': { ...stockOf([BOX, PRIVATE_BOX]), total: 30 },
    })
    const { container } = renderApp(<AppRoutes />, { path: '/pharmacy/inventory?page=2' })
    const user = userEvent.setup()

    await screen.findByText('A123')
    const order = screen.getByRole('group', { name: stock.sortLabel })
    expect(within(order).getByRole('button', { name: stock.sorts.expiry })).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(order).getByRole('button', { name: stock.sorts.medicine }))

    await waitFor(() =>
      expect(api.calls.map((call) => call.path)).toContainEqual(
        expect.stringMatching(/inventory\?q=&sort=medicine&cursor=0&limit=25/),
      ),
    )
    expect(within(order).getByRole('button', { name: stock.sorts.medicine })).toHaveAttribute('aria-pressed', 'true')
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it("says how to write a medicine's name in a stock file", async () => {
    stockApi()
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })

    expect(await screen.findByText(/as the Ministry's price list writes it/)).toBeInTheDocument()
    expect(screen.getByText(/2\.5mg is not 25mg/)).toBeInTheDocument()
  })

  it('writes a pack that is a bare number as "Pack: N" on the add-box choices', async () => {
    stockApi({
      'GET /api/v1/catalog/products': {
        items: [{ ...RESERVATION.product, form: 'Tablet, film coated', pack: '30' }],
        did_you_mean: [],
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(stock.add.product), 'augm')

    expect(
      await screen.findByRole('button', { name: /Tablet, film coated · Pack: 30 · 1,000,000 LBP/ }),
    ).toBeInTheDocument()
  })

  it('adds a box typed by hand, the medicine chosen from the catalog', async () => {
    const api = stockApi({
      'GET /api/v1/catalog/products': { items: [RESERVATION.product], did_you_mean: [] },
      'POST /api/v1/pharmacy/inventory/items': answer(201, { ...BOX, batch: 'B77' }),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()
    const a = stock.add

    await user.type(await screen.findByLabelText(a.product), 'augm')
    // The pack, the price and the code are on the choice: a name and a strength can be
    // listed twice, and the code is what a stock file writes to say which one.
    await user.click(
      await screen.findByRole('button', {
        name: /AUGMENTIN 1G · 1 g · tablet · 14 tablets · 1,000,000 LBP · code 7001/,
      }),
    )
    await user.type(screen.getByLabelText(a.batch), 'B77')
    // The expiry as printed on the box: a month and a year, never a day to invent.
    await user.selectOptions(screen.getByLabelText(a.expiryMonth), '2')
    await user.selectOptions(screen.getByLabelText(a.expiryYear), '2028')
    await user.type(screen.getByLabelText(a.quantity), '4')
    await user.click(screen.getByRole('button', { name: a.submit }))

    // It says whether clients see the box now.
    expect(await screen.findByText(a.addedVisible(BOX.product.name, 'B77'))).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/pharmacy/inventory/items')[0].body).toEqual({
      product_id: RESERVATION.product.id,
      batch: 'B77',
      // The last day of February, in a leap year (R-D6).
      expiry_date: '2028-02-29',
      qty: 4,
    })
  })

  it('says on each field what is missing, and moves the focus to the first', async () => {
    const api = stockApi({
      'GET /api/v1/catalog/products': { items: [RESERVATION.product], did_you_mean: [] },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()
    const a = stock.add

    await user.type(await screen.findByLabelText(a.product), 'augm')
    await user.click(await screen.findByRole('button', { name: /AUGMENTIN 1G/ }))
    await user.click(screen.getByRole('button', { name: a.submit }))

    // The medicine was chosen: only the three empty fields are named.
    expect(await screen.findByText(a.problems.batch)).toBeInTheDocument()
    expect(screen.getByText(a.problems.expiry)).toBeInTheDocument()
    expect(screen.getByText(a.problems.quantity)).toBeInTheDocument()
    expect(screen.queryByText(a.problems.product)).not.toBeInTheDocument()
    expect(screen.queryByText(a.problem)).not.toBeInTheDocument()
    expect(screen.getByText(strings.forms.check(3))).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText(a.batch)).toHaveFocus())

    // A month that has passed is not a box anyone can sell.
    await user.type(screen.getByLabelText(a.batch), 'B77')
    await user.selectOptions(screen.getByLabelText(a.expiryMonth), '1')
    await user.selectOptions(screen.getByLabelText(a.expiryYear), '2026')
    await user.type(screen.getByLabelText(a.quantity), '0')
    await user.click(screen.getByRole('button', { name: a.submit }))
    expect(await screen.findByText(a.problems.expired)).toBeInTheDocument()
    expect(screen.getByText(a.problems.quantity)).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/pharmacy/inventory/items')).toEqual([])
  })

  it('comes before the stock table, and says when a box is not listed yet', async () => {
    stockApi({
      'GET /api/v1/catalog/products': { items: [RESERVATION.product], did_you_mean: [] },
      'POST /api/v1/pharmacy/inventory/items': answer(201, {
        ...BOX,
        days_left: 120,
        visible: false,
        held_back: true,
      }),
      'GET /api/v1/pharmacy/me': { ...PROFILE, auto_list_days: 30 },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()
    const a = stock.add

    const add = await screen.findByRole('region', { name: a.title })
    const table = await screen.findByRole('region', { name: stock.title })
    expect(add.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    await user.type(screen.getByLabelText(a.product), 'augm')
    await user.click(await screen.findByRole('button', { name: /AUGMENTIN 1G/ }))
    await user.type(screen.getByLabelText(a.batch), 'A123')
    await user.selectOptions(screen.getByLabelText(a.expiryMonth), '3')
    await user.selectOptions(screen.getByLabelText(a.expiryYear), '2027')
    await user.type(screen.getByLabelText(a.quantity), '5')
    await user.click(screen.getByRole('button', { name: a.submit }))

    expect(await screen.findByText(a.addedHeld(BOX.product.name, 'A123', 30))).toBeInTheDocument()
  })
})

describe('The files a pharmacy downloads', () => {
  it('asks the API for the template and for the errors, with its login', async () => {
    // A browser saves what a link points at; here we only watch the link being made.
    const made = vi.fn(() => 'blob:test')
    Object.assign(URL, { createObjectURL: made, revokeObjectURL: vi.fn() })
    const csv = () => new Response('product,strength,batch,expiry,quantity\r\n', {
      headers: { 'Content-Type': 'text/csv; charset=utf-8' },
    })
    const api = stockApi({
      'GET /api/v1/pharmacy/inventory/uploads/waiting': { upload: UPLOAD },
    })
    api.spy.mockImplementation(((original) => async (input: RequestInfo | URL, init?: RequestInit) => {
      const address = input instanceof Request ? input.url : String(input)
      return address.endsWith('/template') || address.endsWith('/errors.csv')
        ? csv()
        : original(input, init)
    })(api.spy.getMockImplementation() as typeof fetch))
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: u.template }))
    await waitFor(() => expect(made).toHaveBeenCalledTimes(1))
    await user.click(await screen.findByRole('button', { name: u.errorsFile }))
    await waitFor(() => expect(made).toHaveBeenCalledTimes(2))

    const asked = api.spy.mock.calls.map(([input]) =>
      input instanceof Request ? input : new Request(String(input)),
    )
    const template = asked.find((request) => request.url.endsWith('/inventory/template'))
    const errors = asked.find((request) => request.url.endsWith(`/uploads/${UPLOAD.id}/errors.csv`))
    expect(template?.headers.get('Authorization')).toBe('Bearer a-test-token')
    expect(errors?.headers.get('Authorization')).toBe('Bearer a-test-token')
  })
})

describe('A stock file (SM-4)', () => {
  it('says which boxes a file left as they are, and how to empty one (Q44)', async () => {
    stockApi({
      'GET /api/v1/pharmacy/inventory/uploads/waiting': {
        upload: { ...UPLOAD, summary: { ...UPLOAD.summary, left_alone: 2 } },
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })

    expect(await screen.findByText(u.leftAlone(2))).toBeInTheDocument()
    expect(screen.getByText(u.codeHint)).toBeInTheDocument()
  })

  it('is read and summarised, and changes nothing until it is applied', async () => {
    let waiting: unknown = null
    const api = stockApi({
      'GET /api/v1/pharmacy/inventory/uploads/waiting': () => ({ upload: waiting }),
      'POST /api/v1/pharmacy/inventory/uploads': () => {
        waiting = UPLOAD
        return answer(201, UPLOAD)
      },
      [`POST /api/v1/pharmacy/inventory/uploads/${UPLOAD.id}/apply`]: () => {
        waiting = null
        return { ...UPLOAD, status: 'APPLIED' }
      },
    })
    const { container } = renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    const file = new File(['product,batch,expiry,quantity\nPanadol,A1,2027-03,10\n'], 'stock.csv', {
      type: 'text/csv',
    })
    await user.upload(await screen.findByLabelText(u.choose), file)

    expect(await screen.findByText(u.waiting('stock.csv'))).toBeInTheDocument()
    // Four counts, the one that takes stock away in red.
    const tiles = screen.getByRole('group', { name: u.tilesLabel })
    const count = (label: string) => within(tiles).getByText(label).parentElement as HTMLElement
    expect(count(u.tiles.ready)).toHaveTextContent('2')
    expect(count(u.tiles.fix)).toHaveTextContent('1')
    expect(count(u.tiles.new)).toHaveTextContent('2')
    expect(count(u.tiles.zeroed)).toHaveTextContent('1')
    expect(count(u.tiles.zeroed)).toHaveClass('upload-tile--red')
    // A refused row is never read: its box is one of those set to 0.
    expect(screen.getByText(u.zeroedWarning)).toBeInTheDocument()
    expect(screen.getByText(u.reservedKept(1))).toBeInTheDocument()
    expect(screen.getByText(/Panadoll: no product with this name/)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(u.didYouMean('PANADOL')))).toBeInTheDocument()
    // The file went as a form, with the login and without a JSON body.
    const [sent] = api.sent('POST', '/api/v1/pharmacy/inventory/uploads')
    expect(sent.headers.get('Content-Type')).toMatch(/^multipart\/form-data/)
    expect(String(sent.body)).toContain('name="file"')
    expect(await accessibilityProblems(container)).toEqual([])

    await user.click(screen.getByRole('button', { name: u.applyRows(2) }))

    expect(await screen.findByText(u.applied)).toBeInTheDocument()
    expect(api.sent('POST', `/api/v1/pharmacy/inventory/uploads/${UPLOAD.id}/apply`)).toHaveLength(1)
    await waitFor(() => expect(screen.queryByText(u.waiting('stock.csv'))).not.toBeInTheDocument())
  })

  it('warns of nothing more when every row was read', async () => {
    stockApi({
      'GET /api/v1/pharmacy/inventory/uploads/waiting': {
        upload: { ...UPLOAD, rows_ok: 3, rows_error: 0, errors: [] },
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })

    expect(await screen.findByRole('button', { name: u.applyRows(3) })).toBeInTheDocument()
    expect(screen.queryByText(u.zeroedWarning)).not.toBeInTheDocument()
  })

  it('is found again after a reload, and can be discarded', async () => {
    let waiting: unknown = UPLOAD
    const api = stockApi({
      'GET /api/v1/pharmacy/inventory/uploads/waiting': () => ({ upload: waiting }),
      [`POST /api/v1/pharmacy/inventory/uploads/${UPLOAD.id}/discard`]: () => {
        waiting = null
        return answer(204)
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: u.discard }))

    await waitFor(() => expect(screen.queryByText(u.waiting('stock.csv'))).not.toBeInTheDocument())
    expect(api.sent('POST', `/api/v1/pharmacy/inventory/uploads/${UPLOAD.id}/discard`)).toHaveLength(1)
  })

  it('says why a file cannot be used', async () => {
    stockApi({
      'POST /api/v1/pharmacy/inventory/uploads': refusal(422, 'UPLOAD_FAILED', {
        reason: 'not a CSV file: in Excel, use File > Save As > CSV',
      }),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    const workbook = new File(['PK'], 'stock.csv', { type: 'text/csv' })
    await user.upload(await screen.findByLabelText(u.choose), workbook)

    expect(await screen.findByText(/Save As > CSV/)).toBeInTheDocument()
  })
})

describe("The pharmacy's listings (PS-7)", () => {
  const listedApi = (more: Record<string, unknown> = {}) =>
    stockApi({ 'GET /api/v1/pharmacy/inventory': stockOf([BOX]), ...more })
  const changed = { item: BOX, reserved_kept: false }

  it('shows what clients see, and the prices DawaLink sets', async () => {
    const api = listedApi()
    const { container } = renderApp(<AppRoutes />, { path: '/pharmacy/listings' })

    const listing = await screen.findByRole('article', { name: `${BOX.product.name} · A123` })

    expect(within(listing).getByText(l.visible)).toBeInTheDocument()
    expect(within(listing).getByText(l.available(3, 2))).toBeInTheDocument()
    expect(within(listing).getByText(/400,000 LBP · 60% off/)).toBeInTheDocument()
    expect(await screen.findByText(l.tier(0, 30, 60))).toBeInTheDocument()
    // Only the boxes near their expiry are asked for.
    expect(api.sent('GET', '/api/v1/pharmacy/inventory?')[0].path).toContain('zone=NEAR_EXPIRY')
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('shows the shapes of its cards while they load, and the words once there are none (B#43)', async () => {
    let arrive: (body: unknown) => void = () => {}
    listedApi({ 'GET /api/v1/pharmacy/inventory': () => new Promise((done) => (arrive = done)) })
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })

    await screen.findByRole('heading', { name: l.title, level: 1 })
    const loading = screen.getByText(strings.common.loading)
    expect(loading.closest('[role="status"]')).toHaveClass('placeholder')
    expect(screen.queryByText(l.none)).not.toBeInTheDocument()

    arrive(stockOf([]))
    expect(await screen.findByText(l.none)).toBeInTheDocument()
    expect(screen.queryByText(strings.common.loading)).not.toBeInTheDocument()
  })

  it('sets its own price, and goes back to the DawaLink price', async () => {
    const own = { ...BOX.price, effective: { lbp: 250_000, usd_approx: 2.8 }, override: { lbp: 250_000, usd_approx: 2.8 }, discount_pct: 75 }
    let item = BOX as typeof BOX | (Omit<typeof BOX, 'price'> & { price: typeof own })
    const api = listedApi({
      'GET /api/v1/pharmacy/inventory': () => stockOf([item as typeof BOX]),
      [`PATCH /api/v1/pharmacy/inventory/items/${BOX.id}`]: (call: { body: unknown }) => {
        const body = call.body as { price_override_lbp: number | null }
        item = body.price_override_lbp === null ? BOX : { ...BOX, price: own }
        return { item, reserved_kept: false }
      },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: l.setPrice }))
    const box = screen.getByLabelText(l.priceLabel)
    // The price clients see now is there to correct, and the focus is in it.
    expect(box).toHaveValue('400,000')
    expect(box).toHaveFocus()
    await user.clear(box)
    await user.type(box, '250000')
    expect(box).toHaveValue('250,000')
    // What clients will read, before it is saved.
    expect(screen.getByText(l.priceLive(75, '1,000,000 LBP'))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: l.savePrice }))

    expect(await screen.findByText(/250,000 LBP · 75% off/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: l.setPrice })).toHaveFocus()
    expect(screen.getByText(new RegExp(l.ownPrice))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: l.backToSystem }))

    await waitFor(() =>
      expect(api.sent('PATCH', '/api/v1/pharmacy/inventory/items').map((call) => call.body)).toEqual([
        { price_override_lbp: 250000 },
        { price_override_lbp: null },
      ]),
    )
  })

  it('says when a price is above the public price, and never cuts it down', async () => {
    const api = listedApi()
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: l.setPrice }))
    const box = screen.getByLabelText(l.priceLabel)
    await user.clear(box)
    await user.type(box, '9999999')
    await user.tab()

    expect(box).toHaveValue('9,999,999')
    expect(screen.getByText(l.priceRange('1,000,000'))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: l.savePrice })).toBeDisabled()
    expect(api.sent('PATCH', '/api/v1/pharmacy/inventory/items')).toEqual([])
  })

  it("says the API's refusal of a price", async () => {
    listedApi({
      [`PATCH /api/v1/pharmacy/inventory/items/${BOX.id}`]: refusal(422, 'PRICE_ABOVE_PUBLIC'),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: l.setPrice }))
    // Untouched, the DawaLink price would become the pharmacy's own: nothing to save.
    expect(screen.getByRole('button', { name: l.savePrice })).toBeDisabled()
    const box = screen.getByLabelText(l.priceLabel)
    await user.clear(box)
    await user.type(box, '900000')
    await user.click(screen.getByRole('button', { name: l.savePrice }))

    expect(await screen.findByText(strings.errors.PRICE_ABOVE_PUBLIC)).toBeInTheDocument()
  })

  it('finds a medicine or a batch among the listings', async () => {
    const api = listedApi()
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })
    const user = userEvent.setup()

    await user.type(await screen.findByLabelText(stock.search), 'A12')

    await waitFor(() =>
      expect(api.calls.map((call) => call.path)).toContainEqual(
        expect.stringMatching(/inventory\?q=A12&zone=NEAR_EXPIRY/),
      ),
    )
  })

  it('comes in numbered pages, and puts two batches of one medicine side by side', async () => {
    const api = listedApi({
      'GET /api/v1/pharmacy/inventory': (call: { path: string }) => ({
        ...stockOf([call.path.includes('cursor=25') ? { ...BOX, batch: 'LATE2' } : BOX]),
        total: 27,
      }),
    })
    const { container } = renderApp(<AppRoutes />, { path: '/pharmacy/listings?page=2' })
    const user = userEvent.setup()

    expect(await screen.findByText(/Batch LATE2/)).toBeInTheDocument()
    expect(screen.getByText(strings.pager.summary(2, 2, 27))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: stock.sorts.medicine }))

    await waitFor(() =>
      expect(api.calls.map((call) => call.path)).toContainEqual(
        expect.stringMatching(/zone=NEAR_EXPIRY&sort=medicine&cursor=0&limit=25/),
      ),
    )
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('says the rule the pharmacy chose, with the way to change it', async () => {
    listedApi({ 'GET /api/v1/pharmacy/me': { ...PROFILE, auto_list_days: 30 } })
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })

    expect(await screen.findByText(new RegExp(l.rule(30).slice(0, 40)))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: l.changeRule })).toHaveAttribute('href', '/pharmacy/settings')
  })

  it('lists now a box the rule still holds back (BLD-D44)', async () => {
    const waiting = { ...BOX, days_left: 90, visible: false, held_back: true }
    const api = listedApi({
      'GET /api/v1/pharmacy/me': { ...PROFILE, auto_list_days: 30 },
      'GET /api/v1/pharmacy/inventory': stockOf([waiting]),
      [`PATCH /api/v1/pharmacy/inventory/items/${BOX.id}`]: changed,
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })
    const user = userEvent.setup()

    const listing = await screen.findByRole('article', { name: `${BOX.product.name} · A123` })
    expect(within(listing).getByText(l.heldBack)).toBeInTheDocument()
    expect(await within(listing).findByText(l.waitsFor(30))).toBeInTheDocument()
    // One way out of this state: no [Pause] on a box nobody sees.
    expect(within(listing).queryByRole('button', { name: l.pause })).not.toBeInTheDocument()
    await user.click(within(listing).getByRole('button', { name: l.listNow }))

    await waitFor(() =>
      expect(api.sent('PATCH', '/api/v1/pharmacy/inventory/items')[0]?.body).toEqual({ listed: true }),
    )
  })

  it('takes a box listed by hand back to the rule', async () => {
    const byHand = { ...BOX, days_left: 90, listed_by_hand: true }
    const api = listedApi({
      'GET /api/v1/pharmacy/inventory': stockOf([byHand]),
      [`PATCH /api/v1/pharmacy/inventory/items/${BOX.id}`]: changed,
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })
    const user = userEvent.setup()

    const listing = await screen.findByRole('article', { name: `${BOX.product.name} · A123` })
    expect(within(listing).getByText(l.listedByYou)).toBeInTheDocument()
    await user.click(within(listing).getByRole('button', { name: l.backToRule }))

    await waitFor(() =>
      expect(api.sent('PATCH', '/api/v1/pharmacy/inventory/items')[0]?.body).toEqual({ listed: false }),
    )
  })

  it('pauses a listing', async () => {
    const api = listedApi({ [`PATCH /api/v1/pharmacy/inventory/items/${BOX.id}`]: changed })
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: l.pause }))

    await waitFor(() =>
      expect(api.sent('PATCH', '/api/v1/pharmacy/inventory/items')[0]?.body).toEqual({ paused: true }),
    )
  })
})

describe('Who has an inventory (P-D2)', () => {
  it('a suspended pharmacy keeps its counter and loses its stock screens', async () => {
    loggedIn()
    pretendApi({
      'GET /api/v1/auth/me': PHARMACIST,
      'GET /api/v1/pharmacy/me': { ...PROFILE, status: 'SUSPENDED' },
      'GET /api/v1/pharmacy/reservations': stockOf([]),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy' })

    expect(await screen.findByText(s.suspended)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: s.reservations })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: s.inventory })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: s.listings })).not.toBeInTheDocument()
  })
})
