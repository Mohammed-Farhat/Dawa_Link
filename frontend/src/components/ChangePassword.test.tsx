import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { errorMessage, strings } from '../strings/en'
import { loggedIn, pretendApi, refusal, renderApp } from '../test/render'
import { ChangePassword } from './ChangePassword'

const s = strings.password

describe('Change password', () => {
  it('says a common password as common, not as the length rule it already meets', async () => {
    loggedIn()
    pretendApi({ 'POST /api/v1/auth/password': refusal(422, 'WEAK_PASSWORD', { missing: ['uncommon'] }) })
    renderApp(<ChangePassword />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText(s.current), 'my old passphrase, 1A')
    await user.type(screen.getByLabelText(s.new), 'Password123!')
    await user.click(screen.getByRole('button', { name: s.submit }))

    expect(await screen.findByText(s.common)).toBeInTheDocument()
    expect(screen.queryByText(errorMessage('WEAK_PASSWORD'))).not.toBeInTheDocument()
    expect(screen.getByLabelText(s.new)).toHaveFocus()
  })
})
