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

  it('shows more boxes a page at a time, as the API gives them', async () => {
    const api = stockApi({
      'GET /api/v1/pharmacy/inventory': (call: { path: string }) =>
        call.path.includes('cursor=50')
          ? stockOf([PRIVATE_BOX])
          : { ...stockOf([BOX]), next_cursor: '50' },
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    expect(await screen.findByText('A123')).toBeInTheDocument()
    expect(screen.queryByText('Z9')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: stock.more }))

    expect(await screen.findByText('Z9')).toBeInTheDocument()
    expect(screen.getByText('A123')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: stock.more })).not.toBeInTheDocument(),
    )
    // Never more than the API allows in one call (N-31).
    const asked = api.sent('GET', '/api/v1/pharmacy/inventory?').map((call) => call.path)
    expect(asked.every((path) => path.includes('limit=50'))).toBe(true)
  })

  it('adds a box typed by hand, the medicine chosen from the catalog', async () => {
    const api = stockApi({
      'GET /api/v1/catalog/products': { items: [RESERVATION.product], did_you_mean: [] },
      'POST /api/v1/pharmacy/inventory/items': answer(201, BOX),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()
    const a = stock.add

    await user.click(await screen.findByRole('button', { name: a.submit }))
    expect(await screen.findByText(a.problem)).toBeInTheDocument()
    await user.type(screen.getByLabelText(a.product), 'augm')
    // The pack, the price and the code are on the choice: a name and a strength can be
    // listed twice, and the code is what a stock file writes to say which one.
    await user.click(
      await screen.findByRole('button', {
        name: /AUGMENTIN 1G · 1 g · tablet · 14 tablets · 1,000,000 LBP · code 7001/,
      }),
    )
    await user.type(screen.getByLabelText(a.batch), 'B77')
    await user.type(screen.getByLabelText(a.expiry), '2027-03-31')
    await user.type(screen.getByLabelText(a.quantity), '4')
    await user.click(screen.getByRole('button', { name: a.submit }))

    expect(await screen.findByText(a.added)).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/pharmacy/inventory/items')[0].body).toEqual({
      product_id: RESERVATION.product.id,
      batch: 'B77',
      expiry_date: '2027-03-31',
      qty: 4,
    })
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
    expect(screen.getByText(u.rows(3, 2, 1))).toBeInTheDocument()
    expect(screen.getByText(u.changes(UPLOAD.summary))).toBeInTheDocument()
    expect(screen.getByText(u.reservedKept(1))).toBeInTheDocument()
    expect(screen.getByText(/Panadoll: no product with this name/)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(u.didYouMean('PANADOL')))).toBeInTheDocument()
    // The file went as a form, with the login and without a JSON body.
    const [sent] = api.sent('POST', '/api/v1/pharmacy/inventory/uploads')
    expect(sent.headers.get('Content-Type')).toMatch(/^multipart\/form-data/)
    expect(String(sent.body)).toContain('name="file"')
    expect(await accessibilityProblems(container)).toEqual([])

    await user.click(screen.getByRole('button', { name: u.apply }))

    expect(await screen.findByText(u.applied)).toBeInTheDocument()
    expect(api.sent('POST', `/api/v1/pharmacy/inventory/uploads/${UPLOAD.id}/apply`)).toHaveLength(1)
    await waitFor(() => expect(screen.queryByText(u.waiting('stock.csv'))).not.toBeInTheDocument())
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
    await user.type(screen.getByLabelText(l.priceOf(BOX.product.name)), '250000')
    await user.click(screen.getByRole('button', { name: l.savePrice }))

    expect(await screen.findByText(/250,000 LBP · 75% off/)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(l.ownPrice))).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: l.backToSystem }))

    await waitFor(() =>
      expect(api.sent('PATCH', '/api/v1/pharmacy/inventory/items').map((call) => call.body)).toEqual([
        { price_override_lbp: 250000 },
        { price_override_lbp: null },
      ]),
    )
  })

  it('says when a price is above the public price', async () => {
    listedApi({
      [`PATCH /api/v1/pharmacy/inventory/items/${BOX.id}`]: refusal(422, 'PRICE_ABOVE_PUBLIC'),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: l.setPrice }))
    await user.type(screen.getByLabelText(l.priceOf(BOX.product.name)), '99999999')
    await user.click(screen.getByRole('button', { name: l.savePrice }))

    expect(await screen.findByText(strings.errors.PRICE_ABOVE_PUBLIC)).toBeInTheDocument()
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
