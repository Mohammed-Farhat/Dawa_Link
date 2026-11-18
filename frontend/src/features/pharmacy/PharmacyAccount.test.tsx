import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../../app/App'
import { strings } from '../../strings/en'
import { PHARMACIST, PROFILE } from '../../test/pharmacy'
import {
  accessibilityProblems,
  answer,
  DISTRICTS,
  loggedIn,
  pretendApi,
  refusal,
  renderApp,
} from '../../test/render'

// The real map needs a browser that draws. Here it is a button that puts the pin.
vi.mock('./PinMap', () => ({
  default: ({ onChange }: { onChange: (pin: { lat: number; lon: number }) => void }) => (
    <button type="button" onClick={() => onChange({ lat: 33.8959, lon: 35.4828 })}>
      put the pin
    </button>
  ),
}))

const s = strings.pharmacy
const d = s.details
const r = s.register
const h = s.hours

const visitorApi = (more: Record<string, unknown> = {}) =>
  pretendApi({
    'GET /api/v1/auth/me': refusal(401, 'UNAUTHENTICATED'),
    'GET /api/v1/districts': DISTRICTS,
    ...more,
  })

async function fillIn(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText(r.email), 'owner@hamra.example.com')
  await user.type(screen.getByLabelText(r.password), 'A long enough passphrase, 1')
  await user.type(screen.getByLabelText(d.name), 'Hamra Pharmacy')
  await user.type(screen.getByLabelText(d.license), 'PH 1234')
  await user.type(screen.getByLabelText(d.phone), '01 234 567')
  await user.type(screen.getByLabelText(d.address), '12 Hamra Street')
  await user.selectOptions(await screen.findByRole('combobox', { name: d.district }), '1')
  await user.click(await screen.findByRole('button', { name: 'put the pin' }))
}

describe('A pharmacy registers (PS-1)', () => {
  it('is reached from the welcome page', async () => {
    visitorApi()
    renderApp(<AppRoutes />, { path: '/welcome' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('link', { name: strings.welcome.pharmacy }))

    expect(await screen.findByRole('heading', { name: r.title })).toBeInTheDocument()
  })

  it('says what is missing and sends nothing', async () => {
    const api = visitorApi()
    const { container } = renderApp(<AppRoutes />, { path: '/pharmacy/signup' })
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: r.submit }))

    expect(await screen.findByText(d.problems.name)).toBeInTheDocument()
    expect(screen.getByText(d.problems.phone)).toBeInTheDocument()
    expect(screen.getByText(d.problems.location)).toBeInTheDocument()
    expect(screen.getByText(r.termsProblem)).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/auth/register')).toEqual([])
    expect(await accessibilityProblems(container)).toEqual([])
  })

  it('sends the details, the pin and the hours, then says "check your email"', async () => {
    const api = visitorApi({
      'POST /api/v1/auth/register/pharmacy': answer(202, { message: 'Check your email' }),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/signup' })
    const user = userEvent.setup()

    await fillIn(user)
    expect(await screen.findByText(d.pinSet)).toBeInTheDocument()
    // Saturday closes at midday and reopens; Sunday stays closed.
    await user.click(screen.getByRole('button', { name: h.addRange('Saturday') }))
    await user.click(screen.getByRole('button', { name: d.days(2) }))
    await user.click(screen.getByLabelText(r.terms))
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(await screen.findByRole('heading', { name: strings.checkEmail.title })).toBeInTheDocument()
    const [sent] = api.sent('POST', '/api/v1/auth/register/pharmacy')
    const body = sent.body as { pharmacy: Record<string, unknown> & { hours: unknown[] } }
    expect(body).toMatchObject({
      email: 'owner@hamra.example.com',
      accept_terms: true,
      pharmacy: {
        name: 'Hamra Pharmacy',
        license_number: 'PH 1234',
        phone: '01 234 567',
        district_id: 1,
        location: { lat: 33.8959, lon: 35.4828 },
        pickup_days: 2,
      },
    })
    // Monday to Saturday, and Saturday twice: the day was split at midday.
    expect(body.pharmacy.hours).toHaveLength(7)
    expect(body.pharmacy.hours).toContainEqual({ weekday: 5, open: '08:00', close: '13:00' })
    expect(body.pharmacy.hours).toContainEqual({ weekday: 5, open: '16:00', close: '20:00' })
    expect(body.pharmacy.hours).not.toContainEqual(expect.objectContaining({ weekday: 6 }))
  })

  it("shows the API's refusal on the field it names", async () => {
    visitorApi({
      'POST /api/v1/auth/register/pharmacy': refusal(422, 'VALIDATION_ERROR', { field: 'phone' }),
    })
    renderApp(<AppRoutes />, { path: '/pharmacy/signup' })
    const user = userEvent.setup()

    await fillIn(user)
    await user.click(screen.getByLabelText(r.terms))
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(await screen.findByText(d.problems.phone)).toBeInTheDocument()
  })

  it('says that the licence is already registered', async () => {
    visitorApi({ 'POST /api/v1/auth/register/pharmacy': refusal(409, 'LICENSE_TAKEN') })
    renderApp(<AppRoutes />, { path: '/pharmacy/signup' })
    const user = userEvent.setup()

    await fillIn(user)
    await user.click(screen.getByLabelText(r.terms))
    await user.click(screen.getByRole('button', { name: r.submit }))

    expect(await screen.findByText(strings.errors.LICENSE_TAKEN)).toBeInTheDocument()
  })
})

