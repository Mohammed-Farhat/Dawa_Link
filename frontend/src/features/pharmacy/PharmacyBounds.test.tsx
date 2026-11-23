import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { AppRoutes } from '../../app/App'
import { strings } from '../../strings/en'
import { BOX, PHARMACIST, PROFILE, stockOf } from '../../test/pharmacy'
import { CONFIG, loggedIn, pretendApi, refusal, renderApp, RESERVATION } from '../../test/render'
import { BATCH_MAX, batchFits, tidyBatch } from './draft'

// What the forms of the stock let through is what the API takes: a box the API always
// refuses was sent, then came back as "Enter the batch", which the pharmacist had done.

const stock = strings.pharmacy.stock
const a = stock.add

function stockApi(more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': PHARMACIST,
    'GET /api/v1/pharmacy/me': PROFILE,
    'GET /api/v1/config/public': CONFIG,
    'GET /api/v1/pharmacy/inventory': stockOf([BOX]),
    'GET /api/v1/pharmacy/inventory/uploads/waiting': { upload: null },
    'GET /api/v1/catalog/products': { items: [RESERVATION.product], did_you_mean: [] },
    ...more,
  })
}

async function fillBox(user: ReturnType<typeof userEvent.setup>, batch: string) {
  await user.type(await screen.findByLabelText(a.product), 'augm')
  await user.click(await screen.findByRole('button', { name: /AUGMENTIN 1G/ }))
  await user.type(screen.getByLabelText(a.batch), batch)
  await user.selectOptions(screen.getByLabelText(a.expiryMonth), '2')
  await user.selectOptions(screen.getByLabelText(a.expiryYear), '2028')
  await user.type(screen.getByLabelText(a.quantity), '4')
  await user.click(screen.getByRole('button', { name: a.submit }))
}

describe("A batch, as the API's rule has it (domain/pharmacy_details.py)", () => {
  it.each([
    ['B77', true],
    ['LOT 2027/03-a_1.5', true],
    ['  B  77  ', true],
    ['x'.repeat(BATCH_MAX), true],
    ['x'.repeat(BATCH_MAX + 1), false],
    ['', false],
    ['   ', false],
    ['-B77', false],
    ['B#77', false],
    ['دفعة', false],
  ])('%j fits: %s', (batch, fits) => {
    expect(batchFits(batch)).toBe(fits)
  })

  it('is sent with its spaces tidied, as the API stores it', () => {
    expect(tidyBatch('  B  77 ')).toBe('B 77')
    expect(BATCH_MAX).toBe(30)
  })
})

describe('Adding one box by hand', () => {
  it("says the batch's rule before sending a batch the API would refuse", async () => {
    const api = stockApi()
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    expect(await screen.findByLabelText(a.batch)).toHaveAttribute('maxlength', String(BATCH_MAX))
    await fillBox(user, 'B#77')

    expect(await screen.findByText(a.problems.batchRule(BATCH_MAX))).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/pharmacy/inventory/items')).toEqual([])
  })

  it("says the batch's rule when the API refuses the batch", async () => {
    const api = stockApi({
      'POST /api/v1/pharmacy/inventory/items': refusal(422, 'VALIDATION_ERROR', { field: 'batch' }),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })
    const user = userEvent.setup()

    await fillBox(user, 'B  77')

    expect(await screen.findByText(a.problems.batchRule(BATCH_MAX))).toBeInTheDocument()
    expect(screen.queryByText(a.problems.batch)).not.toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/pharmacy/inventory/items')[0].body).toMatchObject({ batch: 'B 77' })
  })
})

describe("The stock's search boxes", () => {
  it('take no more than the API does (100 characters)', async () => {
    stockApi()
    renderApp(<AppRoutes />, { path: '/pharmacy/inventory' })

    expect(await screen.findByLabelText(stock.search)).toHaveAttribute('maxlength', '100')
    expect(screen.getByLabelText(a.product)).toHaveAttribute('maxlength', '100')
  })

  it('in the listings too', async () => {
    stockApi()
    renderApp(<AppRoutes />, { path: '/pharmacy/listings' })

    expect(await screen.findByLabelText(stock.search)).toHaveAttribute('maxlength', '100')
  })
})
