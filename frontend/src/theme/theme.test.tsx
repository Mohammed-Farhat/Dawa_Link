import { Checkbox, Modal, PasswordInput, TextInput } from '@mantine/core'
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderApp } from '../test/render'
import { contrast } from '../test/contrast'
import { cssVariablesResolver, theme } from './theme'

describe("The component library's defaults (docs/11 §9)", () => {
  it("gives a dialog's close button a name and the 44 px of a finger (B#41)", async () => {
    renderApp(
      <Modal opened onClose={() => {}} title="A sheet">
        Inside
      </Modal>,
    )
    const close = await screen.findByRole('button', { name: 'Close' })
    // "xl" is the library's 44 px close button.
    expect(close.style.getPropertyValue('--cb-size')).toBe('var(--cb-size-xl)')
  })

  it('lets the keyboard reach the eye that shows a password (B#42)', () => {
    renderApp(<PasswordInput label="Password" />)
    const eye = document.querySelector<HTMLElement>('.mantine-PasswordInput-visibilityToggle')
    expect(eye).not.toBeNull()
    expect(eye).not.toHaveAttribute('tabindex', '-1')
  })

  it("still marks its fields where global.css draws their edges and the one focus ring (B#18, B#45)", async () => {
    renderApp(
      <>
        <TextInput label="Name" />
        <TextInput label="Phone" error="Wrong" />
        <PasswordInput label="Password" />
        <Checkbox label="I agree" />
        <Modal opened onClose={() => {}} title="A sheet">
          Inside
        </Modal>
      </>,
    )
    const wrapperOf = (label: string) => screen.getByLabelText(label).closest('.mantine-Input-wrapper')
    expect(wrapperOf('Name')).toHaveAttribute('data-variant', 'default')
    expect(wrapperOf('Name')).not.toHaveAttribute('data-error')
    // A field in error is marked on the same element: its red edge wins over ours.
    expect(wrapperOf('Phone')).toHaveAttribute('data-error')
    expect(wrapperOf('Password')).toHaveAttribute('data-variant', 'default')
    expect(screen.getByLabelText('I agree')).toHaveClass('mantine-Checkbox-input')
    expect(document.querySelector('.mantine-PasswordInput-visibilityToggle')).toHaveClass('mantine-focus-auto')
    expect(await screen.findByRole('button', { name: 'Close' })).toHaveClass('mantine-focus-auto')
  })

  it("writes hints and placeholders in greys that reach 4.5:1 on white (B#18)", () => {
    const light = cssVariablesResolver(theme as never).light
    expect(contrast(light['--mantine-color-dimmed']!, '#ffffff')).toBeGreaterThanOrEqual(4.5)
    expect(contrast(light['--mantine-color-placeholder']!, '#ffffff')).toBeGreaterThanOrEqual(4.5)
  })
})