function portalApi(profile: Record<string, unknown>, more: Record<string, unknown> = {}) {
  loggedIn()
  return pretendApi({
    'GET /api/v1/auth/me': PHARMACIST,
    'GET /api/v1/pharmacy/me': { ...PROFILE, ...profile },
    'GET /api/v1/districts': DISTRICTS,
    ...more,
  })
}

describe('A pharmacy that waits (PS-2)', () => {
  it('is told to confirm its email first, not that it is being checked', async () => {
    const api = portalApi(
      { status: 'PENDING', email_verified: false },
      { 'POST /api/v1/auth/verify-email/resend': answer(202, { message: 'ok' }) },
    )
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    expect(await screen.findByText(s.confirmEmail)).toBeInTheDocument()
    expect(screen.queryByText(s.pending)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: strings.banner.resend }))

    expect(await screen.findByText(strings.banner.resent)).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/auth/verify-email/resend')).toHaveLength(1)
  })

  it('corrects what it typed while it waits', async () => {
    const api = portalApi(
      { status: 'PENDING', info_requested: true, status_reason: 'Which street is it on?' },
      { 'PATCH /api/v1/pharmacy/me/registration': { ...PROFILE, status: 'PENDING' } },
    )
    const { container } = renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    // What the admin asked for is on the pharmacy's own screen, in the admin's words.
    expect(await screen.findByText(s.infoRequested('Which street is it on?'))).toBeInTheDocument()
    const name = await screen.findByLabelText(d.name)
    expect(name).toHaveValue('Hamra Pharmacy')
    // Midnight is shown as 00:00: a time field has no 24:00.
    expect(screen.getByLabelText(h.closes('Tuesday', false))).toHaveValue('00:00')
    expect(await accessibilityProblems(container)).toEqual([])
    await user.clear(name)
    await user.type(name, 'Hamra Pharmacy 2')
    await user.click(screen.getByRole('button', { name: d.save }))

    expect(await screen.findByText(d.saved)).toBeInTheDocument()
    const [sent] = api.sent('PATCH', '/api/v1/pharmacy/me/registration')
    expect(sent.body).toMatchObject({ name: 'Hamra Pharmacy 2', phone: '+9611000000' })
    // And midnight goes back as the API writes it.
    expect((sent.body as { hours: unknown[] }).hours).toContainEqual({
      weekday: 1,
      open: '08:00',
      close: '24:00',
    })
    // No stock before approval (P-D2).
    expect(screen.queryByRole('link', { name: s.inventory })).not.toBeInTheDocument()
  })

  it('after a rejection sees why, and saving sends the registration again', async () => {
    const api = portalApi(
      { status: 'REJECTED', status_reason: "The licence number doesn't match." },
      {
        'PATCH /api/v1/pharmacy/me/registration': { ...PROFILE, status: 'REJECTED' },
        'POST /api/v1/pharmacy/me/resubmit': { ...PROFILE, status: 'PENDING' },
      },
    )
    renderApp(<AppRoutes />, { path: '/pharmacy' })
    const user = userEvent.setup()

    expect(await screen.findByText(/The licence number doesn't match/)).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: d.resubmit }))

    await waitFor(() => expect(api.sent('POST', '/api/v1/pharmacy/me/resubmit')).toHaveLength(1))
    expect(api.sent('PATCH', '/api/v1/pharmacy/me/registration')).toHaveLength(1)
    expect(await screen.findByText(s.pending)).toBeInTheDocument()
  })
})

describe("The pharmacy's settings (PS-10)", () => {
  it('changes the hours and the pickup time, and nothing else', async () => {
    const api = portalApi(
      {},
      {
        'GET /api/v1/pharmacy/dashboard': answer(404),
        'PATCH /api/v1/pharmacy/me': { ...PROFILE, pickup_days: 3 },
      },
    )
    const { container } = renderApp(<AppRoutes />, { path: '/pharmacy/settings' })
    const user = userEvent.setup()

    const hours = await screen.findByRole('group', { name: d.hours })
    // Monday closes at midday and reopens: both ranges are there.
    expect(within(hours).getByLabelText(h.opens('Monday', true))).toHaveValue('16:00')
    expect(await accessibilityProblems(container)).toEqual([])
    await user.click(within(hours).getByRole('button', { name: h.removeRange('Monday') }))
    await user.click(screen.getByRole('button', { name: d.days(3) }))
    await user.click(screen.getByRole('button', { name: d.save }))

    expect(await screen.findByText(d.saved)).toBeInTheDocument()
    const [sent] = api.sent('PATCH', '/api/v1/pharmacy/me')
    expect(sent.body).toEqual({
      pickup_days: 3,
      hours: [
        { weekday: 0, open: '08:00', close: '13:00' },
        { weekday: 1, open: '08:00', close: '24:00' },
      ],
    })
    // Its name is shown with who changes it (TM-D2): no field. The phone was not
    // touched, so it is not sent.
    expect(screen.getByText(d.fixed)).toBeInTheDocument()
    expect(screen.queryByLabelText(d.name)).not.toBeInTheDocument()
    expect(screen.getByLabelText(d.phone)).toHaveValue('+9611000000')
  })

  it('changes its own phone number (the owner, Q42)', async () => {
    const api = portalApi(
      {},
      {
        'GET /api/v1/pharmacy/dashboard': answer(404),
        'PATCH /api/v1/pharmacy/me': { ...PROFILE, phone: '+96170555123' },
      },
    )
    renderApp(<AppRoutes />, { path: '/pharmacy/settings' })
    const user = userEvent.setup()

    const phone = await screen.findByLabelText(d.phone)
    await user.clear(phone)
    await user.type(phone, '12')
    await user.click(screen.getByRole('button', { name: d.save }))
    // Not a number: said on the field, nothing sent.
    expect(await screen.findByText(d.problems.phone)).toBeInTheDocument()
    expect(api.sent('PATCH', '/api/v1/pharmacy/me')).toEqual([])

    await user.clear(phone)
    await user.type(phone, '70 555 123')
    await user.click(screen.getByRole('button', { name: d.save }))

    expect(await screen.findByText(d.saved)).toBeInTheDocument()
    expect(api.sent('PATCH', '/api/v1/pharmacy/me')[0].body).toMatchObject({ phone: '70 555 123' })
    // The field shows the number as it is stored now.
    expect(phone).toHaveValue('+96170555123')
  })

  it('changes its own address and pin when it moves (the owner, Q45)', async () => {
    const api = portalApi(
      // It is at another place than where the test map puts the pin.
      { location: { lat: 33.9, lon: 35.5 } },
      {
        'GET /api/v1/pharmacy/dashboard': answer(404),
        'PATCH /api/v1/pharmacy/me': {
          ...PROFILE,
          address: '9 New Street',
          location: { lat: 33.8959, lon: 35.4828 },
        },
      },
    )
    renderApp(<AppRoutes />, { path: '/pharmacy/settings' })
    const user = userEvent.setup()
    const page = s.settingsPage

    const save = await screen.findByRole('button', { name: page.placeSave })
    // Nothing was changed yet: nothing to save.
    expect(save).toBeDisabled()
    const address = screen.getByLabelText(d.address)
    await user.clear(address)
    await user.type(address, '9 New Street')
    await user.click(await screen.findByRole('button', { name: 'put the pin' }))
    await user.click(save)

    expect(await screen.findByText(page.placeSaved)).toBeInTheDocument()
    // Only what changed is sent: the district was not touched.
    expect(api.sent('PATCH', '/api/v1/pharmacy/me')[0].body).toEqual({
      address: '9 New Street',
      location: { lat: 33.8959, lon: 35.4828 },
    })
    // Its name and its licence stay with DawaLink's team.
    expect(screen.queryByLabelText(d.name)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(d.license)).not.toBeInTheDocument()
  })

  it('says so when the new number belongs to another pharmacy', async () => {
    portalApi(
      {},
      {
        'GET /api/v1/pharmacy/dashboard': answer(404),
        'PATCH /api/v1/pharmacy/me': refusal(409, 'PHONE_TAKEN'),
      },
    )
    renderApp(<AppRoutes />, { path: '/pharmacy/settings' })
    const user = userEvent.setup()

    const phone = await screen.findByLabelText(d.phone)
    await user.clear(phone)
    await user.type(phone, '03 999 888')
    await user.click(screen.getByRole('button', { name: d.save }))

    expect(await screen.findByText(strings.errors.PHONE_TAKEN)).toBeInTheDocument()
  })

  it('refuses hours that overlap before sending them', async () => {
    const api = portalApi({}, { 'GET /api/v1/pharmacy/dashboard': answer(404) })
    renderApp(<AppRoutes />, { path: '/pharmacy/settings' })
    const user = userEvent.setup()

    const reopens = await screen.findByLabelText(h.opens('Monday', true))
    await user.clear(reopens)
    await user.type(reopens, '12:00')
    await user.click(screen.getByRole('button', { name: d.save }))

    expect(await screen.findByText(h.order)).toBeInTheDocument()
    expect(api.sent('PATCH', '/api/v1/pharmacy/me')).toEqual([])
  })

  it('changes the password', async () => {
    const api = portalApi(
      {},
      {
        'GET /api/v1/pharmacy/dashboard': answer(404),
        'POST /api/v1/auth/password': answer(204),
      },
    )
    renderApp(<AppRoutes />, { path: '/pharmacy/settings' })
    const user = userEvent.setup()
    const p = strings.password

    await user.type(await screen.findByLabelText(p.current), 'the old passphrase')
    await user.type(screen.getByLabelText(p.new), 'A new long passphrase, 2')
    await user.click(screen.getByRole('button', { name: p.submit }))

    expect(await screen.findByText(p.done)).toBeInTheDocument()
    expect(api.sent('POST', '/api/v1/auth/password')[0].body).toEqual({
      current_password: 'the old passphrase',
      new_password: 'A new long passphrase, 2',
    })
  })
})
